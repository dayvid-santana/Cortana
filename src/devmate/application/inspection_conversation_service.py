"""Perguntas rastreáveis sobre código explicitamente autorizado."""

from __future__ import annotations

from devmate.adapters.llm.registry import ProviderRegistry
from devmate.adapters.persistence.repositories import RepositoryStore
from devmate.application.conversation_service import Answer, load_history
from devmate.application.inspection_service import InspectionService
from devmate.domain.enums import Scope
from devmate.domain.models import LLMRequest
from devmate.prompts.code_inspection import CODE_INSPECTION_SYSTEM


class InspectionConversationService:
    """Monta contexto de código read-only e mantém a troca no histórico local."""

    def __init__(
        self,
        inspection: InspectionService,
        store: RepositoryStore,
        providers: ProviderRegistry,
    ) -> None:
        self.inspection = inspection
        self.store = store
        self.providers = providers

    def ask(
        self,
        project_id: int,
        question: str,
        provider_name: str,
        commit_ref: str | None = None,
        model: str | None = None,
        files: list[str] | None = None,
        full_repo: bool = False,
        system_instructions: str | None = None,
    ) -> Answer:
        context = self.inspection.build(project_id, commit_ref, files or [], full_repo)
        # Lido antes de gravar a pergunta atual, para não duplicá-la no histórico.
        history = load_history(self.store, project_id, context.commit_hash)
        previous_response_id = self.store.last_response_id(
            project_id, context.commit_hash, provider_name
        )
        request = LLMRequest(
            task="code_inspection",
            question=question,
            scope=Scope.CODE,
            chunks=context.chunks,
            system_instructions=system_instructions or CODE_INSPECTION_SYSTEM,
            model=model,
            history=history,
            previous_response_id=previous_response_id,
        )
        provider = self.providers.get(provider_name)
        self.store.add_message(project_id, context.commit_hash, "user", question)
        response = provider.complete(request)
        self.store.add_message(
            project_id,
            context.commit_hash,
            "assistant",
            response.text,
            provider_name,
            response.response_id,
        )
        return Answer(context.commit_hash, response)
