from __future__ import annotations

import json
import socket
import sqlite3
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

from devmate.api.app import _system_instructions, app
from devmate.api.project_registry import ProjectRegistry
from devmate.api.schemas import ChatRequest
from devmate.application.project_service import initialize_project
from devmate.bootstrap import load_runtime


@pytest.fixture()
def client(git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.chdir(git_repo)
    initialize_project(git_repo)
    runtime = load_runtime(git_repo)
    runtime.scan_service().scan(runtime.project_id)
    return TestClient(app)


def test_health_does_not_require_a_project() -> None:
    response = TestClient(app).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_status_reflects_the_initialized_repo(client: TestClient, git_repo: Path) -> None:
    response = client.get("/api/v1/status")

    assert response.status_code == 200
    body = response.json()
    assert body["repo"] == str(git_repo.resolve())
    assert body["branch"] == "main"
    assert body["last_processed"] is not None


def test_status_without_init_reports_409_with_a_typed_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True, text=True
    )
    monkeypatch.chdir(tmp_path)

    response = TestClient(app).get("/api/v1/status")

    assert response.status_code == 409
    assert response.json()["code"] == "ConfigurationError"


def test_chat_docs_scope_returns_structured_citations(client: TestClient) -> None:
    response = client.post(
        "/api/v1/chat", json={"question": "O que mudou?", "provider": "mock", "scope": "docs"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "docs"
    assert body["provider"] == "mock"
    assert body["commit"]
    assert body["sources"], "MockProvider deveria citar ao menos uma fonte"
    source = body["sources"][0]
    assert set(source) == {"path", "start_line", "end_line", "commit_hash", "heading", "label"}
    assert source["label"].startswith(f"[{source['path']}")


def test_chat_code_scope_requires_files_or_full_repo(client: TestClient) -> None:
    response = client.post(
        "/api/v1/chat", json={"question": "Como funciona?", "provider": "mock", "scope": "code"}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "UnsafePathError"


def test_chat_docs_scope_rejects_code_only_flags_explicitly(client: TestClient) -> None:
    # docs nunca deve incluir código, nem silenciosamente ignorar o pedido.
    response = client.post(
        "/api/v1/chat",
        json={"question": "?", "provider": "mock", "scope": "docs", "full_repo": True},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "UnsafePathError"


def test_chat_auto_indexes_a_commit_that_has_not_been_scanned_yet(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reproduz o 500 real encontrado ao testar `devmate serve` manualmente:
    # HEAD avança para um commit novo e /chat precisa se recuperar sozinho,
    # do mesmo jeito que a CLI já faz, em vez de vazar um erro genérico.
    monkeypatch.chdir(git_repo)
    initialize_project(git_repo)
    runtime = load_runtime(git_repo)
    runtime.scan_service().scan(runtime.project_id)
    (git_repo / "docs" / "new.md").write_text("# Novo\n\nConteúdo.\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "docs/new.md"], cwd=git_repo, check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "commit", "-m", "docs: adiciona novo documento"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    )

    response = TestClient(app).post(
        "/api/v1/chat", json={"question": "O que mudou?", "provider": "mock", "scope": "docs"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["commit"] == runtime.git.head()


def test_chat_defaults_to_the_project_provider_when_omitted(client: TestClient) -> None:
    response = client.post("/api/v1/chat", json={"question": "?"})

    assert response.status_code == 200
    assert response.json()["provider"] == "mock"


def test_openai_api_key_never_appears_in_a_chat_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-never-leak")

    response = client.post(
        "/api/v1/chat", json={"question": "?", "provider": "mock", "scope": "docs"}
    )

    assert "sk-should-never-leak" not in response.text


def test_speech_source_adds_the_concise_instruction_text_does_not() -> None:
    text_body = ChatRequest(question="x", source="text")
    speech_body = ChatRequest(question="x", source="speech")

    assert "transcrição de voz" not in _system_instructions(text_body)
    assert "transcrição de voz" in _system_instructions(speech_body)


def test_cors_allows_the_local_vite_dev_server(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"Origin": "http://127.0.0.1:5173"})

    assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"


def test_cors_rejects_an_unknown_origin(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})

    assert "access-control-allow-origin" not in response.headers


def test_web_projects_register_and_expose_real_files(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("devmate.api.app.projects", ProjectRegistry(tmp_path / "projects.json"))
    client = TestClient(app)

    created = client.post("/api/v1/projects", json={"path": str(git_repo), "name": "Example"})

    assert created.status_code == 201, created.text
    project = created.json()
    assert project["name"] == "Example"
    assert project["activeCommitHash"]

    tree = client.get(
        f"/api/v1/projects/{project['id']}/files",
        params={"commit": project["activeCommitHash"]},
    )

    assert tree.status_code == 200, tree.text
    files = [item for item in tree.json()["items"] if item["type"] == "file"]
    assert files

    content = client.get(
        f"/api/v1/projects/{project['id']}/files/content",
        params={"commit": project["activeCommitHash"], "path": files[0]["path"]},
    )

    assert content.status_code == 200, content.text
    assert content.json()["path"] == files[0]["path"]


def test_web_projects_list_skips_a_registered_project_whose_directory_is_gone(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: a registered project's checkout can be moved/deleted afterwards (a
    disposable temp repo, a renamed folder). Listing used to 500 — git discovery's
    subprocess call raised a plain OSError, which only DevMateError was caught for."""
    registry_path = tmp_path / "projects.json"
    monkeypatch.setattr("devmate.api.app.projects", ProjectRegistry(registry_path))
    client = TestClient(app)
    kept = client.post("/api/v1/projects", json={"path": str(git_repo)}).json()

    # Written directly (not via POST /projects, which requires a real git repo to
    # register) so the "gone" entry never needs a real directory that would then have
    # to be removed — sidesteps Windows file-locking on the entry's own SQLite handle.
    registry_path.write_text(
        json.dumps(
            [
                {"root": str(git_repo), "name": git_repo.name},
                {"root": str(tmp_path / "never-existed"), "name": "gone"},
            ]
        ),
        encoding="utf-8",
    )

    response = client.get("/api/v1/projects")

    assert response.status_code == 200, response.text
    ids = {item["id"] for item in response.json()["items"]}
    assert ids == {kept["id"]}


@contextmanager
def _live_server() -> Iterator[str]:
    """A real uvicorn server on a real socket, for the two SSE tests below.

    stream_run_events's response body deliberately never ends on its own once a run
    finishes (see that function's docstring-equivalent comment) — a real EventSource
    closes it client-side instead. FastAPI's in-process TestClient hangs on that: its
    `.stream()` doesn't hand back control until the ASGI app's request-handling task
    fully finishes, which for this endpoint only happens when the client disconnects —
    a chicken-and-egg wait TestClient never resolves. A real socket doesn't have that
    problem: closing the httpx connection actually severs it, which is exactly the
    "client disconnects" case this endpoint relies on to eventually stop.
    """
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
    """The stream deliberately never ends on its own once a run finishes (see
    stream_run_events) — a real EventSource client closes it after processing
    run.completed, so tests must read incrementally and stop there too, instead of
    waiting for a natural EOF that no longer comes."""
    lines: list[str] = []
    saw_completed = False
    for line in response.iter_lines():
        lines.append(line)
        if saw_completed:
            break  # this is the data: line belonging to the run.completed frame
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


def test_web_chat_run_streams_events_and_persists_the_final_message(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("devmate.api.app.projects", ProjectRegistry(tmp_path / "projects.json"))
    with _live_server() as base_url, httpx.Client(base_url=base_url) as client:
        project = client.post("/api/v1/projects", json={"path": str(git_repo)}).json()

        created = client.post(
            f"/api/v1/projects/{project['id']}/chat/runs",
            json={
                "message": "O que mudou?",
                "scope": "docs",
                "commitHash": project["activeCommitHash"],
                "provider": "mock",
            },
        )

        assert created.status_code == 202, created.text
        run = created.json()
        assert run["status"] == "queued"
        with client.stream("GET", f"/api/v1/runs/{run['id']}/events") as response:
            assert response.status_code == 200
            payload = _read_until_run_completed(response)
        assert "event: run.started" in payload
        assert "event: assistant.delta" in payload
        assert "event: source.reference" in payload
        assert "event: run.completed" in payload

        # Regression: run.completed used to omit `message` entirely. The frontend's
        # onEvent handler reads event.message.threadId to invalidate the messages
        # query — without this field it throws there, and the answer never reaches
        # the transcript even though it was correctly persisted.
        completed = _extract_event_data(payload, "run.completed")
        assert completed["message"]["threadId"] == run["threadId"]  # type: ignore[index]
        assert completed["message"]["role"] == "assistant"  # type: ignore[index]
        assert completed["message"]["content"]  # type: ignore[index]

        messages = client.get(
            f"/api/v1/projects/{project['id']}/threads/{run['threadId']}/messages"
        ).json()["items"]
        assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[-1]["status"] == "complete"


def test_web_chat_run_events_resume_from_last_event_id_without_losing_events(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reconnecting EventSource sends back Last-Event-ID; the server must replay from
    there instead of restarting at 0 — and must not have silently dropped events a
    now-dead earlier connection had already pulled off a (formerly) consumable queue."""
    monkeypatch.setattr("devmate.api.app.projects", ProjectRegistry(tmp_path / "projects.json"))
    with _live_server() as base_url, httpx.Client(base_url=base_url) as client:
        project = client.post("/api/v1/projects", json={"path": str(git_repo)}).json()

        created = client.post(
            f"/api/v1/projects/{project['id']}/chat/runs",
            json={
                "message": "O que mudou?",
                "scope": "docs",
                "commitHash": project["activeCommitHash"],
                "provider": "mock",
            },
        )
        run = created.json()

        first_ids: list[int] = []
        with client.stream("GET", f"/api/v1/runs/{run['id']}/events") as response:
            for line in response.iter_lines():
                if line.startswith("id: "):
                    first_ids.append(int(line.removeprefix("id: ")))
                if len(first_ids) >= 2:
                    break

        assert first_ids == [0, 1]

        with client.stream(
            "GET",
            f"/api/v1/runs/{run['id']}/events",
            headers={"Last-Event-ID": str(first_ids[-1])},
        ) as response:
            payload = _read_until_run_completed(response)

    assert "id: 0" not in payload.splitlines()
    assert "id: 1" not in payload.splitlines()
    assert "event: run.completed" in payload


def test_web_chat_run_can_be_cancelled_before_provider_execution(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("devmate.api.app.projects", ProjectRegistry(tmp_path / "projects.json"))
    client = TestClient(app)
    project = client.post("/api/v1/projects", json={"path": str(git_repo)}).json()
    created = client.post(
        f"/api/v1/projects/{project['id']}/chat/runs",
        json={
            "message": "Pare",
            "scope": "docs",
            "commitHash": project["activeCommitHash"],
            "provider": "mock",
        },
    ).json()

    cancelled = client.post(f"/api/v1/runs/{created['id']}/cancel")
    assert cancelled.status_code == 200
    # O worker observa o sinal antes/depois da chamada bloqueante ao provider.
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        state = client.get(f"/api/v1/runs/{created['id']}").json()
        if state["status"] in {"cancelled", "completed"}:
            break
        time.sleep(0.01)
    assert state["status"] in {"cancelled", "completed"}


def test_openapi_schema_is_generated() -> None:
    schema = app.openapi()

    assert "/api/v1/chat" in schema["paths"]
    assert "/api/v1/status" in schema["paths"]


def test_runtime_upgrades_a_legacy_database_without_dropping_existing_data(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(git_repo)
    initialize_project(git_repo)
    database = git_repo / ".devmate" / "state.db"
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE conversation_threads")
        connection.execute("DROP TABLE web_conversation_messages")
        connection.execute(
            "INSERT INTO project_facts (project_id, key, value, status, confidence, introduced_at) VALUES (1, 'legacy', 'kept', 'candidate', 0.5, CURRENT_TIMESTAMP)"
        )

    load_runtime(git_repo)

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"conversation_threads", "web_conversation_messages"} <= tables
        assert connection.execute(
            "SELECT value FROM project_facts WHERE key = 'legacy'"
        ).fetchone() == ("kept",)
