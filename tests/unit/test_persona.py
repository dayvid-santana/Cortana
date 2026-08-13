from __future__ import annotations

from devmate.config import DEFAULT_CODEX_SYSTEM_INSTRUCTION, DEFAULT_CONFIG_TOML
from devmate.constants import ASSISTANT_NAME
from devmate.prompts.code_inspection import CODE_INSPECTION_SYSTEM
from devmate.prompts.documentation_chat import DOCUMENTATION_CHAT_SYSTEM


def test_assistant_is_named_diana() -> None:
    assert ASSISTANT_NAME == "Diana"


def test_every_persona_surface_uses_the_central_name() -> None:
    surfaces = (
        DOCUMENTATION_CHAT_SYSTEM,
        CODE_INSPECTION_SYSTEM,
        DEFAULT_CODEX_SYSTEM_INSTRUCTION,
        DEFAULT_CONFIG_TOML,
    )
    for surface in surfaces:
        assert ASSISTANT_NAME in surface
        assert "Cortana" not in surface
