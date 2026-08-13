from __future__ import annotations

from pathlib import Path

from openai_codex import Sandbox

from devmate.adapters.llm.codex_provider import CodexProvider
from devmate.domain.enums import Scope
from devmate.domain.models import ContextChunk, LLMRequest, SourceReference


class FakeResult:
    final_response = "Análise pronta."


class FakeThread:
    def __init__(self) -> None:
        self.sandbox: Sandbox | None = None

    def run(self, _prompt: str, **kwargs: object) -> FakeResult:
        self.sandbox = kwargs["sandbox"]  # type: ignore[assignment]
        return FakeResult()


class FakeCodex:
    def __init__(self) -> None:
        self.thread = FakeThread()
        self.started_with: dict[str, object] = {}

    def __enter__(self) -> FakeCodex:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        return None

    def thread_start(self, **kwargs: object) -> FakeThread:
        self.started_with = kwargs
        return self.thread


def test_codex_provider_starts_and_runs_read_only_thread() -> None:
    fake = FakeCodex()
    captured: dict[str, str] = {}

    def client_factory(workspace: Path) -> FakeCodex:
        captured["source"] = (workspace / "selected_context" / "src" / "app.py").read_text(
            encoding="utf-8"
        )
        return fake

    provider = CodexProvider("modelo", "Instrução da Cortana.", client_factory=client_factory)
    request = LLMRequest(
        "inspect",
        "Verifique.",
        Scope.CODE,
        (ContextChunk("x = 1", SourceReference("src/app.py", 1, 1, "a" * 40)),),
        "Sistema",
    )
    response = provider.complete(request)
    assert response.text == "Análise pronta."
    assert fake.started_with["sandbox"] is Sandbox.read_only
    assert "Instrução da Cortana." in str(fake.started_with["developer_instructions"])
    assert fake.thread.sandbox is Sandbox.read_only
    assert "x = 1" in captured["source"]
