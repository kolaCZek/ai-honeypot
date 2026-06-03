"""Dashboard routes: live feed, IP detail, baits, stats, metrics, settings."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import desc, func, select

from shared.config import (
    BasicAuthConfig, DashboardConfig, FakeLoginConfig, HoneypotConfig,
    LLMConfig, RateLimitConfig, RetentionConfig, Settings, SlowdownConfig,
    StorageConfig, load_config, save_config,
)
from shared.config_reload import publish_reload
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


# ---- Settings editor -------------------------------------------------------

def _check_referer(request: Request) -> None:
    """Simple CSRF defense: require a same-origin Referer on state-changing
    requests. We rely on Referer (rather than a signed token) because the
    dashboard already sits behind HTTP Basic auth and has no session cookie
    to bind a token to. Browsers always send Referer on form POSTs to the
    same origin; bots replaying a stolen cookie won't have it from the
    dashboard URL.
    """
    ref = request.headers.get("referer", "")
    if not ref:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="missing referer")
    try:
        ref_host = urlsplit(ref).netloc
    except Exception:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="bad referer")
    host = request.headers.get("host", "")
    if not ref_host or ref_host != host:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="cross-origin referer")


def _settings_to_form(s: Settings) -> dict:
    """Project a Settings into the dict shape the template expects."""
    return {
        "llm": s.llm.model_dump(),
        "honeypot": s.honeypot.model_dump(),
        "dashboard": s.dashboard.model_dump(),
        "storage": s.storage.model_dump(),
    }


def _split_lines(value: str) -> list[str]:
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def _parse_opt_int(value: str | None) -> int | None:
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    return int(v)


async def _build_settings_from_form(request: Request, current: Settings) -> Settings:
    form = await request.form()

    def g(name: str, default: str = "") -> str:
        v = form.get(name)
        return v if isinstance(v, str) else default

    # "Leave blank to keep" secrets.
    api_key = g("llm.api_key").strip() or current.llm.api_key
    basic_pw = g("dashboard.basic_auth.password").strip() or current.dashboard.basic_auth.password

    llm = LLMConfig(
        endpoint=g("llm.endpoint"),
        api_key=api_key,
        model=g("llm.model"),
        timeout_s=float(g("llm.timeout_s") or current.llm.timeout_s),
        max_tokens=int(g("llm.max_tokens") or current.llm.max_tokens),
        cost_per_mtok_in=float(g("llm.cost_per_mtok_in") or 0),
        cost_per_mtok_out=float(g("llm.cost_per_mtok_out") or 0),
    )
    slowdown = SlowdownConfig(
        enabled=g("honeypot.slowdown.enabled") == "on",
        min_s=float(g("honeypot.slowdown.min_s") or 0),
        max_s=float(g("honeypot.slowdown.max_s") or 0),
    )
    rate_limit = RateLimitConfig(
        max_concurrent_per_ip=int(g("honeypot.rate_limit.max_concurrent_per_ip") or 1),
        block_on_exceed=g("honeypot.rate_limit.block_on_exceed") == "on",
    )
    retention = RetentionConfig(
        max_ips=_parse_opt_int(g("honeypot.retention.max_ips")),
        ttl_days=_parse_opt_int(g("honeypot.retention.ttl_days")),
    )
    fake_login = FakeLoginConfig(
        success_ratio=float(g("honeypot.fake_login.success_ratio") or 0),
    )
    honeypot = HoneypotConfig(
        port=int(g("honeypot.port") or current.honeypot.port),
        slowdown=slowdown,
        rate_limit=rate_limit,
        retention=retention,
        whitelist_ips=_split_lines(g("honeypot.whitelist_ips")),
        bait_endpoints=_split_lines(g("honeypot.bait_endpoints")),
        fake_login=fake_login,
        secret_key_file=g("honeypot.secret_key_file") or current.honeypot.secret_key_file,
    )
    dashboard = DashboardConfig(
        port=int(g("dashboard.port") or current.dashboard.port),
        basic_auth=BasicAuthConfig(
            username=g("dashboard.basic_auth.username"),
            password=basic_pw,
        ),
    )
    storage = StorageConfig(
        sqlite_path=g("storage.sqlite_path") or current.storage.sqlite_path,
        redis_url=g("storage.redis_url") or current.storage.redis_url,
    )
    return Settings(
        llm=llm, honeypot=honeypot, dashboard=dashboard, storage=storage,
        secret_key=current.secret_key,
    )


@router.get("/settings")
async def settings_get(request: Request, _user: str = Depends(require_basic_auth),
                       saved: int = 0):
    s = _settings(request)
    last_saved = getattr(request.app.state, "settings_last_saved", None)
    return _templates(request).TemplateResponse(request, "settings.html", {
        "form": _settings_to_form(s),
        "saved": bool(saved),
        "last_saved": last_saved,
        "error": None,
    })


@router.post("/settings")
async def settings_post(request: Request, _user: str = Depends(require_basic_auth)):
    _check_referer(request)
    current = _settings(request)
    try:
        new_settings = await _build_settings_from_form(request, current)
    except (ValidationError, ValueError) as e:
        return _templates(request).TemplateResponse(request, "settings.html", {
            "form": _settings_to_form(current),
            "saved": False,
            "last_saved": getattr(request.app.state, "settings_last_saved", None),
            "error": str(e),
        }, status_code=400)

    path = getattr(request.app.state, "config_path", None)
    if not path:
        raise HTTPException(status_code=500, detail="config_path not set")
    save_config(new_settings, path)

    # Reload locally too (picks up secret_key bootstrap if needed).
    reloaded = load_config(path)
    request.app.state.settings = reloaded
    now = datetime.now(timezone.utc)
    request.app.state.settings_last_saved = now.isoformat()

    rds = getattr(request.app.state, "redis", None)
    if rds is not None:
        try:
            await publish_reload(rds)
        except Exception:
            # Reload locally still succeeded; the honeypot will pick up
            # changes on its next restart even if pub/sub failed.
            pass

    return RedirectResponse(url="/settings?saved=1",
                            status_code=status.HTTP_303_SEE_OTHER)
