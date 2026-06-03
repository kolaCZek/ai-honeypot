"""Bait endpoint helpers."""
from __future__ import annotations

import random

from shared.config import Settings


def is_bait(path: str, settings: Settings) -> bool:
    p = (path or "/").split("?", 1)[0]
    baits = settings.honeypot.bait_endpoints or []
    return p in baits


def random_login_success(settings: Settings) -> bool:
    return random.random() < settings.honeypot.fake_login.success_ratio
