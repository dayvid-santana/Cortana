from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from devmate.application.edit_service import EditProposalService
from devmate.application.project_service import initialize_project
from devmate.bootstrap import load_runtime
from devmate.domain.models import LLMResponse
from devmate.errors import ProviderResponseError


class _FixedProvider:
    name = "fixed"

    def __init__(self, text: str) -> None:
        self.text = text

    def available(self) -> tuple[bool, str | None]:
        return True, None

    def complete(self, request: object) -> LLMResponse:
        del request
        return LLMResponse(text=self.text)


class _FixedRegistry:
    def __init__(self, provider: _FixedProvider) -> None:
        self._provider = provider

    def get(self, name: str) -> _FixedProvider:
        del name
        return self._provider


def _service_over_repo(git_repo: Path, response_text: str) -> tuple[EditProposalService, int]:
    source = git_repo / "src"
    source.mkdir()
    (source / "app.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "src/app.py"], cwd=git_repo, check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "commit", "-m", "feat: adiciona app"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    initialize_project(git_repo)
    runtime = load_runtime(git_repo)
    runtime.scan_service().scan(runtime.project_id)
    registry = _FixedRegistry(_FixedProvider(response_text))
    service = EditProposalService(runtime.inspection_service(), runtime.filesystem, registry)
    return service, runtime.project_id


def test_propose_parses_a_well_formed_file_block(git_repo: Path) -> None:
    service, project_id = _service_over_repo(
        git_repo, "Troquei o valor.\n\n>>> FILE: src/app.py\nx = 2\n\n<<< END FILE\n"
    )

    proposal = service.propose(project_id, "mude o valor", "fixed", None, ["src/app.py"])

    assert proposal.narrative == "Troquei o valor."
    assert len(proposal.changes) == 1
    change = proposal.changes[0]
    assert change.path == "src/app.py"
    assert change.original == "x = 1\n"
    assert change.proposed == "x = 2\n"
    assert change.changed is True
    assert "-x = 1" in change.diff
    assert "+x = 2" in change.diff


def test_propose_strips_a_stray_code_fence(git_repo: Path) -> None:
    service, project_id = _service_over_repo(
        git_repo, ">>> FILE: src/app.py\n```python\nx = 3\n```\n<<< END FILE\n"
    )

    proposal = service.propose(project_id, "mude o valor", "fixed", None, ["src/app.py"])

    assert proposal.changes[0].proposed == "x = 3"


def test_propose_rejects_a_path_outside_the_authorized_selection(git_repo: Path) -> None:
    service, project_id = _service_over_repo(
        git_repo, ">>> FILE: src/other.py\nx = 1\n\n<<< END FILE\n"
    )

    with pytest.raises(ProviderResponseError):
        service.propose(project_id, "mude o valor", "fixed", None, ["src/app.py"])


def test_propose_with_no_file_blocks_returns_no_changes(git_repo: Path) -> None:
    service, project_id = _service_over_repo(git_repo, "Nenhuma alteração é necessária.")

    proposal = service.propose(project_id, "revise", "fixed", None, ["src/app.py"])

    assert proposal.changes == ()
    assert proposal.narrative == "Nenhuma alteração é necessária."
