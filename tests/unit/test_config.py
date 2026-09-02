from __future__ import annotations

import os
import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from devmate.config import DEFAULT_CONFIG_TOML, AppConfig, load_dotenv
from devmate.constants import ASSISTANT_NAME
from devmate.domain.enums import Scope


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


def test_default_scope_is_docs() -> None:
    config = AppConfig.model_validate(tomllib.loads(DEFAULT_CONFIG_TOML))

    assert config.security.default_scope is Scope.DOCS


def test_default_scope_can_be_set_to_code() -> None:
    config = AppConfig.model_validate({"security": {"default_scope": "code"}})

    assert config.security.default_scope is Scope.CODE


def test_voice_help_command_needs_no_document_path() -> None:
    config = AppConfig.model_validate(
        {"voice": {"commands": [{"phrases": ["o que você pode fazer"], "action": "help"}]}}
    )

    command = config.voice.commands[0]
    assert command.action == "help"
    assert command.path is None


def test_load_dotenv_exposes_openai_key_without_overwriting_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text(
        'OPENAI_API_KEY="sk-from-dotenv"\nDEVMATE_PROVIDER=openai\n', encoding="utf-8"
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("DEVMATE_PROVIDER", "mock")

    load_dotenv(tmp_path)

    assert os.environ["OPENAI_API_KEY"] == "sk-from-dotenv"
    assert os.environ["DEVMATE_PROVIDER"] == "mock"
