"""Honeypot HTTP routes (FastAPI)."""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import yaml
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import Settings
from shared.llm import LLMClient, LLMError
from shared.models import CredentialAttempt, IPUniverse, LinkEdge, Page, RequestLog
from shared.page_type import detect_page_type
from shared.ua import parse_ua

from .bait import is_bait, random_login_success
from .error_pages import nginx_404, nginx_500, NGINX_VERSION
from .link_token import sanitize_and_sign_links, verify

PROMPTS_DIR = Path(__file__).parent / "prompts"
_jinja = Environment(
    loader=FileSystemLoader(str(PROMPTS_DIR)),
    autoescape=select_autoescape([]),
    keep_trailing_newline=True,
)

_RANDOM_COMPANIES = [
    "Acme Corp", "Globex", "Initech", "Umbrella", "Soylent", "Wonka Industries",
    "Stark Industries", "Hooli", "Pied Piper", "Massive Dynamic", "Tyrell Corp",
]


def _load_scenarios() -> list[dict]:
    p = PROMPTS_DIR / "index_scenarios.yaml"
    return yaml.safe_load(p.read_text()) or []


_SCENARIOS = _load_scenarios()


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "0.0.0.0"


def _content_type_for(page_type: str) -> str:
    return {"html": "text/html; charset=utf-8",
            "json": "application/json",
            "text": "text/plain; charset=utf-8"}.get(page_type, "text/html; charset=utf-8")


def _render_prompt(page_type: str, path: str, scenario: Optional[dict]) -> str:
    tmpl_name = {"html": "html_page.j2", "json": "api_json.j2", "text": "plain_text.j2"}[page_type]
    tmpl = _jinja.get_template(tmpl_name)
    ctx = {
        "path": path,
        "page_type": page_type,
        "scenario_business": (scenario or {}).get("business"),
        "scenario_links": (scenario or {}).get("suggested_links"),
    }
    return tmpl.render(**ctx)


async def _touch_ip(session: AsyncSession, ip: str, ua: str) -> None:
    row = await session.get(IPUniverse, ip)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    if row is None:
        session.add(IPUniverse(ip=ip, ua=ua, first_seen=now, last_seen=now, request_count=1))
    else:
        row.last_seen = now
        row.request_count = (row.request_count or 0) + 1
        if ua:
            row.ua = ua
    await session.commit()


async def _log_request(session: AsyncSession, *, ip: str, method: str, path: str,
                       status: int, ua: str, referer: str, was_generated: bool,
                       was_bait_flag: bool, post_body: Optional[str] = None) -> None:
    session.add(RequestLog(
        ip=ip, method=method, path=path, status=status, ua=ua, referer=referer,
        was_generated=was_generated, was_bait=was_bait_flag, post_body=post_body,
    ))
    await session.commit()


async def _maybe_log_edge(session: AsyncSession, ip: str, referer: str, to_path: str,
                          request: Request) -> None:
    if not referer:
        return
    try:
        ref_parts = urlsplit(referer)
        host = request.headers.get("host", "")
        if ref_parts.netloc and host and ref_parts.netloc != host:
            return
        from_path = ref_parts.path or "/"
        if from_path == to_path:
            return
        session.add(LinkEdge(ip=ip, from_path=from_path, to_path=to_path))
        await session.commit()
    except Exception:
        pass


async def _get_cached_page(session: AsyncSession, ip: str, path: str) -> Optional[Page]:
    res = await session.execute(
        select(Page).where(Page.ip == ip, Page.path == path)
    )
    return res.scalar_one_or_none()


async def _generate_page(*, session: AsyncSession, llm: LLMClient, settings: Settings,
                         ip: str, path: str, scenario: Optional[dict] = None,
                         extra_hint: Optional[str] = None) -> Page:
    page_type = detect_page_type(path)
    prompt = _render_prompt(page_type, path, scenario)
    if extra_hint:
        prompt = prompt + "\n\nAdditional context: " + extra_hint
    text, t_in, t_out = await llm.generate(prompt)
    ct = _content_type_for(page_type)
    sanitized = sanitize_and_sign_links(text, ip, settings.secret_key, ct)
    page = Page(ip=ip, path=path, content_type=ct, body=sanitized,
                tokens_in=t_in, tokens_out=t_out)
    session.add(page)
    # bump token counters on universe
    universe = await session.get(IPUniverse, ip)
    if universe is not None:
        universe.token_count_in = (universe.token_count_in or 0) + t_in
        universe.token_count_out = (universe.token_count_out or 0) + t_out
    await session.commit()
    return page


def _response_for(page: Page) -> Response:
    ct = page.content_type
    headers = {"Server": NGINX_VERSION}
    if "json" in ct:
        return Response(content=page.body, media_type="application/json", headers=headers)
    if "html" in ct:
        return HTMLResponse(content=page.body, headers=headers)
    return PlainTextResponse(content=page.body, headers=headers)


def _nginx_response(triple) -> Response:
    body, headers, status = triple
    return Response(content=body, status_code=status, headers=headers)


# ---- Dependency injection helpers (filled in main.py) ----

async def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_llm(request: Request) -> LLMClient:
    return request.app.state.llm


async def get_session(request: Request) -> AsyncSession:
    factory = request.app.state.session_factory
    async with factory() as s:
        yield s


# ---- Router ----

router = APIRouter()


