"""Inicialização síncrona do banco local SQLite."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from devmate.adapters.persistence.orm_models import Base
from devmate.errors import DatabaseError


def create_database_engine(path: Path) -> Engine:
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path.as_posix()}", future=True)


def migrate_database(engine: Engine) -> None:
    """Cria o schema atual e o índice FTS opcional de maneira idempotente."""
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS document_search "
                    "USING fts5(path, content, commit_hash UNINDEXED)"
                )
            )
    except Exception as exc:  # SQLAlchemy expõe subclasses por dialeto.
        raise DatabaseError(f"Não foi possível inicializar o banco: {exc}") from exc


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
