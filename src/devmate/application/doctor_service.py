"""Diagnóstico local que não chama LLMs nem rede."""

from __future__ import annotations

import shutil
import sqlite3
import sys
from dataclasses import dataclass

from devmate.bootstrap import Runtime


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str


def doctor(runtime: Runtime) -> list[Check]:
    checks = [
        Check("Python", sys.version_info >= (3, 11), sys.version.split()[0]),
        Check(
            "Git",
            shutil.which("git") is not None,
            "encontrado" if shutil.which("git") else "não encontrado",
        ),
        Check("Repositório", runtime.root.is_dir(), str(runtime.root)),
        Check("Configuração", (runtime.root / ".devmate" / "config.toml").exists(), "local"),
        Check("Banco", (runtime.root / ".devmate" / "state.db").exists(), "SQLite"),
    ]
    try:
        connection = sqlite3.connect(runtime.root / ".devmate" / "state.db")
        connection.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS __devmate_fts_probe USING fts5(content)"
        )
        connection.execute("DROP TABLE __devmate_fts_probe")
        connection.close()
        checks.append(Check("SQLite FTS5", True, "disponível"))
    except sqlite3.DatabaseError:
        checks.append(Check("SQLite FTS5", False, "indisponível"))
    for name, available, detail in runtime.providers.entries():
        checks.append(Check(f"Provider {name}", available, detail or "disponível"))
    speech = runtime.reading_service().speech
    available, detail = speech.available()
    checks.append(Check(f"Fala {speech.name}", available, detail or "disponível"))
    voice_input = runtime.voice_service().input_provider
    available, detail = voice_input.available()
    checks.append(Check(f"Entrada de voz {voice_input.name}", available, detail or "disponível"))
    checks.extend(_speech_checks(runtime))
    return checks


def _speech_checks(runtime: Runtime) -> list[Check]:
    """Seção dedicada de fala: provider, modelo, voz, credencial e reprodução.

    Nunca inclui o valor da credencial — só se a variável de ambiente está presente.
    """
    config = runtime.config.speech
    speech = runtime.reading_service().speech
    capabilities = speech.capabilities()
    checks = [
        Check("Speech provider", True, config.provider),
        Check("Speech voice", config.voice is not None, config.voice or "(padrão do provider)"),
    ]
    if capabilities.remote:
        api_key_configured = getattr(speech, "api_key_configured", lambda: False)()
        model_name = f"Speech model ({config.provider})"
        checks.append(Check(model_name, True, config.providers.openai.model))
        key_detail = "configured" if api_key_configured else "missing"
        checks.append(Check("Speech API key", api_key_configured, key_detail))
        player = getattr(speech, "player", None)
        if player is not None:
            player_available, player_detail = player.available()
            checks.append(Check("Audio player", player_available, player_detail or "available"))
        checks.append(
            Check(
                "Preview cache",
                runtime.root.joinpath(".devmate").is_dir(),
                "available",
            )
        )
    return checks
