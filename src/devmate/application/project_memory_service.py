"""Contexto curto e sempre presente do projeto (ex.: AGENTS.md).

Diferente da busca por trechos relevantes (que muda a cada pergunta), esta é
uma memória fixa: os mesmos arquivos, lidos e injetados no `system_instructions`
de toda conversa, para a Diana já chegar sabendo convenções do projeto sem
precisar que o histórico ou a busca "encontrem" isso. Conteúdo confiável — os
mesmos arquivos que já orientam qualquer pessoa (ou agente) trabalhando no
projeto — não é tratado como `untrusted_repository_context`.
"""

from __future__ import annotations

from devmate.adapters.filesystem.local_filesystem import LocalFilesystem
from devmate.errors import DevMateError


class ProjectMemoryService:
    def __init__(
        self,
        filesystem: LocalFilesystem,
        files: tuple[str, ...],
        max_chars: int,
        enabled: bool = True,
    ) -> None:
        self.filesystem = filesystem
        self.files = files
        self.max_chars = max_chars
        self.enabled = enabled
        # Chave: caminho configurado. Valor: (hash do conteúdo, bloco já renderizado).
        # Evita re-truncar/re-formatar quando o arquivo não mudou entre chamadas no
        # mesmo processo (ex.: `devmate serve`, o daemon de voz).
        self._cache: dict[str, tuple[str, str]] = {}

    def render(self) -> str:
        """Concatena os arquivos configurados; arquivos ausentes são ignorados em silêncio."""
        if not self.enabled or not self.files:
            return ""
        rendered = (self._render_one(relative) for relative in self.files)
        return "\n\n".join(block for block in rendered if block)

    def _render_one(self, relative: str) -> str | None:
        try:
            _path, content, digest = self.filesystem.read_text(relative)
        except DevMateError:
            return None
        cached = self._cache.get(relative)
        if cached is not None and cached[0] == digest:
            return cached[1]
        trimmed = content
        if len(trimmed) > self.max_chars:
            trimmed = trimmed[: self.max_chars] + "\n\n[conteúdo truncado pelo limite configurado]"
        block = f'<project_memory source="{relative}">\n{trimmed.strip()}\n</project_memory>'
        self._cache[relative] = (digest, block)
        return block