@router.get("/")
async def index(request: Request, settings: Settings = Depends(get_settings),
                llm: LLMClient = Depends(get_llm),
                session: AsyncSession = Depends(get_session)):
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")
    await _touch_ip(session, ip, ua)

    path = "/"
    cached = await _get_cached_page(session, ip, path)
    if cached is not None:
        await _log_request(session, ip=ip, method="GET", path=path, status=200,
                           ua=ua, referer=request.headers.get("referer", ""),
                           was_generated=False, was_bait_flag=False)
        return _response_for(cached)

    scenario = random.choice(_SCENARIOS) if _SCENARIOS else None
    if scenario:
        scenario = dict(scenario)
        scenario["business"] = scenario.get("business", "").replace(
            "{company}", random.choice(_RANDOM_COMPANIES)
        )
    try:
        page = await _generate_page(session=session, llm=llm, settings=settings,
                                    ip=ip, path=path, scenario=scenario)
    except LLMError:
        await _log_request(session, ip=ip, method="GET", path=path, status=500,
                           ua=ua, referer=request.headers.get("referer", ""),
                           was_generated=False, was_bait_flag=False)
        return _nginx_response(nginx_500())

    await _log_request(session, ip=ip, method="GET", path=path, status=200,
                       ua=ua, referer=request.headers.get("referer", ""),
                       was_generated=True, was_bait_flag=False)
    return _response_for(page)


@router.get("/{full_path:path}")
async def any_get(full_path: str, request: Request,
                  settings: Settings = Depends(get_settings),
                  llm: LLMClient = Depends(get_llm),
                  session: AsyncSession = Depends(get_session)):
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")
    referer = request.headers.get("referer", "")
    path = "/" + full_path
    await _touch_ip(session, ip, ua)

    # 1. cached?
    cached = await _get_cached_page(session, ip, path)
    if cached is not None:
        await _maybe_log_edge(session, ip, referer, path, request)
        await _log_request(session, ip=ip, method="GET", path=path, status=200,
                           ua=ua, referer=referer, was_generated=False,
                           was_bait_flag=is_bait(path, settings))
        return _response_for(cached)

    bait = is_bait(path, settings)
    token = request.query_params.get("_t", "")
    token_ok = verify(ip, path, token, settings.secret_key) if token else False

    if not bait and not token_ok:
        await _log_request(session, ip=ip, method="GET", path=path, status=404,
                           ua=ua, referer=referer, was_generated=False,
                           was_bait_flag=False)
        return _nginx_response(nginx_404())

    try:
        page = await _generate_page(session=session, llm=llm, settings=settings,
                                    ip=ip, path=path)
    except LLMError:
        await _log_request(session, ip=ip, method="GET", path=path, status=500,
                           ua=ua, referer=referer, was_generated=False,
                           was_bait_flag=bait)
        return _nginx_response(nginx_500())

    await _maybe_log_edge(session, ip, referer, path, request)
    await _log_request(session, ip=ip, method="GET", path=path, status=200,
                       ua=ua, referer=referer, was_generated=True,
                       was_bait_flag=bait)
    return _response_for(page)


@router.post("/{full_path:path}")
async def any_post(full_path: str, request: Request,
                   settings: Settings = Depends(get_settings),
                   llm: LLMClient = Depends(get_llm),
                   session: AsyncSession = Depends(get_session)):
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")
    referer = request.headers.get("referer", "")
    path = "/" + full_path if full_path else "/"
    await _touch_ip(session, ip, ua)

    # Parse body: form or JSON.
    username = None
    password = None
    extra: dict = {}
    raw_body = b""
    try:
        raw_body = await request.body()
    except Exception:
        raw_body = b""

    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        try:
            data = json.loads(raw_body or b"{}")
            if isinstance(data, dict):
                username = data.get("username") or data.get("user") or data.get("email")
                password = data.get("password") or data.get("pass")
                extra = {k: v for k, v in data.items() if k not in {"username", "password"}}
        except Exception:
            pass
    else:
        try:
            form = await request.form()
            username = form.get("username") or form.get("user") or form.get("email")
            password = form.get("password") or form.get("pass")
            extra = {k: v for k, v in form.items() if k not in {"username", "password"}}
        except Exception:
            pass

    session.add(CredentialAttempt(
        ip=ip, path=path,
        username=str(username) if username is not None else None,
        password=str(password) if password is not None else None,
        extra_json=json.dumps({k: str(v) for k, v in extra.items()}) if extra else None,
    ))
    await session.commit()

    post_body_snippet = raw_body[:500].decode("utf-8", errors="replace") if raw_body else None

    if random_login_success(settings):
        # 302 redirect to fake /dashboard?session=...
        sess_id = "s_" + hex(random.getrandbits(64))[2:]
        await _log_request(session, ip=ip, method="POST", path=path, status=302,
                           ua=ua, referer=referer, was_generated=False,
                           was_bait_flag=is_bait(path, settings), post_body=post_body_snippet)
        return RedirectResponse(url=f"/dashboard?session={sess_id}", status_code=302,
                                headers={"Server": NGINX_VERSION})

    # Failure: generate "invalid credentials" version of the login page.
    try:
        page = await _generate_page(
            session=session, llm=llm, settings=settings, ip=ip, path=path,
            extra_hint="Render the page with a visible 'Invalid credentials' error message above the form.",
        )
    except LLMError:
        await _log_request(session, ip=ip, method="POST", path=path, status=500,
                           ua=ua, referer=referer, was_generated=False,
                           was_bait_flag=is_bait(path, settings), post_body=post_body_snippet)
        return _nginx_response(nginx_500())

    await _log_request(session, ip=ip, method="POST", path=path, status=401,
                       ua=ua, referer=referer, was_generated=True,
                       was_bait_flag=is_bait(path, settings), post_body=post_body_snippet)
    resp = _response_for(page)
    resp.status_code = 401
    return resp
