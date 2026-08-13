"""Provider de fala nulo para testes e automações."""

from __future__ import annotations


class NullSpeechProvider:
    name = "null"

    def available(self) -> tuple[bool, str | None]:
        return True, None

    def speak(self, text: str) -> None:
        del text
