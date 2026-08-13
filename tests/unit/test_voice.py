from __future__ import annotations

from pathlib import Path

import pytest

from devmate.adapters.speech.faster_whisper_provider import FasterWhisperInputProvider
from devmate.application.conversation_service import Answer, load_history
from devmate.application.reading_service import ReadingResult
from devmate.application.voice_service import (
    VoiceCommand,
    VoiceConversationService,
    VoiceHelp,
    VoiceReading,
    is_exit_phrase,
)
from devmate.domain.models import ConversationTurn, LLMResponse
from devmate.errors import SpeechRecognitionUnavailableError


class FakeSegment:
    text = "O que mudou na documentação?"


class FakeWhisperModel:
    def __init__(self) -> None:
        self.audio: object | None = None
        self.arguments: dict[str, object] = {}

    def transcribe(self, audio: object, **kwargs: object) -> tuple[list[FakeSegment], object]:
        self.audio = audio
        self.arguments = kwargs
        return [FakeSegment()], object()


class FakeInput:
    name = "fake"

    def available(self) -> tuple[bool, str | None]:
        return True, None

    def listen(self, duration_seconds: int | None = None) -> str:
        assert duration_seconds == 4
        return "O que mudou?"


class FakeSpeech:
    name = "fake"

    def __init__(self) -> None:
        self.spoken: list[str] = []

    def available(self) -> tuple[bool, str | None]:
        return True, None

    def speak(self, text: str) -> None:
        self.spoken.append(text)


class FakeConversation:
    def __init__(self) -> None:
        self.question: str | None = None

    def ask(
        self,
        project_id: int,
        question: str,
        provider_name: str,
        commit_ref: str | None = None,
        model: str | None = None,
    ) -> Answer:
        assert project_id == 1
        assert provider_name == "mock"
        assert commit_ref is None
        assert model is None
        self.question = question
        return Answer("a" * 40, LLMResponse("Resposta falada."))


class FakeInspectionConversation:
    def __init__(self) -> None:
        self.arguments: tuple[object, ...] | None = None

    def ask(
        self,
        project_id: int,
        question: str,
        provider_name: str,
        commit_ref: str | None = None,
        model: str | None = None,
        files: list[str] | None = None,
        full_repo: bool = False,
    ) -> Answer:
        self.arguments = (
            project_id,
            question,
            provider_name,
            commit_ref,
            model,
            files,
            full_repo,
        )
        return Answer("b" * 40, LLMResponse("Resposta sobre o código."))


def test_faster_whisper_transcribes_audio_in_memory(tmp_path: Path) -> None:
    model = FakeWhisperModel()
    provider = FasterWhisperInputProvider(
        model_name="base",
        language="pt-BR",
        duration_seconds=10,
        model_directory=tmp_path / "models",
        audio_recorder=lambda seconds, sample_rate: [seconds, sample_rate],
        model_factory=lambda _name, _directory: model,
    )

    assert provider.listen(3) == "O que mudou na documentação?"
    assert model.audio == [3, 16_000]
    assert model.arguments["language"] == "pt"
    assert model.arguments["vad_filter"] is True
    assert not (tmp_path / "models").exists()


def test_voice_service_sends_only_transcript_and_speaks_response() -> None:
    output = FakeSpeech()
    conversation = FakeConversation()
    service = VoiceConversationService(FakeInput(), output, conversation)  # type: ignore[arg-type]

    result = service.listen_and_ask(1, "mock", duration_seconds=4)

    assert conversation.question == "O que mudou?"
    assert output.spoken == ["Resposta falada."]
    assert result.transcript == "O que mudou?"


