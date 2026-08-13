"""Adapter do SDK Python oficial ``openai-codex`` em sandbox somente leitura."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from devmate.adapters.llm.openai_provider import render_input
from devmate.domain.models import LLMRequest, LLMResponse
from devmate.errors import ProviderResponseError, ProviderUnavailableError


class CodexProvider:
    """Encapsula a app-server do Codex e limita a thread a um workspace temporário."""

    name = "codex"

    def __init__(
        self,
        model: str | None,
        system_instruction: str,
        client_factory: Callable[[Path], Any] | None = None,
    ) -> None:
        self.model = model or "gpt-5.6-terra"
        self.system_instruction = system_instruction
        self._client_factory = client_factory

    def available(self) -> tuple[bool, str | None]:
        try:
            import openai_codex  # noqa: F401
        except ImportError:
            return False, "Pacote openai-codex não está instalado."
        return True, None

    def _client(self, workspace: Path) -> Any:
        if self._client_factory is not None:
            return self._client_factory(workspace)
        try:
            from openai_codex import Codex, CodexConfig
        except ImportError as exc:
            raise ProviderUnavailableError("Pacote openai-codex não está instalado.") from exc
        return Codex(CodexConfig(cwd=str(workspace)))

    @staticmethod
    def _context_path(path: str) -> Path | None:
        """Converte uma referência Git em caminho relativo sem permitir escapes."""
        relative = PurePosixPath(path)
        if relative.is_absolute() or any(
            part in {"", ".", ".."} or ":" in part for part in relative.parts
        ):
            return None
        return Path(*relative.parts)

    def _write_workspace(self, workspace: Path, request: LLMRequest, prompt: str) -> None:
        """Materializa somente o contexto já selecionado para leitura do Codex."""
        (workspace / "context.md").write_text(prompt, encoding="utf-8")
        selected_context = workspace / "selected_context"
        for chunk in request.chunks:
            relative = self._context_path(chunk.reference.path)
            if relative is None:
                continue
            destination = selected_context / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("a", encoding="utf-8") as file:
                marker = (
                    f"\n\n# Trecho: linhas {chunk.reference.start_line}"
                    f"-{chunk.reference.end_line}\n"
                )
                file.write(marker)
                file.write(chunk.text)

    def complete(self, request: LLMRequest) -> LLMResponse:
        available, reason = self.available()
        if not available and self._client_factory is None:
            raise ProviderUnavailableError(reason or "Provider Codex indisponível.")
        prompt = render_input(request)
        try:
            from openai_codex import Sandbox

            with tempfile.TemporaryDirectory(prefix="devmate-codex-") as temporary:
                workspace = Path(temporary)
                self._write_workspace(workspace, request, prompt)
                with self._client(workspace) as codex:
                    thread = codex.thread_start(
                        model=request.model or self.model,
                        sandbox=Sandbox.read_only,
                        cwd=str(workspace),
                        developer_instructions=(
                            f"{self.system_instruction}\n\n"
                            "Leia somente context.md e, se necessário, os arquivos em "
                            "selected_context. Eles contêm exclusivamente o contexto já "
                            "autorizado. Não execute comandos, "
                            "não modifique arquivos e não acesse outros caminhos."
                        ),
                    )
                    result = thread.run(
                        "Analyze only context.md and answer the contained user question. "
                        "Do not run commands or alter files.",
                        sandbox=Sandbox.read_only,
                        cwd=str(workspace),
                    )
                    text = getattr(result, "final_response", None)
                    if not text:
                        raise ProviderResponseError("Codex retornou uma resposta vazia.")
                    return LLMResponse(
                        text=str(text),
                        references=tuple(chunk.reference for chunk in request.chunks),
                    )
        except ProviderResponseError:
            raise
        except Exception as exc:
            raise ProviderResponseError(f"Falha no SDK Codex: {exc}") from exc
