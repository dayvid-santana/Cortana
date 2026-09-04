"""Catálogo das vozes do Edge TTS — único lugar onde esses nomes aparecem.

O ``edge-tts`` expõe ``list_voices()`` (assíncrono) como fonte de descoberta; ele
é preferido quando a rede está disponível. O catálogo abaixo cobre as vozes
neurais em português do Brasil, para listar/pré-visualizar mesmo offline.
"""

from __future__ import annotations

from devmate.domain.speech import VoiceInfo

PROVIDER_NAME = "edge"

_DESCRIPTIONS: dict[str, str] = {
    "pt-BR-FranciscaNeural": "Feminina, amigável e natural.",
    "pt-BR-AntonioNeural": "Masculina, amigável e natural.",
    "pt-BR-ThalitaMultilingualNeural": "Feminina, multilíngue, tom positivo.",
}

_CATALOG_ORDER = tuple(_DESCRIPTIONS.keys())

_RECOMMENDED = frozenset({"pt-BR-FranciscaNeural"})


def _build(voice_id: str) -> VoiceInfo:
    return VoiceInfo(
        id=voice_id,
        name=voice_id,
        provider=PROVIDER_NAME,
        description=_DESCRIPTIONS.get(voice_id),
        language="pt-BR",
        recommended=voice_id in _RECOMMENDED,
        preview_supported=True,
    )


EDGE_BUILTIN_VOICES: tuple[VoiceInfo, ...] = tuple(_build(voice_id) for voice_id in _CATALOG_ORDER)


def is_known_voice(identifier: str) -> bool:
    """Aceita qualquer id: o catálogo completo do Edge tem centenas de vozes/idiomas."""
    return bool(identifier)


def voice_ids() -> tuple[str, ...]:
    return tuple(voice.id for voice in EDGE_BUILTIN_VOICES)
