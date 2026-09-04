"""Edição pelo chat web: proposta -> diff -> apply, sempre atrás de confirmação
explícita. dev-agent é forçado indisponível (URL inalcançável) nesses testes, então
todos exercitam o caminho de reserva (LLM direto, provider `mock`, offline)."""

from __future__ import annotations

import json
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from devmate.api.app import _split_diff_by_file, app
from devmate.api.project_registry import ProjectRegistry


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def _add_a_source_file(git_repo: Path) -> None:
    """`git_repo` (conftest) só tem .md; `full_repo=True` na inspeção de código exige
    pelo menos um arquivo de código de verdade para autorizar o escopo."""
    (git_repo / "app.py").write_text("def greet():\n    return 'oi'\n", encoding="utf-8")
    _git(git_repo, "add", "app.py")
    _git(git_repo, "commit", "-m", "feat: adiciona app.py")


def _closed_local_port() -> int:
    """Uma porta livre em 127.0.0.1 que recusa conexão na hora (RST), diferente de
    uma porta baixa/filtrada (ex.: 1), que em alguns Windows apenas descarta pacotes
    em silêncio até o connect() do SO expirar sozinho — bem mais lento que o teste."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _force_dev_agent_unreachable(git_repo: Path) -> None:
    """`[edit]` já existe no config padrão — troca os valores em vez de duplicar a
    seção (TOML rejeita declarar a mesma tabela duas vezes). Também reduz o timeout,
    como segunda camada de proteção contra qualquer travamento de conexão."""
    config_path = git_repo / ".devmate" / "config.toml"
    text = config_path.read_text(encoding="utf-8")
    updated = text.replace(
        'dev_agent_url = "http://127.0.0.1:8765"',
        f'dev_agent_url = "http://127.0.0.1:{_closed_local_port()}"',
    ).replace("dev_agent_timeout_seconds = 600.0", "dev_agent_timeout_seconds = 10.0")
    assert updated != text, "dev_agent_url padrão não encontrada no config.toml"
    config_path.write_text(updated, encoding="utf-8")


@pytest.fixture()
def web_client(git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("DEVMATE_PROVIDER", raising=False)
    monkeypatch.delenv("DEVMATE_MODEL", raising=False)
    monkeypatch.setattr("devmate.api.app.projects", ProjectRegistry(tmp_path / "projects.json"))
    return TestClient(app)


def _register(web_client: TestClient, git_repo: Path) -> dict[str, object]:
    """Registra o projeto (o que cria `.devmate/config.toml`) e só então força o
    dev-agent inalcançável, pra todo teste cair no caminho de reserva via LLM."""
    created = web_client.post("/api/v1/projects", json={"path": str(git_repo)})
    assert created.status_code == 201, created.text
    _force_dev_agent_unreachable(git_repo)
    project: dict[str, object] = created.json()
    return project


@contextmanager
def _live_server() -> Iterator[str]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{base_url}/api/v1/health", timeout=0.2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        else:
            raise RuntimeError("Live test server did not become healthy in time.")
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _read_until_run_completed(response: httpx.Response) -> str:
    lines: list[str] = []
    saw_completed = False
    for line in response.iter_lines():
        lines.append(line)
        if saw_completed:
            break
        if line == "event: run.completed":
            saw_completed = True
    return "\n".join(lines)


def _extract_event_data(payload: str, event_type: str) -> dict[str, object]:
    lines = payload.splitlines()
    for index, line in enumerate(lines):
        if line == f"event: {event_type}":
            data_line = lines[index + 1]
            parsed = json.loads(data_line.removeprefix("data: "))
            assert isinstance(parsed, dict)
            return parsed
    raise AssertionError(f"event {event_type} not found in payload")


def test_split_diff_by_file_breaks_a_multi_file_unified_diff() -> None:
    diff = (
        "diff --git a/a.py b/a.py\n"
        "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n"
        "diff --git a/b.py b/b.py\n"
        "--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-x\n+y\n"
    )

    files = _split_diff_by_file(diff)

    assert [item["path"] for item in files] == ["a.py", "b.py"]
    assert "diff --git a/a.py b/a.py" in files[0]["diff"]
    assert "diff --git a/b.py b/b.py" not in files[0]["diff"]


def test_split_diff_by_file_falls_back_to_a_single_block_without_git_headers() -> None:
    files = _split_diff_by_file("some diff text without headers")

    assert files == [{"path": "(diff)", "diff": "some diff text without headers"}]


def test_split_diff_by_file_returns_nothing_for_an_empty_diff() -> None:
    assert _split_diff_by_file("   \n") == []


def test_edit_chat_run_proposes_a_change_and_applies_it_after_confirmation(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEVMATE_PROVIDER", raising=False)
    monkeypatch.delenv("DEVMATE_MODEL", raising=False)
    monkeypatch.setattr("devmate.api.app.projects", ProjectRegistry(tmp_path / "projects.json"))
    _add_a_source_file(git_repo)

    with _live_server() as base_url, httpx.Client(base_url=base_url) as client:
        project = client.post("/api/v1/projects", json={"path": str(git_repo)}).json()
        _force_dev_agent_unreachable(git_repo)

        created = client.post(
            f"/api/v1/projects/{project['id']}/chat/runs",
            json={
                "message": "adicione um comentário de teste",
                "scope": "edit",
                "commitHash": project["activeCommitHash"],
                "provider": "mock",
            },
        )
        assert created.status_code == 202, created.text
        run = created.json()

        with client.stream("GET", f"/api/v1/runs/{run['id']}/events") as response:
            payload = _read_until_run_completed(response)
        completed = _extract_event_data(payload, "run.completed")
        message = completed["message"]
        assert isinstance(message, dict)
        proposal = message["editProposal"]
        assert isinstance(proposal, dict)
        assert proposal["applied"] is False
        assert proposal["engine"] == "llm"
        files = proposal["files"]
        assert isinstance(files, list) and len(files) == 1
        changed_path = files[0]["path"]
        assert "devmate: alteração de teste" in files[0]["diff"]

        applied = client.post(
            f"/api/v1/projects/{project['id']}/edit-proposals/{proposal['id']}/apply"
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["applied"] is True

        written = (git_repo / changed_path).read_text(encoding="utf-8")
        assert "# devmate: alteração de teste (MockProvider)" in written

        # Regressão: aplicar de novo deve ser rejeitado, não escrever duas vezes.
        second_apply = client.post(
            f"/api/v1/projects/{project['id']}/edit-proposals/{proposal['id']}/apply"
        )
        assert second_apply.status_code == 400


def test_apply_unknown_proposal_returns_a_clear_error(
    web_client: TestClient, git_repo: Path
) -> None:
    project = _register(web_client, git_repo)

    response = web_client.post(
        f"/api/v1/projects/{project['id']}/edit-proposals/does-not-exist/apply"
    )

    assert response.status_code == 400
    assert "desconhecida" in response.json()["detail"]
