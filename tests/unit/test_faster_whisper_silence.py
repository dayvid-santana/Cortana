from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np

from devmate.adapters.speech.faster_whisper_provider import (
    FRAME_SAMPLES,
    FasterWhisperInputProvider,
)

LOUD = np.full(FRAME_SAMPLES, 0.5, dtype="float32")
SILENT = np.zeros(FRAME_SAMPLES, dtype="float32")


class FakeSegment:
    text = "transcrição"


class FakeWhisperModel:
    def __init__(self) -> None:
        self.audio: Any = None

    def transcribe(self, audio: Any, **_kwargs: Any) -> tuple[list[FakeSegment], object]:
        self.audio = audio
        return [FakeSegment()], object()


def make_provider(
    tmp_path: Path, frames: list[Any], silence_seconds: float = 0.09
) -> tuple[FasterWhisperInputProvider, FakeWhisperModel]:
    model = FakeWhisperModel()

    def chunk_source() -> Iterator[Any]:
        yield from frames

    provider = FasterWhisperInputProvider(
        model_name="base",
        language="pt-BR",
        duration_seconds=10,
        model_directory=tmp_path / "models",
        model_factory=lambda _name, _directory: model,
        silence_seconds=silence_seconds,
        chunk_source=chunk_source,
    )
    return provider, model


def test_stops_after_the_configured_silence_window_following_speech(tmp_path: Path) -> None:
    # silence_seconds=0.09 -> silence_limit = round(90/30) = 3 frames.
    frames = [LOUD, LOUD, SILENT, SILENT, SILENT, LOUD, LOUD]  # nunca deveria ler o resto
    provider, model = make_provider(tmp_path, frames)

    provider.listen(10)

    assert len(model.audio) == 5 * FRAME_SAMPLES  # parou logo após o 3º silêncio


def test_leading_silence_before_speech_does_not_count_toward_the_cutoff(
    tmp_path: Path,
) -> None:
    # Pausa antes de começar a falar não deve encerrar a captura.
    frames = [SILENT, SILENT, SILENT, SILENT, SILENT, LOUD, SILENT, SILENT, SILENT]
    provider, model = make_provider(tmp_path, frames)

    provider.listen(10)

    assert len(model.audio) == len(frames) * FRAME_SAMPLES


def test_max_duration_caps_recording_even_without_silence(tmp_path: Path) -> None:
    frames = [LOUD] * 20
    provider, model = make_provider(tmp_path, frames)

    provider.listen(1)  # 1000ms / 30ms ~= 33 frames de teto, mas só há 20 disponíveis

    assert len(model.audio) == 20 * FRAME_SAMPLES


def test_grace_window_survives_a_pause_shorter_than_the_silence_timeout(
    tmp_path: Path,
) -> None:
    # silence_seconds=0.09 -> 3 frames; uma pausa de 2 frames não deve cortar.
    frames = [LOUD, SILENT, SILENT, LOUD, LOUD]
    provider, model = make_provider(tmp_path, frames)

    provider.listen(10)

    assert len(model.audio) == len(frames) * FRAME_SAMPLES
