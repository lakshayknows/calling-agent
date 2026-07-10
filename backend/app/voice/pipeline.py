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
import random
import time
from collections.abc import Callable
from typing import cast

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
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext, LLMContextMessage
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
from pipecat.turns.user_start.vad_user_turn_start_strategy import VADUserTurnStartStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

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

    def _schedule_gate_release(self, delay: float = 0.065) -> None:
        """Add a 65ms release delay after BotStoppedSpeakingFrame to swallow acoustic tail echo."""
        if self._safety_task is not None:
            self._safety_task.cancel()
        self._safety_task = asyncio.create_task(self._delayed_release(delay))

    async def _delayed_release(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        self._bot_speaking = False
        self._safety_task = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame) and self._bot_speaking:
            self._arm_safety()  # protect the opening greeting
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
            self._arm_safety()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._schedule_gate_release(delay=0.065)  # 65ms release delay to swallow acoustic tail echo

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


class LatencyMasker(FrameProcessor):
    """Pushes soft acoustic/conversational filler frames during tool calls or complex turns.

    When an AI agent triggers a function/tool execution or begins a complex reasoning step,
    the user would otherwise experience dead silence while waiting for tool completion and LLM
    generation. This processor catches function call frames (or is triggered after user turn completion)
    and immediately queues a soft acoustic filler like `TTSSpeakFrame("Hmm...")` or
    `TTSSpeakFrame("One second...")` so the caller hears instant responsiveness while background
    reasoning happens, without sounding like a repetitive robot.
    """

    _FILLER_PHRASES = ["Hmm...", "One moment...", "Let me check...", "Sure..."]

    def __init__(
        self,
        get_task: Callable[[], PipelineWorker | None],
        filler: str = "Hmm...",
    ) -> None:
        super().__init__()
        self._get_task = get_task
        self._filler = filler
        self._last_mask_time = 0.0
        self._backchannel_task: asyncio.Task | None = None

    def _cancel_backchannel(self) -> None:
        if self._backchannel_task is not None:
            self._backchannel_task.cancel()
            self._backchannel_task = None

    def _schedule_backchannel(self, delay: float = 0.55) -> None:
        self._cancel_backchannel()
        self._backchannel_task = asyncio.create_task(self._delayed_backchannel(delay))

    async def _delayed_backchannel(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        self._backchannel_task = None
        await self._maybe_push_filler(
            reason="conversational_bridge",
            phrase=random.choice(self._FILLER_PHRASES),
        )

    async def _maybe_push_filler(self, reason: str, phrase: str | None = None) -> None:
        now = time.monotonic()
        if now - self._last_mask_time > 2.5:
            self._last_mask_time = now
            task = self._get_task()
            if task:
                target_phrase = phrase or self._filler
                log.info("latency_mask_triggered", reason=reason, phrase=target_phrase)
                await task.queue_frames([TTSSpeakFrame(target_phrase)])

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        name = type(frame).__name__
        if name in (
            "FunctionCallInProgressFrame",
            "FunctionCallRequestFrame",
            "FunctionCallFrame",
        ):
            await self._maybe_push_filler(reason=name)
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._schedule_backchannel(delay=0.55)
        elif isinstance(frame, (BotStartedSpeakingFrame, TTSSpeakFrame, UserStartedSpeakingFrame)) or name in ("LLMFullResponseStartFrame", "LLMResponseStartFrame"):
            self._cancel_backchannel()
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
    )
    tts = SarvamTTSService(
        api_key=settings.sarvam_api_key,
        model=_TTS_MODEL,
        voice_id=voice,
        sample_rate=8000,
        params=SarvamTTSService.InputParams(language=language),
    )

    greeting = _render(agent.greeting or "", agent.custom_variables or {}).strip()
    base_prompt = (agent.system_prompt or "You are a helpful phone assistant.").strip()
    voice_system_prompt = (
        f"{base_prompt}\n\n"
        "CRITICAL VOICE INSTRUCTION: Speak in short, concise sentences suitable for a live telephone call. "
        "Never use long introductory clauses, bullet points, or markdown formatting. "
        "Your very first clause MUST be under 6 words and end with a comma or period right away (e.g., 'Sure, I can help with that.') so audio synthesis starts instantaneously."
    )
    messages: list[dict] = [{"role": "system", "content": voice_system_prompt}]
    if greeting:
        messages.append({"role": "assistant", "content": greeting})

    # Telephony lines are noisy and echo the bot's own audio back. Defaults
    # (confidence 0.7 / start 0.2 / stop 0.2 / min_volume 0.6) treat that as
    # the caller speaking and fire spurious interruptions, so the agent never
    # finishes a reply. Require louder, higher-confidence, sustained speech.
    # Note: stop_secs=0.30 is tuned for fast conversational turns without silence gaps.
    vad = SileroVADAnalyzer(
        params=VADParams(
            # Keep noise/echo rejection high so the caller's turn ends cleanly
            # (loose thresholds let ambient noise hold the turn open -> big lag).
            confidence=0.85,
            start_secs=0.20,
            stop_secs=0.30,  # 0.30s for fast conversational turns without silence gaps
            min_volume=0.7,
        )
    )

    context = LLMContext(cast(list[LLMContextMessage], messages))
    user_turn_strategies = UserTurnStrategies(
        start=[VADUserTurnStartStrategy(enable_interruptions=agent.interruptible)]
    )
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=vad,
            user_turn_strategies=user_turn_strategies,
        ),
    )

    # Half-duplex echo gate — always on (essential for speakerphone). Starts
    # closed when there's a greeting so the callee's pickup audio can't wipe it.
    gate = InputGate(start_closed=bool(greeting))

    # Latency masker queues instant filler audio on function/tool calls or complex turns
    task: PipelineWorker | None = None
    masker = LatencyMasker(get_task=lambda: task)

    @llm.event_handler("on_function_calls")
    async def _on_function_calls(_service, _function_calls):  # noqa: ANN001
        await masker._maybe_push_filler(reason="on_function_calls")

    @llm.event_handler("on_function_start")
    async def _on_function_start(_service, _function_name, _arguments):  # noqa: ANN001
        await masker._maybe_push_filler(reason="on_function_start")

    pipeline = Pipeline(
        [
            transport.input(),
            gate,
            stt,
            user_aggregator,
            llm,
            masker,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    task = PipelineWorker(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
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

    runner = WorkerRunner(handle_sigint=False)
    await runner.run(task)
