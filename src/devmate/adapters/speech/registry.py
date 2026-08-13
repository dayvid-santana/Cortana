"""Registro de providers de fala."""

from __future__ import annotations

from pathlib import Path

from devmate.adapters.speech.faster_whisper_provider import FasterWhisperInputProvider
from devmate.adapters.speech.null_input_provider import NullSpeechInputProvider
from devmate.adapters.speech.null_provider import NullSpeechProvider
from devmate.adapters.speech.system_provider import SystemSpeechProvider
from devmate.config import AppConfig
from devmate.domain.ports import SpeechInputProvider, SpeechProvider
from devmate.errors import ProviderNotFoundError


def get_speech_provider(name: str, config: AppConfig) -> SpeechProvider:
    providers: dict[str, SpeechProvider] = {
        "null": NullSpeechProvider(),
        "system": SystemSpeechProvider(config.speech.rate, config.speech.voice),
    }
    try:
        return providers[name]
    except KeyError as exc:
        raise ProviderNotFoundError(f"Provider de fala desconhecido: {name}") from exc


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
        ),
    }
    try:
        return providers[name]
    except KeyError as exc:
        raise ProviderNotFoundError(f"Provider de entrada de voz desconhecido: {name}") from exc
