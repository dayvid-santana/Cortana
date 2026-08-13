from __future__ import annotations

import tomllib

import pytest
from pydantic import ValidationError

from devmate.config import DEFAULT_CONFIG_TOML, AppConfig
from devmate.constants import ASSISTANT_NAME


def test_default_config_exposes_the_assistant_instruction_for_codex() -> None:
    config = AppConfig.model_validate(tomllib.loads(DEFAULT_CONFIG_TOML))

    assert f"Você é a {ASSISTANT_NAME}" in config.language_model.providers.codex.system_instruction
    assert "narrada por voz" in config.language_model.providers.codex.system_instruction


def test_codex_system_instruction_can_be_overridden() -> None:
    config = AppConfig.model_validate(
        {
            "language_model": {
                "providers": {"codex": {"system_instruction": "Responda em uma frase."}}
            }
        }
    )

    assert config.language_model.providers.codex.system_instruction == "Responda em uma frase."


def test_voice_commands_are_configurable_for_markdown_reading() -> None:
    config = AppConfig.model_validate(
        {
            "voice": {
                "commands": [
                    {
                        "phrases": ["leia a arquitetura", "explique a arquitetura"],
                        "action": "read",
                        "path": "docs/architecture.md",
                        "section": "Segurança",
                    }
                ]
            }
        }
    )

    command = config.voice.commands[0]
    assert command.phrases == ["leia a arquitetura", "explique a arquitetura"]
    assert command.path == "docs/architecture.md"
    assert command.section == "Segurança"


def test_voice_commands_reject_non_markdown_targets() -> None:
    with pytest.raises(ValidationError, match="Markdown"):
        AppConfig.model_validate(
            {"voice": {"commands": [{"phrases": ["leia o código"], "path": "src/app.py"}]}}
        )
