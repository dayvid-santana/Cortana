"""Conversa por voz, de uma rodada ou contínua, com áudio de entrada e resposta falada."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from devmate.application.conversation_service import Answer, ConversationService
from devmate.application.inspection_conversation_service import InspectionConversationService
from devmate.domain.ports import SpeechInputProvider, SpeechProvider
from devmate.errors import SpeechRecognitionUnavailableError

EXIT_PHRASES = frozenset(
    {
        "sair",
        "tchau",
        "encerrar",
        "parar",
        "até logo",
        "ate logo",
        "adeus",
        "fim",
        "obrigado, tchau",
    }
)


def is_exit_phrase(transcript: str) -> bool:
    """Reconhece um pedido falado de encerramento, tolerando pontuação da transcrição."""
    normalized = transcript.strip().casefold().strip(".!?,… ")
    return normalized in EXIT_PHRASES


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
        answer = self._answer(
            project_id, transcript, provider_name, commit_ref, model, code_files, full_repo
        )
        if speak_response:
            self._speak(answer.response.text)
        return VoiceAnswer(transcript=transcript, answer=answer)

    def converse(
        self,
        project_id: int,
        provider_name: str,
        commit_ref: str | None = None,
        model: str | None = None,
        duration_seconds: int | None = None,
        speak_response: bool = True,
        code_files: list[str] | None = None,
        full_repo: bool = False,
        on_notice: Callable[[str], None] | None = None,
        max_silent_rounds: int = 3,
    ) -> Iterator[VoiceAnswer]:
        """Escuta e responde em rodadas sucessivas até um pedido de encerramento.

        O histórico é recuperado do banco a cada rodada, portanto a conversa mantém
        contexto entre as perguntas. Silêncio não encerra a conversa: apenas consome
        uma tentativa, até ``max_silent_rounds`` seguidas.
        """
        silent_rounds = 0
        while True:
            try:
                transcript = self.input_provider.listen(duration_seconds)
            except SpeechRecognitionUnavailableError as exc:
                silent_rounds += 1
                if silent_rounds >= max_silent_rounds:
                    raise
                if on_notice is not None:
                    on_notice(str(exc))
                continue
            silent_rounds = 0
            if is_exit_phrase(transcript):
                return
            answer = self._answer(
                project_id, transcript, provider_name, commit_ref, model, code_files, full_repo
            )
            if speak_response:
                self._speak(answer.response.text)
            yield VoiceAnswer(transcript=transcript, answer=answer)

    def _answer(
        self,
        project_id: int,
        transcript: str,
        provider_name: str,
        commit_ref: str | None,
        model: str | None,
        code_files: list[str] | None,
        full_repo: bool,
    ) -> Answer:
        if code_files or full_repo:
            if self.inspection_conversation is None:
                raise RuntimeError("Inspeção de código não está configurada.")
            return self.inspection_conversation.ask(
                project_id,
                transcript,
                provider_name,
                commit_ref,
                model,
                code_files,
                full_repo,
            )
        return self.conversation.ask(
            project_id,
            transcript,
            provider_name,
            commit_ref,
            model,
        )

    def _speak(self, text: str) -> None:
        available, reason = self.output_provider.available()
        if not available:
            raise RuntimeError(reason or "Provider de fala indisponível.")
        self.output_provider.speak(text)
