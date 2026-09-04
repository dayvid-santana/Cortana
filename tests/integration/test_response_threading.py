from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from devmate.adapters.persistence.database import (
    create_database_engine,
    migrate_database,
    session_factory,
)
from devmate.adapters.persistence.repositories import RepositoryStore
from devmate.domain.models import Project


def make_store(tmp_path: Path) -> RepositoryStore:
    engine = create_database_engine(tmp_path / "state.db")
    migrate_database(engine)
    return RepositoryStore(session_factory(engine))


def test_last_response_id_is_none_before_any_message(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    project_id = store.ensure_project(Project(None, "p", tmp_path, tmp_path, None))

    assert store.last_response_id(project_id, "a" * 40, "openai") is None


def test_last_response_id_returns_the_most_recent_assistant_turn(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    project_id = store.ensure_project(Project(None, "p", tmp_path, tmp_path, None))
    commit = "a" * 40

    store.add_message(project_id, commit, "user", "pergunta 1")
    store.add_message(project_id, commit, "assistant", "resposta 1", "openai", "resp_1")
    store.add_message(project_id, commit, "user", "pergunta 2")
    store.add_message(project_id, commit, "assistant", "resposta 2", "openai", "resp_2")

    assert store.last_response_id(project_id, commit, "openai") == "resp_2"


def test_last_response_id_is_none_when_the_provider_changed(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    project_id = store.ensure_project(Project(None, "p", tmp_path, tmp_path, None))
    commit = "a" * 40

    store.add_message(project_id, commit, "assistant", "resposta", "openai", "resp_1")

    assert store.last_response_id(project_id, commit, "codex") is None


def test_migrate_database_adds_the_column_to_a_database_created_before_this_feature(
    tmp_path: Path,
) -> None:
    """Bancos de projetos já inicializados não passam por `create_all` de novo."""
    db_path = tmp_path / "state.db"
    engine = create_database_engine(db_path)
    migrate_database(engine)
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE conversation_messages DROP COLUMN provider_response_id")
        )

    migrate_database(engine)  # deve adicionar a coluna de volta sem erro

    store = RepositoryStore(session_factory(engine))
    project_id = store.ensure_project(Project(None, "p", tmp_path, tmp_path, None))
    store.add_message(project_id, "a" * 40, "assistant", "resposta", "openai", "resp_1")

    assert store.last_response_id(project_id, "a" * 40, "openai") == "resp_1"
