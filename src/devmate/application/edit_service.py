"""Propostas de edição sobre código já autorizado; a Diana nunca escreve sem confirmação."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from devmate.adapters.filesystem.local_filesystem import LocalFilesystem
from devmate.adapters.llm.registry import ProviderRegistry
from devmate.application.inspection_service import InspectionService
from devmate.domain.enums import Scope
from devmate.domain.models import LLMRequest
from devmate.errors import ProviderResponseError, ProviderUnavailableError
from devmate.prompts.code_edit import CODE_EDIT_SYSTEM

_FILE_BLOCK = re.compile(r">>> FILE: *(?P<path>[^\n]+)\n(?P<body>.*?)\n<<< END FILE", re.DOTALL)

# O provider codex roda sempre em sandbox somente leitura (ver CodexProvider.complete:
# Sandbox.read_only + instrução explícita de não modificar arquivos) — isso é uma
# característica estrutural do adapter, não algo que varia por tarefa. Usá-lo aqui só
# produz uma resposta em prosa explicando por que não pode editar, nunca um
# ">>> FILE:" de verdade, então falhar cedo e com uma mensagem clara é melhor do que
# deixar `_parse_response` devolver uma proposta vazia e confusa.
_READ_ONLY_PROVIDERS = frozenset({"codex"})


@dataclass(frozen=True, slots=True)
class ProposedFileChange:
    path: str
    original: str
    proposed: str

    @property
    def changed(self) -> bool:
        return self.original != self.proposed

    @property
    def diff(self) -> str:
        return "".join(
            difflib.unified_diff(
                self.original.splitlines(keepends=True),
                self.proposed.splitlines(keepends=True),
                fromfile=f"a/{self.path}",
                tofile=f"b/{self.path}",
            )
        )


@dataclass(frozen=True, slots=True)
class EditProposal:
    commit_hash: str
    narrative: str
    changes: tuple[ProposedFileChange, ...]


def _strip_stray_fence(body: str) -> str:
    """Tolera o modelo envolver o conteúdo em ``` apesar da instrução em contrário."""
    lines = body.split("\n")
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


def _parse_response(text: str) -> tuple[str, list[tuple[str, str]]]:
    matches = list(_FILE_BLOCK.finditer(text))
    narrative = text[: matches[0].start()].strip() if matches else text.strip()
    blocks = [
        (match.group("path").strip(), _strip_stray_fence(match.group("body"))) for match in matches
    ]
    return narrative, blocks


class EditProposalService:
    """Gera propostas de edição; a escrita em disco só acontece fora deste serviço."""

    def __init__(
        self,
        inspection: InspectionService,
        filesystem: LocalFilesystem,
        providers: ProviderRegistry,
    ) -> None:
        self.inspection = inspection
        self.filesystem = filesystem
        self.providers = providers

    def propose(
        self,
        project_id: int,
        question: str,
        provider_name: str,
        commit_ref: str | None,
        files: list[str],
        full_repo: bool = False,
        model: str | None = None,
        system_instructions: str | None = None,
        task: str = "code_edit",
    ) -> EditProposal:
        if provider_name in _READ_ONLY_PROVIDERS:
            raise ProviderUnavailableError(
                f"O provider '{provider_name}' é somente leitura por design e nunca propõe "
                "edições — escolha outro provider (ex.: openai) para editar diretamente, ou "
                "use o dev-agent."
            )
        context = self.inspection.build(project_id, commit_ref, files, full_repo)
        originals = dict(context.code_files)
        request = LLMRequest(
            task=task,
            question=question,
            scope=Scope.CODE,
            chunks=context.chunks,
            system_instructions=system_instructions or CODE_EDIT_SYSTEM,
            model=model,
        )
        response = self.providers.get(provider_name).complete(request)
        narrative, blocks = _parse_response(response.text)
        changes: list[ProposedFileChange] = []
        for raw_path, proposed in blocks:
            relative = raw_path.replace("\\", "/").strip()
            if relative not in originals:
                raise ProviderResponseError(
                    f"A resposta propôs alterar '{relative}', fora do escopo de código "
                    "autorizado para esta pergunta."
                )
            changes.append(ProposedFileChange(relative, originals[relative], proposed))
        return EditProposal(context.commit_hash, narrative, tuple(changes))
