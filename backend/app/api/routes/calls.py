"""Telephony smoke-test slice.

This is the minimal, DB-independent path that proves the telephony plumbing end
to end: place an outbound call (Plivo) whose answer webhook (served here) speaks
a greeting via TTS, then hangs up. The full AI conversation pipeline
(STT -> LLM -> TTS streaming) is built on top of these same pieces later.

Endpoints:
  POST /calls/test    place a test call (guarded by SMOKE_TEST_TOKEN header)
  GET  /calls/answer  PUBLIC — Plivo fetches this to get call instructions (XML)
  POST /calls/status  PUBLIC — Plivo posts call status events here
  GET  /calls/numbers list rented Plivo numbers (guarded)
"""

from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import quote
from xml.sax.saxutils import escape

from fastapi import APIRouter, Form, Header, Query, Response, WebSocket
from pydantic import BaseModel, Field

from app.api.deps import AuthContextDep, DBSession, SettingsDep
from app.core.config import Settings, get_settings
from app.core.database import Database
from app.core.exceptions import ForbiddenError, ProviderError, ValidationError
from app.core.logging import get_logger
from app.providers.base import OutboundCallRequest
from app.providers.telephony.plivo import PlivoProvider
from app.repositories.agent import AgentRepository
from app.services.agent_service import AgentService
from app.utils.phone import normalize_number

log = get_logger(__name__)
router = APIRouter(prefix="/calls", tags=["calls"])

DEFAULT_GREETING = (
    "Hello! This is a test call from your A I calling agent. "
    "If you can hear this message, your telephony setup is working correctly. "
    "Goodbye!"
)


def _require_smoke_token(settings: Settings, token: str | None) -> None:
    if not settings.smoke_test_token:
        raise ForbiddenError("Call test endpoint is disabled (set SMOKE_TEST_TOKEN)")
    if token != settings.smoke_test_token:
        raise ForbiddenError("Invalid smoke-test token")


class TestCallRequest(BaseModel):
    to: str = Field(min_length=4, description="Destination number")
    from_: str | None = Field(default=None, alias="from", description="Caller ID override")
    message: str | None = Field(default=None, description="What the agent should say")

    model_config = {"populate_by_name": True}


class TestCallResponse(BaseModel):
    status: str
    request_uuid: str
    to: str
    from_: str


@router.post("/test", response_model=TestCallResponse)
async def place_test_call(
    body: TestCallRequest,
    settings: SettingsDep,
    x_smoke_token: Annotated[str | None, Header()] = None,
) -> TestCallResponse:
    _require_smoke_token(settings, x_smoke_token)

    from_number = body.from_ or settings.plivo_caller_id
    if not from_number:
        raise ValidationError("No caller ID: pass 'from' or set PLIVO_CALLER_ID")

    to = normalize_number(body.to, default_country_code=settings.default_country_code)
    frm = normalize_number(from_number, default_country_code=settings.default_country_code)
    message = body.message or DEFAULT_GREETING

    answer_url = (
        f"{settings.public_base_url}{settings.api_v1_prefix}/calls/answer"
        f"?message={quote(message)}"
    )
    hangup_url = f"{settings.public_base_url}{settings.api_v1_prefix}/calls/status"

    provider = PlivoProvider(settings)
    handle = await provider.place_call(
        OutboundCallRequest(
            to_number=to,
            from_number=frm,
            answer_url=answer_url,
            hangup_url=hangup_url,
            record=False,
        )
    )
    log.info("test_call_placed", to=to, from_=frm, request_uuid=handle.provider_call_id)
    return TestCallResponse(
        status="call_fired", request_uuid=handle.provider_call_id, to=to, from_=frm
    )


@router.get("/answer")
async def answer(
    message: Annotated[str, Query()] = DEFAULT_GREETING,
    voice: Annotated[str, Query()] = "Polly.Aditi",
    language: Annotated[str, Query()] = "en-IN",
) -> Response:
    """PUBLIC. Returns Plivo XML instructing the call to speak `message`."""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Speak voice="{escape(voice, {chr(34): "&quot;"})}" '
        f'language="{escape(language, {chr(34): "&quot;"})}">{escape(message)}</Speak>'
        "</Response>"
    )
    return Response(content=xml, media_type="application/xml")


