"""User-Agent parsing + simple bot heuristic."""
from __future__ import annotations

import re

_BOT_RE = re.compile(
    r"(?i)(requests|curl|wget|go-http|python|scrapy|bot|crawler|spider|httpx|java/)"
)


def _detect_browser(ua: str) -> str:
    s = ua or ""
    low = s.lower()
    if "edg/" in low:
        return "Edge"
    if "chrome/" in low and "chromium" not in low:
        return "Chrome"
    if "firefox/" in low:
        return "Firefox"
    if "safari/" in low and "chrome/" not in low:
        return "Safari"
    if "curl/" in low:
        return "curl"
    if "wget/" in low:
        return "wget"
    if "python-requests" in low:
        return "python-requests"
    if "httpx" in low:
        return "httpx"
    return "unknown"


def _detect_os(ua: str) -> str:
    s = (ua or "").lower()
    if "windows" in s:
        return "Windows"
    if "mac os x" in s or "macintosh" in s:
        return "macOS"
    if "android" in s:
        return "Android"
    if "iphone" in s or "ipad" in s or "ios" in s:
        return "iOS"
    if "linux" in s:
        return "Linux"
    return "unknown"


def _detect_device(ua: str) -> str:
    s = (ua or "").lower()
    if "mobile" in s or "iphone" in s or "android" in s:
        return "mobile"
    if "ipad" in s or "tablet" in s:
        return "tablet"
    return "desktop"


def parse_ua(ua: str) -> dict:
    """Return {browser, os, device, is_bot}. is_bot via regex heuristic."""
    ua = ua or ""
    return {
        "browser": _detect_browser(ua),
        "os": _detect_os(ua),
        "device": _detect_device(ua),
        "is_bot": bool(_BOT_RE.search(ua)),
    }
