from __future__ import annotations

import subprocess
from pathlib import Path

from devmate.application.project_service import initialize_project
from devmate.bootstrap import load_runtime


def test_inspection_reads_only_explicit_code_at_selected_commit(git_repo: Path) -> None:
    source = git_repo / "src"
    source.mkdir()
    (source / "app.py").write_text("AUTH = 'jwt'\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "src/app.py"], cwd=git_repo, check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "commit", "-m", "feat: adiciona implementação"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    initialize_project(git_repo)
    runtime = load_runtime(git_repo)
    runtime.scan_service().scan(runtime.project_id)
    context = runtime.inspection_service().build(runtime.project_id, None, ["src/app.py"])
    assert any(chunk.reference.path == "src/app.py" for chunk in context.chunks)
    assert "AUTH = 'jwt'" in next(
        chunk.text for chunk in context.chunks if chunk.reference.path == "src/app.py"
    )
