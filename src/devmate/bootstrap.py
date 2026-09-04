"""Composição explícita de adapters e serviços por execução de CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from devmate.adapters.agents.dev_agent_client import DevAgentClient
from devmate.adapters.filesystem.local_filesystem import LocalFilesystem
from devmate.adapters.git.subprocess_git import SubprocessGit
from devmate.adapters.llm.registry import ProviderRegistry
from devmate.adapters.persistence.database import (
    create_database_engine,
    migrate_database,
    session_factory,
)
from devmate.adapters.persistence.repositories import RepositoryStore
from devmate.adapters.speech.registry import get_speech_input_provider, get_speech_provider
from devmate.application.context_service import ContextService
from devmate.application.conversation_service import ConversationService
from devmate.application.dev_agent_edit_service import DevAgentEditService
from devmate.application.edit_service import EditProposalService
from devmate.application.inspection_conversation_service import InspectionConversationService
from devmate.application.inspection_service import InspectionService
from devmate.application.instance_lock import InstanceLock
from devmate.application.memory_service import MemoryService
from devmate.application.reading_service import ReadingService
from devmate.application.scan_service import ScanService
from devmate.application.voice_service import VoiceCommand, VoiceConversationService
from devmate.config import AppConfig, config_path, database_path, load_config
from devmate.domain.ports import SpeechInputProvider, SpeechProvider
from devmate.errors import CommitNotFoundError, ConfigurationError
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

    def ensure_indexed(self, commit: str | None = None) -> bool:
        """Indexa o commit selecionado se ele ainda não estiver no banco.

        Compartilhado por CLI e API: um commit novo não deveria interromper uma
        pergunta com um erro manual pedindo `devmate scan` — a indexação é local,
        não chama provider nem rede. Retorna ``True`` quando indexou agora.
        """
        try:
            self.context_service().selected_commit(self.project_id, commit)
            return False
        except CommitNotFoundError:
            self.scan_service().scan(self.project_id, commit or "HEAD", False)
            return True

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

    def edit_service(self) -> EditProposalService:
        return EditProposalService(self.inspection_service(), self.filesystem, self.providers)

    def dev_agent_client(self) -> DevAgentClient:
        return DevAgentClient(
            base_url=self.config.edit.dev_agent_url,
            timeout_seconds=self.config.edit.dev_agent_timeout_seconds,
        )

    def dev_agent_edit_service(self) -> DevAgentEditService:
        return DevAgentEditService(self.dev_agent_client(), self.git, self.root)

    def speech_provider(
        self, provider_name: str | None = None, voice: str | None = None
    ) -> SpeechProvider:
        return get_speech_provider(
            provider_name or self.config.speech.provider, self.config, self.root, voice
        )

    def reading_service(
        self, provider_name: str | None = None, voice: str | None = None
    ) -> ReadingService:
        speech = self.speech_provider(provider_name, voice)
        return ReadingService(self.filesystem, self.store, MarkdownNarrator(), speech)

    def speech_input(self) -> SpeechInputProvider:
        return get_speech_input_provider(
            self.config.speech.input_provider,
            self.config,
            self.root / ".devmate" / "models",
        )

    def daemon_lock(self) -> InstanceLock:
        return InstanceLock(self.root / ".devmate" / "daemon.lock")

    def voice_service(
        self, input_provider: SpeechInputProvider | None = None
    ) -> VoiceConversationService:
        output = self.speech_provider()
        input_provider = input_provider or self.speech_input()
        conversation = ConversationService(self.store, self.context_service(), self.providers)
        inspection_conversation = InspectionConversationService(
            self.inspection_service(), self.store, self.providers
        )
        return VoiceConversationService(
            input_provider,
            output,
            conversation,
            inspection_conversation,
            self.reading_service(),
            tuple(
                VoiceCommand(
                    phrases=tuple(command.phrases),
                    action=command.action,
                    path=command.path,
                    section=command.section,
                )
                for command in self.config.voice.commands
            ),
        )


def load_runtime(start: Path) -> Runtime:
    git = SubprocessGit.from_start(start)
    root = git.root
    if not config_path(root).exists() or not database_path(root).exists():
        raise ConfigurationError("DevMate não foi inicializado. Execute `devmate init`.")
    config = load_config(root)
    engine = create_database_engine(database_path(root))
    # ``create_all`` é aditivo: bancos de projetos já registrados recebem as
    # tabelas introduzidas por migrations sem remover nem recriar dados antigos.
    migrate_database(engine)
    store = RepositoryStore(session_factory(engine))
    filesystem = LocalFilesystem(
        root=root,
        max_file_bytes=config.security.max_file_bytes,
        ignored_patterns=config.security.ignored_patterns,
        follow_external_symlinks=config.security.follow_external_symlinks,
    )
    return Runtime(root, config, git, store, filesystem, ProviderRegistry(config))
