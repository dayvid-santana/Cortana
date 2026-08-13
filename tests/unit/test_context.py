from __future__ import annotations

from devmate.application.context_service import ContextService
from devmate.application.project_service import initialize_project
from devmate.bootstrap import load_runtime
from devmate.domain.enums import Scope


def test_documentation_context_never_includes_code_by_default(git_repo) -> None:  # type: ignore[no-untyped-def]
    initialize_project(git_repo)
    runtime = load_runtime(git_repo)
    runtime.scan_service().scan(runtime.project_id)
    commit, chunks = ContextService(runtime.git, runtime.store).build(
        runtime.project_id, Scope.DOCS
    )
    assert commit.subject == "docs: descreve autenticação"
    assert chunks
    assert all(chunk.reference.path.endswith((".md", ".mdx")) for chunk in chunks)


def test_default_context_uses_current_branch_head(git_repo) -> None:  # type: ignore[no-untyped-def]
    import subprocess

    subprocess.run(
        ["git", "switch", "-c", "feature"], cwd=git_repo, check=True, capture_output=True
    )
    (git_repo / "docs" / "feature.md").write_text("# Feature\n", encoding="utf-8")
    subprocess.run(["git", "add", "docs/feature.md"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "docs: decisão somente na feature"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )
    initialize_project(git_repo)
    runtime = load_runtime(git_repo)
    runtime.scan_service().scan(runtime.project_id)
    subprocess.run(["git", "switch", "main"], cwd=git_repo, check=True, capture_output=True)
    commit, _ = ContextService(runtime.git, runtime.store).build(runtime.project_id, Scope.DOCS)
    assert commit.subject == "docs: descreve autenticação"
