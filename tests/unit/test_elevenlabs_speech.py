from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from devmate.adapters.speech.elevenlabs_provider import ElevenLabsSpeechProvider
from devmate.domain.speech import SpeechRequest
from devmate.errors import (
    ProviderAuthenticationError,
    SpeechSynthesisError,
    UnknownVoiceError,
)


class FakeResponse:
    def __init__(
        self,
        content: bytes = b"fake-mp3-bytes",
        status_code: int = 200,
        detail: str = "",
    ) -> None:
        self.content = content
        self.status_code = status_code
        self._detail = detail
        self.text = detail

    def json(self) -> dict[str, Any]:
        return {"detail": self._detail}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttpClient:
    def __init__(self, response: FakeResponse | None = None) -> None:
        self.response = response or FakeResponse()
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.response

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.response


class FakePlayer:
    def __init__(self) -> None:
        self.played: list[Path] = []

    def available(self) -> tuple[bool, str | None]:
        return True, None

    def play(self, path: Path) -> None:
        self.played.append(path)


VOICE_ID = "EXAVITQu4vr4xnSDxMaL"


def make_provider(
    tmp_path: Path,
    response: FakeResponse | None = None,
    voice: str | None = VOICE_ID,
    **kwargs: Any,
) -> tuple[ElevenLabsSpeechProvider, FakeHttpClient]:
    client = FakeHttpClient(response)
    provider = ElevenLabsSpeechProvider(
        voice=voice,
        cache_directory=tmp_path,
        client_factory=lambda: client,
        **kwargs,
    )
    return provider, client


def test_no_voice_selected_raises_without_calling_the_api(tmp_path: Path) -> None:
    provider, client = make_provider(tmp_path, voice=None)

    with pytest.raises(UnknownVoiceError, match="Nenhuma voz"):
        provider.synthesize(SpeechRequest(text="oi"))

    assert client.calls == []


def test_synthesize_writes_audio_and_uses_the_selected_voice(tmp_path: Path) -> None:
    provider, client = make_provider(tmp_path)

    result = provider.synthesize(SpeechRequest(text="Olá"))

    assert result.voice == VOICE_ID
    assert result.cached is False
    assert result.audio_path is not None
    assert result.audio_path.read_bytes() == b"fake-mp3-bytes"
    assert client.calls[0]["url"].endswith(f"/text-to-speech/{VOICE_ID}")
    assert client.calls[0]["json"]["text"] == "Olá"


def test_synthesize_hits_cache_on_the_second_identical_request(tmp_path: Path) -> None:
    provider, client = make_provider(tmp_path)
    request = SpeechRequest(text="Olá")

    first = provider.synthesize(request)
    second = provider.synthesize(request)

    assert first.cached is False
    assert second.cached is True
    assert second.audio_path == first.audio_path
    assert len(client.calls) == 1


def test_cache_key_changes_with_voice_and_text(tmp_path: Path) -> None:
    provider, _ = make_provider(tmp_path)

    base = provider.cache_path(SpeechRequest(text="Olá", voice=VOICE_ID))
    other_voice = provider.cache_path(SpeechRequest(text="Olá", voice="pNInz6obpgDQGcFmaJgB"))
    other_text = provider.cache_path(SpeechRequest(text="Oi", voice=VOICE_ID))

    assert base != other_voice
    assert base != other_text


def test_cache_path_never_embeds_the_api_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-super-secret-value")
    provider, _ = make_provider(tmp_path)

    path = provider.cache_path(SpeechRequest(text="Olá"))

    assert path is not None
    assert "sk-super-secret-value" not in str(path)


def test_missing_api_key_raises_authentication_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    provider = ElevenLabsSpeechProvider(voice=VOICE_ID, cache_directory=tmp_path)

    with pytest.raises(ProviderAuthenticationError, match="ELEVENLABS_API_KEY"):
        provider.synthesize(SpeechRequest(text="Olá"))


def test_http_error_status_is_translated_into_actionable_messages(tmp_path: Path) -> None:
    provider, _ = make_provider(
        tmp_path, response=FakeResponse(status_code=401, detail="invalid_api_key")
    )

    with pytest.raises(ProviderAuthenticationError, match="credencial inválida"):
        provider.synthesize(SpeechRequest(text="Olá"))


def test_synthesis_error_never_includes_a_python_traceback(tmp_path: Path) -> None:
    provider, _ = make_provider(
        tmp_path, response=FakeResponse(status_code=500, detail="algo obscuro")
    )

    with pytest.raises(SpeechSynthesisError) as excinfo:
        provider.synthesize(SpeechRequest(text="Olá"))

    assert "Traceback" not in str(excinfo.value)
    assert "Provider: ElevenLabs" in str(excinfo.value)


def test_empty_audio_response_raises_synthesis_error(tmp_path: Path) -> None:
    provider, _ = make_provider(tmp_path, response=FakeResponse(content=b""))

    with pytest.raises(SpeechSynthesisError, match="não retornou áudio"):
        provider.synthesize(SpeechRequest(text="Olá"))


def test_speak_uses_the_configured_player_and_never_touches_windows_sapi(tmp_path: Path) -> None:
    player = FakePlayer()
    client = FakeHttpClient()
    provider = ElevenLabsSpeechProvider(
        voice=VOICE_ID,
        cache_directory=tmp_path,
        client_factory=lambda: client,
        player=player,
    )

    provider.speak("Olá, eu sou a Diana.")

    assert len(player.played) == 1
    import devmate.adapters.speech.elevenlabs_provider as module

    source = Path(module.__file__ or "").read_text(encoding="utf-8")
    assert "SAPI" not in source
    assert "system_provider" not in source
