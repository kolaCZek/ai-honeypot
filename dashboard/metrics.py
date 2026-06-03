"""Prometheus metrics: built per-scrape from DB aggregates."""
from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest
from sqlalchemy import func, select

from shared.models import CredentialAttempt, IPUniverse, Page, RequestLog


async def build_metrics(session, settings) -> bytes:
    reg = CollectorRegistry()

    req_counter = Counter(
        "honeypot_requests_total", "Total honeypot HTTP requests",
        ["status", "bait"], registry=reg,
    )
    pages_counter = Counter(
        "honeypot_pages_generated_total", "Total LLM-generated pages", registry=reg,
    )
    tokens_counter = Counter(
        "honeypot_llm_tokens_total", "Total LLM tokens", ["direction"], registry=reg,
    )
    creds_counter = Counter(
        "honeypot_credential_attempts_total", "Total credential submissions", registry=reg,
    )
    active_ips = Gauge("honeypot_active_ips", "Distinct IPs in universe", registry=reg)
    cost_gauge = Gauge("honeypot_estimated_cost_usd", "Estimated LLM cost USD", registry=reg)

    rows = (await session.execute(
        select(RequestLog.status, RequestLog.was_bait, func.count())
        .group_by(RequestLog.status, RequestLog.was_bait)
    )).all()
    for st, was_bait, n in rows:
        req_counter.labels(status=str(st), bait=str(bool(was_bait)).lower()).inc(int(n))

    page_count = (await session.execute(select(func.count()).select_from(Page))).scalar() or 0
    pages_counter.inc(int(page_count))

    tin = (await session.execute(select(func.coalesce(func.sum(IPUniverse.token_count_in), 0)))).scalar() or 0
    tout = (await session.execute(select(func.coalesce(func.sum(IPUniverse.token_count_out), 0)))).scalar() or 0
    tokens_counter.labels(direction="in").inc(int(tin))
    tokens_counter.labels(direction="out").inc(int(tout))

    cred_count = (await session.execute(select(func.count()).select_from(CredentialAttempt))).scalar() or 0
    creds_counter.inc(int(cred_count))

    ip_count = (await session.execute(select(func.count()).select_from(IPUniverse))).scalar() or 0
    active_ips.set(int(ip_count))

    llm = settings.llm
    cost = (int(tin) * llm.cost_per_mtok_in + int(tout) * llm.cost_per_mtok_out) / 1_000_000
    cost_gauge.set(cost)

    return generate_latest(reg)
