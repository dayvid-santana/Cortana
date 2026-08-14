"""Edição pontual de ``.devmate/config.toml`` preservando comentários e ordem.

``tomllib`` (stdlib) só lê. Para ``devmate voices set`` alterar uma única chave
sem reescrever o arquivo inteiro — perdendo comentários e a instrução do Codex —
usamos ``tomlkit``, que mantém a formatação de tudo que não foi tocado.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import tomlkit

from devmate.errors import ConfigurationError


def set_speech_voice(path: Path, voice: str, provider: str | None = None) -> None:
    """Grava ``[speech].voice`` (e opcionalmente ``[speech].provider``) no lugar."""
    document = _load(path)
    _assign(document, ("speech", "voice"), voice)
    if provider is not None:
        _assign(document, ("speech", "provider"), provider)
    _save(path, document)


def set_speech_style(path: Path, style: str | None) -> None:
    document = _load(path)
    _assign(document, ("speech", "style"), style)
    _save(path, document)


def set_default_provider(path: Path, name: str) -> None:
    document = _load(path)
    _assign(document, ("provider", "default"), name)
    _save(path, document)


def set_default_scope(path: Path, scope: str) -> None:
    """Grava ``[security].default_scope`` ("docs" ou "code") no lugar."""
    document = _load(path)
    _assign(document, ("security", "default_scope"), scope)
    _save(path, document)


def _load(path: Path) -> tomlkit.TOMLDocument:
    if not path.exists():
        return tomlkit.document()
    try:
        return tomlkit.parse(path.read_text(encoding="utf-8"))
    except tomlkit.exceptions.TOMLKitError as exc:
        raise ConfigurationError(f"Não foi possível ler {path}: {exc}") from exc


def _save(path: Path, document: tomlkit.TOMLDocument) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomlkit.dumps(document), encoding="utf-8")


def _assign(document: tomlkit.TOMLDocument, keys: tuple[str, ...], value: str | None) -> None:
    table: Any = document
    for key in keys[:-1]:
        if key not in table:
            table[key] = tomlkit.table()
        table = table[key]
    if value is None:
        table.pop(keys[-1], None)
    else:
        table[keys[-1]] = value
