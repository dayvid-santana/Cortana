"""Composição explícita de adapters e serviços por execução de CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from devmate.adapters.filesystem.local_filesystem import LocalFilesystem
from devmate.adapters.git.subprocess_git import SubprocessGit
from devmate.adapters.llm.registry import ProviderRegistry
from devmate.adapters.persistence.database import create_database_engine, session_factory
from devmate.adapters.persistence.repositories import RepositoryStore
from devmate.adapters.speech.registry import get_speech_input_provider, get_speech_provider
from devmate.application.context_service import ContextService
from devmate.application.conversation_service import ConversationService
from devmate.application.inspection_conversation_service import InspectionConversationService
from devmate.application.inspection_service import InspectionService
from devmate.application.memory_service import MemoryService
from devmate.application.reading_service import ReadingService
from devmate.application.scan_service import ScanService
from devmate.application.voice_service import VoiceConversationService
from devmate.config import AppConfig, config_path, database_path, load_config
from devmate.errors import ConfigurationError
from devmate.markdown.narrator import MarkdownNarrator


@dataclass(frozen=True, slots=True)
class Runtime:
    root: Path
    config: AppConfig
    git: SubprocessGit
    store: RepositoryStore
    filesystem: LocalFilesystem
    providers: ProviderRegistry

    @property
    def project_id(self) -> int:
        value = self.store.project_id(self.root)
        if value is None:
            raise ConfigurationError("DevMate não foi inicializado. Execute `devmate init`.")
        return value

    def scan_service(self) -> ScanService:
        return ScanService(
            self.git,
            self.store,
            MemoryService(self.git, self.store),
            self.config.security.max_diff_chars,
        )

    def context_service(self) -> ContextService:
        return ContextService(self.git, self.store)

    def inspection_service(self) -> InspectionService:
        return InspectionService(self.filesystem, self.context_service(), self.store)

    def reading_service(self) -> ReadingService:
        speech = get_speech_provider(self.config.speech.provider, self.config)
        return ReadingService(self.filesystem, self.store, MarkdownNarrator(), speech)

    def voice_service(self) -> VoiceConversationService:
        output = get_speech_provider(self.config.speech.provider, self.config)
        input_provider = get_speech_input_provider(
            self.config.speech.input_provider,
            self.config,
            self.root / ".devmate" / "models",
        )
        conversation = ConversationService(self.store, self.context_service(), self.providers)
        inspection_conversation = InspectionConversationService(
            self.inspection_service(), self.store, self.providers
        )
        return VoiceConversationService(
            input_provider, output, conversation, inspection_conversation
        )


def load_runtime(start: Path) -> Runtime:
    git = SubprocessGit.from_start(start)
    root = git.root
    if not config_path(root).exists() or not database_path(root).exists():
        raise ConfigurationError("DevMate não foi inicializado. Execute `devmate init`.")
    config = load_config(root)
    store = RepositoryStore(session_factory(create_database_engine(database_path(root))))
    filesystem = LocalFilesystem(
        root=root,
        max_file_bytes=config.security.max_file_bytes,
        ignored_patterns=config.security.ignored_patterns,
        follow_external_symlinks=config.security.follow_external_symlinks,
    )
    return Runtime(root, config, git, store, filesystem, ProviderRegistry(config))
