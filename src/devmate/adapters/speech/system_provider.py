"""Fala local com argumentos seguros, sem interpolar conteúdo em comandos."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from devmate.errors import SpeechProviderUnavailableError


class SystemSpeechProvider:
    name = "system"

    def __init__(self, rate: int = 180) -> None:
        self.rate = rate

    def available(self) -> tuple[bool, str | None]:
        if sys.platform == "win32":
            available = shutil.which("powershell") is not None
            return available, None if available else "PowerShell não foi encontrado."
        command = "say" if sys.platform == "darwin" else "espeak"
        available = shutil.which(command) is not None
        return available, None if available else f"{command} não foi encontrado."

    def speak(self, text: str) -> None:
        available, reason = self.available()
        if not available:
            raise SpeechProviderUnavailableError(reason or "Provider de fala indisponível.")
        if sys.platform == "win32":
            environment = os.environ.copy()
            environment["DEVMATE_TTS_TEXT"] = text
            script = (
                "$speaker = New-Object -ComObject SAPI.SpVoice; "
                "$speaker.Rate = 0; $speaker.Speak($env:DEVMATE_TTS_TEXT)"
            )
            command = ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
        elif sys.platform == "darwin":
            environment = None
            command = ["say", "-r", str(self.rate), text]
        else:
            environment = None
            command = ["espeak", "-s", str(self.rate), text]
        try:
            subprocess.run(command, check=True, timeout=90, env=environment, capture_output=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SpeechProviderUnavailableError(f"Falha ao narrar localmente: {exc}") from exc
