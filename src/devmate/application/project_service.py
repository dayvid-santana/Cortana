"""Inicialização local de um projeto DevMate."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from devmate.adapters.git.subprocess_git import SubprocessGit
from devmate.adapters.persistence.database import (
    create_database_engine,
    migrate_database,
    session_factory,
)
from devmate.adapters.persistence.repositories import RepositoryStore
from devmate.config import AppConfig, database_path, load_config, write_default_config
from devmate.domain.models import Project


@dataclass(frozen=True, slots=True)
class InitializedProject:
    root: Path
    branch: str | None
    config_path: Path
    database_path: Path
    config: AppConfig
    project_id: int


def initialize_project(start: Path) -> InitializedProject:
    git = SubprocessGit.from_start(start)
    root = git.root
    config_file = write_default_config(root)
    config = load_config(root)
    database_file = database_path(root)
    engine = create_database_engine(database_file)
    migrate_database(engine)
    store = RepositoryStore(session_factory(engine))
    project_id = store.ensure_project(
        Project(
            id=None,
            name=root.name,
            root_path=root,
            git_common_dir=git.common_dir(),
            default_branch=git.current_branch(),
        )
    )
    return InitializedProject(
        root=root,
        branch=git.current_branch(),
        config_path=config_file,
        database_path=database_file,
        config=config,
        project_id=project_id,
    )
