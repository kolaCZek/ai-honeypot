"""OpenAI-compatible async LLM client (no SDK, pure httpx)."""
from __future__ import annotations

from typing import Optional

import httpx

from .config import Settings


class LLMError(RuntimeError):
    pass


class LLMClient:
    """Thin async wrapper around POST {endpoint}/chat/completions."""

    def __init__(self, settings: Settings, *, transport: Optional[httpx.AsyncBaseTransport] = None):
        self._cfg = settings.llm
        self._client = httpx.AsyncClient(
            timeout=self._cfg.timeout_s,
            transport=transport,
            headers={
                "Authorization": f"Bearer {self._cfg.api_key}",
                "Content-Type": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def generate(
        self, prompt: str, *, system: Optional[str] = None
    ) -> tuple[str, int, int]:
        """Call chat/completions. Returns (text, tokens_in, tokens_out)."""
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self._cfg.model,
            "messages": messages,
            "max_tokens": self._cfg.max_tokens,
        }
        url = self._cfg.endpoint.rstrip("/") + "/chat/completions"

        try:
            resp = await self._client.post(url, json=payload)
        except httpx.HTTPError as e:
            raise LLMError(f"LLM transport error: {e}") from e

        if resp.status_code != 200:
            raise LLMError(f"LLM HTTP {resp.status_code}: {resp.text[:300]}")

        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {}) or {}
            t_in = int(usage.get("prompt_tokens", 0))
            t_out = int(usage.get("completion_tokens", 0))
        except (KeyError, IndexError, ValueError, TypeError) as e:
            raise LLMError(f"LLM response parse error: {e}") from e

        return text, t_in, t_out
