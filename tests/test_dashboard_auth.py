import pytest

pytestmark = pytest.mark.asyncio


async def test_no_auth_returns_401(dashboard_noauth_client):
    r = await dashboard_noauth_client.get("/")
    assert r.status_code == 401
    assert r.headers.get("www-authenticate", "").lower().startswith("basic")


async def test_bad_password_401(dashboard_app):
    from httpx import ASGITransport, AsyncClient, BasicAuth
    transport = ASGITransport(app=dashboard_app)
    from tests.conftest import _lifespan_ctx
    async with AsyncClient(transport=transport, base_url="http://testserver",
                           auth=BasicAuth("a", "WRONG")) as c:
        async with _lifespan_ctx(dashboard_app):
            r = await c.get("/")
    assert r.status_code == 401


async def test_correct_auth_200(dashboard_client):
    r = await dashboard_client.get("/")
    assert r.status_code == 200
