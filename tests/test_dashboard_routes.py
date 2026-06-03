import pytest

pytestmark = pytest.mark.asyncio


async def test_live_feed(dashboard_client, seeded):
    r = await dashboard_client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert seeded in r.text  # IP appears
    assert "/admin" in r.text


async def test_ip_detail_with_mermaid(dashboard_client, seeded):
    r = await dashboard_client.get(f"/ip/{seeded}")
    assert r.status_code == 200
    assert "graph TD" in r.text
    assert "/users" in r.text  # link edge target


async def test_baits(dashboard_client, seeded):
    r = await dashboard_client.get("/baits")
    assert r.status_code == 200
    assert "/admin" in r.text


async def test_stats(dashboard_client, seeded):
    r = await dashboard_client.get("/stats")
    assert r.status_code == 200
    # numeric values present
    assert "100" in r.text or "200" in r.text
    assert "Total IPs" in r.text
