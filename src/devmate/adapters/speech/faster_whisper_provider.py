"""Captura de microfone e transcrição Whisper executadas inteiramente localmente."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from devmate.errors import SpeechRecognitionUnavailableError

AudioRecorder = Callable[[int, int], Any]
ModelFactory = Callable[[str, Path], Any]
ChunkSource = Callable[[], Iterator[Any]]

SAMPLE_RATE = 16_000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000

DEFAULT_SILENCE_SECONDS = 2.0
DEFAULT_VOICE_THRESHOLD = 0.02


def _is_voiced(frame: Any, threshold: float) -> bool:
    """Corte por energia (RMS); simples e sem dependência nativa extra."""
    import numpy as np

    if frame.size == 0:
        return False
    return float(np.sqrt(np.mean(np.square(frame)))) > threshold


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
        silence_seconds: float = DEFAULT_SILENCE_SECONDS,
        voice_threshold: float = DEFAULT_VOICE_THRESHOLD,
        chunk_source: ChunkSource | None = None,
    ) -> None:
        self.model_name = model_name
        self.language = language
        self.duration_seconds = duration_seconds
        self.model_directory = model_directory
        self._audio_recorder = audio_recorder
        self._model_factory = model_factory
        self._loaded_model: Any | None = None
        # Após detectar fala, quanto silêncio contínuo até encerrar a captura.
        # Dá margem para a pessoa fazer uma pausa para pensar sem ser cortada.
        self.silence_seconds = silence_seconds
        self.voice_threshold = voice_threshold
        self._chunk_source = chunk_source

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

    def _record(self, max_duration_seconds: int) -> Any:
        """Grava até ``silence_seconds`` de silêncio após a fala começar.

        ``max_duration_seconds`` é um teto de segurança: se a pessoa nunca parar
        de falar (ou o microfone captar só ruído), a captura ainda encerra.
        """
        if self._audio_recorder is not None:
            return self._audio_recorder(max_duration_seconds, SAMPLE_RATE)
        return self._record_until_silence(max_duration_seconds)

    def _record_until_silence(self, max_duration_seconds: int) -> Any:
        import numpy as np

        silence_limit = max(1, round(self.silence_seconds * 1000 / FRAME_MS))
        max_frames = max(1, round(max_duration_seconds * 1000 / FRAME_MS))

        collected: list[Any] = []
        speech_started = False
        silence_run = 0
        for index, frame in enumerate(self._frame_source(max_duration_seconds)):
            collected.append(frame)
            if _is_voiced(frame, self.voice_threshold):
                speech_started = True
                silence_run = 0
            elif speech_started:
                silence_run += 1
                if silence_run >= silence_limit:
                    break
            if index + 1 >= max_frames:
                break

        if not collected:
            return np.zeros(0, dtype="float32")
        return np.concatenate(collected)

    def _frame_source(self, max_duration_seconds: int) -> Iterator[Any]:
        """Produz quadros de ~30ms; substituível em teste via ``chunk_source``."""
        if self._chunk_source is not None:
            yield from self._chunk_source()
            return

        import queue

        import sounddevice

        frame_queue: queue.Queue[Any] = queue.Queue()

        def callback(indata: Any, _frames: int, _time: Any, _status: Any) -> None:
            frame_queue.put(indata.copy().reshape(-1))

        max_frames = max(1, round(max_duration_seconds * 1000 / FRAME_MS))
        with sounddevice.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=FRAME_SAMPLES,
            callback=callback,
        ):
            for _ in range(max_frames):
                yield frame_queue.get()

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
