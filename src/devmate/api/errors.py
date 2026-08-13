"""Tradução de erros de domínio em respostas HTTP, sem vazar traceback."""

from __future__ import annotations

from devmate.errors import (
    CommitNotFoundError,
    ConfigurationError,
    ContextLimitError,
    DatabaseError,
    DevMateError,
    FileTooLargeError,
    GitCommandError,
    ProviderAuthenticationError,
    ProviderNotFoundError,
    ProviderResponseError,
    ProviderUnavailableError,
    RepositoryNotFoundError,
    UnsafePathError,
    UnsupportedFileError,
)

DEFAULT_ERROR_STATUS = 400

# Checada na ordem: a primeira subclasse compatível decide o status HTTP.
_STATUS_BY_ERROR: tuple[tuple[type[DevMateError], int], ...] = (
    (RepositoryNotFoundError, 404),
    (CommitNotFoundError, 404),
    (ProviderNotFoundError, 404),
    (ConfigurationError, 409),
    (GitCommandError, 502),
    (ProviderResponseError, 502),
    (UnsafePathError, 400),
    (UnsupportedFileError, 415),
    (FileTooLargeError, 413),
    (ContextLimitError, 413),
    (ProviderAuthenticationError, 401),
    (ProviderUnavailableError, 503),
    (DatabaseError, 500),
)


def status_for(exc: DevMateError) -> int:
    for error_type, status in _STATUS_BY_ERROR:
        if isinstance(exc, error_type):
            return status
    return DEFAULT_ERROR_STATUS
