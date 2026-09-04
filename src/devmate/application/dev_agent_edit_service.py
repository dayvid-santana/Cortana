"""Edição delegada ao dev-agent: plano revisável, execução isolada, diff aplicado localmente.

Diferente de `EditProposalService` (uma chamada de LLM, escrita direta), aqui o
dev-agent planeja e executa num worktree Git isolado em background; devmate só
acompanha o job e, com a pessoa usuária confirmando, aplica o diff resultante
no working tree real via `git apply` — nunca importa nem escreve por conta própria.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from devmate.adapters.agents.dev_agent_client import DevAgentClient
from devmate.adapters.git.subprocess_git import SubprocessGit
from devmate.errors import DevAgentJobFailedError

FAILURE_STATUSES = frozenset({"failed", "cancelled", "blocked"})


@dataclass(frozen=True, slots=True)
class DevAgentPlan:
    id: str
    objective: str
    relevant_files: tuple[str, ...]
    warnings: tuple[str, ...]
    architecture_decision_required: bool


@dataclass(frozen=True, slots=True)
class DevAgentEditResult:
    job_id: str
    status: str
    diff: str
    worktree_path: str | None
    branch: str | None
    error: str | None

    @property
    def succeeded(self) -> bool:
        return self.status not in FAILURE_STATUSES

    @property
    def has_changes(self) -> bool:
        return bool(self.diff.strip())


class DevAgentEditService:
    def __init__(self, client: DevAgentClient, git: SubprocessGit, project_root: Path) -> None:
        self.client = client
        self.git = git
        self.project_root = project_root

    def propose(self, objective: str) -> DevAgentPlan:
        raw = self.client.create_plan(self.project_root, objective)
        return DevAgentPlan(
            id=str(raw["id"]),
            objective=str(raw.get("objective", objective)),
            relevant_files=tuple(raw.get("relevant_files") or ()),
            warnings=tuple(raw.get("warnings") or ()),
            architecture_decision_required=bool(raw.get("architecture_decision_required")),
        )

    def run(
        self, plan_id: str, poll_seconds: float = 2.0, timeout_seconds: float = 600.0
    ) -> DevAgentEditResult:
        started = self.client.start(plan_id, confirmed_write=True)
        job_id = str(started["id"])
        final = self.client.wait_for_completion(job_id, poll_seconds, timeout_seconds)
        return DevAgentEditResult(
            job_id=job_id,
            status=str(final.get("status", "unknown")),
            diff=str(final.get("diff") or ""),
            worktree_path=final.get("worktree_path"),
            branch=final.get("branch"),
            error=final.get("error"),
        )

    def apply(self, diff_text: str) -> None:
        ok, detail = self.git.apply_check(diff_text)
        if not ok:
            raise DevAgentJobFailedError(
                f"O diff do dev-agent não se aplica ao working tree atual: {detail}"
            )
        self.git.apply(diff_text)

    def cleanup(self, job_id: str) -> None:
        self.client.cleanup(job_id)
