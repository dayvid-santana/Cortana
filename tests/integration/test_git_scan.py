from __future__ import annotations

import subprocess
from pathlib import Path

from devmate.application.project_service import initialize_project
from devmate.bootstrap import load_runtime


def run_git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def test_scan_is_idempotent_and_tracks_rename(git_repo: Path) -> None:
    initialize_project(git_repo)
    runtime = load_runtime(git_repo)
    first = runtime.scan_service().scan(runtime.project_id)
    second = runtime.scan_service().scan(runtime.project_id)
    assert first.commits_created == 2
    assert second.commits_created == 0
    run_git(git_repo, "mv", "docs/auth.md", "docs/authentication.md")
    run_git(git_repo, "commit", "-m", "docs: renomeia autenticação")
    third = runtime.scan_service().scan(runtime.project_id)
    assert third.commits_created == 1
    latest = runtime.store.latest_commit(runtime.project_id)
    assert latest is not None
    assert latest.changes[0].status == "renamed"
    assert latest.changes[0].old_path == "docs/auth.md"
    assert latest.changes[0].new_path == "docs/authentication.md"
    (git_repo / "docs" / "authentication.md").unlink()
    run_git(git_repo, "add", "-u")
    run_git(git_repo, "commit", "-m", "docs: remove autenticação")
    runtime.scan_service().scan(runtime.project_id)
    deleted = runtime.store.latest_commit(runtime.project_id)
    assert deleted is not None
    assert deleted.changes[0].status == "deleted"
