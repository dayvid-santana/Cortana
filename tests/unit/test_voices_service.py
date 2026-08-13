from __future__ import annotations

from pathlib import Path

import pytest

from devmate.application import voices_service
from devmate.config import DEFAULT_CONFIG_TOML, AppConfig
from devmate.domain.speech import DEFAULT_VOICE_PREVIEW_TEXT, SpeechRequest, VoiceInfo
from devmate.errors import UnknownVoiceError


def test_current_voice_reports_openai_model_only_for_that_provider() -> None:
    config = AppConfig.model_validate(
        {
            "speech": {
                "provider": "openai",
                "voice": "marin",
                "providers": {"openai": {"model": "tts-1-hd"}},
            }
        }
    )

    current = voices_service.current_voice(config)

    assert current.provider == "openai"
    assert current.voice == "marin"
    assert current.model == "tts-1-hd"


def test_current_voice_omits_model_for_the_system_provider() -> None:
    config = AppConfig.model_validate({"speech": {"provider": "system", "voice": "Maria"}})

    current = voices_service.current_voice(config)

    assert current.model is None


def test_validate_voice_accepts_known_openai_voices() -> None:
    voices_service.validate_voice("openai", "marin")  # não deve levantar


def test_validate_voice_rejects_unknown_openai_voice_locally() -> None:
    with pytest.raises(UnknownVoiceError, match="banana"):
        voices_service.validate_voice("openai", "banana")


def test_validate_voice_does_not_constrain_the_system_provider() -> None:
    # O provider "system" descobre vozes do SO; não há catálogo local a validar.
    voices_service.validate_voice("system", "qualquer-coisa")


def test_persist_voice_rejects_unknown_voice_before_writing(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")

    with pytest.raises(UnknownVoiceError):
        voices_service.persist_voice(path, "openai", "banana", set_as_provider=False)

    assert 'voice = "banana"' not in path.read_text(encoding="utf-8")


def test_persist_voice_writes_a_known_voice(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")

    voices_service.persist_voice(path, "openai", "marin", set_as_provider=True)

    content = path.read_text(encoding="utf-8")
    assert 'voice = "marin"' in content
    assert 'provider = "openai"' in content


class FakeProviderWithCache:
    """Simula um provider com cache: metade das vozes já tem arquivo salvo."""

    def __init__(self, cached_voice_ids: set[str], tmp_path: Path) -> None:
        self.cached_voice_ids = cached_voice_ids
        self.tmp_path = tmp_path

    def cache_path(self, request: SpeechRequest) -> Path:
        return self.tmp_path / f"{request.voice}.mp3"


def test_build_preview_plan_detects_cache_hits_without_network(tmp_path: Path) -> None:
    (tmp_path / "marin.mp3").write_bytes(b"ja existe")
    provider = FakeProviderWithCache({"marin"}, tmp_path)
    voices = [
        VoiceInfo(id="marin", name="marin", provider="openai"),
        VoiceInfo(id="cedar", name="cedar", provider="openai"),
    ]

    plans = voices_service.build_preview_plan(provider, voices, None, 180, "tts-1-hd")

    by_id = {plan.voice.id: plan for plan in plans}
    assert by_id["marin"].already_cached is True
    assert by_id["cedar"].already_cached is False
    assert all(plan.request.text == DEFAULT_VOICE_PREVIEW_TEXT for plan in plans)


def test_build_preview_plan_uses_custom_text_when_given(tmp_path: Path) -> None:
    provider = FakeProviderWithCache(set(), tmp_path)
    voices = [VoiceInfo(id="marin", name="marin", provider="openai")]

    plans = voices_service.build_preview_plan(provider, voices, "Teste customizado", 180, None)

    assert plans[0].request.text == "Teste customizado"


def test_uncached_count_only_counts_missing_samples(tmp_path: Path) -> None:
    (tmp_path / "marin.mp3").write_bytes(b"ja existe")
    provider = FakeProviderWithCache({"marin"}, tmp_path)
    voices = [
        VoiceInfo(id="marin", name="marin", provider="openai"),
        VoiceInfo(id="cedar", name="cedar", provider="openai"),
    ]

    plans = voices_service.build_preview_plan(provider, voices, None, 180, None)

    assert voices_service.uncached_count(plans) == 1


def test_resolve_voice_target_selects_a_single_voice_by_id() -> None:
    known = [
        VoiceInfo(id="marin", name="marin", provider="openai"),
        VoiceInfo(id="cedar", name="cedar", provider="openai"),
    ]

    resolved = voices_service.resolve_voice_target("cedar", False, known)

    assert [voice.id for voice in resolved] == ["cedar"]


def test_resolve_voice_target_returns_everything_with_all_flag() -> None:
    known = [
        VoiceInfo(id="marin", name="marin", provider="openai"),
        VoiceInfo(id="cedar", name="cedar", provider="openai"),
    ]

    resolved = voices_service.resolve_voice_target("", True, known)

    assert resolved == known


def test_resolve_voice_target_rejects_an_unknown_voice() -> None:
    known = [VoiceInfo(id="marin", name="marin", provider="openai")]

    with pytest.raises(UnknownVoiceError, match="banana"):
        voices_service.resolve_voice_target("banana", False, known)
