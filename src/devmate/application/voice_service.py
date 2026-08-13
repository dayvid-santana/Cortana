"""Conversa de uma rodada com áudio de entrada e resposta falada."""

from __future__ import annotations

from dataclasses import dataclass

from devmate.application.conversation_service import Answer, ConversationService
from devmate.application.inspection_conversation_service import InspectionConversationService
from devmate.domain.ports import SpeechInputProvider, SpeechProvider


@dataclass(frozen=True, slots=True)
class VoiceAnswer:
    transcript: str
    answer: Answer


class VoiceConversationService:
    """Mantém áudio local e delega somente texto à conversa existente."""

    def __init__(
        self,
        input_provider: SpeechInputProvider,
        output_provider: SpeechProvider,
        conversation: ConversationService,
        inspection_conversation: InspectionConversationService | None = None,
    ) -> None:
        self.input_provider = input_provider
        self.output_provider = output_provider
        self.conversation = conversation
        self.inspection_conversation = inspection_conversation

    def listen_and_ask(
        self,
        project_id: int,
        provider_name: str,
        commit_ref: str | None = None,
        model: str | None = None,
        duration_seconds: int | None = None,
        speak_response: bool = True,
        code_files: list[str] | None = None,
        full_repo: bool = False,
    ) -> VoiceAnswer:
        transcript = self.input_provider.listen(duration_seconds)
        if code_files or full_repo:
            if self.inspection_conversation is None:
                raise RuntimeError("Inspeção de código não está configurada.")
            answer = self.inspection_conversation.ask(
                project_id,
                transcript,
                provider_name,
                commit_ref,
                model,
                code_files,
                full_repo,
            )
        else:
            answer = self.conversation.ask(
                project_id,
                transcript,
                provider_name,
                commit_ref,
                model,
            )
        if speak_response:
            available, reason = self.output_provider.available()
            if not available:
                raise RuntimeError(reason or "Provider de fala indisponível.")
            self.output_provider.speak(answer.response.text)
        return VoiceAnswer(transcript=transcript, answer=answer)
