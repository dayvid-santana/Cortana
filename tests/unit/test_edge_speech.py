from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from devmate.adapters.speech.edge_provider import EdgeSpeechProvider
from devmate.domain.speech import SpeechRequest
from devmate.errors import SpeechSynthesisError

VOICE = "pt-BR-FranciscaNeural"


class FakeCommunicate:
    def __init__(
        self,
        text: str,
        voice: str,
        rate: str,
        audio: bytes = b"fake-mp3-bytes",
        error: Exception | None = None,
    ) -> None:
        self.text = text
        self.voice = voice
        self.rate = rate
        self.audio = audio
        self.error = error
        self.saved_to: Path | None = None

    def save_sync(self, path: str) -> None:
        if self.error is not None:
            raise self.error
        self.saved_to = Path(path)
        self.saved_to.parent.mkdir(parents=True, exist_ok=True)
        self.saved_to.write_bytes(self.audio)


class FakePlayer:
    def __init__(self) -> None:
        self.played: list[Path] = []

    def available(self) -> tuple[bool, str | None]:
        return True, None

    def play(self, path: Path) -> None:
        self.played.append(path)


def make_provider(
    tmp_path: Path,
    voice: str | None = VOICE,
    audio: bytes = b"fake-mp3-bytes",
    error: Exception | None = None,
    **kwargs: Any,
) -> tuple[EdgeSpeechProvider, list[FakeCommunicate]]:
    created: list[FakeCommunicate] = []

    def factory(text: str, voice_id: str, rate: str) -> FakeCommunicate:
        communicate = FakeCommunicate(text, voice_id, rate, audio=audio, error=error)
        created.append(communicate)
        return communicate

    provider = EdgeSpeechProvider(
        voice=voice,
        cache_directory=tmp_path,
        communicate_factory=factory,
        **kwargs,
    )
    return provider, created


def test_synthesize_writes_audio_and_uses_the_selected_voice(tmp_path: Path) -> None:
    provider, calls = make_provider(tmp_path)

    result = provider.synthesize(SpeechRequest(text="Olá"))

    assert result.voice == VOICE
    assert result.cached is False
    assert result.audio_path is not None
    assert result.audio_path.read_bytes() == b"fake-mp3-bytes"
    assert calls[0].text == "Olá"
    assert calls[0].voice == VOICE


def test_falls_back_to_default_voice_when_none_is_selected(tmp_path: Path) -> None:
    provider, calls = make_provider(tmp_path, voice=None)

    result = provider.synthesize(SpeechRequest(text="Olá"))

    assert result.voice == "pt-BR-FranciscaNeural"
    assert calls[0].voice == "pt-BR-FranciscaNeural"


def test_synthesize_hits_cache_on_the_second_identical_request(tmp_path: Path) -> None:
    provider, calls = make_provider(tmp_path)
    request = SpeechRequest(text="Olá")

    first = provider.synthesize(request)
    second = provider.synthesize(request)

    assert first.cached is False
    assert second.cached is True
    assert second.audio_path == first.audio_path
    assert len(calls) == 1


def test_cache_key_changes_with_voice_and_text(tmp_path: Path) -> None:
    provider, _ = make_provider(tmp_path)

    base = provider.cache_path(SpeechRequest(text="Olá", voice=VOICE))
    other_voice = provider.cache_path(SpeechRequest(text="Olá", voice="pt-BR-AntonioNeural"))
    other_text = provider.cache_path(SpeechRequest(text="Oi", voice=VOICE))

    assert base != other_voice
    assert base != other_text


def test_rate_is_converted_to_a_relative_percentage(tmp_path: Path) -> None:
    provider, calls = make_provider(tmp_path, rate=270)

    provider.synthesize(SpeechRequest(text="Olá"))

    assert calls[0].rate == "+50%"


def test_synthesis_error_never_includes_a_python_traceback(tmp_path: Path) -> None:
    provider, _ = make_provider(tmp_path, error=RuntimeError("algo obscuro"))

    with pytest.raises(SpeechSynthesisError) as excinfo:
        provider.synthesize(SpeechRequest(text="Olá"))

    assert "Traceback" not in str(excinfo.value)
    assert "Provider: Edge TTS" in str(excinfo.value)


def test_empty_audio_response_raises_synthesis_error(tmp_path: Path) -> None:
    provider, _ = make_provider(tmp_path, audio=b"")

    with pytest.raises(SpeechSynthesisError, match="não retornou áudio"):
        provider.synthesize(SpeechRequest(text="Olá"))


def test_speak_uses_the_configured_player_and_never_touches_windows_sapi(tmp_path: Path) -> None:
    player = FakePlayer()
    provider, _ = make_provider(tmp_path)
    provider.player = player

    provider.speak("Olá, eu sou a Diana.")

    assert len(player.played) == 1
    import devmate.adapters.speech.edge_provider as module

    source = Path(module.__file__ or "").read_text(encoding="utf-8")
    assert "SAPI" not in source
    assert "system_provider" not in source
