"""Registro de providers de fala."""

from __future__ import annotations

from pathlib import Path

from devmate.adapters.audio.system_player import SystemAudioPlayer
from devmate.adapters.speech.edge_provider import EdgeSpeechProvider
from devmate.adapters.speech.elevenlabs_provider import ElevenLabsSpeechProvider
from devmate.adapters.speech.faster_whisper_provider import FasterWhisperInputProvider
from devmate.adapters.speech.null_input_provider import NullSpeechInputProvider
from devmate.adapters.speech.null_provider import NullSpeechProvider
from devmate.adapters.speech.openai_provider import OpenAISpeechProvider
from devmate.adapters.speech.system_provider import SystemSpeechProvider
from devmate.config import AppConfig
from devmate.domain.ports import SpeechInputProvider, SpeechProvider
from devmate.errors import ProviderNotFoundError

PREVIEW_CACHE_SUBDIRECTORY = Path("cache") / "voice-previews"


def get_speech_provider(
    name: str,
    config: AppConfig,
    root: Path | None = None,
    voice: str | None = None,
) -> SpeechProvider:
    """Constrói o provider de fala; ``voice`` sobrepõe o configurado sem persistir nada."""
    selected_voice = voice or config.speech.voice
    if name == "null":
        return NullSpeechProvider()
    if name == "system":
        return SystemSpeechProvider(config.speech.rate, selected_voice)
    if name == "openai":
        cache_directory = (root / ".devmate" / PREVIEW_CACHE_SUBDIRECTORY) if root else None
        return OpenAISpeechProvider(
            voice=selected_voice,
            model=config.speech.providers.openai.model,
            rate=config.speech.rate,
            style=config.speech.style,
            api_key_env=config.speech.providers.openai.api_key_env,
            response_format=config.speech.providers.openai.response_format,
            cache_directory=cache_directory,
            player=SystemAudioPlayer(),
        )
    if name == "elevenlabs":
        cache_directory = (root / ".devmate" / PREVIEW_CACHE_SUBDIRECTORY) if root else None
        return ElevenLabsSpeechProvider(
            voice=selected_voice,
            model=config.speech.providers.elevenlabs.model,
            rate=config.speech.rate,
            api_key_env=config.speech.providers.elevenlabs.api_key_env,
            output_format=config.speech.providers.elevenlabs.output_format,
            cache_directory=cache_directory,
            player=SystemAudioPlayer(),
        )
    if name == "edge":
        cache_directory = (root / ".devmate" / PREVIEW_CACHE_SUBDIRECTORY) if root else None
        return EdgeSpeechProvider(
            voice=selected_voice,
            rate=config.speech.rate,
            cache_directory=cache_directory,
            player=SystemAudioPlayer(),
        )
    raise ProviderNotFoundError(f"Provider de fala desconhecido: {name}")


def get_speech_input_provider(
    name: str, config: AppConfig, model_directory: Path
) -> SpeechInputProvider:
    providers: dict[str, SpeechInputProvider] = {
        "null": NullSpeechInputProvider(),
        "faster_whisper": FasterWhisperInputProvider(
            model_name=config.speech.input_model,
            language=config.speech.input_language,
            duration_seconds=config.speech.input_duration_seconds,
            model_directory=model_directory,
            silence_seconds=config.speech.input_silence_seconds,
        ),
    }
    try:
        return providers[name]
    except KeyError as exc:
        raise ProviderNotFoundError(f"Provider de entrada de voz desconhecido: {name}") from exc
