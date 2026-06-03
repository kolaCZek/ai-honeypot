"""Dashboard routes: live feed, IP detail, baits, stats, metrics."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import desc, func, select

from shared.models import CredentialAttempt, IPUniverse, LinkEdge, Page, RequestLog

from .auth import require_basic_auth
from .metrics import build_metrics

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


def _factory(request: Request):
    return request.app.state.session_factory


def _settings(request: Request):
    return request.app.state.settings


def _cost(settings, tin: int, tout: int) -> float:
    llm = settings.llm
    return (tin * llm.cost_per_mtok_in + tout * llm.cost_per_mtok_out) / 1_000_000


@router.get("/")
async def live_feed(
    request: Request,
    ip: str | None = None,
    country: str | None = None,
    ua: str | None = None,
    bait_only: bool = False,
    _user: str = Depends(require_basic_auth),
):
    async with _factory(request)() as s:
        stmt = (
            select(RequestLog, IPUniverse)
            .join(IPUniverse, IPUniverse.ip == RequestLog.ip, isouter=True)
            .order_by(desc(RequestLog.ts))
            .limit(100)
        )
        if ip:
            stmt = stmt.where(RequestLog.ip == ip)
        if country:
            stmt = stmt.where(IPUniverse.country == country)
        if ua:
            stmt = stmt.where(RequestLog.ua.like(f"%{ua}%"))
        if bait_only:
            stmt = stmt.where(RequestLog.was_bait.is_(True))
        rows = (await s.execute(stmt)).all()
    items = []
    for rl, ipu in rows:
        items.append({
            "ts": rl.ts, "ip": rl.ip,
            "country": (ipu.country if ipu else None),
            "method": rl.method, "path": rl.path, "status": rl.status,
            "generated": rl.was_generated, "bait": rl.was_bait,
            "ua": rl.ua or "",
        })
    return _templates(request).TemplateResponse(request, "live.html", {"items": items,
         "filters": {"ip": ip or "", "country": country or "",
                     "ua": ua or "", "bait_only": bait_only}})


@router.get("/ip/{ip}")
async def ip_detail(request: Request, ip: str, _user: str = Depends(require_basic_auth)):
    async with _factory(request)() as s:
        ipu = (await s.execute(select(IPUniverse).where(IPUniverse.ip == ip))).scalar_one_or_none()
        pages = (await s.execute(
            select(Page).where(Page.ip == ip).order_by(Page.generated_at)
        )).scalars().all()
        edges = (await s.execute(select(LinkEdge).where(LinkEdge.ip == ip))).scalars().all()
        creds = (await s.execute(
            select(CredentialAttempt).where(CredentialAttempt.ip == ip).order_by(CredentialAttempt.ts)
        )).scalars().all()
        req_count = (await s.execute(
            select(func.count()).select_from(RequestLog).where(RequestLog.ip == ip)
        )).scalar() or 0

    mermaid = ""
    if edges:
        lines = ["graph TD"]
        nodes: dict[str, str] = {}

        def nid(p: str) -> str:
            if p not in nodes:
                nodes[p] = f"N{len(nodes)}"
            return nodes[p]

        for e in edges:
            a, b = nid(e.from_path), nid(e.to_path)
            la = e.from_path.replace('"', "'")
            lb = e.to_path.replace('"', "'")
            lines.append(f'  {a}["{la}"] --> {b}["{lb}"]')
        mermaid = "\n".join(lines)

    tin = ipu.token_count_in if ipu else 0
    tout = ipu.token_count_out if ipu else 0
    summary = {
        "ip": ip,
        "first_seen": ipu.first_seen if ipu else None,
        "last_seen": ipu.last_seen if ipu else None,
        "country": ipu.country if ipu else None,
        "ua": ipu.ua if ipu else None,
        "requests": req_count,
        "tokens_in": tin,
        "tokens_out": tout,
        "cost_usd": _cost(_settings(request), tin, tout),
    }
    return _templates(request).TemplateResponse(request, "ip_detail.html", {"summary": summary, "pages": pages,
         "creds": creds, "mermaid": mermaid})


@router.get("/baits")
async def baits(request: Request, _user: str = Depends(require_basic_auth)):
    async with _factory(request)() as s:
        rows = (await s.execute(
            select(RequestLog.path, func.count(), func.count(func.distinct(RequestLog.ip)))
            .where(RequestLog.was_bait.is_(True))
            .group_by(RequestLog.path)
            .order_by(desc(func.count()))
        )).all()
    items = [{"path": p, "count": c, "unique_ips": u} for p, c, u in rows]
    return _templates(request).TemplateResponse(request, "baits.html", {"items": items})


@router.get("/stats")
async def stats(request: Request, _user: str = Depends(require_basic_auth)):
    settings = _settings(request)
    async with _factory(request)() as s:
        total_ips = (await s.execute(select(func.count()).select_from(IPUniverse))).scalar() or 0
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        active_24h = (await s.execute(
            select(func.count()).select_from(IPUniverse).where(IPUniverse.last_seen >= cutoff)
        )).scalar() or 0
        total_pages = (await s.execute(select(func.count()).select_from(Page))).scalar() or 0
        tin = (await s.execute(select(func.coalesce(func.sum(IPUniverse.token_count_in), 0)))).scalar() or 0
        tout = (await s.execute(select(func.coalesce(func.sum(IPUniverse.token_count_out), 0)))).scalar() or 0
        countries = (await s.execute(
            select(IPUniverse.country, func.count())
            .group_by(IPUniverse.country).order_by(desc(func.count())).limit(10)
        )).all()
        uas = (await s.execute(
            select(IPUniverse.ua, func.count())
            .group_by(IPUniverse.ua).order_by(desc(func.count())).limit(10)
        )).all()
        # bot vs not: heuristically use ua presence of 'bot'
        bots = (await s.execute(
            select(func.count()).select_from(IPUniverse).where(IPUniverse.ua.ilike("%bot%"))
        )).scalar() or 0
        non_bots = total_ips - bots

    data = {
        "total_ips": int(total_ips),
        "active_24h": int(active_24h),
        "total_pages": int(total_pages),
        "tokens_in": int(tin),
        "tokens_out": int(tout),
        "cost_usd": _cost(settings, int(tin), int(tout)),
        "countries": [{"country": c or "?", "count": n} for c, n in countries],
        "uas": [{"ua": (u or "?")[:80], "count": n} for u, n in uas],
        "bots": int(bots),
        "non_bots": int(non_bots),
    }
    return _templates(request).TemplateResponse(request, "stats.html", {"data": data})


@router.get("/metrics")
async def metrics(request: Request, _user: str = Depends(require_basic_auth)):
    async with _factory(request)() as s:
        body = await build_metrics(s, _settings(request))
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")
