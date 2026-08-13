"""Registro de providers de fala."""

from __future__ import annotations

from devmate.adapters.speech.null_provider import NullSpeechProvider
from devmate.adapters.speech.system_provider import SystemSpeechProvider
from devmate.config import AppConfig
from devmate.domain.ports import SpeechProvider
from devmate.errors import ProviderNotFoundError


def get_speech_provider(name: str, config: AppConfig) -> SpeechProvider:
    providers: dict[str, SpeechProvider] = {
        "null": NullSpeechProvider(),
        "system": SystemSpeechProvider(config.speech.rate),
    }
    try:
        return providers[name]
    except KeyError as exc:
        raise ProviderNotFoundError(f"Provider de fala desconhecido: {name}") from exc
