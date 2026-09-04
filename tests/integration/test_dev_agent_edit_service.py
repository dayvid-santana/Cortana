from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from devmate.adapters.git.subprocess_git import SubprocessGit
from devmate.application.dev_agent_edit_service import DevAgentEditService
from devmate.errors import DevAgentJobFailedError

VALID_DIFF = """diff --git a/greeting.txt b/greeting.txt
index e69de29..3b18e51 100644
--- a/greeting.txt
+++ b/greeting.txt
@@ -1 +1 @@
-ola mundo
+ola, mundo!
"""


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "greeting.txt").write_text("ola mundo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


class FakeClient:
    def __init__(self, plan: dict[str, Any], job_states: list[dict[str, Any]]) -> None:
        self.plan = plan
        self.job_states = job_states
        self.job_calls = 0
        self.cleaned_up: list[str] = []

    def available(self) -> tuple[bool, str | None]:
        return True, None

    def create_plan(self, cwd: Path, objective: str) -> dict[str, Any]:
        return self.plan

    def start(self, plan_id: str, confirmed_write: bool) -> dict[str, Any]:
        return {"id": "job-1"}

    def wait_for_completion(
        self, job_id: str, poll_seconds: float, timeout_seconds: float
    ) -> dict[str, Any]:
        return self.job_states[-1]

    def cleanup(self, job_id: str) -> None:
        self.cleaned_up.append(job_id)


def make_service(repo: Path, plan: dict[str, Any], job: dict[str, Any]) -> DevAgentEditService:
    client = FakeClient(plan, [job])
    git = SubprocessGit(repo)
    return DevAgentEditService(client, git, repo)  # type: ignore[arg-type]


def test_propose_builds_a_plan_from_the_dev_agent_response(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    plan_payload = {
        "id": "plan-1",
        "objective": "corrigir saudação",
        "relevant_files": ["greeting.txt"],
        "warnings": ["arquivo pequeno"],
        "architecture_decision_required": False,
    }
    service = make_service(repo, plan_payload, {"status": "completed", "diff": VALID_DIFF})

    plan = service.propose("corrigir saudação")

    assert plan.id == "plan-1"
    assert plan.relevant_files == ("greeting.txt",)
    assert plan.warnings == ("arquivo pequeno",)
    assert plan.architecture_decision_required is False


def test_run_returns_the_diff_from_the_completed_job(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    service = make_service(repo, {"id": "plan-1"}, {"status": "completed", "diff": VALID_DIFF})

    result = service.run("plan-1")

    assert result.succeeded is True
    assert result.has_changes is True
    assert result.diff == VALID_DIFF


def test_run_reports_failure_without_raising(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    service = make_service(
        repo, {"id": "plan-1"}, {"status": "failed", "diff": "", "error": "codex indisponível"}
    )

    result = service.run("plan-1")

    assert result.succeeded is False
    assert result.error == "codex indisponível"


def test_apply_writes_the_diff_to_the_real_working_tree(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    service = make_service(repo, {"id": "plan-1"}, {"status": "completed", "diff": VALID_DIFF})

    service.apply(VALID_DIFF)

    assert (repo / "greeting.txt").read_text(encoding="utf-8") == "ola, mundo!\n"


def test_apply_rejects_a_diff_that_does_not_match_the_working_tree(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "greeting.txt").write_text("já mudou por fora\n", encoding="utf-8")
    service = make_service(repo, {"id": "plan-1"}, {"status": "completed", "diff": VALID_DIFF})

    with pytest.raises(DevAgentJobFailedError):
        service.apply(VALID_DIFF)

    # o arquivo não deve ter sido tocado por uma aplicação parcial
    assert (repo / "greeting.txt").read_text(encoding="utf-8") == "já mudou por fora\n"
