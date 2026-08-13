"""Resolução do Runtime para cada requisição, igual ao caminho da CLI."""

from __future__ import annotations

from pathlib import Path

from devmate.bootstrap import Runtime, load_runtime


def get_runtime() -> Runtime:
    """Repositório é resolvido a partir do diretório de trabalho do processo da API.

    Igual à CLI: um processo serve um repositório. ``ConfigurationError`` (não
    inicializado) propaga e vira 409 pelo handler central de erros.
    """
    return load_runtime(Path.cwd())
