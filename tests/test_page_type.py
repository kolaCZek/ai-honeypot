import pytest

from shared.page_type import detect_page_type


@pytest.mark.parametrize("path,expected", [
    ("/api/users", "json"),
    ("/api/v1/status", "json"),
    ("/config.json", "json"),
    ("/.env", "text"),
    ("/robots.txt", "text"),
    ("/sitemap.xml", "text"),
    ("/some/file.xml", "text"),
    ("/notes.txt", "text"),
    ("/settings", "html"),
    ("/admin", "html"),
    ("/", "html"),
])
def test_detect(path, expected):
    assert detect_page_type(path) == expected
