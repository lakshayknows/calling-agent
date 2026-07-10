"""Real-time voice pipeline (Pipecat) for agentic phone calls.

Runs one Pipecat pipeline per connected call:

    Plivo WS  ->  Sarvam STT  ->  [agent context]  ->  OpenRouter LLM  ->  Sarvam TTS  ->  Plivo WS
                                        ^ Silero VAD = turn-taking + barge-in

Pipecat is the orchestration adapter for the real-time path; the agent's config
(prompt, greeting, voice, language, model) still comes from our DB. Heavy Pipecat
imports live at module top, but this module is imported lazily (only when a call
WebSocket connects), so normal REST requests never pay the import cost.
"""

from __future__ import annotations

import asyncio

from starlette.websockets import WebSocket

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.agent import Agent

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InputAudioRawFrame,
    StartFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.plivo import PlivoFrameSerializer
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import SarvamTTSService
from pipecat.transcriptions.language import Language
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

log = get_logger(__name__)

# Sarvam bulbul:v2 speakers (see TTS_MODEL_CONFIGS). Agent voices outside this
# set fall back to a safe default so TTS never fails on an unknown voice.
_VALID_V2_VOICES = {"anushka", "abhilash", "manisha", "vidya", "arya", "karun", "hitesh"}
_DEFAULT_VOICE = "anushka"
_STT_MODEL = "saarika:v2.5"
_TTS_MODEL = "bulbul:v2"

_LANGUAGES = {
    "en-in": Language.EN_IN,
    "hi-in": Language.HI_IN,
    "en": Language.EN,
    "hi": Language.HI,
}


def _language(code: str | None) -> Language:
    return _LANGUAGES.get((code or "en-IN").lower(), Language.EN_IN)


def _render(text: str, variables: dict) -> str:
    try:
        return text.format(**variables)
    except (KeyError, IndexError, ValueError):
        return text


class InputGate(FrameProcessor):
    """Half-duplex echo gate — makes the agent usable on speakerphone.

    Sits right after ``transport.input()`` and DROPS the caller's inbound audio /
    turn frames whenever the bot is speaking, so the bot never transcribes its own
    voice echoing back through the phone (severe on speaker) and background noise
    during the bot's turn can't interrupt it. The gate opens the moment the bot
    finishes so the caller is heard normally between turns.

    Bot speaking state is tracked from ``BotStartedSpeakingFrame`` /
    ``BotStoppedSpeakingFrame`` (pushed by the output transport and seen here
    regardless of direction). The gate starts CLOSED when there's an opening
    greeting so the callee's "Hello?" can't wipe it. A per-turn safety timer
    reopens the gate if a bot turn never reports finishing, so a TTS hiccup can't
    leave the call permanently deaf.
    """

    def __init__(self, *, start_closed: bool, max_gate_secs: float = 20.0) -> None:
        super().__init__()
        self._bot_speaking = start_closed
        self._max_gate_secs = max_gate_secs
        self._safety_task: asyncio.Task | None = None

    def _arm_safety(self) -> None:
        if self._safety_task is not None:
            self._safety_task.cancel()
        self._safety_task = asyncio.create_task(self._safety_release())

    async def _safety_release(self) -> None:
        try:
            await asyncio.sleep(self._max_gate_secs)
        except asyncio.CancelledError:
            return
        self._safety_task = None
        self._bot_speaking = False
        log.info("input_gate_safety_release")

    def _cancel_safety(self) -> None:
        if self._safety_task is not None:
            self._safety_task.cancel()
            self._safety_task = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame) and self._bot_speaking:
            self._arm_safety()  # protect the opening greeting
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
            self._arm_safety()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
            self._cancel_safety()

        # Suppress the caller's mic while the bot talks → no echo/self-interrupt.
        if (
            self._bot_speaking
            and direction == FrameDirection.DOWNSTREAM
            and isinstance(
                frame,
                (InputAudioRawFrame, UserStartedSpeakingFrame, UserStoppedSpeakingFrame),
            )
        ):
            return

        await self.push_frame(frame, direction)


