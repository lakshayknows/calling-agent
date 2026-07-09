"""Provider interfaces (ports) for all external vendors.

Business/service logic depends ONLY on these abstract interfaces — never on
Plivo, Sarvam, OpenRouter, R2, or Redis directly. Concrete adapters live under
`app/providers/<domain>/` and are wired in via dependency injection, so any
vendor can be swapped without touching business code.

Feature 1 defines the contracts. Concrete implementations arrive with the
features that need them (telephony/speech/LLM in Feature 3–5, storage in
Feature 5).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# --------------------------------------------------------------------------- #
# Telephony
# --------------------------------------------------------------------------- #
class CallStatus(str, Enum):
    QUEUED = "queued"
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BUSY = "busy"
    NO_ANSWER = "no_answer"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass(slots=True)
class OutboundCallRequest:
    to_number: str
    from_number: str
    answer_url: str  # webhook the telephony vendor hits when the call is answered
    hangup_url: str | None = None
    record: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CallHandle:
    provider_call_id: str
    status: CallStatus
    raw: dict[str, Any] = field(default_factory=dict)


class TelephonyProvider(ABC):
    """Places and controls phone calls (e.g. Plivo)."""

    @abstractmethod
    async def place_call(self, request: OutboundCallRequest) -> CallHandle: ...

    @abstractmethod
    async def hangup(self, provider_call_id: str) -> None: ...

    @abstractmethod
    async def transfer(self, provider_call_id: str, to_number: str) -> None: ...


# --------------------------------------------------------------------------- #
# Speech (STT + TTS)
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class TranscriptChunk:
    text: str
    is_final: bool
    confidence: float | None = None


class SpeechToTextProvider(ABC):
    """Streaming STT (e.g. Sarvam). Consumes audio frames, yields transcripts."""

    @abstractmethod
    def stream_transcribe(
        self,
        audio: AsyncIterator[bytes],
        *,
        language: str = "en-IN",
        sample_rate: int = 8000,
    ) -> AsyncIterator[TranscriptChunk]: ...


class TextToSpeechProvider(ABC):
    """Streaming TTS (e.g. Sarvam). Consumes text, yields audio frames."""

    @abstractmethod
    def stream_synthesize(
        self,
        text: str,
        *,
        language: str = "en-IN",
        voice: str | None = None,
        sample_rate: int = 8000,
    ) -> AsyncIterator[bytes]: ...


# --------------------------------------------------------------------------- #
# LLM
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class LLMMessage:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    name: str | None = None
    tool_call_id: str | None = None


@dataclass(slots=True)
class LLMResponse:
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


class LLMProvider(ABC):
    """Chat completion (e.g. OpenRouter). Streaming + tool calling."""

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse: ...

    @abstractmethod
    def stream_complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]: ...


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class StoredObject:
    key: str
    url: str
    size: int
    content_type: str


class StorageProvider(ABC):
    """Object storage (e.g. Cloudflare R2). Only URLs/metadata hit the DB."""

    @abstractmethod
    async def upload(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> StoredObject: ...

    @abstractmethod
    async def presigned_url(self, key: str, *, expires_in: int = 3600) -> str: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...
