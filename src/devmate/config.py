"""Configuração local, explícita e sem segredos persistidos."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from devmate.constants import (
    ASSISTANT_NAME,
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


DEFAULT_CODEX_SYSTEM_INSTRUCTION = (
    f"Você é a {ASSISTANT_NAME}, uma assistente especialista em engenharia de software "
    "integrada ao DevMate.\n"
    "Sua tarefa é analisar os metadados do Git, documentos e códigos fornecidos no contexto.\n"
    "\n"
    "Diretrizes de resposta:\n"
    "1. Vá além do óbvio e relacione mudanças no código com impactos na documentação "
    "e na arquitetura.\n"
    "2. Responda de forma natural, amigável e concisa, pois a resposta poderá ser "
    "narrada por voz.\n"
    "3. Prefira frases completas e conectivos naturais. Evite listas longas ou "
    "caracteres especiais complexos.\n"
    "4. Baseie-se apenas nos dados fornecidos no contexto. Se não souber algo, admita."
)


class CodexProviderSettings(BaseModel):
    """Comportamento confiável configurado localmente para o provider Codex."""

    model: str | None = None
    system_instruction: str = Field(default=DEFAULT_CODEX_SYSTEM_INSTRUCTION, min_length=1)


class LanguageModelProvidersConfig(BaseModel):
    codex: CodexProviderSettings = Field(default_factory=CodexProviderSettings)


class LanguageModelConfig(BaseModel):
    providers: LanguageModelProvidersConfig = Field(default_factory=LanguageModelProvidersConfig)


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
    input_provider: str = "faster_whisper"
    input_model: str = "base"
    input_language: str = "pt-BR"
    input_duration_seconds: int = Field(default=10, ge=1, le=60)


class DaemonConfig(BaseModel):
    """Processo residente acionado por atalho global."""

    hotkey: str = Field(default="ctrl+alt+d", min_length=1)
    preload_model: bool = True


class LoggingConfig(BaseModel):
    include_content: bool = False


class AppConfig(BaseModel):
    """Configuração persistida em ``.devmate/config.toml``."""

    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    language_model: LanguageModelConfig = Field(default_factory=LanguageModelConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    speech: SpeechConfig = Field(default_factory=SpeechConfig)
    daemon: DaemonConfig = Field(default_factory=DaemonConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


DEFAULT_CONFIG_TOML = (
    "# Configuração local do DevMate. Não armazene chaves neste arquivo.\n\n"
    "[provider]\n"
    'default = "mock"\n'
    '# model = ""\n'
    '# openai_base_url = "https://api.exemplo.local/v1"\n\n'
    "[language_model.providers.codex]\n"
    'system_instruction = """\n'
    f"Você é a {ASSISTANT_NAME}, uma assistente especialista em engenharia de software "
    "integrada ao DevMate.\n"
    "Sua tarefa é analisar os metadados do Git, documentos e códigos fornecidos no contexto.\n\n"
    "Diretrizes de resposta:\n"
    "1. Análise profunda: vá além do óbvio e relacione mudanças no código com impactos na "
    "documentação e na arquitetura.\n"
    "2. Responda de forma natural, amigável e concisa, pois a resposta poderá ser narrada por "
    "voz.\n"
    "3. Prefira frases completas e conectivos naturais. Evite listas longas ou caracteres "
    "especiais complexos.\n"
    "4. Baseie-se apenas nos dados fornecidos no contexto. Se não souber algo, admita.\n"
    '"""\n\n'
    "[security]\n"
    "max_file_bytes = 512000\n"
    "max_diff_chars = 80000\n"
    "follow_external_symlinks = false\n"
    'ignored_patterns = [".env", ".env.*", "*.pem", "*.key", "id_rsa", '
    '"id_ed25519", "credentials*", "secrets*"]\n\n'
    "[speech]\n"
    'provider = "system"\n'
    "rate = 180\n\n"
    'input_provider = "faster_whisper"\n'
    'input_model = "base"\n'
    'input_language = "pt-BR"\n'
    "input_duration_seconds = 10\n\n"
    "[daemon]\n"
    'hotkey = "ctrl+alt+d"\n'
    "preload_model = true\n\n"
    "[logging]\n"
    "include_content = false\n"
)


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
