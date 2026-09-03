"""Diagnostics, providers, fala e sessões de leitura via HTTP — sem fixtures nem
respostas fabricadas: tudo aqui vem dos mesmos application services que a CLI usa
(`doctor`, `ProviderRegistry`, `get_speech_provider`, `MarkdownNarrator`)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from devmate.api.app import app
from devmate.api.project_registry import ProjectRegistry
from devmate.application.project_service import initialize_project
from devmate.bootstrap import load_runtime


def _isolate_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # `load_config` lets DEVMATE_PROVIDER/DEVMATE_MODEL override the TOML default (see
    # config.py), and a project's own local `.env` sets these process-wide the first
    # time any test resolves a runtime for it (os.environ.setdefault has no per-test
    # scope). These tests assert on *which* provider is the default, so they need a
    # clean slate regardless of what an unrelated earlier test — or this machine's own
    # `.env` — already exported into the process.
    monkeypatch.delenv("DEVMATE_PROVIDER", raising=False)
    monkeypatch.delenv("DEVMATE_MODEL", raising=False)


@pytest.fixture()
def client(git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    _isolate_provider_env(monkeypatch)
    monkeypatch.chdir(git_repo)
    initialize_project(git_repo)
    runtime = load_runtime(git_repo)
    runtime.scan_service().scan(runtime.project_id)
    return TestClient(app)


@pytest.fixture()
def web_client(git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    _isolate_provider_env(monkeypatch)
    monkeypatch.setattr("devmate.api.app.projects", ProjectRegistry(tmp_path / "projects.json"))
    return TestClient(app)


def _register(web_client: TestClient, git_repo: Path) -> dict[str, object]:
    created = web_client.post("/api/v1/projects", json={"path": str(git_repo)})
    assert created.status_code == 201, created.text
    project: dict[str, object] = created.json()
    return project


def test_diagnostics_reports_the_mock_provider_as_available(client: TestClient) -> None:
    response = client.get("/api/v1/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["backendVersion"]
    assert body["database"]["status"] == "ready"
    names = {item["name"]: item for item in body["providers"]}
    assert names["mock"]["availability"] == "available"
    assert names["mock"]["authConfigured"] is True
    speech_names = {item["name"] for item in body["speechProviders"]}
    assert speech_names == {"system", "openai"}


def test_providers_list_and_detail_reflect_real_availability(client: TestClient) -> None:
    listed = client.get("/api/v1/providers")
    assert listed.status_code == 200
    items = {item["name"]: item for item in listed.json()["items"]}
    assert set(items) == {"mock", "codex", "openai", "openai_compatible"}
    assert items["mock"]["availability"] == "available"

    detail = client.get("/api/v1/providers/mock")
    assert detail.status_code == 200
    assert detail.json()["name"] == "mock"


def test_unknown_provider_detail_is_a_404(client: TestClient) -> None:
    response = client.get("/api/v1/providers/does-not-exist")

    assert response.status_code == 404
    assert response.json()["code"] == "ProviderNotFoundError"


def test_provider_settings_update_persists_default_and_task_routing(
    web_client: TestClient, git_repo: Path
) -> None:
    project = _register(web_client, git_repo)

    updated = web_client.put(
        f"/api/v1/projects/{project['id']}/settings/providers",
        json={
            "defaultProvider": "codex",
            "defaultModel": "gpt-5-codex",
            "taskRouting": {"documentation_chat": "openai"},
        },
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["defaultProvider"] == "codex"

    detail = web_client.get("/api/v1/providers/openai")
    assert detail.json()["routedTasks"] == ["documentation_chat"]

    config_text = (git_repo / ".devmate" / "config.toml").read_text(encoding="utf-8")
    assert 'default = "codex"' in config_text
    assert 'documentation_chat = "openai"' in config_text


def test_provider_settings_update_rejects_an_unknown_provider(
    web_client: TestClient, git_repo: Path
) -> None:
    project = _register(web_client, git_repo)

    response = web_client.put(
        f"/api/v1/projects/{project['id']}/settings/providers",
        json={"defaultProvider": "not-a-real-provider"},
    )

    assert response.status_code == 400


def test_speech_providers_and_voices_list_come_from_the_real_registry(client: TestClient) -> None:
    providers = client.get("/api/v1/speech/providers")
    assert providers.status_code == 200
    names = {item["name"] for item in providers.json()["items"]}
    assert names == {"system", "openai"}

    voices = client.get("/api/v1/speech/voices", params={"provider": "openai"})
    assert voices.status_code == 200
    items = voices.json()["items"]
    assert items, "o catálogo embutido da OpenAI não depende de rede nem de credencial"
    assert all(item["provider"] == "openai" for item in items)


def test_speech_settings_update_persists_provider_and_voice(
    web_client: TestClient, git_repo: Path
) -> None:
    project = _register(web_client, git_repo)

    updated = web_client.put(
        f"/api/v1/projects/{project['id']}/settings/speech",
        json={"provider": "openai", "voiceId": "marin", "rate": 200},
    )

    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["provider"] == "openai"
    assert body["voiceId"] == "marin"
    assert body["rate"] == 200

    config_text = (git_repo / ".devmate" / "config.toml").read_text(encoding="utf-8")
    assert 'voice = "marin"' in config_text
    assert 'provider = "openai"' in config_text


def test_speech_settings_update_rejects_an_unknown_provider(
    web_client: TestClient, git_repo: Path
) -> None:
    project = _register(web_client, git_repo)

    response = web_client.put(
        f"/api/v1/projects/{project['id']}/settings/speech",
        json={"provider": "not-a-real-provider", "voiceId": "x"},
    )

    assert response.status_code == 400


def test_reading_session_verbatim_keeps_the_literal_markdown(
    web_client: TestClient, git_repo: Path
) -> None:
    project = _register(web_client, git_repo)

    created = web_client.post(
        f"/api/v1/projects/{project['id']}/reading-sessions",
        json={
            "filePath": "README.md",
            "commitHash": project["activeCommitHash"],
            "mode": "verbatim",
            "skipCode": True,
            "changesOnly": False,
        },
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["mode"] == "verbatim"
    assert body["stale"] is False
    assert any("Documento inicial" in segment["text"] for segment in body["segments"])
    assert all(
        segment["audioUrl"].startswith("/api/v1/reading-sessions/") for segment in body["segments"]
    )


def test_reading_session_narrate_normalizes_the_text(
    web_client: TestClient, git_repo: Path
) -> None:
    project = _register(web_client, git_repo)

    created = web_client.post(
        f"/api/v1/projects/{project['id']}/reading-sessions",
        json={
            "filePath": "README.md",
            "commitHash": project["activeCommitHash"],
            "mode": "narrate",
            "skipCode": True,
            "changesOnly": False,
        },
    )

    assert created.status_code == 201, created.text
    segments = created.json()["segments"]
    assert any(segment["text"].startswith("Seção:") for segment in segments)


def test_reading_session_explain_uses_the_project_llm_provider(
    web_client: TestClient, git_repo: Path
) -> None:
    project = _register(web_client, git_repo)

    created = web_client.post(
        f"/api/v1/projects/{project['id']}/reading-sessions",
        json={
            "filePath": "README.md",
            "commitHash": project["activeCommitHash"],
            "mode": "explain",
            "skipCode": True,
            "changesOnly": False,
        },
    )

    assert created.status_code == 201, created.text
    segments = created.json()["segments"]
    assert segments
    assert any("MockProvider" in segment["text"] for segment in segments)


def test_reading_session_becomes_stale_after_the_file_changes(
    web_client: TestClient, git_repo: Path
) -> None:
    project = _register(web_client, git_repo)
    created = web_client.post(
        f"/api/v1/projects/{project['id']}/reading-sessions",
        json={
            "filePath": "README.md",
            "commitHash": project["activeCommitHash"],
            "mode": "verbatim",
            "skipCode": True,
            "changesOnly": False,
        },
    ).json()

    (git_repo / "README.md").write_text("# Projeto\n\nConteúdo atualizado.\n", encoding="utf-8")
    import subprocess

    subprocess.run(["git", "add", "README.md"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "docs: atualiza README"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )

    reread = web_client.get(f"/api/v1/reading-sessions/{created['id']}")

    assert reread.status_code == 200
    assert reread.json()["stale"] is True


def test_reading_session_audio_requires_a_provider_that_produces_files(
    web_client: TestClient, git_repo: Path
) -> None:
    project = _register(web_client, git_repo)
    created = web_client.post(
        f"/api/v1/projects/{project['id']}/reading-sessions",
        json={
            "filePath": "README.md",
            "commitHash": project["activeCommitHash"],
            "mode": "verbatim",
            "skipCode": True,
            "changesOnly": False,
            # Provider padrão do projeto é "system": fala local, sem arquivo de áudio.
        },
    ).json()

    audio = web_client.get(f"/api/v1/reading-sessions/{created['id']}/segments/0/audio")

    assert audio.status_code == 400
    assert audio.json()["code"] == "UnsafePathError"


def test_reading_session_stop_marks_it_and_returns_no_content(
    web_client: TestClient, git_repo: Path
) -> None:
    project = _register(web_client, git_repo)
    created = web_client.post(
        f"/api/v1/projects/{project['id']}/reading-sessions",
        json={
            "filePath": "README.md",
            "commitHash": project["activeCommitHash"],
            "mode": "verbatim",
            "skipCode": True,
            "changesOnly": False,
        },
    ).json()

    stopped = web_client.post(f"/api/v1/reading-sessions/{created['id']}/stop")

    assert stopped.status_code == 204


def test_unknown_reading_session_is_a_404_style_problem(client: TestClient) -> None:
    response = client.get("/api/v1/reading-sessions/does-not-exist")

    assert response.status_code == 400
    assert response.json()["code"] == "UnsafePathError"
