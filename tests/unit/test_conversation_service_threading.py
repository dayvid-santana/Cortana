from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from devmate.application.conversation_service import ConversationService
from devmate.domain.enums import Scope
from devmate.domain.models import LLMRequest, LLMResponse


@dataclass
class FakeCommit:
    commit_hash: str = "a" * 40


class FakeContext:
    def build(
        self, project_id: int, scope: Scope, commit_ref: str | None
    ) -> tuple[FakeCommit, tuple[()]]:
        return FakeCommit(), ()


class FakeStore:
    def __init__(self, last_response_id: str | None = None) -> None:
        self._last_response_id = last_response_id
        self.messages: list[tuple[Any, ...]] = []

    def conversation(self, project_id: int, commit_hash: str, limit: int = 12) -> list[Any]:
        return []

    def last_response_id(self, project_id: int, commit_hash: str, provider_name: str) -> Any:
        return self._last_response_id

    def add_message(
        self,
        project_id: int,
        commit_hash: str,
        role: str,
        content: str,
        provider_name: str | None = None,
        provider_response_id: str | None = None,
    ) -> None:
        self.messages.append(
            (project_id, commit_hash, role, content, provider_name, provider_response_id)
        )


class FakeProvider:
    def __init__(self, response_id: str) -> None:
        self.response_id = response_id
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(text="resposta", response_id=self.response_id)


class FakeProviders:
    def __init__(self, provider: FakeProvider) -> None:
        self.provider = provider

    def get(self, name: str) -> FakeProvider:
        return self.provider


def test_ask_forwards_the_stored_response_id_as_previous_response_id() -> None:
    store = FakeStore(last_response_id="resp_1")
    provider = FakeProvider(response_id="resp_2")
    service = ConversationService(store, FakeContext(), FakeProviders(provider))  # type: ignore[arg-type]

    service.ask(1, "e essa outra parte?", "openai")

    assert provider.requests[0].previous_response_id == "resp_1"


def test_ask_persists_the_new_response_id_with_the_assistant_message() -> None:
    store = FakeStore(last_response_id=None)
    provider = FakeProvider(response_id="resp_2")
    service = ConversationService(store, FakeContext(), FakeProviders(provider))  # type: ignore[arg-type]

    service.ask(1, "primeira pergunta", "openai")

    assistant_message = next(m for m in store.messages if m[2] == "assistant")
    assert assistant_message[5] == "resp_2"
