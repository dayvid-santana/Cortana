"""Ports que isolam Git, providers e persistência do domínio."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from devmate.domain.models import CommitRecord, LLMRequest, LLMResponse


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
    name: str

    def available(self) -> tuple[bool, str | None]: ...

    def speak(self, text: str) -> None: ...


class SpeechInputProvider(Protocol):
    """Transcreve uma fala sem enviar o áudio a serviços remotos."""

    name: str

    def available(self) -> tuple[bool, str | None]: ...

    def listen(self, duration_seconds: int | None = None) -> str: ...
