"""Enumerações do domínio."""

from enum import StrEnum


class ChangeStatus(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
    COPIED = "copied"


class Scope(StrEnum):
    DOCS = "docs"
    CODE = "code"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REVOKED = "revoked"
    CANDIDATE = "candidate"


class Explicitness(StrEnum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    USER_CONFIRMED = "user_confirmed"
