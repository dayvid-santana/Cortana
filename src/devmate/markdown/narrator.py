"""Normalização estrutural para uma narração clara e previsível."""

from __future__ import annotations

import re

from devmate.domain.models import NarrationSegment
from devmate.markdown.parser import MarkdownParser


class MarkdownNarrator:
    def __init__(self, parser: MarkdownParser | None = None) -> None:
        self.parser = parser or MarkdownParser()

    def segments(self, text: str, section: str | None = None) -> list[NarrationSegment]:
        source = self.parser.blocks(text)
        result: list[NarrationSegment] = []
        active = section is None
        for block in source:
            if block.kind == "heading":
                active = section is None or block.content.casefold() == section.casefold()
                if active:
                    spoken = f"Seção: {self._normalize(block.content)}."
                else:
                    continue
            elif not active:
                continue
            elif block.kind == "list_item":
                spoken = f"Item: {self._normalize(block.content)}."
            elif block.kind == "code":
                spoken = "Bloco de código omitido da narração."
            else:
                spoken = self._normalize(block.content)
            if spoken:
                result.append(
                    NarrationSegment(
                        ordinal=len(result) + 1,
                        text=spoken,
                        start_line=block.start_line,
                        end_line=block.end_line,
                        heading=block.heading,
                    )
                )
        return result

    @staticmethod
    def _normalize(text: str) -> str:
        normalized = re.sub(r"!?(\[[^\]]+\])\([^)]*\)", r"\1", text)
        normalized = re.sub(r"`([^`]+)`", r"\1", normalized)
        normalized = re.sub(r"[*_~#]", "", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized
