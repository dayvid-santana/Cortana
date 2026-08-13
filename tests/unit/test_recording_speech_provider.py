from __future__ import annotations

from devmate.adapters.speech.null_provider import RecordingSpeechProvider
from devmate.domain.speech import SpeechRequest


def test_recording_provider_captures_voice_text_and_rate_from_speak() -> None:
    provider = RecordingSpeechProvider(voice="marin", model="tts-1-hd", rate=200)

    provider.speak("Olá")

    assert len(provider.spoken_requests) == 1
    recorded = provider.spoken_requests[0]
    assert recorded.text == "Olá"
    assert recorded.voice == "marin"
    assert recorded.rate == 200
    assert recorded.model == "tts-1-hd"


def test_recording_provider_lets_the_request_override_defaults() -> None:
    provider = RecordingSpeechProvider(voice="marin")

    provider.synthesize(SpeechRequest(text="Oi", voice="cedar", rate=90))

    assert provider.spoken_requests[0].voice == "cedar"
    assert provider.spoken_requests[0].rate == 90
