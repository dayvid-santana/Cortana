from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from devmate.adapters.audio.system_player import PATH_VARIABLE, SystemAudioPlayer
from devmate.errors import AudioPlaybackError

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Script é do Windows.")


class RecordingRunner:
    def __init__(self) -> None:
        self.command: Sequence[str] | None = None
        self.environment: dict[str, str] | None = None

    def __call__(self, command: Sequence[str], environment: dict[str, str] | None) -> None:
        self.command = command
        self.environment = environment


@windows_only
def test_play_passes_the_path_by_environment_never_in_the_script(tmp_path: Path) -> None:
    audio = tmp_path / "sample.mp3"
    audio.write_bytes(b"fake")
    runner = RecordingRunner()
    player = SystemAudioPlayer(runner=runner)

    player.play(audio)

    assert runner.environment is not None
    assert runner.environment[PATH_VARIABLE] == str(audio)
    assert str(audio) not in " ".join(runner.command or [])


def test_play_raises_when_the_file_does_not_exist() -> None:
    player = SystemAudioPlayer(runner=RecordingRunner())

    with pytest.raises(AudioPlaybackError, match="não encontrado"):
        player.play(Path("nao-existe.mp3"))
