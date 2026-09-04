"""Watcher real, com eventos de filesystem de verdade — sem isto, os testes
unitários da cache não provam que o `watchdog` está de fato ligado nela."""

from __future__ import annotations

import time
from pathlib import Path

from devmate.adapters.filesystem.local_filesystem import LocalFilesystem
from devmate.adapters.filesystem.working_tree_watcher import WorkingTreeWatcher


def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def make_watcher(root: Path) -> WorkingTreeWatcher:
    filesystem = LocalFilesystem(root, max_file_bytes=1_000_000, ignored_patterns=[".env", "*.key"])
    return WorkingTreeWatcher(filesystem)


def test_watcher_picks_up_a_new_file_without_being_asked(tmp_path: Path) -> None:
    watcher = make_watcher(tmp_path)
    watcher.start()
    try:
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")

        assert _wait_until(lambda: "a.py" in watcher.cache.known_paths())
        assert watcher.cache.get("a.py") == "x = 1\n"
    finally:
        watcher.stop()


def test_watcher_updates_the_cache_when_a_watched_file_changes(tmp_path: Path) -> None:
    path = tmp_path / "a.py"
    path.write_text("x = 1\n", encoding="utf-8")
    watcher = make_watcher(tmp_path)
    watcher.start()
    try:
        assert _wait_until(lambda: watcher.cache.get("a.py") == "x = 1\n")

        path.write_text("x = 2\n", encoding="utf-8")

        assert _wait_until(lambda: watcher.cache.get("a.py") == "x = 2\n")
    finally:
        watcher.stop()


def test_watcher_removes_deleted_files_from_the_cache(tmp_path: Path) -> None:
    path = tmp_path / "a.py"
    watcher = make_watcher(tmp_path)
    watcher.start()
    try:
        path.write_text("x = 1\n", encoding="utf-8")
        assert _wait_until(lambda: "a.py" in watcher.cache.known_paths())

        path.unlink()

        assert _wait_until(lambda: "a.py" not in watcher.cache.known_paths())
    finally:
        watcher.stop()


def test_watcher_never_caches_sensitive_files(tmp_path: Path) -> None:
    watcher = make_watcher(tmp_path)
    watcher.start()
    try:
        (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")
        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")

        assert _wait_until(lambda: "app.py" in watcher.cache.known_paths())
        time.sleep(0.3)  # dá tempo do evento do .env, se algum dia existir, aparecer
        assert ".env" not in watcher.cache.known_paths()
    finally:
        watcher.stop()


def test_watcher_ignores_excluded_directories(tmp_path: Path) -> None:
    excluded = tmp_path / "node_modules"
    excluded.mkdir()
    watcher = make_watcher(tmp_path)
    watcher.start()
    try:
        (excluded / "lib.js").write_text("x", encoding="utf-8")
        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")

        assert _wait_until(lambda: "app.py" in watcher.cache.known_paths())
        time.sleep(0.3)
        assert "node_modules/lib.js" not in watcher.cache.known_paths()
    finally:
        watcher.stop()
