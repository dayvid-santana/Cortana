"""Reprodução local de um arquivo de áudio já sintetizado.

No Windows a reprodução usa o ``MediaPlayer`` do WPF via PowerShell. As vozes SAPI
não participam: este componente apenas toca o arquivo produzido pelo provider
remoto, portanto a síntese continua independente das vozes instaladas no sistema.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from devmate.errors import AudioPlaybackError

CommandRunner = Callable[[Sequence[str], dict[str, str] | None], None]

PATH_VARIABLE = "DEVMATE_AUDIO_PATH"

# O caminho chega por variável de ambiente para nunca ser interpolado no script.
_PLAY_SCRIPT = (
    "Add-Type -AssemblyName PresentationCore; "
    "$player = New-Object System.Windows.Media.MediaPlayer; "
    f"$player.Open([uri]$env:{PATH_VARIABLE}); "
    "Start-Sleep -Milliseconds 400; "
    "$duration = $player.NaturalDuration; "
    "$player.Play(); "
    "if ($duration.HasTimeSpan) { "
    "  Start-Sleep -Seconds $duration.TimeSpan.TotalSeconds "
    "} else { Start-Sleep -Seconds 10 }; "
    "$player.Stop(); $player.Close()"
)

_LINUX_PLAYERS = ("paplay", "aplay", "ffplay", "mpv")


def _default_runner(command: Sequence[str], environment: dict[str, str] | None) -> None:
    subprocess.run(
        list(command),
        check=True,
        timeout=300,
        env=environment,
        capture_output=True,
    )


class SystemAudioPlayer:
    """Toca arquivos de áudio com o mecanismo disponível no sistema operacional."""

    name = "system"

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self._runner = runner or _default_runner

    def _linux_player(self) -> str | None:
        for candidate in _LINUX_PLAYERS:
            if shutil.which(candidate) is not None:
                return candidate
        return None

    def available(self) -> tuple[bool, str | None]:
        if sys.platform == "win32":
            available = shutil.which("powershell") is not None
            return available, None if available else "PowerShell não foi encontrado."
        if sys.platform == "darwin":
            available = shutil.which("afplay") is not None
            return available, None if available else "afplay não foi encontrado."
        player = self._linux_player()
        if player is None:
            return False, f"Nenhum player encontrado (procurei por {', '.join(_LINUX_PLAYERS)})."
        return True, None

    def _command(self, path: Path) -> tuple[list[str], dict[str, str] | None]:
        if sys.platform == "win32":
            environment = os.environ.copy()
            environment[PATH_VARIABLE] = str(path)
            return (
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PLAY_SCRIPT],
                environment,
            )
        if sys.platform == "darwin":
            return ["afplay", str(path)], None
        player = self._linux_player() or "aplay"
        if player == "ffplay":
            return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)], None
        if player == "mpv":
            return ["mpv", "--no-video", "--really-quiet", str(path)], None
        return [player, str(path)], None

    def play(self, path: Path) -> None:
        available, reason = self.available()
        if not available:
            raise AudioPlaybackError(reason or "Não há player de áudio disponível.")
        if not path.exists():
            raise AudioPlaybackError(f"Arquivo de áudio não encontrado: {path}")
        command, environment = self._command(path)
        try:
            self._runner(command, environment)
        except (OSError, subprocess.SubprocessError) as exc:
            raise AudioPlaybackError(f"Falha ao reproduzir o áudio: {exc}") from exc
