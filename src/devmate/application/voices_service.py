"""Seleção, pré-visualização e persistência de voz — independente de provider.

Só o adapter ``openai_provider``/``openai_catalog`` conhece nomes de voz da OpenAI;
este módulo trata apenas do fluxo de negócio (validar, planejar, persistir).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from devmate.adapters.speech.openai_catalog import PROVIDER_NAME as OPENAI_PROVIDER_NAME
from devmate.adapters.speech.openai_catalog import is_known_voice
from devmate.adapters.speech.openai_provider import unknown_voice_error as openai_voice_error
from devmate.config import AppConfig
from devmate.config_writer import set_speech_voice
from devmate.domain.ports import SpeechProvider
from devmate.domain.speech import DEFAULT_VOICE_PREVIEW_TEXT, SpeechRequest, VoiceInfo
from devmate.errors import UnknownVoiceError


@dataclass(frozen=True, slots=True)
class CurrentVoice:
    provider: str
    voice: str | None
    model: str | None
    language: str
    rate: int
    style: str | None


@dataclass(frozen=True, slots=True)
class PreviewPlan:
    """O que ``preview --all`` vai fazer, calculado sem tocar a rede."""

    voice: VoiceInfo
    request: SpeechRequest
    already_cached: bool


def current_voice(config: AppConfig, provider_name: str | None = None) -> CurrentVoice:
    name = provider_name or config.speech.provider
    model = config.speech.providers.openai.model if name == OPENAI_PROVIDER_NAME else None
    return CurrentVoice(
        provider=name,
        voice=config.speech.voice,
        model=model,
        language=config.speech.input_language,
        rate=config.speech.rate,
        style=config.speech.style,
    )


def validate_voice(provider_name: str, voice: str) -> None:
    """Rejeita localmente uma voz desconhecida, sem gastar uma chamada à API."""
    if provider_name == OPENAI_PROVIDER_NAME and not is_known_voice(voice):
        raise openai_voice_error(voice)


def persist_voice(config_path: Path, provider_name: str, voice: str, set_as_provider: bool) -> None:
    validate_voice(provider_name, voice)
    set_speech_voice(config_path, voice, provider_name if set_as_provider else None)


def build_preview_plan(
    provider: SpeechProvider,
    voices: list[VoiceInfo],
    text: str | None,
    rate: int,
    model: str | None,
) -> list[PreviewPlan]:
    """Monta o roteiro de prévias e informa quais já existem em cache — sem gerar nada."""
    phrase = text or DEFAULT_VOICE_PREVIEW_TEXT
    plans: list[PreviewPlan] = []
    cache_path = getattr(provider, "cache_path", None)
    for voice in voices:
        request = SpeechRequest(text=phrase, voice=voice.id, rate=rate, model=model)
        cached = bool(callable(cache_path) and (path := cache_path(request)) and path.exists())
        plans.append(PreviewPlan(voice=voice, request=request, already_cached=cached))
    return plans


def uncached_count(plans: list[PreviewPlan]) -> int:
    return sum(1 for plan in plans if not plan.already_cached)


def resolve_voice_target(
    voice_id: str, all_voices: bool, known: list[VoiceInfo]
) -> list[VoiceInfo]:
    """Resolve o argumento de ``preview`` num roteiro de vozes, validando o pedido."""
    if all_voices:
        return known
    matches = [voice for voice in known if voice.id == voice_id]
    if not matches:
        raise UnknownVoiceError(
            f"Voz desconhecida: {voice_id}\n\nVozes disponíveis:\n"
            + ", ".join(voice.id for voice in known)
        )
    return matches
