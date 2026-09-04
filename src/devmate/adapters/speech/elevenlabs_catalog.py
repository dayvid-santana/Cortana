"""Catálogo das vozes da ElevenLabs — único lugar onde esses nomes aparecem.

A ElevenLabs expõe um endpoint de descoberta (``GET /v1/voices``); ele é a fonte
preferida quando a credencial está disponível. O catálogo abaixo cobre vozes
públicas estáveis da biblioteca deles, para permitir listar/pré-visualizar mesmo
sem chamar a API (ex.: ``devmate voices list --offline``).
"""

from __future__ import annotations

from devmate.domain.speech import VoiceInfo

PROVIDER_NAME = "elevenlabs"

DEFAULT_MODEL = "eleven_multilingual_v2"

_DESCRIPTIONS: dict[str, str] = {
    "21m00Tcm4TlvDq8ikWAM": "Rachel — neutra e clara.",
    "AZnzlk1XvdvUeBnXmlld": "Domi — confiante e forte.",
    "EXAVITQu4vr4xnSDxMaL": "Bella — suave e conversacional.",
    "ErXwobaYiN019PkySvjV": "Antoni — calma e bem articulada.",
    "MF3mGyEYCl7XYWbV9V6O": "Elli — jovem e emotiva.",
    "TxGEqnHWrfWFTfGW9XjX": "Josh — grave e direta.",
    "VR6AewLTigWG4xSOukaG": "Arnold — grave e enérgica.",
    "pNInz6obpgDQGcFmaJgB": "Adam — profunda e narrativa.",
    "yoZ06aMxZJJ28mfd3POQ": "Sam — versátil, tom neutro.",
}

_CATALOG_ORDER = tuple(_DESCRIPTIONS.keys())

_RECOMMENDED = frozenset({"EXAVITQu4vr4xnSDxMaL", "pNInz6obpgDQGcFmaJgB"})


def _build(voice_id: str, name: str | None = None) -> VoiceInfo:
    description = _DESCRIPTIONS.get(voice_id)
    return VoiceInfo(
        id=voice_id,
        name=name or description or voice_id,
        provider=PROVIDER_NAME,
        description=description,
        recommended=voice_id in _RECOMMENDED,
        preview_supported=True,
    )


ELEVENLABS_BUILTIN_VOICES: tuple[VoiceInfo, ...] = tuple(
    _build(voice_id) for voice_id in _CATALOG_ORDER
)


def is_known_voice(identifier: str) -> bool:
    """Aceita qualquer id: a biblioteca da conta pode ter vozes fora do catálogo local."""
    return bool(identifier)


def voice_ids() -> tuple[str, ...]:
    return tuple(voice.id for voice in ELEVENLABS_BUILTIN_VOICES)
