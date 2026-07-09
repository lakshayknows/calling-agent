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

from starlette.websockets import WebSocket

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.agent import Agent

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
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

    stt = SarvamSTTService(
        api_key=settings.sarvam_api_key,
        model=_STT_MODEL,
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
        params=SarvamTTSService.InputParams(language=language),
    )

    greeting = _render(agent.greeting or "", agent.custom_variables or {}).strip()
    messages: list[dict] = [
        {"role": "system", "content": agent.system_prompt or "You are a helpful phone assistant."}
    ]
    if greeting:
        messages.append({"role": "assistant", "content": greeting})

    context = LLMContext(messages)
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline(
        [
            transport.input(),
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
