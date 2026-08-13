"""Captura de microfone e transcrição Whisper executadas inteiramente localmente."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from devmate.errors import SpeechRecognitionUnavailableError

AudioRecorder = Callable[[int, int], Any]
ModelFactory = Callable[[str, Path], Any]


class FasterWhisperInputProvider:
    """Transcreve uma janela curta de áudio sem persistir a gravação.

    O modelo pode ser baixado na primeira execução, exclusivamente como resultado
    do comando explícito ``devmate listen``. Depois disso, áudio e transcrição
    permanecem locais; somente a pergunta transcrita é enviada ao LLM escolhido.
    """

    name = "faster_whisper"

    def __init__(
        self,
        model_name: str,
        language: str,
        duration_seconds: int,
        model_directory: Path,
        audio_recorder: AudioRecorder | None = None,
        model_factory: ModelFactory | None = None,
    ) -> None:
        self.model_name = model_name
        self.language = language
        self.duration_seconds = duration_seconds
        self.model_directory = model_directory
        self._audio_recorder = audio_recorder
        self._model_factory = model_factory
        self._loaded_model: Any | None = None

    def available(self) -> tuple[bool, str | None]:
        try:
            import faster_whisper  # type: ignore[import-untyped]  # noqa: F401
            import sounddevice  # type: ignore[import-untyped]
        except ImportError:
            return (
                False,
                "Entrada de voz requer faster-whisper e sounddevice. "
                "Instale com `python -m pip install -r requirements.txt`.",
            )
        try:
            sounddevice.query_devices(kind="input")
        except Exception as exc:
            return False, f"Nenhum microfone padrão disponível: {exc}"
        return True, None

    def listen(self, duration_seconds: int | None = None) -> str:
        available, reason = self.available()
        if not available and self._audio_recorder is None:
            raise SpeechRecognitionUnavailableError(reason or "Entrada de voz indisponível.")
        duration = duration_seconds or self.duration_seconds
        if duration <= 0:
            raise SpeechRecognitionUnavailableError("A duração de captura deve ser positiva.")
        try:
            audio = self._record(duration)
            transcript = self._transcribe(audio)
        except SpeechRecognitionUnavailableError:
            raise
        except Exception as exc:
            raise SpeechRecognitionUnavailableError(
                f"Não foi possível transcrever o áudio: {exc}"
            ) from exc
        if not transcript:
            raise SpeechRecognitionUnavailableError(
                "Nenhuma fala foi reconhecida. Tente novamente."
            )
        return transcript

    def _record(self, duration_seconds: int) -> Any:
        if self._audio_recorder is not None:
            return self._audio_recorder(duration_seconds, 16_000)
        import sounddevice

        frame_count = duration_seconds * 16_000
        recording = sounddevice.rec(
            frame_count,
            samplerate=16_000,
            channels=1,
            dtype="float32",
            blocking=True,
        )
        return recording.reshape(-1)

    def _transcribe(self, audio: Any) -> str:
        model = self._model()
        language_code = self.language.split("-", maxsplit=1)[0].lower()
        segments, _ = model.transcribe(
            audio,
            language=language_code,
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return " ".join(str(segment.text).strip() for segment in segments).strip()

    def _model(self) -> Any:
        """Reaproveita o modelo já carregado; construí-lo custa ~0,6s por rodada."""
        if self._model_factory is not None:
            return self._model_factory(self.model_name, self.model_directory)
        if self._loaded_model is not None:
            return self._loaded_model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise SpeechRecognitionUnavailableError(
                "Pacote faster-whisper não está instalado."
            ) from exc
        self.model_directory.mkdir(parents=True, exist_ok=True)
        self._loaded_model = WhisperModel(
            self.model_name,
            device="cpu",
            compute_type="int8",
            download_root=str(self.model_directory),
        )
        return self._loaded_model

    def preload(self) -> None:
        """Carrega o modelo antecipadamente, para a primeira resposta não pagar o custo."""
        self._model()
