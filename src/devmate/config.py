"""Configuração local, explícita e sem segredos persistidos."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from devmate.constants import (
    CONFIG_DIRECTORY,
    CONFIG_FILENAME,
    DATABASE_FILENAME,
    DEFAULT_MAX_DIFF_CHARS,
    DEFAULT_MAX_FILE_BYTES,
    DEFAULT_PROVIDER,
    DEFAULT_SPEECH_PROVIDER,
)
from devmate.errors import ConfigurationError


class ProviderConfig(BaseModel):
    default: str = DEFAULT_PROVIDER
    model: str | None = None
    openai_base_url: str | None = None


class SecurityConfig(BaseModel):
    max_file_bytes: int = Field(default=DEFAULT_MAX_FILE_BYTES, gt=0)
    max_diff_chars: int = Field(default=DEFAULT_MAX_DIFF_CHARS, gt=0)
    follow_external_symlinks: bool = False
    ignored_patterns: list[str] = Field(
        default_factory=lambda: [
            ".env",
            ".env.*",
            "*.pem",
            "*.key",
            "id_rsa",
            "id_ed25519",
            "credentials*",
            "secrets*",
        ]
    )


class SpeechConfig(BaseModel):
    provider: str = DEFAULT_SPEECH_PROVIDER
    rate: int = Field(default=180, ge=80, le=450)


class LoggingConfig(BaseModel):
    include_content: bool = False


class AppConfig(BaseModel):
    """Configuração persistida em ``.devmate/config.toml``."""

    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    speech: SpeechConfig = Field(default_factory=SpeechConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


DEFAULT_CONFIG_TOML = """# Configuração local do DevMate. Não armazene chaves neste arquivo.\n\n[provider]\ndefault = \"mock\"\n# model = \"\"\n# openai_base_url = \"https://api.exemplo.local/v1\"\n\n[security]\nmax_file_bytes = 512000\nmax_diff_chars = 80000\nfollow_external_symlinks = false\nignored_patterns = [\".env\", \".env.*\", \"*.pem\", \"*.key\", \"id_rsa\", \"id_ed25519\", \"credentials*\", \"secrets*\"]\n\n[speech]\nprovider = \"system\"\nrate = 180\n\n[logging]\ninclude_content = false\n"""


def state_directory(root: Path) -> Path:
    return root / CONFIG_DIRECTORY


def config_path(root: Path) -> Path:
    return state_directory(root) / CONFIG_FILENAME


def database_path(root: Path) -> Path:
    return state_directory(root) / DATABASE_FILENAME


def write_default_config(root: Path) -> Path:
    directory = state_directory(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = config_path(root)
    if not path.exists():
        path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")
    return path


def load_config(root: Path) -> AppConfig:
    """Carrega TOML e aplica variáveis de ambiente não secretas."""
    path = config_path(root)
    raw: dict[str, Any] = {}
    if path.exists():
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigurationError(f"Não foi possível ler {path}: {exc}") from exc
    provider = raw.setdefault("provider", {})
    if os.getenv("DEVMATE_PROVIDER"):
        provider["default"] = os.environ["DEVMATE_PROVIDER"]
    if os.getenv("DEVMATE_MODEL"):
        provider["model"] = os.environ["DEVMATE_MODEL"]
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigurationError(f"Configuração inválida em {path}: {exc}") from exc
