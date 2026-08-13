from __future__ import annotations

import tomllib

from devmate.config import DEFAULT_CONFIG_TOML, AppConfig


def test_default_config_exposes_cortana_instruction_for_codex() -> None:
    config = AppConfig.model_validate(tomllib.loads(DEFAULT_CONFIG_TOML))

    assert "Você é a Cortana" in config.language_model.providers.codex.system_instruction
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
