"""Observa o filesystem do projeto e mantém uma `WorkingTreeCache` fresca em tempo
real — só o arquivo que mudou é relido, nunca o projeto inteiro, e nada disto chama
um provider de linguagem: é puro I/O local, disparado por evento do sistema
operacional (não por polling)."""

from __future__ import annotations

from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from devmate.adapters.filesystem.local_filesystem import LocalFilesystem
from devmate.application.working_tree_cache import WorkingTreeCache
from devmate.constants import is_excluded_directory


class _CacheEventHandler(FileSystemEventHandler):
    def __init__(self, filesystem: LocalFilesystem, cache: WorkingTreeCache) -> None:
        self.filesystem = filesystem
        self.cache = cache

    def _relative(self, raw_path: str) -> str | None:
        try:
            path = Path(raw_path).resolve()
            relative = path.relative_to(self.cache.root)
        except ValueError:
            return None
        if any(is_excluded_directory(part) for part in relative.parts[:-1]):
            return None
        if self.filesystem.is_sensitive(path):
            return None
        return relative.as_posix()

    def _touch(self, raw_path: str) -> None:
        relative = self._relative(raw_path)
        if relative is None:
            return
        try:
            self.cache.refresh(relative)
        except OSError:
            # Apagado/movido entre o evento e a leitura: sem problema, some da cache
            # até o próximo evento relevante em vez de guardar conteúdo obsoleto.
            self.cache.invalidate(relative)

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._touch(str(event.src_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._touch(str(event.src_path))

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        relative = self._relative(str(event.src_path))
        if relative:
            self.cache.invalidate(relative)

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        old = self._relative(str(event.src_path))
        if old:
            self.cache.invalidate(old)
        self._touch(str(event.dest_path))


class WorkingTreeWatcher:
    """Um observador por projeto — inicia sob demanda quando o backend (`devmate
    serve`) precisa dele pela primeira vez, e roda enquanto o processo estiver de pé."""

    def __init__(self, filesystem: LocalFilesystem) -> None:
        self.cache = WorkingTreeCache(filesystem.root)
        self._observer = Observer()
        self._observer.schedule(
            _CacheEventHandler(filesystem, self.cache), str(self.cache.root), recursive=True
        )
        self._started = False

    def start(self) -> None:
        if not self._started:
            self._observer.start()
            self._started = True

    def stop(self) -> None:
        if self._started:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._started = False
