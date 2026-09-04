from __future__ import annotations

from pathlib import Path

import pytest

from devmate.application.working_tree_cache import WorkingTreeCache


def test_get_lazily_reads_the_file_on_first_access(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    cache = WorkingTreeCache(tmp_path)

    assert cache.get("a.py") == "x = 1\n"
    assert "a.py" in cache.known_paths()


def test_get_returns_the_cached_value_without_rereading(tmp_path: Path) -> None:
    path = tmp_path / "a.py"
    path.write_text("x = 1\n", encoding="utf-8")
    cache = WorkingTreeCache(tmp_path)
    cache.get("a.py")

    path.write_text("x = 2\n", encoding="utf-8")  # muda no disco, sem passar pela cache

    assert cache.get("a.py") == "x = 1\n"  # continua servindo o valor em cache


def test_refresh_rereads_the_file_even_if_already_cached(tmp_path: Path) -> None:
    path = tmp_path / "a.py"
    path.write_text("x = 1\n", encoding="utf-8")
    cache = WorkingTreeCache(tmp_path)
    cache.get("a.py")

    path.write_text("x = 2\n", encoding="utf-8")
    cache.refresh("a.py")

    assert cache.get("a.py") == "x = 2\n"


def test_invalidate_removes_the_entry(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    cache = WorkingTreeCache(tmp_path)
    cache.get("a.py")

    cache.invalidate("a.py")

    assert "a.py" not in cache.known_paths()


def test_get_raises_for_a_path_that_does_not_exist(tmp_path: Path) -> None:
    cache = WorkingTreeCache(tmp_path)

    with pytest.raises(OSError):
        cache.get("missing.py")
