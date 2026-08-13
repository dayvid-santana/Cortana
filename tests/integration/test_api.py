from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from devmate.api.app import _system_instructions, app
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


def test_openapi_schema_is_generated() -> None:
    schema = app.openapi()

    assert "/api/v1/chat" in schema["paths"]
    assert "/api/v1/status" in schema["paths"]
