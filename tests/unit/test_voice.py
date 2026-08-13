from __future__ import annotations

from pathlib import Path

from devmate.adapters.speech.faster_whisper_provider import FasterWhisperInputProvider
from devmate.application.conversation_service import Answer
from devmate.application.voice_service import VoiceConversationService
from devmate.domain.models import LLMResponse


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