def test_voice_service_uses_code_scope_only_when_explicitly_authorized() -> None:
    output = FakeSpeech()
    code_conversation = FakeInspectionConversation()
    service = VoiceConversationService(
        FakeInput(),
        output,
        FakeConversation(),  # type: ignore[arg-type]
        code_conversation,  # type: ignore[arg-type]
    )

    result = service.listen_and_ask(
        1,
        "codex",
        duration_seconds=4,
        code_files=["src/app.py"],
        full_repo=False,
    )

    assert result.answer.response.text == "Resposta sobre o código."
    assert code_conversation.arguments == (
        1,
        "O que mudou?",
        "codex",
        None,
        None,
        ["src/app.py"],
        False,
    )
    assert output.spoken == ["Resposta sobre o código."]


class ScriptedInput:
    """Reproduz uma sequência de rodadas; um item ``None`` simula silêncio."""

    name = "scripted"

    def __init__(self, transcripts: list[str | None]) -> None:
        self.transcripts = list(transcripts)
        self.calls = 0

    def available(self) -> tuple[bool, str | None]:
        return True, None

    def listen(self, duration_seconds: int | None = None) -> str:
        self.calls += 1
        if not self.transcripts:
            raise AssertionError("A conversa pediu mais rodadas do que o roteiro previa.")
        transcript = self.transcripts.pop(0)
        if transcript is None:
            raise SpeechRecognitionUnavailableError("Nenhuma fala foi reconhecida.")
        return transcript


class RecordingConversation:
    def __init__(self) -> None:
        self.questions: list[str] = []

    def ask(
        self,
        project_id: int,
        question: str,
        provider_name: str,
        commit_ref: str | None = None,
        model: str | None = None,
    ) -> Answer:
        self.questions.append(question)
        return Answer("c" * 40, LLMResponse(f"Resposta {len(self.questions)}."))


class ReadmeInput:
    name = "readme"

    def available(self) -> tuple[bool, str | None]:
        return True, None

    def listen(self, duration_seconds: int | None = None) -> str:
        assert duration_seconds == 4
        return "Diana, leia o documento."


class FakeReading:
    def __init__(self) -> None:
        self.arguments: tuple[int, str, str | None, bool] | None = None

    def read(
        self,
        project_id: int,
        requested_path: str,
        section: str | None = None,
        dry_run: bool = False,
        resume: bool = False,
    ) -> ReadingResult:
        assert not resume
        self.arguments = (project_id, requested_path, section, dry_run)
        return ReadingResult(requested_path, (), dry_run)


@pytest.mark.parametrize("phrase", ["sair", "Tchau!", "  ATÉ LOGO  ", "encerrar."])
def test_exit_phrases_are_recognized_despite_case_and_punctuation(phrase: str) -> None:
    assert is_exit_phrase(phrase)


@pytest.mark.parametrize("phrase", ["o que mudou?", "saiba mais sobre o scan", ""])
def test_regular_questions_are_not_treated_as_exit(phrase: str) -> None:
    assert not is_exit_phrase(phrase)


@pytest.mark.parametrize("phrase", ["leia o documento", "Diana, leia o documento."])
def test_voice_read_command_recognizes_configured_phrases(phrase: str) -> None:
    command = VoiceCommand(("leia o documento", "ler o documento"), "read", "README.md")

    assert command.matches(phrase)


def test_voice_read_command_does_not_match_unconfigured_phrase() -> None:
    command = VoiceCommand(("leia o documento",), "read", "README.md")

    assert not command.matches("Diana, leia o README")


def test_readme_voice_command_uses_local_reader_without_calling_provider() -> None:
    output = FakeSpeech()
    conversation = RecordingConversation()
    reader = FakeReading()
    service = VoiceConversationService(
        ReadmeInput(),  # type: ignore[arg-type]
        output,
        conversation,  # type: ignore[arg-type]
        reading=reader,  # type: ignore[arg-type]
        commands=(VoiceCommand(("leia o documento",), "read", "README.md"),),
    )

    result = service.listen_and_ask(1, "codex", duration_seconds=4)

    assert isinstance(result, VoiceReading)
    assert result.result.path == "README.md"
    assert reader.arguments == (1, "README.md", None, False)
    assert conversation.questions == []
    assert output.spoken == []


