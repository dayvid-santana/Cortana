from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from devmate.adapters.agents.dev_agent_client import DevAgentClient
from devmate.errors import DevAgentUnavailableError


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self) -> Any:
        return self._payload


class FakeHttpClient:
    def __init__(
        self, responses: list[FakeResponse] | None = None, error: Exception | None = None
    ) -> None:
        self.responses = responses or [FakeResponse()]
        self.error = error
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def get(self, path: str) -> FakeResponse:
        self.calls.append(("GET", path, None))
        if self.error is not None:
            raise self.error
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]

    def request(self, method: str, path: str, json: dict[str, Any] | None = None) -> FakeResponse:
        self.calls.append((method, path, json))
        if self.error is not None:
            raise self.error
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


def make_client(
    responses: list[FakeResponse] | None = None, error: Exception | None = None
) -> tuple[DevAgentClient, FakeHttpClient]:
    fake = FakeHttpClient(responses, error)
    client = DevAgentClient(client_factory=lambda: fake)
    return client, fake


def test_available_reports_connection_refused_clearly() -> None:
    client, _ = make_client(error=httpx.ConnectError("recusado"))

    available, reason = client.available()

    assert available is False
    assert "dev-agent start" in (reason or "")


def test_available_true_when_server_answers_even_with_an_error_status() -> None:
    client, _ = make_client(responses=[FakeResponse(status_code=404)])

    available, _ = client.available()

    assert available is True


def test_create_plan_sends_cwd_and_objective() -> None:
    client, fake = make_client(responses=[FakeResponse(payload={"id": "plan-1"})])
    project_path = Path("some", "project")

    plan = client.create_plan(project_path, "corrija o typo")

    assert plan["id"] == "plan-1"
    method, path, body = fake.calls[0]
    assert method == "POST"
    assert path == "/assistant/task-plans"
    assert body == {"cwd": str(project_path), "objective": "corrija o typo"}


def test_start_posts_confirmed_write() -> None:
    client, fake = make_client(responses=[FakeResponse(payload={"id": "job-1"})])

    job = client.start("plan-1", confirmed_write=True)

    assert job["id"] == "job-1"
    method, path, body = fake.calls[0]
    assert method == "POST"
    assert path == "/assistant/task-plans/plan-1/start"
    assert body == {"confirmed_write": True}


def test_wait_for_completion_polls_until_terminal_status() -> None:
    client, fake = make_client(
        responses=[
            FakeResponse(payload={"status": "running"}),
            FakeResponse(payload={"status": "running"}),
            FakeResponse(payload={"status": "completed", "diff": "diff --git a b"}),
        ]
    )

    result = client.wait_for_completion("job-1", poll_seconds=0.01, timeout_seconds=5)

    assert result["status"] == "completed"
    assert len(fake.calls) == 3


def test_wait_for_completion_raises_after_timeout() -> None:
    client, _ = make_client(responses=[FakeResponse(payload={"status": "running"})])

    with pytest.raises(DevAgentUnavailableError, match="job-1"):
        client.wait_for_completion("job-1", poll_seconds=0.01, timeout_seconds=0.03)


def test_error_status_raises_with_the_response_detail() -> None:
    client, _ = make_client(
        responses=[FakeResponse(status_code=400, payload={"detail": "sem projeto"})]
    )

    with pytest.raises(DevAgentUnavailableError, match="sem projeto"):
        client.job("job-1")


def test_cleanup_swallows_failures() -> None:
    client, _ = make_client(error=httpx.ConnectError("fora do ar"))

    client.cleanup("job-1")  # não deve levantar
