from __future__ import annotations

from devmate.markdown.narrator import MarkdownNarrator
from devmate.markdown.parser import MarkdownParser


def test_parser_tracks_heading_and_lines() -> None:
    text = "# Título\n\nTexto com [link](https://example.test).\n\n```python\npass\n```\n"
    blocks = MarkdownParser().blocks(text)
    assert blocks[0].kind == "heading"
    assert blocks[1].heading == "Título"
    assert blocks[1].start_line == 3
    assert blocks[2].kind == "code"


def test_narrator_normalizes_links_and_omits_code() -> None:
    segments = MarkdownNarrator().segments(
        "# T\n\nUse [aqui](https://x.test) e `valor`.\n\n```\nsegredo\n```"
    )
    text = " ".join(item.text for item in segments)
    assert "https://" not in text
    assert "valor" in text
    assert "Bloco de código omitido" in text
