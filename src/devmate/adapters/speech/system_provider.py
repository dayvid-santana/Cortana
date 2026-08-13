"""Fala local com argumentos seguros, sem interpolar conteúdo em comandos."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence

from devmate.errors import SpeechProviderUnavailableError

CommandRunner = Callable[[Sequence[str], dict[str, str] | None], str]

# O texto e a voz viajam por variável de ambiente para nunca entrarem no script.
TEXT_VARIABLE = "DEVMATE_TTS_TEXT"
VOICE_VARIABLE = "DEVMATE_TTS_VOICE"
RATE_VARIABLE = "DEVMATE_TTS_RATE"

_SPEAK_SCRIPT = (
    "$speaker = New-Object -ComObject SAPI.SpVoice; "
    f"$speaker.Rate = [int]$env:{RATE_VARIABLE}; "
    f"$wanted = $env:{VOICE_VARIABLE}; "
    "if ($wanted) { "
    "  $match = $speaker.GetVoices() | Where-Object "
    '{ $_.GetDescription() -like "*$wanted*" } | Select-Object -First 1; '
    "  if ($match) { $speaker.Voice = $match } "
    "}; "
    f"$speaker.Speak($env:{TEXT_VARIABLE})"
)

_LIST_SCRIPT = (
    "$speaker = New-Object -ComObject SAPI.SpVoice; "
    "foreach ($v in $speaker.GetVoices()) { $v.GetDescription() }"
)


def _default_runner(command: Sequence[str], environment: dict[str, str] | None) -> str:
    result = subprocess.run(
        list(command),
        check=True,
        timeout=90,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout


class SystemSpeechProvider:
    name = "system"

    def __init__(
        self,
        rate: int = 180,
        voice: str | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        self.rate = rate
        self.voice = voice
        self._runner = runner or _default_runner

    def available(self) -> tuple[bool, str | None]:
        if sys.platform == "win32":
            available = shutil.which("powershell") is not None
            return available, None if available else "PowerShell não foi encontrado."
        command = "say" if sys.platform == "darwin" else "espeak"
        available = shutil.which(command) is not None
        return available, None if available else f"{command} não foi encontrado."

    def sapi_rate(self) -> int:
        """Converte palavras por minuto na escala -10..10 do SAPI, centrada em 180."""
        if self.rate <= 180:
            return max(-10, round((self.rate - 180) / 10))
        return min(10, round((self.rate - 180) / 27))

    def list_voices(self) -> list[str]:
        """Enumera as vozes instaladas no sistema operacional."""
        available, reason = self.available()
        if not available:
            raise SpeechProviderUnavailableError(reason or "Provider de fala indisponível.")
        if sys.platform == "win32":
            command = ["powershell", "-NoProfile", "-NonInteractive", "-Command", _LIST_SCRIPT]
            environment = os.environ.copy()
        elif sys.platform == "darwin":
            command = ["say", "-v", "?"]
            environment = None
        else:
            command = ["espeak", "--voices"]
            environment = None
        try:
            output = self._runner(command, environment)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SpeechProviderUnavailableError(f"Falha ao listar vozes: {exc}") from exc
        return [line.strip() for line in output.splitlines() if line.strip()]

    def _speak_command(self, text: str) -> tuple[list[str], dict[str, str] | None]:
        if sys.platform == "win32":
            environment = os.environ.copy()
            environment[TEXT_VARIABLE] = text
            environment[VOICE_VARIABLE] = self.voice or ""
            environment[RATE_VARIABLE] = str(self.sapi_rate())
            command = ["powershell", "-NoProfile", "-NonInteractive", "-Command", _SPEAK_SCRIPT]
            return command, environment
        if sys.platform == "darwin":
            command = ["say", "-r", str(self.rate)]
            if self.voice:
                command += ["-v", self.voice]
            return [*command, text], None
        command = ["espeak", "-s", str(self.rate)]
        if self.voice:
            command += ["-v", self.voice]
        return [*command, text], None

    def speak(self, text: str) -> None:
        available, reason = self.available()
        if not available:
            raise SpeechProviderUnavailableError(reason or "Provider de fala indisponível.")
        command, environment = self._speak_command(text)
        try:
            self._runner(command, environment)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SpeechProviderUnavailableError(f"Falha ao narrar localmente: {exc}") from exc
