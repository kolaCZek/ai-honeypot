"""nginx-mimicked error pages so the honeypot looks like an aging nginx."""
from __future__ import annotations

NGINX_VERSION = "nginx/1.24.0"
_HEADERS = {"Server": NGINX_VERSION, "Content-Type": "text/html"}


def _page(status_line: str) -> str:
    return (
        f"<html>\r\n<head><title>{status_line}</title></head>\r\n"
        f"<body>\r\n<center><h1>{status_line}</h1></center>\r\n"
        f"<hr><center>{NGINX_VERSION}</center>\r\n</body>\r\n</html>\r\n"
    )


def nginx_404() -> tuple[str, dict, int]:
    return _page("404 Not Found"), dict(_HEADERS), 404


def nginx_500() -> tuple[str, dict, int]:
    return _page("500 Internal Server Error"), dict(_HEADERS), 500


def nginx_429() -> tuple[str, dict, int]:
    return _page("429 Too Many Requests"), dict(_HEADERS), 429
