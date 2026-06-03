"""Integration: publishing config:reload reloads honeypot settings + LLM."""
from __future__ import annotations

import asyncio
from pathlib import Path

import fakeredis.aioredis
import pytest

from shared.config import load_config, save_config
from shared.config_reload import publish_reload

pytestmark = pytest.mark.asyncio


def _write_initial_config(tmp_path: Path) -> Path:
    src = Path(__file__).resolve().parents[1] / "config.yaml.example"
    txt = src.read_text().replace("/data/secret.key", str(tmp_path / "secret.key"))
    txt = txt.replace("/data/honeypot.db", str(tmp_path / "h.db"))
    cfg = tmp_path / "config.yaml"
    cfg.write_text(txt)
    return cfg


async def test_honeypot_reloads_on_publish(tmp_path, session_factory, monkeypatch):
    cfg = _write_initial_config(tmp_path)
    monkeypatch.setenv("CONFIG_PATH", str(cfg))

    s = load_config(cfg)
    # Whitelist testclient so middleware doesn't slow us down (not needed here
    # since we never send HTTP; we only drive the lifespan).
    s.honeypot.whitelist_ips = ["testclient"]
    s.storage.sqlite_path = ":memory:"

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    rebuilt: list[str] = []

    class FakeLLM:
        def __init__(self, settings):
            rebuilt.append(settings.llm.model)
        async def aclose(self):
            pass

    from honeypot.main import create_app
    app = create_app(
        settings=s, session_factory=session_factory, redis_client=redis_client,
    )
    # Install a factory so reload uses our spy.
    app.state.llm_factory = lambda settings: FakeLLM(settings)
    app.state.llm = app.state.llm_factory(s)

    async with app.router.lifespan_context(app):
        # Let the subscriber finish subscribing.
        await asyncio.sleep(0.1)
        # Edit config on disk (do NOT mutate the in-memory `s` — that would
        # be the same object as app.state.settings and fake-pass the test).
        s2 = load_config(cfg)
        s2.llm.model = "reloaded-model-xyz"
        save_config(s2, cfg)
        n = await publish_reload(redis_client)
        assert n >= 1
        # Wait for subscriber to consume.
        for _ in range(40):
            if app.state.settings.llm.model == "reloaded-model-xyz":
                break
            await asyncio.sleep(0.05)
        assert app.state.settings.llm.model == "reloaded-model-xyz"
        # LLM was rebuilt with new settings.
        assert "reloaded-model-xyz" in rebuilt

    await redis_client.aclose()
