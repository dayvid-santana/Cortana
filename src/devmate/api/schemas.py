"""Schemas Pydantic da API HTTP — o contrato exposto a um frontend."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from devmate.domain.models import SourceReference


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class StatusResponse(BaseModel):
    repo: str
    branch: str | None
    head: str
    last_processed: str | None


class SourceReferenceOut(BaseModel):
    path: str
    start_line: int
    end_line: int
    commit_hash: str
    heading: str | None
    label: str

    @classmethod
    def from_domain(cls, reference: SourceReference) -> SourceReferenceOut:
        return cls(
            path=reference.path,
            start_line=reference.start_line,
            end_line=reference.end_line,
            commit_hash=reference.commit_hash,
            heading=reference.heading,
            label=reference.render(),
        )


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    scope: Literal["docs", "code"] = "docs"
    commit: str | None = None
    provider: str | None = None
    model: str | None = None
    files: list[str] | None = None
    full_repo: bool = False
    # "speech" ativa a instrução de concisão do prompt de API para perguntas
    # transcritas por voz; não altera o escopo nem a autorização de código.
    source: Literal["text", "speech"] = "text"


class ChatResponse(BaseModel):
    commit: str
    scope: Literal["docs", "code"]
    provider: str
    model: str | None
    text: str
    sources: list[SourceReferenceOut]


class ErrorResponse(BaseModel):
    detail: str
    code: str
