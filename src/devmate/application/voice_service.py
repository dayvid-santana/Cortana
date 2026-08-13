"""Conversa por voz, de uma rodada ou contínua, com áudio de entrada e resposta falada."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from devmate.application.conversation_service import Answer, ConversationService
from devmate.application.inspection_conversation_service import InspectionConversationService
from devmate.application.reading_service import ReadingResult, ReadingService
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
        "obrigado tchau",
    }
)

README_READ_PHRASES = frozenset(
    {
        "leia o documento",
        "ler o documento",
    }
)


def _normalize_voice_phrase(transcript: str) -> str:
    decomposed = unicodedata.normalize("NFD", transcript.casefold())
    without_accents = "".join(
        character for character in decomposed if unicodedata.category(character) != "Mn"
    )
    normalized = re.sub(r"[^a-z0-9]+", " ", without_accents).strip()
    if normalized.startswith("diana "):
        return normalized.removeprefix("diana ")
    return normalized


def is_exit_phrase(transcript: str) -> bool:
    """Reconhece um pedido falado de encerramento, tolerando pontuação da transcrição."""
    normalized = _normalize_voice_phrase(transcript)
    return normalized in EXIT_PHRASES


def is_readme_read_phrase(transcript: str) -> bool:
    """Reconhece a ordem local para narrar o README sem consultar o provider."""
    return _normalize_voice_phrase(transcript) in README_READ_PHRASES


@dataclass(frozen=True, slots=True)
class VoiceAnswer:
    transcript: str
    answer: Answer


@dataclass(frozen=True, slots=True)
class VoiceReading:
    transcript: str
    result: ReadingResult


VoiceTurn = VoiceAnswer | VoiceReading


class VoiceConversationService:
    """Mantém áudio local e delega somente texto à conversa existente."""

    def __init__(
        self,
        input_provider: SpeechInputProvider,
        output_provider: SpeechProvider,
        conversation: ConversationService,
        inspection_conversation: InspectionConversationService | None = None,
        reading: ReadingService | None = None,
    ) -> None:
        self.input_provider = input_provider
        self.output_provider = output_provider
        self.conversation = conversation
        self.inspection_conversation = inspection_conversation
        self.reading = reading

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
    ) -> VoiceTurn:
        transcript = self.input_provider.listen(duration_seconds)
        reading = self._readme_command(project_id, transcript, speak_response)
        if reading is not None:
            return VoiceReading(transcript=transcript, result=reading)
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
    ) -> Iterator[VoiceTurn]:
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
            reading = self._readme_command(project_id, transcript, speak_response)
            if reading is not None:
                yield VoiceReading(transcript=transcript, result=reading)
                continue
            answer = self._answer(
                project_id, transcript, provider_name, commit_ref, model, code_files, full_repo
            )
            if speak_response:
                self._speak(answer.response.text)
            yield VoiceAnswer(transcript=transcript, answer=answer)

    def _readme_command(
        self, project_id: int, transcript: str, speak_response: bool
    ) -> ReadingResult | None:
        if not is_readme_read_phrase(transcript):
            return None
        if self.reading is None:
            raise RuntimeError("Leitura por voz não está configurada.")
        return self.reading.read(
            project_id=project_id,
            requested_path="README.md",
            dry_run=not speak_response,
        )

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
