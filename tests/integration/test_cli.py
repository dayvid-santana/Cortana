from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from devmate.cli import app


def test_offline_cli_flow(git_repo, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(git_repo)
    runner = CliRunner()
    assert runner.invoke(app, ["init"]).exit_code == 0
    scan = runner.invoke(app, ["scan"])
    assert scan.exit_code == 0, scan.output
    answer = runner.invoke(app, ["ask", "--provider", "mock", "O que mudou?"])
    assert answer.exit_code == 0, answer.output
    assert "Fontes:" in answer.output
    read = runner.invoke(app, ["read", "README.md", "--dry-run"])
    assert read.exit_code == 0, read.output
    assert "Segmentos:" in read.output
    assert runner.invoke(app, ["providers", "list"]).exit_code == 0
    assert runner.invoke(app, ["decisions"]).exit_code == 0
    assert runner.invoke(app, ["questions"]).exit_code == 0
    assert runner.invoke(app, ["doctor"]).exit_code == 0


def test_full_access_and_activity_commands_offline(git_repo: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
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

    monkeypatch.chdir(git_repo)
    runner = CliRunner()
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert runner.invoke(app, ["scan"]).exit_code == 0

    # Sem full-access, inspecionar código sem --files/--full-repo continua bloqueado (exit 7).
    blocked = runner.invoke(app, ["inspect", "--provider", "mock", "explique este módulo"])
    assert blocked.exit_code == 7, blocked.output

    enable = runner.invoke(app, ["config", "full-access", "--enable"])
    assert enable.exit_code == 0, enable.output

    unblocked = runner.invoke(app, ["inspect", "--provider", "mock", "explique este módulo"])
    assert unblocked.exit_code == 0, unblocked.output

    review = runner.invoke(app, ["review", "--files", "src/app.py", "--provider", "mock"])
    assert review.exit_code == 0, review.output

    architecture = runner.invoke(
        app, ["architecture", "--files", "src/app.py", "--provider", "mock"]
    )
    assert architecture.exit_code == 0, architecture.output

    edit = runner.invoke(
        app,
        [
            "edit",
            "--files",
            "src/app.py",
            "--provider",
            "mock",
            "--yes",
            "--json",
            "adicione um comentário",
        ],
    )
    assert edit.exit_code == 0, edit.output
    payload = json.loads(edit.output)
    assert payload["applied"] == ["src/app.py"]
    assert "# devmate: alteração de teste" in (source / "app.py").read_text(encoding="utf-8")

    disable = runner.invoke(app, ["config", "full-access", "--disable"])
    assert disable.exit_code == 0, disable.output
