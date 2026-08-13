"""Entrada de voz nula para testes que não devem abrir o microfone."""

from __future__ import annotations

from devmate.errors import SpeechRecognitionUnavailableError


class NullSpeechInputProvider:
    name = "null"

    def available(self) -> tuple[bool, str | None]:
        return True, None

    def listen(self, duration_seconds: int | None = None) -> str:
        del duration_seconds
        raise SpeechRecognitionUnavailableError(
            "O provider de entrada 'null' não captura áudio. Configure faster_whisper."
        )
