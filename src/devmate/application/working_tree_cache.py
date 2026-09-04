"""Cache de conteúdo de arquivos do working tree, mantida fresca por eventos.

Diferente do contexto baseado em commit (`git show <commit>:<arquivo>`, o padrão do
resto do DevMate), isto lê o disco de verdade — pensado para quem está programando
com a Diana ativa e não quer commitar a cada pergunta. Nunca chama um provider de
LLM: é leitura de arquivo e comparação de hash, local e gratuito. O custo de tokens
só existe quando uma pergunta de verdade é feita com esse conteúdo já pronto.
"""

from __future__ import annotations

import threading
from pathlib import Path


class WorkingTreeCache:
    """Uma por projeto. `WorkingTreeWatcher` mantém as entradas frescas a partir de
    eventos de filesystem; `get` só lê o disco por conta própria no primeiro acesso a
    um caminho que nenhum evento ainda tocou (ex.: logo após o servidor subir)."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._lock = threading.Lock()
        self._content: dict[str, str] = {}

    def get(self, relative_path: str) -> str:
        with self._lock:
            cached = self._content.get(relative_path)
        if cached is not None:
            return cached
        return self.refresh(relative_path)

    def refresh(self, relative_path: str) -> str:
        """Lê `relative_path` do disco agora e atualiza a entrada — é isto que o
        watcher chama a cada evento de criação/edição, só para o arquivo mudado."""
        content = (self.root / relative_path).read_text(encoding="utf-8", errors="replace")
        with self._lock:
            self._content[relative_path] = content
        return content

    def invalidate(self, relative_path: str) -> None:
        with self._lock:
            self._content.pop(relative_path, None)

    def known_paths(self) -> list[str]:
        with self._lock:
            return list(self._content)
