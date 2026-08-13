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


class DaemonAlreadyRunningError(DevMateError):
    exit_code = 8


class ReadingSessionStaleError(DevMateError):
    exit_code = 7


class ContextLimitError(DevMateError):
    exit_code = 5
