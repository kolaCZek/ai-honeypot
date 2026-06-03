from honeypot.link_token import sanitize_and_sign_links, verify, sign

SECRET = b"\x02" * 32
IP = "9.9.9.9"


def test_html_sanitizer_drops_bad_keeps_good():
    html = """
    <html><body>
      <a href="/users">u</a>
      <a href="/reports/2025?x=1">r</a>
      <a href="http://evil.com">e</a>
      <a href="https://evil.com">e</a>
      <a href="javascript:alert(1)">j</a>
      <a href="//cdn.com/x">p</a>
      <a href="mailto:a@b.com">m</a>
      <a href="#frag">h</a>
    </body></html>
    """
    out = sanitize_and_sign_links(html, IP, SECRET, "text/html")
    assert "evil.com" not in out
    assert "javascript:" not in out
    assert "mailto:" not in out
    assert "//cdn.com" not in out
    assert "/users?_t=" in out
    assert "/reports/2025" in out and "_t=" in out
    # Good token verifies
    tok = sign(IP, "/users", SECRET)
    assert tok in out


def test_html_sanitizer_preserves_existing_query():
    html = '<a href="/x?a=1&b=2">x</a>'
    out = sanitize_and_sign_links(html, IP, SECRET, "text/html")
    assert "a=1" in out and "b=2" in out and "_t=" in out


def test_json_sanitizer_signs_internal_links():
    import json
    body = json.dumps({"_links": {"self": "/api/v1/users", "ext": "https://x"}, "ok": True})
    out = sanitize_and_sign_links(body, IP, SECRET, "application/json")
    data = json.loads(out)
    self_url = data["_links"]["self"]
    assert "_t=" in self_url
    assert "/api/v1/users" in self_url
