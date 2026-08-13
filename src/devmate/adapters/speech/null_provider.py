"""Providers de fala sem áudio, para testes e automações."""

from __future__ import annotations

from devmate.domain.speech import (
    SpeechCapabilities,
    SpeechRequest,
    SpeechResult,
    VoiceInfo,
)


class NullSpeechProvider:
    """Descarta o texto; útil quando não deve haver som algum."""

    name = "null"

    def available(self) -> tuple[bool, str | None]:
        return True, None

    def capabilities(self) -> SpeechCapabilities:
        return SpeechCapabilities()

    def list_voices(self) -> list[VoiceInfo]:
        return []

    def speak(self, text: str) -> None:
        del text

    def synthesize(self, request: SpeechRequest) -> SpeechResult:
        return SpeechResult(provider=self.name, voice=request.voice, model=request.model)

    def stop(self) -> None:
        return None


class RecordingSpeechProvider:
    """Registra cada pedido, permitindo asserções sobre voz, modelo e ritmo."""

    name = "recording"

    def __init__(self, voice: str | None = None, model: str | None = None, rate: int = 180) -> None:
        self.voice = voice
        self.model = model
        self.rate = rate
        self.spoken_requests: list[SpeechRequest] = []

    def available(self) -> tuple[bool, str | None]:
        return True, None

    def capabilities(self) -> SpeechCapabilities:
        return SpeechCapabilities(lists_voices=True, supports_voice_selection=True)

    def list_voices(self) -> list[VoiceInfo]:
        return [VoiceInfo(id="fake", name="fake", provider=self.name)]

    def speak(self, text: str) -> None:
        self.synthesize(SpeechRequest(text=text, voice=self.voice, rate=self.rate))

    def synthesize(self, request: SpeechRequest) -> SpeechResult:
        recorded = SpeechRequest(
            text=request.text,
            voice=request.voice or self.voice,
            rate=request.rate if request.rate is not None else self.rate,
            model=request.model or self.model,
            instructions=request.instructions,
        )
        self.spoken_requests.append(recorded)
        return SpeechResult(provider=self.name, voice=recorded.voice, model=recorded.model)

    def stop(self) -> None:
        return None