def test_custom_voice_command_reads_its_configured_document_section() -> None:
    output = FakeSpeech()
    conversation = RecordingConversation()
    reader = FakeReading()
    service = VoiceConversationService(
        ScriptedInput(["Diana, leia a arquitetura"]),  # type: ignore[arg-type]
        output,
        conversation,  # type: ignore[arg-type]
        reading=reader,  # type: ignore[arg-type]
        commands=(
            VoiceCommand(
                ("leia a arquitetura",),
                "read",
                "docs/architecture.md",
                "Segurança",
            ),
        ),
    )

    result = service.listen_and_ask(1, "codex")

    assert isinstance(result, VoiceReading)
    assert reader.arguments == (1, "docs/architecture.md", "Segurança", False)
    assert conversation.questions == []


def test_help_voice_command_speaks_capabilities_without_calling_provider() -> None:
    output = FakeSpeech()
    conversation = RecordingConversation()
    service = VoiceConversationService(
        ScriptedInput(["Diana, o que você pode fazer?"]),  # type: ignore[arg-type]
        output,
        conversation,  # type: ignore[arg-type]
        commands=(VoiceCommand(("o que você pode fazer",), "help"),),
    )

    result = service.listen_and_ask(1, "codex")

    assert isinstance(result, VoiceHelp)
    assert "documentação indexada" in result.text
    assert conversation.questions == []
    assert output.spoken == [result.text]


def test_converse_runs_successive_rounds_until_the_exit_phrase() -> None:
    output = FakeSpeech()
    conversation = RecordingConversation()
    service = VoiceConversationService(
        ScriptedInput(["O que mudou no README?", "E na parte de segurança?", "tchau"]),  # type: ignore[arg-type]
        output,
        conversation,  # type: ignore[arg-type]
    )

    turns = list(service.converse(1, "mock"))

    assert [turn.transcript for turn in turns] == [
        "O que mudou no README?",
        "E na parte de segurança?",
    ]
    assert conversation.questions == ["O que mudou no README?", "E na parte de segurança?"]
    assert output.spoken == ["Resposta 1.", "Resposta 2."]


def test_converse_survives_a_round_without_recognized_speech() -> None:
    conversation = RecordingConversation()
    notices: list[str] = []
    service = VoiceConversationService(
        ScriptedInput([None, "O que mudou?", "sair"]),  # type: ignore[arg-type]
        FakeSpeech(),
        conversation,  # type: ignore[arg-type]
    )

    turns = list(service.converse(1, "mock", on_notice=notices.append))

    assert [turn.transcript for turn in turns] == ["O que mudou?"]
    assert notices == ["Nenhuma fala foi reconhecida."]


def test_converse_gives_up_after_repeated_silence() -> None:
    service = VoiceConversationService(
        ScriptedInput([None, None, None]),  # type: ignore[arg-type]
        FakeSpeech(),
        RecordingConversation(),  # type: ignore[arg-type]
    )

    with pytest.raises(SpeechRecognitionUnavailableError):
        list(service.converse(1, "mock", max_silent_rounds=3))


class FakeStore:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self.rows = rows
        self.arguments: tuple[int, str, int] | None = None

    def conversation(
        self, project_id: int, commit_hash: str, limit: int = 12
    ) -> list[tuple[str, str]]:
        self.arguments = (project_id, commit_hash, limit)
        return self.rows


def test_load_history_maps_persisted_rows_into_turns() -> None:
    store = FakeStore([("user", "Primeira?"), ("assistant", "Primeira resposta.")])

    history = load_history(store, 1, "d" * 40)  # type: ignore[arg-type]

    assert history == (
        ConversationTurn("user", "Primeira?"),
        ConversationTurn("assistant", "Primeira resposta."),
    )
    assert store.arguments == (1, "d" * 40, 12)
