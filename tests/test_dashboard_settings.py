"""Tests for the dashboard /settings editor (GET/POST/CSRF)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, BasicAuth

from shared.config import load_config

pytestmark = pytest.mark.asyncio


def _write_initial_config(tmp_path: Path) -> Path:
    src = Path(__file__).resolve().parents[1] / "config.yaml.example"
    txt = src.read_text().replace("/data/secret.key", str(tmp_path / "secret.key"))
    txt = txt.replace("/data/honeypot.db", str(tmp_path / "h.db"))
    cfg = tmp_path / "config.yaml"
    cfg.write_text(txt)
    cfg.chmod(0o600)
    return cfg


@pytest_asyncio.fixture
async def settings_dashboard(tmp_path, session_factory):
    cfg = _write_initial_config(tmp_path)
    s = load_config(cfg)
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    from dashboard.main import create_app
    app = create_app(
        settings=s,
        session_factory=session_factory,
        redis_client=redis_client,
        config_path=str(cfg),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver",
        auth=BasicAuth("admin", "change-me"),
    ) as client:
        async with app.router.lifespan_context(app):
            yield client, app, cfg, redis_client
    await redis_client.aclose()


async def test_settings_get_renders_form(settings_dashboard):
    client, _app, _cfg, _r = settings_dashboard
    r = await client.get("/settings")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    # form is present with current values
    assert 'name="llm.model"' in r.text
    assert 'name="honeypot.bait_endpoints"' in r.text
    assert "gpt-4o-mini" in r.text  # current model from example
    # api_key/password rendered as blank (leave-blank-to-keep)
    assert 'name="llm.api_key" value=""' in r.text


async def _form_payload(current_text: str) -> dict:
    # Minimal valid form payload derived from config.yaml.example defaults
    return {
        "llm.endpoint": "https://api.example.com/v1",
        "llm.api_key": "",
        "llm.model": "new-model",
        "llm.timeout_s": "20",
        "llm.max_tokens": "1000",
        "llm.cost_per_mtok_in": "0.1",
        "llm.cost_per_mtok_out": "0.2",
        "honeypot.port": "8888",
        "honeypot.secret_key_file": "",  # blank -> keep
        "honeypot.slowdown.enabled": "on",
        "honeypot.slowdown.min_s": "5",
        "honeypot.slowdown.max_s": "15",
        "honeypot.rate_limit.max_concurrent_per_ip": "5",
        "honeypot.retention.max_ips": "",
        "honeypot.retention.ttl_days": "3",
        "honeypot.fake_login.success_ratio": "0.5",
        "honeypot.whitelist_ips": "127.0.0.1\n::1\n",
        "honeypot.bait_endpoints": "/admin\n/.env\n",
        "dashboard.basic_auth.username": "admin",
        "dashboard.basic_auth.password": "",
        "dashboard.port": "8080",
        "storage.sqlite_path": "",
        "storage.redis_url": "redis://redis:6379/0",
    }


async def test_settings_post_saves_and_publishes(settings_dashboard):
    client, app, cfg, _r = settings_dashboard
    payload = await _form_payload(cfg.read_text())

    # Spy on publish_reload by patching it where routes imported it from.
    from dashboard import routes as droutes
    publish_spy = AsyncMock(return_value=1)
    orig = droutes.publish_reload
    droutes.publish_reload = publish_spy
    try:
        r = await client.post(
            "/settings", data=payload,
            headers={"Referer": "http://testserver/settings"},
        )
    finally:
        droutes.publish_reload = orig

    assert r.status_code == 303
    assert r.headers["location"].startswith("/settings")

    # File on disk changed.
    reloaded = load_config(cfg)
    assert reloaded.llm.model == "new-model"
    assert reloaded.honeypot.bait_endpoints == ["/admin", "/.env"]
    # blank api_key kept previous value
    assert reloaded.llm.api_key == "sk-CHANGE-ME"

    # publish was called.
    publish_spy.assert_awaited_once()


async def test_settings_post_invalid_returns_400(settings_dashboard):
    client, _app, cfg, _r = settings_dashboard
    payload = await _form_payload(cfg.read_text())
    payload["llm.endpoint"] = ""  # required string -> Pydantic empty? Actually empty is allowed
    payload["llm.timeout_s"] = "not-a-number"  # triggers ValueError on float()
    before = cfg.read_text()

    r = await client.post(
        "/settings", data=payload,
        headers={"Referer": "http://testserver/settings"},
    )
    assert r.status_code == 400
    assert cfg.read_text() == before


async def test_settings_post_without_referer_is_forbidden(settings_dashboard):
    client, _app, cfg, _r = settings_dashboard
    payload = await _form_payload(cfg.read_text())
    before = cfg.read_text()

    r = await client.post("/settings", data=payload)
    assert r.status_code == 403
    assert cfg.read_text() == before


async def test_settings_post_cross_origin_referer_forbidden(settings_dashboard):
    client, _app, cfg, _r = settings_dashboard
    payload = await _form_payload(cfg.read_text())
    before = cfg.read_text()

    r = await client.post(
        "/settings", data=payload,
        headers={"Referer": "http://evil.example.com/settings"},
    )
    assert r.status_code == 403
    assert cfg.read_text() == before
