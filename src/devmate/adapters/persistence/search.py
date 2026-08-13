"""Busca lexical local extensível para futura estratégia semântica."""

from __future__ import annotations

from typing import Protocol


class SearchBackend(Protocol):
    def search(self, query: str, limit: int = 10) -> list[str]: ...


class LexicalSearch:
    """Implementação de busca lexical propositalmente simples no MVP."""

    def search(self, query: str, limit: int = 10) -> list[str]:
        del query, limit
        return []
