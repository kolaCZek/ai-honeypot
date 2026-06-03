"""Path -> page type heuristic."""
from __future__ import annotations

_TEXT_EXACT = {"/robots.txt", "/.env", "/sitemap.xml"}
_TEXT_SUFFIXES = (".txt", ".xml")


def detect_page_type(path: str) -> str:
    """Return one of: 'html', 'json', 'text'."""
    p = (path or "/").split("?", 1)[0].split("#", 1)[0]

    if p.startswith("/api/") or p.endswith(".json"):
        return "json"
    if p in _TEXT_EXACT or p.endswith(_TEXT_SUFFIXES):
        return "text"
    return "html"
