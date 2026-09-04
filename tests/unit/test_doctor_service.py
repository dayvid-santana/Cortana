from __future__ import annotations

from pathlib import Path
from typing import Any

from devmate.application.doctor_service import _speech_checks
from devmate.config import AppConfig


class FakeReadingService:
    def __init__(self, speech: Any) -> None:
        self.speech = speech


class FakeRuntime:
    def __init__(self, root: Path, config: AppConfig, speech: Any) -> None:
        self.root = root
        self.config = config
        self._speech = speech

    def reading_service(self) -> FakeReadingService:
        return FakeReadingService(self._speech)


class FakePlayer:
    def available(self) -> tuple[bool, str | None]:
        return True, None


class FakeCapabilities:
    remote = True


class FakeEdgeSpeech:
    """Sem `model` nem `api_key_configured`: provider gratuito, sem credencial."""

    def capabilities(self) -> FakeCapabilities:
        return FakeCapabilities()


class FakeOpenAISpeech:
    def __init__(self, model: str, configured: bool) -> None:
        self.model = model
        self.player = FakePlayer()
        self._configured = configured

    def capabilities(self) -> FakeCapabilities:
        return FakeCapabilities()

    def api_key_configured(self) -> bool:
        return self._configured


def make_config(provider: str) -> AppConfig:
    config = AppConfig()
    config.speech.provider = provider
    config.speech.voice = "some-voice"
    return config


def test_free_providers_without_a_credential_do_not_report_a_missing_api_key(
    tmp_path: Path,
) -> None:
    runtime = FakeRuntime(tmp_path, make_config("edge"), FakeEdgeSpeech())

    checks = _speech_checks(runtime)  # type: ignore[arg-type]
    names = {check.name for check in checks}

    assert "Speech API key" not in names
    assert not any(name.startswith("Speech model") for name in names)


def test_remote_provider_reports_its_own_model_not_a_hardcoded_one(tmp_path: Path) -> None:
    runtime = FakeRuntime(tmp_path, make_config("elevenlabs"), FakeOpenAISpeech("tts-1-hd", True))

    checks = _speech_checks(runtime)  # type: ignore[arg-type]
    model_checks = [check for check in checks if check.name == "Speech model (elevenlabs)"]

    assert len(model_checks) == 1
    assert model_checks[0].detail == "tts-1-hd"


def test_missing_api_key_is_reported_as_not_ok(tmp_path: Path) -> None:
    runtime = FakeRuntime(
        tmp_path, make_config("openai"), FakeOpenAISpeech("gpt-4o-mini-tts", False)
    )

    checks = _speech_checks(runtime)  # type: ignore[arg-type]
    key_check = next(check for check in checks if check.name == "Speech API key")

    assert key_check.ok is False
    assert key_check.detail == "missing"
