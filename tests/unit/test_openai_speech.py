from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from devmate.adapters.speech.openai_catalog import PROVIDER_NAME, voice_ids
from devmate.adapters.speech.openai_provider import OpenAISpeechProvider
from devmate.domain.speech import SpeechRequest
from devmate.errors import (
    ProviderAuthenticationError,
    SpeechSynthesisError,
    UnknownVoiceError,
)


class FakeAudioResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content


class FakeSpeechEndpoint:
    def __init__(self, audio: bytes = b"fake-mp3-bytes", error: Exception | None = None) -> None:
        self.audio = audio
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeAudioResponse:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return FakeAudioResponse(self.audio)


class FakeAudio:
    def __init__(self, speech: FakeSpeechEndpoint) -> None:
        self.speech = speech


class FakeOpenAIClient:
    def __init__(self, speech: FakeSpeechEndpoint) -> None:
        self.audio = FakeAudio(speech)


class FakePlayer:
    def __init__(self) -> None:
        self.played: list[Path] = []

    def available(self) -> tuple[bool, str | None]:
        return True, None

    def play(self, path: Path) -> None:
        self.played.append(path)


def make_provider(
    tmp_path: Path,
    speech: FakeSpeechEndpoint | None = None,
    voice: str | None = "marin",
    **kwargs: Any,
) -> tuple[OpenAISpeechProvider, FakeSpeechEndpoint]:
    endpoint = speech or FakeSpeechEndpoint()
    client = FakeOpenAIClient(endpoint)
    provider = OpenAISpeechProvider(
        voice=voice,
        cache_directory=tmp_path,
        client_factory=lambda: client,
        **kwargs,
    )
    return provider, endpoint


def test_list_voices_returns_the_local_catalog_without_network() -> None:
    provider = OpenAISpeechProvider()

    voices = provider.list_voices()

    assert {voice.id for voice in voices} == set(voice_ids())
    assert all(voice.provider == PROVIDER_NAME for voice in voices)


def test_unknown_voice_is_rejected_locally_without_calling_the_api(tmp_path: Path) -> None:
    provider, endpoint = make_provider(tmp_path, voice="banana")

    with pytest.raises(UnknownVoiceError, match="banana"):
        provider.synthesize(SpeechRequest(text="oi"))

    assert endpoint.calls == []


def test_no_voice_selected_raises_without_calling_the_api(tmp_path: Path) -> None:
    provider, endpoint = make_provider(tmp_path, voice=None)

    with pytest.raises(UnknownVoiceError, match="Nenhuma voz"):
        provider.synthesize(SpeechRequest(text="oi"))

    assert endpoint.calls == []


def test_synthesize_writes_audio_and_uses_the_selected_voice(tmp_path: Path) -> None:
    provider, endpoint = make_provider(tmp_path, voice="marin")

    result = provider.synthesize(SpeechRequest(text="Olá"))

    assert result.voice == "marin"
    assert result.cached is False
    assert result.audio_path is not None
    assert result.audio_path.read_bytes() == b"fake-mp3-bytes"
    assert endpoint.calls[0]["voice"] == "marin"
    assert endpoint.calls[0]["input"] == "Olá"


def test_synthesize_hits_cache_on_the_second_identical_request(tmp_path: Path) -> None:
    provider, endpoint = make_provider(tmp_path, voice="marin")
    request = SpeechRequest(text="Olá")

    first = provider.synthesize(request)
    second = provider.synthesize(request)

    assert first.cached is False
    assert second.cached is True
    assert second.audio_path == first.audio_path
    assert len(endpoint.calls) == 1  # A segunda chamada não tocou a API.


def test_cache_key_changes_with_voice_text_and_model(tmp_path: Path) -> None:
    provider, _ = make_provider(tmp_path, voice="marin", model="tts-1-hd")

    base = provider.cache_path(SpeechRequest(text="Olá", voice="marin"))
    other_voice = provider.cache_path(SpeechRequest(text="Olá", voice="cedar"))
    other_text = provider.cache_path(SpeechRequest(text="Oi", voice="marin"))

    assert base != other_voice
    assert base != other_text


def test_cache_path_never_embeds_the_api_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-value")
    provider, _ = make_provider(tmp_path, voice="marin")

    path = provider.cache_path(SpeechRequest(text="Olá"))

    assert path is not None
    assert "sk-super-secret-value" not in str(path)


def test_missing_api_key_raises_authentication_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    endpoint = FakeSpeechEndpoint()
    provider = OpenAISpeechProvider(voice="marin", cache_directory=tmp_path)
    # Sem client_factory, `available()` depende de verdade da variável de ambiente.

    with pytest.raises(ProviderAuthenticationError, match="OPENAI_API_KEY"):
        provider.synthesize(SpeechRequest(text="Olá"))
    assert endpoint.calls == []


@pytest.mark.parametrize(
    ("exception_name", "expected_match"),
    [
        ("RateLimitError", "limite de requisições"),
        ("APITimeoutError", "tempo limite"),
        ("APIConnectionError", "rede"),
    ],
)
def test_sdk_errors_are_translated_into_actionable_messages(
    tmp_path: Path, exception_name: str, expected_match: str
) -> None:
    fake_exception_type = type(exception_name, (Exception,), {})
    provider, _ = make_provider(
        tmp_path, speech=FakeSpeechEndpoint(error=fake_exception_type("detalhe"))
    )

    with pytest.raises(SpeechSynthesisError, match=expected_match):
        provider.synthesize(SpeechRequest(text="Olá"))


def test_synthesis_error_never_includes_a_python_traceback(tmp_path: Path) -> None:
    provider, _ = make_provider(
        tmp_path, speech=FakeSpeechEndpoint(error=RuntimeError("algo obscuro"))
    )

    with pytest.raises(SpeechSynthesisError) as excinfo:
        provider.synthesize(SpeechRequest(text="Olá"))

    assert "Traceback" not in str(excinfo.value)
    assert "Provider: OpenAI" in str(excinfo.value)


def test_empty_audio_response_raises_synthesis_error(tmp_path: Path) -> None:
    provider, _ = make_provider(tmp_path, speech=FakeSpeechEndpoint(audio=b""))

    with pytest.raises(SpeechSynthesisError, match="não retornou áudio"):
        provider.synthesize(SpeechRequest(text="Olá"))


def test_style_instructions_are_sent_only_when_the_model_supports_them(tmp_path: Path) -> None:
    supported, endpoint_supported = make_provider(
        tmp_path, voice="marin", model="gpt-4o-mini-tts", style="technical_calm"
    )
    supported.synthesize(SpeechRequest(text="Olá"))
    assert "instructions" in endpoint_supported.calls[0]

    unsupported, endpoint_unsupported = make_provider(
        tmp_path, voice="marin", model="tts-1-hd", style="technical_calm"
    )
    unsupported.synthesize(SpeechRequest(text="Olá"))
    assert "instructions" not in endpoint_unsupported.calls[0]


def test_speak_uses_the_configured_player_and_never_touches_windows_sapi(tmp_path: Path) -> None:
    player = FakePlayer()
    endpoint = FakeSpeechEndpoint()
    client = FakeOpenAIClient(endpoint)
    provider = OpenAISpeechProvider(
        voice="marin",
        cache_directory=tmp_path,
        client_factory=lambda: client,
        player=player,
    )

    provider.speak("Olá, eu sou a Diana.")

    assert len(player.played) == 1
    import devmate.adapters.speech.openai_provider as module

    source = Path(module.__file__ or "").read_text(encoding="utf-8")
    assert "SAPI" not in source
    assert "system_provider" not in source
