"""Erros de domínio e seus códigos de saída."""

from __future__ import annotations


class DevMateError(Exception):
    """Erro base apresentado de modo seguro pela CLI."""

    exit_code = 2


class ConfigurationError(DevMateError):
    exit_code = 2


class RepositoryNotFoundError(DevMateError):
    exit_code = 3


class GitCommandError(DevMateError):
    exit_code = 3


class CommitNotFoundError(DevMateError):
    exit_code = 3


class UnsafePathError(DevMateError):
    exit_code = 7


class FileTooLargeError(DevMateError):
    exit_code = 7


class UnsupportedFileError(DevMateError):
    exit_code = 7


class DatabaseError(DevMateError):
    exit_code = 4


class ProviderNotFoundError(DevMateError):
    exit_code = 5


class ProviderUnavailableError(DevMateError):
    exit_code = 5


class ProviderAuthenticationError(DevMateError):
    exit_code = 5


class ProviderResponseError(DevMateError):
    exit_code = 5


class SpeechProviderUnavailableError(DevMateError):
    exit_code = 6


class SpeechRecognitionUnavailableError(DevMateError):
    exit_code = 6


class HotkeyUnavailableError(DevMateError):
    exit_code = 6


class AudioPlaybackError(DevMateError):
    exit_code = 6


class UnknownVoiceError(DevMateError):
    exit_code = 6


class SpeechSynthesisError(DevMateError):
    """Falha ao gerar o áudio: rede, rate limit, timeout ou resposta vazia."""

    exit_code = 6


class DaemonAlreadyRunningError(DevMateError):
    exit_code = 8


class ReadingSessionStaleError(DevMateError):
    exit_code = 7


class ContextLimitError(DevMateError):
    exit_code = 5


class DevAgentUnavailableError(DevMateError):
    """O servidor do dev-agent (127.0.0.1:8765) não respondeu ou não está rodando."""

    exit_code = 9


class DevAgentJobFailedError(DevMateError):
    """O job do dev-agent terminou em falha, cancelado ou bloqueado."""

    exit_code = 9
