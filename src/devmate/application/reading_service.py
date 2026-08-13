"""Narração local de Markdown com checkpoints seguros."""

from __future__ import annotations

from dataclasses import dataclass

from devmate.adapters.filesystem.local_filesystem import LocalFilesystem
from devmate.adapters.persistence.repositories import RepositoryStore
from devmate.domain.models import NarrationSegment
from devmate.domain.ports import SpeechProvider
from devmate.errors import ReadingSessionStaleError
from devmate.markdown.narrator import MarkdownNarrator


@dataclass(frozen=True, slots=True)
class ReadingResult:
    path: str
    segments: tuple[NarrationSegment, ...]
    dry_run: bool


class ReadingService:
    def __init__(
        self,
        filesystem: LocalFilesystem,
        store: RepositoryStore,
        narrator: MarkdownNarrator,
        speech: SpeechProvider,
    ) -> None:
        self.filesystem = filesystem
        self.store = store
        self.narrator = narrator
        self.speech = speech

    def read(
        self,
        project_id: int,
        requested_path: str,
        section: str | None = None,
        dry_run: bool = False,
        resume: bool = False,
    ) -> ReadingResult:
        path, content, content_hash = self.filesystem.read_text(requested_path)
        relative = path.relative_to(self.filesystem.root).as_posix()
        checkpoint = self.store.checkpoint(project_id, relative)
        start = 0
        if resume and checkpoint:
            if checkpoint[0] != content_hash:
                raise ReadingSessionStaleError("O arquivo mudou desde o checkpoint de leitura.")
            start = checkpoint[1]
        segments = self.narrator.segments(content, section)
        remaining = tuple(segments[start:])
        if not dry_run:
            available, reason = self.speech.available()
            if not available:
                raise RuntimeError(reason or "Provider de fala indisponível.")
            for offset, segment in enumerate(remaining, start=start):
                self.speech.speak(segment.text)
                self.store.save_checkpoint(project_id, relative, content_hash, offset + 1)
        elif remaining:
            self.store.save_checkpoint(project_id, relative, content_hash, start)
        return ReadingResult(relative, remaining, dry_run)
