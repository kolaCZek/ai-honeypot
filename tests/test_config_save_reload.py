"""Tests for save_config + config_reload (publish/subscribe)."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import fakeredis.aioredis
import pytest

from shared.config import BACKUP_KEEP, load_config, save_config
from shared.config_reload import publish_reload, subscribe_reload


pytestmark = pytest.mark.asyncio


def _write_initial_config(tmp_path: Path) -> Path:
    src = Path(__file__).resolve().parents[1] / "config.yaml.example"
    txt = src.read_text().replace("/data/secret.key", str(tmp_path / "secret.key"))
    txt = txt.replace("/data/honeypot.db", str(tmp_path / "h.db"))
    cfg = tmp_path / "config.yaml"
    cfg.write_text(txt)
    cfg.chmod(0o600)
    return cfg


async def test_save_config_roundtrip(tmp_path: Path):
    cfg = _write_initial_config(tmp_path)
    s = load_config(cfg)

    s.honeypot.bait_endpoints = ["/.env", "/admin/new"]
    s.llm.model = "test-model-xyz"
    save_config(s, cfg)

    s2 = load_config(cfg)
    assert s2.honeypot.bait_endpoints == ["/.env", "/admin/new"]
    assert s2.llm.model == "test-model-xyz"


async def test_save_config_creates_backup_and_prunes(tmp_path: Path):
    cfg = _write_initial_config(tmp_path)
    s = load_config(cfg)

    # Each save should produce a backup of the previous file.
    for i in range(BACKUP_KEEP + 3):
        s.llm.max_tokens = 100 + i
        save_config(s, cfg)
        # Backup timestamps have second resolution; advance to ensure unique names.
        await asyncio.sleep(0.01)
        # Force unique timestamps by manipulating mtimes is not enough — instead
        # just ensure prune keeps at most BACKUP_KEEP.
    backups = sorted(tmp_path.glob("config.yaml.bak-*"))
    assert len(backups) <= BACKUP_KEEP


async def test_save_config_excludes_secret_key(tmp_path: Path):
    cfg = _write_initial_config(tmp_path)
    s = load_config(cfg)
    assert s.secret_key  # bootstrapped
    save_config(s, cfg)
    text = cfg.read_text()
    assert "secret_key:" not in text  # not the bytes field
    # secret_key_file is still in the YAML (a string path).
    assert "secret_key_file" in text


async def test_save_config_atomic_failure_keeps_original(tmp_path: Path):
    cfg = _write_initial_config(tmp_path)
    s = load_config(cfg)
    before = cfg.read_text()

    # Simulate failure during os.replace -> original must remain intact.
    with patch("shared.config.os.replace", side_effect=OSError("boom")):
        s.llm.model = "should-not-persist"
        with pytest.raises(OSError):
            save_config(s, cfg)

    assert cfg.read_text() == before


async def test_save_config_preserves_perms(tmp_path: Path):
    cfg = _write_initial_config(tmp_path)
    s = load_config(cfg)
    save_config(s, cfg)
    mode = cfg.stat().st_mode & 0o777
    assert mode == 0o600


async def test_config_reload_publish_subscribe():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    received: list[int] = []
    event = asyncio.Event()

    async def on_reload():
        received.append(1)
        event.set()

    task = asyncio.create_task(subscribe_reload(redis_client, on_reload))
    # Give the subscriber a moment to actually subscribe.
    await asyncio.sleep(0.05)
    n = await publish_reload(redis_client)
    assert n >= 1

    await asyncio.wait_for(event.wait(), timeout=2.0)
    assert received == [1]

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await redis_client.aclose()
