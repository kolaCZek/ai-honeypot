from honeypot.error_pages import nginx_404, nginx_500, nginx_429


def test_404():
    body, headers, status = nginx_404()
    assert status == 404
    assert "404 Not Found" in body
    assert headers["Server"].startswith("nginx/")


def test_500():
    body, headers, status = nginx_500()
    assert status == 500
    assert "500" in body
    assert headers["Server"].startswith("nginx/")


def test_429():
    body, headers, status = nginx_429()
    assert status == 429
    assert "429" in body
