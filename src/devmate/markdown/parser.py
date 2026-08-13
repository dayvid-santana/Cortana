"""Parser Markdown baseado em markdown-it-py, não em regex estrutural."""

from __future__ import annotations

from dataclasses import dataclass

from markdown_it import MarkdownIt


@dataclass(frozen=True, slots=True)
class MarkdownBlock:
    kind: str
    content: str
    start_line: int
    end_line: int
    heading: str | None


class MarkdownParser:
    def __init__(self) -> None:
        self._parser = MarkdownIt("commonmark", {"html": False})

    def blocks(self, text: str) -> list[MarkdownBlock]:
        tokens = self._parser.parse(text)
        blocks: list[MarkdownBlock] = []
        current_heading: str | None = None
        for index, token in enumerate(tokens):
            if token.type == "heading_open":
                inline = tokens[index + 1] if index + 1 < len(tokens) else None
                if inline and inline.type == "inline":
                    current_heading = inline.content.strip()
            if token.type not in {"inline", "fence", "code_block"} or not token.content.strip():
                continue
            previous = tokens[index - 1] if index else None
            if token.type == "inline" and previous and previous.type == "heading_open":
                kind = "heading"
            elif token.type == "inline" and previous and previous.type == "paragraph_open":
                kind = "paragraph"
            elif token.type == "inline" and previous and previous.type == "list_item_open":
                kind = "list_item"
            elif token.type in {"fence", "code_block"}:
                kind = "code"
            else:
                continue
            start, end_exclusive = token.map or [0, 1]
            blocks.append(
                MarkdownBlock(
                    kind=kind,
                    content=token.content.strip(),
                    start_line=start + 1,
                    end_line=max(start + 1, end_exclusive),
                    heading=current_heading,
                )
            )
        return blocks

    def heading_at(self, text: str, line_number: int) -> str | None:
        heading: str | None = None
        for block in self.blocks(text):
            if block.kind == "heading" and block.start_line <= line_number:
                heading = block.content
            if block.start_line > line_number:
                break
        return heading
