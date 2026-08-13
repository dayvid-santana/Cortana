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
    return checks
