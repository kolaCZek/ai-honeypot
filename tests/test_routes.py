import pytest
from sqlalchemy import select

from honeypot.link_token import sign
from shared.models import CredentialAttempt, RequestLog


pytestmark = pytest.mark.asyncio


async def test_index_caches_per_ip(client, fake_llm):
    r1 = await client.get("/", headers={"X-Forwarded-For": "8.8.8.8"})
    assert r1.status_code == 200
    assert "<!doctype html>" in r1.text.lower() or "<html" in r1.text.lower()
    assert fake_llm.calls == 1
    r2 = await client.get("/", headers={"X-Forwarded-For": "8.8.8.8"})
    assert r2.status_code == 200
    assert fake_llm.calls == 1  # cached


async def test_random_path_404(client, fake_llm):
    r = await client.get("/totally-random-xyz", headers={"X-Forwarded-For": "8.8.8.9"})
    assert r.status_code == 404
    assert "nginx" in r.headers.get("server", "").lower()
    assert "404 Not Found" in r.text


async def test_bait_endpoint_generates(client, fake_llm):
    r = await client.get("/.env", headers={"X-Forwarded-For": "8.8.8.10"})
    assert r.status_code == 200
    assert fake_llm.calls >= 1


async def test_token_required_for_non_bait(client, fake_llm, settings):
    ip = "8.8.8.11"
    # without token -> 404
    r1 = await client.get("/settings", headers={"X-Forwarded-For": ip})
    assert r1.status_code == 404
    # with valid token -> 200
    tok = sign(ip, "/settings", settings.secret_key)
    r2 = await client.get(f"/settings?_t={tok}", headers={"X-Forwarded-For": ip})
    assert r2.status_code == 200


async def test_post_login_records_credentials(client, settings, session_factory):
    ip = "8.8.8.12"
    r = await client.post(
        "/login",
        data={"username": "root", "password": "hunter2"},
        headers={"X-Forwarded-For": ip},
    )
    assert r.status_code in (200, 302, 401)
    async with session_factory() as s:
        rows = (await s.execute(select(CredentialAttempt).where(CredentialAttempt.ip == ip))).scalars().all()
        assert len(rows) == 1
        assert rows[0].username == "root"
        assert rows[0].password == "hunter2"


async def test_llm_error_returns_500(client, fake_llm):
    fake_llm.raise_next = True
    r = await client.get("/.env", headers={"X-Forwarded-For": "8.8.8.13"})
    assert r.status_code == 500
    assert "nginx" in r.headers.get("server", "").lower()


async def test_request_logged(client, session_factory):
    await client.get("/", headers={"X-Forwarded-For": "8.8.8.14"})
    async with session_factory() as s:
        rows = (await s.execute(select(RequestLog).where(RequestLog.ip == "8.8.8.14"))).scalars().all()
        assert len(rows) >= 1
