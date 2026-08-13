"""Conversa por voz, de uma rodada ou contínua, com áudio de entrada e resposta falada."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal

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

ASSISTANT_HELP_TEXT = (
    "Posso responder sobre a documentação indexada do repositório e manter o contexto "
    "da conversa. Posso analisar arquivos de código quando você os autoriza com --files "
    "ou --full-repo. Posso narrar arquivos Markdown e seções por comandos de voz "
    "configurados. Para ver os comandos ativos, use diana commands no terminal. "
    "Diga sair ou tchau para encerrar a conversa."
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


@dataclass(frozen=True, slots=True)
class VoiceAnswer:
    transcript: str
    answer: Answer


@dataclass(frozen=True, slots=True)
class VoiceReading:
    transcript: str
    result: ReadingResult


@dataclass(frozen=True, slots=True)
class VoiceHelp:
    transcript: str
    text: str = ASSISTANT_HELP_TEXT


VoiceTurn = VoiceAnswer | VoiceReading | VoiceHelp


@dataclass(frozen=True, slots=True)
class VoiceCommand:
    """Comando local configurado; nunca instrui nem chama uma LLM."""

    phrases: tuple[str, ...]
    action: Literal["read", "help"]
    path: str | None = None
    section: str | None = None

    def matches(self, transcript: str) -> bool:
        normalized = _normalize_voice_phrase(transcript)
        return normalized in {_normalize_voice_phrase(phrase) for phrase in self.phrases}


class VoiceConversationService:
    """Mantém áudio local e delega somente texto à conversa existente."""

    def __init__(
        self,
        input_provider: SpeechInputProvider,
        output_provider: SpeechProvider,
        conversation: ConversationService,
        inspection_conversation: InspectionConversationService | None = None,
        reading: ReadingService | None = None,
        commands: tuple[VoiceCommand, ...] = (),
    ) -> None:
        self.input_provider = input_provider
        self.output_provider = output_provider
        self.conversation = conversation
        self.inspection_conversation = inspection_conversation
        self.reading = reading
        self.commands = commands

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
        special = self._special_command(project_id, transcript, speak_response)
        if special is not None:
            return special
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
            special = self._special_command(project_id, transcript, speak_response)
            if special is not None:
                yield special
                continue
            answer = self._answer(
                project_id, transcript, provider_name, commit_ref, model, code_files, full_repo
            )
            if speak_response:
                self._speak(answer.response.text)
            yield VoiceAnswer(transcript=transcript, answer=answer)

    def _special_command(
        self, project_id: int, transcript: str, speak_response: bool
    ) -> VoiceReading | VoiceHelp | None:
        command = next((item for item in self.commands if item.matches(transcript)), None)
        if command is None:
            return None
        if command.action == "help":
            help_result = VoiceHelp(transcript)
            if speak_response:
                self._speak(help_result.text)
            return help_result
        if self.reading is None:
            raise RuntimeError("Leitura por voz não está configurada.")
        if command.path is None:
            raise RuntimeError("O comando de leitura não informa um arquivo Markdown.")
        reading_result = self.reading.read(
            project_id=project_id,
            requested_path=command.path,
            section=command.section,
            dry_run=not speak_response,
        )
        return VoiceReading(transcript=transcript, result=reading_result)

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
