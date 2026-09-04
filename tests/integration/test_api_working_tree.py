"""Escopo "code" do chat web lendo o disco em tempo real (sem exigir commit), via o
observador de filesystem que `devmate serve` mantém por projeto."""

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

from devmate.api.app import app
from devmate.api.project_registry import ProjectRegistry


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


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


def _ask_code_scope(
    client: httpx.Client, project_id: str, active_commit: str, message: str = "explique o app.py"
) -> dict[str, object]:
    created = client.post(
        f"/api/v1/projects/{project_id}/chat/runs",
        json={
            "message": message,
            "scope": "code",
            "commitHash": active_commit,
            "provider": "mock",
        },
    )
    assert created.status_code == 202, created.text
    run = created.json()
    with client.stream("GET", f"/api/v1/runs/{run['id']}/events") as response:
        payload = _read_until_run_completed(response)
    completed = _extract_event_data(payload, "run.completed")
    message_obj = completed["message"]
    assert isinstance(message_obj, dict)
    return message_obj


def test_code_scope_ask_starts_a_watcher_that_tracks_uncommitted_disk_changes(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prova de ponta a ponta do mecanismo: perguntar no escopo "code" liga o
    observador daquele projeto; editar o arquivo depois — sem commit, sem scan — já
    reflete na cache que a próxima pergunta vai usar.

    (`MockProvider`, usado aqui, não ecoa o conteúdo do arquivo na resposta de
    inspeção — só nomes de arquivo — então a prova de frescor lê a cache
    diretamente, em vez de tentar adivinhar isso pelo texto da resposta; a leitura
    de conteúdo em si já está coberta por ``test_inspection.py``.)
    """
    import devmate.api.app as appmod

    monkeypatch.delenv("DEVMATE_PROVIDER", raising=False)
    monkeypatch.delenv("DEVMATE_MODEL", raising=False)
    monkeypatch.setattr("devmate.api.app.projects", ProjectRegistry(tmp_path / "projects.json"))
    appmod._working_tree_watchers.clear()

    (git_repo / "app.py").write_text("# versao original\n", encoding="utf-8")
    _git(git_repo, "add", "app.py")
    _git(git_repo, "commit", "-m", "feat: adiciona app.py")

    with _live_server() as base_url, httpx.Client(base_url=base_url, timeout=20) as client:
        project = client.post("/api/v1/projects", json={"path": str(git_repo)}).json()
        head = project["activeCommitHash"]

        _ask_code_scope(client, project["id"], head)

        watchers = list(appmod._working_tree_watchers.values())
        assert len(watchers) == 1
        cache = watchers[0].cache

        (git_repo / "app.py").write_text("# versao editada sem commit\n", encoding="utf-8")

        deadline = time.monotonic() + 10
        fresh = False
        while time.monotonic() < deadline:
            try:
                if cache.get("app.py") == "# versao editada sem commit\n":
                    fresh = True
                    break
            except OSError:
                pass
            time.sleep(0.1)

        assert fresh
