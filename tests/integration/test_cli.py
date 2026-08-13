from __future__ import annotations

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
