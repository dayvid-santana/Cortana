"""Segmentação de um documento para uma sessão de leitura em voz alta via HTTP.

Independente de ``ReadingService`` (usado pela CLI): a CLI fala um segmento por
vez e mantém um checkpoint por arquivo; aqui cada sessão é identificada por id,
cobre um modo (texto literal, narrado ou explicado) e cada segmento gera áudio
sob demanda via um endpoint próprio, então a divisão de segmentos precisa ficar
disponível sem falar nada.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from devmate.domain.enums import Scope
from devmate.domain.models import ContextChunk, LLMRequest, SourceReference
from devmate.domain.ports import LanguageModelProvider
from devmate.markdown.narrator import MarkdownNarrator
from devmate.markdown.parser import MarkdownParser

ReadingMode = Literal["verbatim", "narrate", "explain"]

EXPLAIN_SYSTEM_INSTRUCTIONS = (
    "Você explica trechos de documentação técnica em linguagem simples e direta, "
    "em até três frases, para alguém ouvir em voz alta. Baseie-se somente no "
    "trecho fornecido; não invente informação além dele."
)

_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True, slots=True)
class ReadingSegment:
    index: int
    text: str
    start_line: int
    end_line: int
    heading: str | None = None


def raw_segments(text: str, skip_code: bool) -> list[ReadingSegment]:
    """Segmentos com o texto literal do Markdown, por bloco (sem narração)."""
    blocks = MarkdownParser().blocks(text)
    result: list[ReadingSegment] = []
    for block in blocks:
        if block.kind == "code" and skip_code:
            continue
        result.append(
            ReadingSegment(
                index=len(result),
                text=block.content,
                start_line=block.start_line,
                end_line=block.end_line,
                heading=block.heading,
            )
        )
    return result


def narrated_segments(text: str, skip_code: bool) -> list[ReadingSegment]:
    """Segmentos com a mesma normalização que ``devmate read`` já narra localmente."""
    return [
        ReadingSegment(
            index=segment.ordinal - 1,
            text=segment.text,
            start_line=segment.start_line,
            end_line=segment.end_line,
            heading=segment.heading,
        )
        for segment in MarkdownNarrator().segments(text, skip_code=skip_code)
    ]


def changed_line_ranges(diff_text: str) -> list[tuple[int, int]]:
    """Intervalos de linha (no arquivo novo) tocados por cada hunk do diff unificado."""
    ranges: list[tuple[int, int]] = []
    for line in diff_text.splitlines():
        match = _HUNK_HEADER.match(line)
        if not match:
            continue
        start = int(match.group(1))
        length = int(match.group(2) or "1")
        ranges.append((start, start + max(length, 1) - 1))
    return ranges


def _renumber(segments: list[ReadingSegment]) -> list[ReadingSegment]:
    return [
        ReadingSegment(index, segment.text, segment.start_line, segment.end_line, segment.heading)
        for index, segment in enumerate(segments)
    ]


def filter_by_line_range(
    segments: list[ReadingSegment], start_line: int | None, end_line: int | None
) -> list[ReadingSegment]:
    if start_line is None and end_line is None:
        return segments
    lo = start_line if start_line is not None else 1
    hi = end_line if end_line is not None else max((s.end_line for s in segments), default=lo)
    return _renumber([s for s in segments if s.end_line >= lo and s.start_line <= hi])


def filter_by_ranges(
    segments: list[ReadingSegment], ranges: list[tuple[int, int]]
) -> list[ReadingSegment]:
    if not ranges:
        return []
    kept = [
        s for s in segments if any(s.start_line <= hi and s.end_line >= lo for lo, hi in ranges)
    ]
    return _renumber(kept)


def explain_segment(
    segment: ReadingSegment,
    provider: LanguageModelProvider,
    file_path: str,
    commit_hash: str,
) -> ReadingSegment:
    chunk = ContextChunk(
        text=segment.text,
        reference=SourceReference(
            path=file_path,
            start_line=segment.start_line,
            end_line=segment.end_line,
            commit_hash=commit_hash,
            heading=segment.heading,
        ),
        trusted=False,
    )
    request = LLMRequest(
        task="document_explanation",
        question=(
            "Explique o trecho a seguir em linguagem simples e direta, "
            "em até três frases, para alguém ouvir em voz alta."
        ),
        scope=Scope.DOCS,
        chunks=(chunk,),
        system_instructions=EXPLAIN_SYSTEM_INSTRUCTIONS,
    )
    response = provider.complete(request)
    explained = response.text.strip()
    return ReadingSegment(
        segment.index,
        explained or segment.text,
        segment.start_line,
        segment.end_line,
        segment.heading,
    )


def build_segments(
    text: str,
    mode: ReadingMode,
    skip_code: bool,
    start_line: int | None,
    end_line: int | None,
    explain_provider: LanguageModelProvider | None,
    file_path: str,
    commit_hash: str,
) -> list[ReadingSegment]:
    segments = (
        raw_segments(text, skip_code) if mode == "verbatim" else narrated_segments(text, skip_code)
    )
    segments = filter_by_line_range(segments, start_line, end_line)
    if mode == "explain":
        if explain_provider is None:
            raise ValueError("explain_provider é obrigatório quando mode='explain'.")
        segments = [
            explain_segment(segment, explain_provider, file_path, commit_hash)
            for segment in segments
        ]
    return segments
