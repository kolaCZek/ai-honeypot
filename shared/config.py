"""Typed configuration loader (YAML -> Pydantic v2) with secret_key bootstrap."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


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
