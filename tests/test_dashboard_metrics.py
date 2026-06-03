import pytest

pytestmark = pytest.mark.asyncio


async def test_metrics_exposes_all_names(dashboard_client, seeded):
    r = await dashboard_client.get("/metrics")
    assert r.status_code == 200
    body = r.text
    for name in [
        "honeypot_requests_total",
        "honeypot_pages_generated_total",
        "honeypot_llm_tokens_total",
        "honeypot_credential_attempts_total",
        "honeypot_active_ips",
        "honeypot_estimated_cost_usd",
    ]:
        assert name in body, f"missing metric {name}"
    # Prometheus format sanity: HELP/TYPE lines
    assert "# HELP" in body and "# TYPE" in body
