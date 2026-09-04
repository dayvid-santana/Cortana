from __future__ import annotations

from pathlib import Path

from devmate.adapters.filesystem.local_filesystem import LocalFilesystem
from devmate.application.project_memory_service import ProjectMemoryService


def make_filesystem(root: Path) -> LocalFilesystem:
    return LocalFilesystem(root, max_file_bytes=1_000_000, ignored_patterns=[".env", "*.key"])


def test_render_wraps_file_content_with_its_source_path(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("Use snake_case para funções Python.", encoding="utf-8")
    memory = ProjectMemoryService(make_filesystem(tmp_path), ("AGENTS.md",), max_chars=4000)

    rendered = memory.render()

    assert '<project_memory source="AGENTS.md">' in rendered
    assert "Use snake_case para funções Python." in rendered


def test_missing_files_are_ignored_silently(tmp_path: Path) -> None:
    memory = ProjectMemoryService(make_filesystem(tmp_path), ("AGENTS.md",), max_chars=4000)

    assert memory.render() == ""


def test_disabled_returns_empty_even_with_existing_files(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("conteúdo", encoding="utf-8")
    memory = ProjectMemoryService(
        make_filesystem(tmp_path), ("AGENTS.md",), max_chars=4000, enabled=False
    )

    assert memory.render() == ""


def test_no_configured_files_returns_empty(tmp_path: Path) -> None:
    memory = ProjectMemoryService(make_filesystem(tmp_path), (), max_chars=4000)

    assert memory.render() == ""


def test_content_over_the_limit_is_truncated(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("x" * 500, encoding="utf-8")
    memory = ProjectMemoryService(make_filesystem(tmp_path), ("AGENTS.md",), max_chars=100)

    rendered = memory.render()

    assert "x" * 100 in rendered
    assert "truncado" in rendered
    assert "x" * 500 not in rendered


def test_sensitive_files_are_never_read_even_if_configured(tmp_path: Path) -> None:
    (tmp_path / "secrets.key").write_text("chave-secreta", encoding="utf-8")
    memory = ProjectMemoryService(make_filesystem(tmp_path), ("secrets.key",), max_chars=4000)

    assert memory.render() == ""


def test_multiple_files_are_concatenated_in_the_configured_order(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("primeiro", encoding="utf-8")
    (tmp_path / "CONVENTIONS.md").write_text("segundo", encoding="utf-8")
    memory = ProjectMemoryService(
        make_filesystem(tmp_path), ("AGENTS.md", "CONVENTIONS.md"), max_chars=4000
    )

    rendered = memory.render()

    assert rendered.index("primeiro") < rendered.index("segundo")


def test_unchanged_file_hits_the_in_process_cache(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("conteúdo estável", encoding="utf-8")
    memory = ProjectMemoryService(make_filesystem(tmp_path), ("AGENTS.md",), max_chars=4000)

    first = memory.render()
    second = memory.render()

    assert first == second
    assert memory._cache["AGENTS.md"][1] == first  # mesmo bloco reaproveitado, não recomputado


def test_changed_file_invalidates_the_cache(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    path.write_text("v1", encoding="utf-8")
    memory = ProjectMemoryService(make_filesystem(tmp_path), ("AGENTS.md",), max_chars=4000)
    first = memory.render()

    path.write_text("v2", encoding="utf-8")
    second = memory.render()

    assert "v1" in first
    assert "v2" in second
    assert "v1" not in second
