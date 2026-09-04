from __future__ import annotations

from typing import Any

from devmate.adapters.llm.openai_provider import (
    OpenAIProvider,
    render_continuation_input,
    render_input,
)
from devmate.domain.enums import Scope
from devmate.domain.models import ContextChunk, LLMRequest, SourceReference


def request(previous_response_id: str | None = None) -> LLMRequest:
    reference = SourceReference("docs/auth.md", 1, 2, "a" * 40)
    return LLMRequest(
        "chat",
        "E essa outra parte?",
        Scope.DOCS,
        (ContextChunk("Conteúdo do documento", reference),),
        "Sistema",
        previous_response_id=previous_response_id,
    )


class FakeResponse:
    def __init__(self, text: str, response_id: str) -> None:
        self.output_text = text
        self.id = response_id


class FakeResponses:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        return self.response


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self.responses = FakeResponses(response)


def make_provider(response: FakeResponse) -> tuple[OpenAIProvider, FakeClient]:
    client = FakeClient(response)
    provider = OpenAIProvider(model="gpt-5", client_factory=lambda: client)
    return provider, client


def test_render_continuation_input_omits_instructions_context_and_history() -> None:
    prompt = render_continuation_input(request())

    assert "untrusted_repository_context" not in prompt
    assert "Sistema" not in prompt
    assert "conversation_history" not in prompt
    assert prompt == "Pergunta da pessoa usuária: E essa outra parte?"


def test_complete_without_previous_response_id_sends_the_full_prompt() -> None:
    provider, client = make_provider(FakeResponse("resposta", "resp_1"))

    provider.complete(request())

    call = client.responses.calls[0]
    assert "previous_response_id" not in call
    assert call["input"] == render_input(request())


def test_complete_with_previous_response_id_sends_only_the_new_question() -> None:
    provider, client = make_provider(FakeResponse("resposta", "resp_2"))

    provider.complete(request(previous_response_id="resp_1"))

    call = client.responses.calls[0]
    assert call["previous_response_id"] == "resp_1"
    assert call["input"] == "Pergunta da pessoa usuária: E essa outra parte?"


def test_complete_returns_the_response_id_for_the_next_turn() -> None:
    provider, _ = make_provider(FakeResponse("resposta", "resp_42"))

    result = provider.complete(request())

    assert result.response_id == "resp_42"
