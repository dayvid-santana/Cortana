"""Conversa persistida por commit e provider selecionável."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from devmate.adapters.llm.registry import ProviderRegistry
from devmate.adapters.persistence.repositories import RepositoryStore
from devmate.application.context_service import ContextService
from devmate.domain.enums import Scope
from devmate.domain.models import ConversationTurn, LLMRequest, LLMResponse
from devmate.errors import ProviderResponseError
from devmate.prompts.documentation_chat import DOCUMENTATION_CHAT_SYSTEM


@dataclass(frozen=True, slots=True)
class Answer:
    commit_hash: str
    response: LLMResponse


def load_history(
    store: RepositoryStore, project_id: int, commit_hash: str, limit: int = 12
) -> tuple[ConversationTurn, ...]:
    """Recupera as rodadas já persistidas deste commit, da mais antiga para a mais recente."""
    return tuple(
        ConversationTurn(role=role, content=content)
        for role, content in store.conversation(project_id, commit_hash, limit)
    )


class ConversationService:
    def __init__(
        self, store: RepositoryStore, context: ContextService, providers: ProviderRegistry
    ) -> None:
        self.store = store
        self.context = context
        self.providers = providers

    def ask(
        self,
        project_id: int,
        question: str,
        provider_name: str,
        commit_ref: str | None = None,
        model: str | None = None,
        system_instructions: str | None = None,
    ) -> Answer:
        commit, chunks = self.context.build(project_id, Scope.DOCS, commit_ref)
        # Lido antes de gravar a pergunta atual, para não duplicá-la no histórico.
        history = load_history(self.store, project_id, commit.commit_hash)
        request = LLMRequest(
            task="documentation_chat",
            question=question,
            scope=Scope.DOCS,
            chunks=chunks,
            system_instructions=system_instructions or DOCUMENTATION_CHAT_SYSTEM,
            model=model,
            history=history,
        )
        provider = self.providers.get(provider_name)
        self.store.add_message(project_id, commit.commit_hash, "user", question)
        response = provider.complete(request)
        self.store.add_message(
            project_id, commit.commit_hash, "assistant", response.text, provider_name
        )
        return Answer(commit.commit_hash, response)

    def ask_stream(
        self,
        project_id: int,
        question: str,
        provider_name: str,
        on_delta: Callable[[str], None],
        commit_ref: str | None = None,
        model: str | None = None,
        system_instructions: str | None = None,
    ) -> Answer:
        """Versão incremental para transportes como SSE.

        O provider continua opcionalmente streaming: adapters legados retornam um
        único delta, mantendo a mesma semântica de persistência e citações.
        """
        commit, chunks = self.context.build(project_id, Scope.DOCS, commit_ref)
        history = load_history(self.store, project_id, commit.commit_hash)
        request = LLMRequest(
            task="documentation_chat",
            question=question,
            scope=Scope.DOCS,
            chunks=chunks,
            system_instructions=system_instructions or DOCUMENTATION_CHAT_SYSTEM,
            model=model,
            history=history,
        )
        provider = self.providers.get(provider_name)
        self.store.add_message(project_id, commit.commit_hash, "user", question)
        stream = getattr(provider, "stream", None)
        if not callable(stream):
            response = provider.complete(request)
            on_delta(response.text)
            self.store.add_message(
                project_id, commit.commit_hash, "assistant", response.text, provider_name
            )
            return Answer(commit.commit_hash, response)
        parts: list[str] = []
        for delta in stream(request):
            parts.append(delta)
            on_delta(delta)
        text = "".join(parts)
        if not text:
            raise ProviderResponseError("O provider retornou uma resposta vazia.")
        response = LLMResponse(text=text, references=tuple(chunk.reference for chunk in chunks))
        self.store.add_message(project_id, commit.commit_hash, "assistant", text, provider_name)
        return Answer(commit.commit_hash, response)
