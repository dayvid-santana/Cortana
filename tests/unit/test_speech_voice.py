from __future__ import annotations

import sys
from collections.abc import Sequence

import pytest

from devmate.adapters.speech.system_provider import (
    RATE_VARIABLE,
    TEXT_VARIABLE,
    VOICE_VARIABLE,
    SystemSpeechProvider,
)
from devmate.config import AppConfig

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Script SAPI é do Windows.")


class RecordingRunner:
    def __init__(self, output: str = "") -> None:
        self.output = output
        self.command: Sequence[str] | None = None
        self.environment: dict[str, str] | None = None

    def __call__(self, command: Sequence[str], environment: dict[str, str] | None) -> str:
        self.command = command
        self.environment = environment
        return self.output


@pytest.mark.parametrize(
    ("words_per_minute", "expected"),
    [(180, 0), (80, -10), (450, 10), (80 - 500, -10), (450 + 500, 10)],
)
def test_sapi_rate_maps_words_per_minute_into_the_sapi_scale(
    words_per_minute: int, expected: int
) -> None:
    assert SystemSpeechProvider(words_per_minute).sapi_rate() == expected


@windows_only
def test_speak_passes_text_and_voice_by_environment_never_in_the_script() -> None:
    runner = RecordingRunner()
    provider = SystemSpeechProvider(rate=180, voice="Maria", runner=runner)

    provider.speak('texto "perigoso"; Remove-Item C:\\ -Recurse')

    assert runner.environment is not None
    assert runner.environment[TEXT_VARIABLE] == 'texto "perigoso"; Remove-Item C:\\ -Recurse'
    assert runner.environment[VOICE_VARIABLE] == "Maria"
    assert runner.environment[RATE_VARIABLE] == "0"
    # O conteúdo não pode aparecer no script; só a referência à variável.
    script = " ".join(runner.command or [])
    assert "Remove-Item" not in script
    assert "Maria" not in script
    assert f"$env:{VOICE_VARIABLE}" in script


@windows_only
def test_speak_without_a_configured_voice_keeps_the_system_default() -> None:
    runner = RecordingRunner()

    SystemSpeechProvider(rate=180, runner=runner).speak("olá")

    assert runner.environment is not None
    # Vazio faz o script pular a seleção e manter a voz padrão do sistema.
    assert runner.environment[VOICE_VARIABLE] == ""


@windows_only
def test_raw_voice_descriptions_returns_one_entry_per_line() -> None:
    runner = RecordingRunner(
        output="Microsoft Maria Desktop - Portuguese(Brazil)\n"
        "Microsoft Zira Desktop - English (United States)\n\n"
    )

    found = SystemSpeechProvider(runner=runner).raw_voice_descriptions()

    assert found == [
        "Microsoft Maria Desktop - Portuguese(Brazil)",
        "Microsoft Zira Desktop - English (United States)",
    ]


@windows_only
def test_list_voices_wraps_each_description_as_voice_info() -> None:
    runner = RecordingRunner(output="Microsoft Maria Desktop - Portuguese(Brazil)\n")

    found = SystemSpeechProvider(runner=runner).list_voices()

    assert len(found) == 1
    assert found[0].id == "Microsoft Maria Desktop - Portuguese(Brazil)"
    assert found[0].provider == "system"


def test_voice_is_optional_in_the_configuration() -> None:
    assert AppConfig().speech.voice is None
    assert AppConfig.model_validate({"speech": {"voice": "Maria"}}).speech.voice == "Maria"
