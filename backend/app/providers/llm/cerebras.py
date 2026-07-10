"""Cerebras adapter implementing the LLMProvider port.

Cerebras exposes an ultra-fast OpenAI-compatible /chat/completions API.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import Settings
from app.core.exceptions import ProviderError
from app.providers.base import LLMMessage, LLMProvider, LLMResponse

# Valid Cerebras models; fallback to gpt-oss-120b if given an old/external model string.
_DEFAULT_CEREBRAS_MODEL = "gpt-oss-120b"


def _normalize_model(model: str) -> str:
    if not model or "/" in model or model.startswith("openai") or model.startswith("openrouter"):
        return _DEFAULT_CEREBRAS_MODEL
    return model


class CerebrasProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        self._base = settings.cerebras_base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {settings.cerebras_api_key}",
            "Content-Type": "application/json",
        }

    def _payload(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        temperature: float,
        tools: list[dict[str, Any]] | None,
        max_tokens: int | None,
        stream: bool,
    ) -> dict[str, Any]:
        target_model = _normalize_model(model)
        payload: dict[str, Any] = {
            "model": target_model,
            "temperature": temperature,
            "stream": stream,
            "messages": [_to_wire(m) for m in messages],
        }
        if tools:
            payload["tools"] = tools
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return payload

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        payload = self._payload(
            messages,
            model=model,
            temperature=temperature,
            tools=tools,
            max_tokens=max_tokens,
            stream=False,
        )
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{self._base}/chat/completions", headers=self._headers, json=payload
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Cerebras request failed: {exc}") from exc

        if resp.status_code != 200:
            raise ProviderError(f"Cerebras error {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message", {})
        return LLMResponse(
            content=message.get("content") or "",
            tool_calls=message.get("tool_calls") or [],
            finish_reason=choice.get("finish_reason"),
            usage=data.get("usage") or {},
        )

    async def stream_complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        payload = self._payload(
            messages,
            model=model,
            temperature=temperature,
            tools=tools,
            max_tokens=max_tokens,
            stream=True,
        )
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                async with client.stream(
                    "POST",
                    f"{self._base}/chat/completions",
                    headers=self._headers,
                    json=payload,
                ) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        raise ProviderError(
                            f"Cerebras error {resp.status_code}: {body[:300]!r}"
                        )
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[len("data:") :].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                        piece = delta.get("content")
                        if piece:
                            yield piece
        except httpx.HTTPError as exc:
            raise ProviderError(f"Cerebras stream failed: {exc}") from exc


def _to_wire(m: LLMMessage) -> dict[str, Any]:
    wire: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.name:
        wire["name"] = m.name
    if m.tool_call_id:
        wire["tool_call_id"] = m.tool_call_id
    return wire
