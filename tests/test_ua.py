import pytest
from shared.ua import parse_ua


@pytest.mark.parametrize("ua,is_bot", [
    ("curl/8.4.0", True),
    ("Wget/1.21.4", True),
    ("python-requests/2.31.0", True),
    ("Scrapy/2.11", True),
    ("Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", True),
    ("Java/17.0.1", True),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", False),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15", False),
])
def test_is_bot(ua, is_bot):
    assert parse_ua(ua)["is_bot"] is is_bot


def test_fields_present():
    info = parse_ua("Mozilla/5.0 (Windows NT 10.0) Chrome/120.0.0.0 Safari/537.36")
    assert info["browser"] == "Chrome"
    assert info["os"] == "Windows"
    assert info["device"] == "desktop"
