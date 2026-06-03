"""HMAC link-token gating and HTML/JSON link sanitization."""
from __future__ import annotations

import hmac
import json
from hashlib import sha256
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup


_BAD_PREFIXES = ("javascript:", "mailto:", "http://", "https://", "data:", "ftp:", "//")


def sign(ip: str, path: str, secret_key: bytes) -> str:
    """Return 16-hex-char HMAC token bound to (ip, path)."""
    msg = f"{ip}|{path}".encode()
    digest = hmac.new(secret_key, msg, sha256).digest()
    return digest[:8].hex()  # 16 hex chars


def verify(ip: str, path: str, token: str, secret_key: bytes) -> bool:
    if not token:
        return False
    try:
        expected = sign(ip, path, secret_key)
    except Exception:
        return False
    return hmac.compare_digest(expected, token)


def _is_bad_link(href: str) -> bool:
    if not href:
        return True
    h = href.strip()
    if not h:
        return True
    if h.startswith("#"):
        return True
    low = h.lower()
    for p in _BAD_PREFIXES:
        if low.startswith(p):
            return True
    if not h.startswith("/"):
        return True
    return False


def _sign_url(url: str, ip: str, secret_key: bytes) -> str:
    """Add ?_t=<token> preserving existing query (path only signed)."""
    parts = urlsplit(url)
    path = parts.path
    if not path.startswith("/"):
        return url
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "_t"]
    q.append(("_t", sign(ip, path, secret_key)))
    return urlunsplit((parts.scheme, parts.netloc, path, urlencode(q), parts.fragment))


def _sanitize_html(html: str, ip: str, secret_key: bytes) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for a in list(soup.find_all("a")):
        href = a.get("href", "")
        if _is_bad_link(href):
            a.decompose()
            continue
        a["href"] = _sign_url(href, ip, secret_key)
    # Strip forms with bad action; rewrite good ones.
    for form in soup.find_all("form"):
        action = form.get("action", "")
        if action and _is_bad_link(action):
            del form["action"]
        elif action:
            form["action"] = _sign_url(action, ip, secret_key)
    return str(soup)


def _sanitize_json_obj(obj, ip: str, secret_key: bytes):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(v, str) and v.startswith("/") and not _is_bad_link(v):
                out[k] = _sign_url(v, ip, secret_key)
            elif isinstance(v, str) and _is_bad_link(v) and (v.startswith("//") or v.lower().startswith(("http://", "https://", "javascript:"))):
                # drop external/bad URLs in known link-ish fields
                if k in {"href", "url", "link"}:
                    continue
                out[k] = v
            else:
                out[k] = _sanitize_json_obj(v, ip, secret_key)
        return out
    if isinstance(obj, list):
        return [_sanitize_json_obj(x, ip, secret_key) for x in obj]
    return obj


def _sanitize_json(text: str, ip: str, secret_key: bytes) -> str:
    try:
        data = json.loads(text)
    except ValueError:
        return text
    return json.dumps(_sanitize_json_obj(data, ip, secret_key), indent=2)


def sanitize_and_sign_links(
    body: str, ip: str, secret_key: bytes, content_type: str
) -> str:
    """Sanitize body, removing/cleaning bad links and signing good /-links."""
    ct = (content_type or "").lower()
    if "json" in ct:
        return _sanitize_json(body, ip, secret_key)
    return _sanitize_html(body, ip, secret_key)
