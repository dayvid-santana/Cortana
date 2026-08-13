"""Conversa persistida por commit e provider selecionável."""

from __future__ import annotations

from dataclasses import dataclass

from devmate.adapters.llm.registry import ProviderRegistry
from devmate.adapters.persistence.repositories import RepositoryStore
from devmate.application.context_service import ContextService
from devmate.domain.enums import Scope
from devmate.domain.models import LLMRequest, LLMResponse
from devmate.prompts.documentation_chat import DOCUMENTATION_CHAT_SYSTEM


@dataclass(frozen=True, slots=True)
class Answer:
    commit_hash: str
    response: LLMResponse


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
    ) -> Answer:
        commit, chunks = self.context.build(project_id, Scope.DOCS, commit_ref)
        request = LLMRequest(
            task="documentation_chat",
            question=question,
            scope=Scope.DOCS,
            chunks=chunks,
            system_instructions=DOCUMENTATION_CHAT_SYSTEM,
            model=model,
        )
        provider = self.providers.get(provider_name)
        self.store.add_message(project_id, commit.commit_hash, "user", question)
        response = provider.complete(request)
        self.store.add_message(
            project_id, commit.commit_hash, "assistant", response.text, provider_name
        )
        return Answer(commit.commit_hash, response)