@router.post("/status")
async def status_callback(
    CallUUID: Annotated[str | None, Form()] = None,
    CallStatus: Annotated[str | None, Form()] = None,
    From: Annotated[str | None, Form()] = None,
    To: Annotated[str | None, Form()] = None,
    HangupCause: Annotated[str | None, Form()] = None,
) -> Response:
    """PUBLIC. Plivo posts call lifecycle events here; we just log them."""
    log.info(
        "call_status",
        call_uuid=CallUUID,
        status=CallStatus,
        from_=From,
        to=To,
        hangup_cause=HangupCause,
    )
    return Response(status_code=204)


@router.get("/numbers")
async def list_numbers(
    settings: SettingsDep,
    x_smoke_token: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    _require_smoke_token(settings, x_smoke_token)
    try:
        numbers = await PlivoProvider(settings).list_numbers()
    except ProviderError as exc:
        raise exc
    slim = [
        {
            "number": n.get("number"),
            "type": n.get("number_type"),
            "voice_enabled": n.get("voice_enabled"),
        }
        for n in numbers
    ]
    return {"count": len(slim), "numbers": slim}


# --------------------------------------------------------------------------- #
# Feature 4: real-time agentic voice
# --------------------------------------------------------------------------- #
class AgentCallRequest(BaseModel):
    to: str = Field(min_length=4)
    agent_id: uuid.UUID
    from_: str | None = Field(default=None, alias="from")

    model_config = {"populate_by_name": True}


@router.post("/agent", response_model=TestCallResponse)
async def place_agent_call(
    body: AgentCallRequest,
    ctx: AuthContextDep,
    db: DBSession,
    settings: SettingsDep,
) -> TestCallResponse:
    """Place an outbound call handled live by an AI agent (streaming voice)."""
    agent = await AgentService(db).get(body.agent_id, ctx.organization_id)

    from_number = body.from_ or settings.plivo_caller_id
    if not from_number:
        raise ValidationError("No caller ID: pass 'from' or set PLIVO_CALLER_ID")

    to = normalize_number(body.to, default_country_code=settings.default_country_code)
    frm = normalize_number(from_number, default_country_code=settings.default_country_code)
    answer_url = (
        f"{settings.public_base_url}{settings.api_v1_prefix}/calls/stream-answer"
        f"?agent_id={agent.id}"
    )
    hangup_url = f"{settings.public_base_url}{settings.api_v1_prefix}/calls/status"

    handle = await PlivoProvider(settings).place_call(
        OutboundCallRequest(
            to_number=to, from_number=frm, answer_url=answer_url,
            hangup_url=hangup_url, record=False,
        )
    )
    log.info("agent_call_placed", agent_id=str(agent.id), to=to, request_uuid=handle.provider_call_id)
    return TestCallResponse(
        status="call_fired", request_uuid=handle.provider_call_id, to=to, from_=frm
    )


@router.get("/stream-answer")
async def stream_answer(
    settings: SettingsDep, agent_id: Annotated[str, Query()]
) -> Response:
    """PUBLIC. Plivo fetches this on answer; returns Stream XML pointing at our WS."""
    ws_base = settings.public_base_url.replace("https://", "wss://").replace("http://", "ws://")
    ws_url = f"{ws_base}{settings.api_v1_prefix}/calls/stream?agent_id={agent_id}"
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        '<Stream bidirectional="true" keepCallAlive="true" '
        f'contentType="audio/x-mulaw;rate=8000">{escape(ws_url)}</Stream>'
        "</Response>"
    )
    return Response(content=xml, media_type="application/xml")


@router.websocket("/stream")
async def voice_stream(websocket: WebSocket) -> None:
    """PUBLIC. Plivo bidirectional audio WebSocket; runs the agent's voice pipeline."""
    agent_id = websocket.query_params.get("agent_id")
    await websocket.accept()

    settings = get_settings()
    db: Database = websocket.app.state.db

    agent = None
    if agent_id:
        try:
            aid = uuid.UUID(agent_id)
        except ValueError:
            aid = None
        if aid is not None:
            async with db.session_factory() as session:
                agent = await AgentRepository(session).get(aid)

    if agent is None:
        await websocket.close(code=1008)
        return

    # Lazy import so heavy Pipecat deps load only when a call actually connects.
    from app.voice.pipeline import run_voice_agent

    try:
        await run_voice_agent(websocket, agent, settings)
    except Exception:
        log.error("voice_stream_error", exc_info=True)
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
