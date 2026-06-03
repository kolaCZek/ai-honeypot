"""Typed configuration loader (YAML -> Pydantic v2) with secret_key bootstrap."""
from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

# Reload-channel constant (Redis pub/sub).
RELOAD_CHANNEL = "config:reload"
# How many timestamped backups of config.yaml to retain.
BACKUP_KEEP = 10


class LLMConfig(BaseModel):
    endpoint: str
    api_key: str
    model: str
    timeout_s: float = 30
    max_tokens: int = 1500
    cost_per_mtok_in: float = 0.0
    cost_per_mtok_out: float = 0.0


class SlowdownConfig(BaseModel):
    enabled: bool = True
    min_s: float = 10
    max_s: float = 30


class RateLimitConfig(BaseModel):
    max_concurrent_per_ip: int = 3
    block_on_exceed: bool = False


class RetentionConfig(BaseModel):
    max_ips: Optional[int] = None
    ttl_days: Optional[int] = None


class FakeLoginConfig(BaseModel):
    success_ratio: float = 0.75


class HoneypotConfig(BaseModel):
    port: int = 8888
    slowdown: SlowdownConfig = Field(default_factory=SlowdownConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    whitelist_ips: list[str] = Field(default_factory=list)
    bait_endpoints: list[str] = Field(default_factory=list)
    fake_login: FakeLoginConfig = Field(default_factory=FakeLoginConfig)
    secret_key_file: str = "/data/secret.key"


class BasicAuthConfig(BaseModel):
    username: str
    password: str


class DashboardConfig(BaseModel):
    port: int = 8080
    basic_auth: BasicAuthConfig


class StorageConfig(BaseModel):
    sqlite_path: str
    redis_url: str = "redis://redis:6379/0"


class Settings(BaseModel):
    llm: LLMConfig
    honeypot: HoneypotConfig
    dashboard: DashboardConfig
    storage: StorageConfig
    # Loaded/generated lazily, not in YAML.
    secret_key: bytes = b""


def _ensure_secret_key(path: str) -> bytes:
    p = Path(path)
    if p.exists():
        return p.read_bytes()
    p.parent.mkdir(parents=True, exist_ok=True)
    key = os.urandom(32)
    p.write_bytes(key)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return key


def load_config(path: str | os.PathLike) -> Settings:
    """Load YAML config, validate, bootstrap secret_key file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config file not found: {p}")
    raw = yaml.safe_load(p.read_text()) or {}
    settings = Settings(**raw)
    settings.secret_key = _ensure_secret_key(settings.honeypot.secret_key_file)
    return settings


def _prune_backups(directory: Path, prefix: str, keep: int) -> None:
    backups = sorted(directory.glob(f"{prefix}.bak-*"))
    excess = len(backups) - keep
    for old in backups[:max(0, excess)]:
        try:
            old.unlink()
        except OSError:
            pass


def save_config(settings: Settings, path: str | os.PathLike) -> Path:
    """Atomically write settings to YAML and rotate timestamped backups.

    - Excludes the in-memory `secret_key` field (kept in a sidecar file).
    - Backs up the previous file as `<name>.bak-<UTC-ISO>` (last BACKUP_KEEP).
    - Atomic via NamedTemporaryFile + os.replace in the same directory.
    - Preserves original file permissions when present.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    data = settings.model_dump(exclude={"secret_key"})
    body = yaml.safe_dump(data, sort_keys=False, default_flow_style=False)

    orig_mode: Optional[int] = None
    if p.exists():
        try:
            orig_mode = p.stat().st_mode & 0o777
        except OSError:
            orig_mode = None
        # Backup with UTC timestamp; ':' is safe on Linux but replace for portability.
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bak = p.with_name(f"{p.name}.bak-{ts}")
        try:
            shutil.copy2(p, bak)
            if orig_mode is not None:
                try:
                    os.chmod(bak, orig_mode)
                except OSError:
                    pass
        except OSError:
            pass
        _prune_backups(p.parent, p.name, BACKUP_KEEP)

    # Atomic write: write to temp in same dir, then os.replace.
    fd, tmp_name = tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w") as f:
            f.write(body)
        if orig_mode is not None:
            try:
                os.chmod(tmp_name, orig_mode)
            except OSError:
                pass
        os.replace(tmp_name, p)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return p
