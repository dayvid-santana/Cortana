"""Catálogo das vozes da OpenAI — único lugar onde esses nomes aparecem.

A OpenAI não publica um endpoint de descoberta de vozes de TTS; o SDK expõe as
vozes suportadas apenas como ``Literal`` em ``speech_create_params.Voice``. Quando
esse tipo está disponível, ele é a fonte preferida e o catálogo abaixo apenas
enriquece a descrição. As vozes legadas continuam listadas porque a API as aceita
com ``tts-1``, embora tenham saído do ``Literal`` mais recente.
"""

from __future__ import annotations

from devmate.domain.speech import VoiceInfo

PROVIDER_NAME = "openai"

# Modelos que aceitam o parâmetro ``instructions`` (estilo de leitura).
INSTRUCTION_CAPABLE_MODELS = frozenset({"gpt-4o-mini-tts", "gpt-4o-mini-tts-2025-12-15"})

# Vozes da geração nova; dependem de um modelo ``gpt-4o-mini-tts``.
NEXT_GENERATION_VOICES = frozenset({"marin", "cedar"})

# Vozes retiradas do ``Literal`` atual do SDK, ainda aceitas por ``tts-1``.
LEGACY_VOICES = frozenset({"fable", "onyx", "nova"})

_DESCRIPTIONS: dict[str, str] = {
    "alloy": "Neutra e equilibrada.",
    "ash": "Grave e calma.",
    "ballad": "Suave, com entonação expressiva.",
    "coral": "Clara e cordial.",
    "echo": "Sóbria e uniforme.",
    "fable": "Narrativa, estilo audiolivro (legada).",
    "onyx": "Grave e firme (legada).",
    "nova": "Ágil e brilhante (legada).",
    "sage": "Serena e didática.",
    "shimmer": "Leve e aguda.",
    "verse": "Versátil, boa para leitura técnica.",
    "marin": "Natural e conversacional (geração nova).",
    "cedar": "Quente e pausada (geração nova).",
}

# Ordem estável de apresentação.
_CATALOG_ORDER = (
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "fable",
    "onyx",
    "nova",
    "sage",
    "shimmer",
    "verse",
    "marin",
    "cedar",
)

_RECOMMENDED = frozenset({"marin", "verse"})


def _build(identifier: str) -> VoiceInfo:
    return VoiceInfo(
        id=identifier,
        name=identifier,
        provider=PROVIDER_NAME,
        description=_DESCRIPTIONS.get(identifier),
        recommended=identifier in _RECOMMENDED,
        preview_supported=True,
    )


OPENAI_BUILTIN_VOICES: tuple[VoiceInfo, ...] = tuple(
    _build(identifier) for identifier in _CATALOG_ORDER
)


def discovered_voice_ids() -> tuple[str, ...]:
    """Lê as vozes declaradas pelo SDK instalado, quando ele as expõe."""
    try:
        import typing

        from openai.types.audio import speech_create_params
    except ImportError:
        return ()
    for argument in typing.get_args(speech_create_params.Voice):
        literal_values = typing.get_args(argument)
        if literal_values and all(isinstance(value, str) for value in literal_values):
            return tuple(str(value) for value in literal_values)
    return ()


def available_voices() -> tuple[VoiceInfo, ...]:
    """Combina o que o SDK declara com o catálogo local, sem perder nenhuma."""
    discovered = discovered_voice_ids()
    if not discovered:
        return OPENAI_BUILTIN_VOICES
    known = {voice.id: voice for voice in OPENAI_BUILTIN_VOICES}
    merged = [known.get(identifier) or _build(identifier) for identifier in discovered]
    # Preserva as legadas que sumiram do Literal mas seguem aceitas pela API.
    merged.extend(voice for voice in OPENAI_BUILTIN_VOICES if voice.id not in set(discovered))
    order = {identifier: index for index, identifier in enumerate(_CATALOG_ORDER)}
    return tuple(sorted(merged, key=lambda voice: order.get(voice.id, len(order))))


def is_known_voice(identifier: str) -> bool:
    return any(voice.id == identifier for voice in available_voices())


def voice_ids() -> tuple[str, ...]:
    return tuple(voice.id for voice in available_voices())


def supports_instructions(model: str) -> bool:
    return model in INSTRUCTION_CAPABLE_MODELS
