"""Ports que isolam Git, providers e persistência do domínio."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from devmate.domain.models import CommitRecord, LLMRequest, LLMResponse
from devmate.domain.speech import (
    SpeechCapabilities,
    SpeechRequest,
    SpeechResult,
    VoiceInfo,
)


class GitPort(Protocol):
    def discover_root(self, start: Path) -> Path: ...

    def current_branch(self) -> str | None: ...

    def head(self) -> str: ...

    def commits(self, revision: str, first_parent: bool = False) -> Sequence[CommitRecord]: ...


class LanguageModelProvider(Protocol):
    name: str

    def available(self) -> tuple[bool, str | None]: ...

    def complete(self, request: LLMRequest) -> LLMResponse: ...


class SpeechProvider(Protocol):
    """Contrato de síntese de fala, comum a providers locais e remotos."""

    name: str

    def available(self) -> tuple[bool, str | None]: ...

    def capabilities(self) -> SpeechCapabilities: ...

    def list_voices(self) -> list[VoiceInfo]: ...

    def speak(self, text: str) -> None: ...

    def synthesize(self, request: SpeechRequest) -> SpeechResult: ...

    def stop(self) -> None: ...


class AudioPlayerPort(Protocol):
    """Reprodução de um arquivo já sintetizado, separada da geração."""

    name: str

    def available(self) -> tuple[bool, str | None]: ...

    def play(self, path: Path) -> None: ...


class SpeechInputProvider(Protocol):
    """Transcreve uma fala sem enviar o áudio a serviços remotos."""

    name: str

    def available(self) -> tuple[bool, str | None]: ...

    def listen(self, duration_seconds: int | None = None) -> str: ...


class HotkeyPort(Protocol):
    """Gatilho explícito da pessoa usuária; o microfone só abre depois dele."""

    name: str

    def available(self) -> tuple[bool, str | None]: ...

    def wait(self) -> bool:
        """Bloqueia até o atalho ser pressionado. ``False`` encerra o daemon."""
        ...