async def run_voice_agent(websocket: WebSocket, agent: Agent, settings: Settings) -> None:
    """Drive a single call's conversation until the caller hangs up."""
    _, call_data = await parse_telephony_websocket(websocket)
    log.info("voice_call_start", agent_id=str(agent.id), stream_id=call_data["stream_id"])

    serializer = PlivoFrameSerializer(
        stream_id=call_data["stream_id"],
        call_id=call_data.get("call_id"),
        auth_id=settings.plivo_auth_id,
        auth_token=settings.plivo_auth_token,
    )

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=serializer,
        ),
    )

    language = _language(agent.language)
    voice = agent.voice if agent.voice in _VALID_V2_VOICES else _DEFAULT_VOICE

    # Match Plivo's 8 kHz telephony rate end to end so we don't resample audio
    # every frame (saves CPU + latency on constrained instances).
    stt = SarvamSTTService(
        api_key=settings.sarvam_api_key,
        model=_STT_MODEL,
        sample_rate=8000,
        params=SarvamSTTService.InputParams(language=language),
    )
    llm = OpenAILLMService(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=agent.llm_model,
        params=OpenAILLMService.InputParams(
            temperature=agent.temperature,
            max_tokens=150,  # phone replies are short; bound generation time
            # Prefer ultra-low-latency OpenRouter providers (Groq ~3x faster
            # time-to-first-token). Falls back gracefully for unhosted models.
            extra={"provider": {"order": ["Groq", "Cerebras", "DeepInfra"]}},
        ),
    )
    tts = SarvamTTSService(
        api_key=settings.sarvam_api_key,
        model=_TTS_MODEL,
        voice_id=voice,
        sample_rate=8000,
        params=SarvamTTSService.InputParams(language=language),
    )

    greeting = _render(agent.greeting or "", agent.custom_variables or {}).strip()
    # Phone calls need short, spoken-style turns — long replies feel sluggish and
    # take longer to synthesize. Nudge every agent toward brevity.
    phone_style = (
        " You are on a live phone call. Reply in one or two short, natural spoken "
        "sentences. Never use lists, markdown, or long explanations."
    )
    system_prompt = (agent.system_prompt or "You are a helpful phone assistant.") + phone_style
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    if greeting:
        messages.append({"role": "assistant", "content": greeting})

    # Telephony lines are noisy and echo the bot's own audio back. Defaults
    # (confidence 0.7 / start 0.2 / stop 0.2 / min_volume 0.6) treat that as
    # the caller speaking and fire spurious interruptions, so the agent never
    # finishes a reply. Require louder, higher-confidence, sustained speech.
    vad = SileroVADAnalyzer(
        params=VADParams(
            # Keep noise/echo rejection high so the caller's turn ends cleanly
            # (loose thresholds let ambient noise hold the turn open -> big lag).
            confidence=0.85,
            start_secs=0.35,
            stop_secs=0.5,   # a bit snappier than the 0.8 default
            min_volume=0.7,
        )
    )

    context = LLMContext(messages)
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=vad),
    )

    # Half-duplex echo gate — always on (essential for speakerphone). Starts
    # closed when there's a greeting so the callee's pickup audio can't wipe it.
    gate = InputGate(start_closed=bool(greeting))

    pipeline = Pipeline(
        [
            transport.input(),
            gate,
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
            allow_interruptions=agent.interruptible,
            enable_metrics=True,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def _on_connected(_transport, _client):  # noqa: ANN001
        if greeting:
            await task.queue_frames([TTSSpeakFrame(greeting)])

    @transport.event_handler("on_client_disconnected")
    async def _on_disconnected(_transport, _client):  # noqa: ANN001
        log.info("voice_call_end", agent_id=str(agent.id))
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)
