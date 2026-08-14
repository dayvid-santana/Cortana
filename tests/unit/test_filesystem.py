from __future__ import annotations

from pathlib import Path

import pytest

from devmate.adapters.filesystem.local_filesystem import LocalFilesystem
from devmate.errors import FileTooLargeError, UnsafePathError


def filesystem(root: Path) -> LocalFilesystem:
    return LocalFilesystem(root, 1_000, [".env", "*.pem"], False)


def test_rejects_path_traversal(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    with pytest.raises(UnsafePathError):
        filesystem(root).read_text("../secret.txt")


def test_rejects_sensitive_files(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("TOKEN=secret", encoding="utf-8")
    with pytest.raises(UnsafePathError):
        filesystem(tmp_path).read_text(".env")


def test_returns_content_and_hash(tmp_path: Path) -> None:
    (tmp_path / "docs.md").write_text("Olá", encoding="utf-8")
    path, content, content_hash = filesystem(tmp_path).read_text("docs.md")
    assert path.name == "docs.md"
    assert content == "Olá"
    assert len(content_hash) == 64


def test_write_text_writes_inside_the_root(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")

    written = filesystem(tmp_path).write_text("app.py", "x = 2\n")

    assert written == tmp_path / "app.py"
    assert written.read_text(encoding="utf-8") == "x = 2\n"


def test_write_text_rejects_path_traversal(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    with pytest.raises(UnsafePathError):
        filesystem(root).write_text("../outside.py", "x = 1\n")


def test_write_text_rejects_sensitive_files(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        filesystem(tmp_path).write_text(".env", "TOKEN=secret\n")


def test_write_text_enforces_the_size_limit(tmp_path: Path) -> None:
    with pytest.raises(FileTooLargeError):
        filesystem(tmp_path).write_text("big.py", "x" * 2_000)
