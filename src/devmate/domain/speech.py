"""Modelos de fala independentes de qualquer provider.

Nenhum tipo do SDK da OpenAI (ou de outro fornecedor) atravessa esta camada.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_VOICE_PREVIEW_TEXT = (
    "Olá. Eu sou sua assistente de desenvolvimento. "
    "Posso ler a documentação do projeto, acompanhar decisões "
    "e conversar com você sobre as mudanças de cada commit."
)


@dataclass(frozen=True, slots=True)
class VoiceInfo:
    """Uma voz oferecida por um provider de fala."""

    id: str
    name: str
    provider: str
    description: str | None = None
    language: str | None = None
    recommended: bool = False
    preview_supported: bool = True


@dataclass(frozen=True, slots=True)
class SpeechCapabilities:
    """O que um provider consegue fazer, para a aplicação não presumir."""

    lists_voices: bool = False
    supports_voice_selection: bool = False
    supports_instructions: bool = False
    supports_rate: bool = True
    produces_audio_files: bool = False
    remote: bool = False


@dataclass(frozen=True, slots=True)
class SpeechRequest:
    """Pedido de síntese já normalizado pela aplicação."""

    text: str
    voice: str | None = None
    rate: int | None = None
    model: str | None = None
    instructions: str | None = None


@dataclass(frozen=True, slots=True)
class SpeechResult:
    """Resultado de uma síntese.

    ``audio_path`` fica vazio quando o provider fala direto pelo sistema
    operacional e não gera arquivo intermediário.
    """

    provider: str
    voice: str | None = None
    model: str | None = None
    audio_path: Path | None = None
    cached: bool = False
