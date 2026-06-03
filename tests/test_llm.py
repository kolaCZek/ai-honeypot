import json

import httpx
import pytest

from shared.config import (
    BasicAuthConfig,
    DashboardConfig,
    HoneypotConfig,
    LLMConfig,
    Settings,
    StorageConfig,
)
from shared.llm import LLMClient, LLMError


def _settings() -> Settings:
    return Settings(
        llm=LLMConfig(
            endpoint="https://example.test/v1",
            api_key="sk-test",
            model="gpt-test",
            timeout_s=5,
            max_tokens=42,
        ),
        honeypot=HoneypotConfig(),
        dashboard=DashboardConfig(basic_auth=BasicAuthConfig(username="a", password="b")),
        storage=StorageConfig(sqlite_path=":memory:"),
    )


def _ok_handler(captured: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "<!doctype html><h1>ok</h1>"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 22},
            },
        )
    return handler


async def test_generate_payload_and_parse():
    captured: dict = {}
    transport = httpx.MockTransport(_ok_handler(captured))
    client = LLMClient(_settings(), transport=transport)
    try:
        text, t_in, t_out = await client.generate("hello", system="be brief")
    finally:
        await client.aclose()

    assert text.startswith("<!doctype html>")
    assert (t_in, t_out) == (11, 22)
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["auth"] == "Bearer sk-test"
    body = captured["body"]
    assert body["model"] == "gpt-test"
    assert body["max_tokens"] == 42
    assert body["messages"][0] == {"role": "system", "content": "be brief"}
    assert body["messages"][1] == {"role": "user", "content": "hello"}


async def test_non_200_raises():
    def h(_req):
        return httpx.Response(500, text="boom")
    client = LLMClient(_settings(), transport=httpx.MockTransport(h))
    try:
        with pytest.raises(LLMError):
            await client.generate("x")
    finally:
        await client.aclose()
