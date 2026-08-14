"""Configuração local, explícita e sem segredos persistidos."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

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
from devmate.domain.enums import Scope
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
    # "docs" (padrão) ou "code": quando "code", ask/inspect/listen/talk tratam código como
    # escopo autorizado sem exigir --scope code/--full-repo a cada chamada. Opt-in por projeto,
    # não muda o bloqueio de segredos/paths nem o limite de 200 arquivos. Ver `devmate config
    # full-access` e docs/security.md.
    default_scope: Scope = Scope.DOCS
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


class OpenAISpeechProviderConfig(BaseModel):
    """Comportamento do provider de fala remoto; nunca guarda a credencial."""

    model: str = "gpt-4o-mini-tts"
    api_key_env: str = Field(default="OPENAI_API_KEY", min_length=1)
    response_format: Literal["mp3", "opus", "aac", "flac", "wav", "pcm"] = "mp3"


class SpeechProvidersConfig(BaseModel):
    openai: OpenAISpeechProviderConfig = Field(default_factory=OpenAISpeechProviderConfig)


class SpeechConfig(BaseModel):
    provider: str = DEFAULT_SPEECH_PROVIDER
    rate: int = Field(default=180, ge=80, le=450)
    # Para "system", um trecho do nome da voz local. Para "openai", o id da voz
    # (ex.: "marin"). Vazio mantém a voz padrão do provider selecionado.
    voice: str | None = None
    # Preset de estilo (ex.: "technical_calm"); só tem efeito em modelos que
    # suportam instruções de leitura. Providers sem suporte o ignoram.
    style: str | None = None
    providers: SpeechProvidersConfig = Field(default_factory=SpeechProvidersConfig)
    input_provider: str = "faster_whisper"
    input_model: str = "base"
    input_language: str = "pt-BR"
    input_duration_seconds: int = Field(default=10, ge=1, le=60)


class VoiceCommandConfig(BaseModel):
    """Ordem local de voz que não precisa consultar um provider de linguagem."""

    phrases: list[str] = Field(min_length=1)
    action: Literal["read", "help"] = "read"
    path: str | None = None
    section: str | None = None

    @field_validator("phrases")
    @classmethod
    def validate_phrases(cls, phrases: list[str]) -> list[str]:
        if any(not phrase.strip() for phrase in phrases):
            raise ValueError("As frases de um comando de voz não podem estar vazias.")
        return phrases

    @field_validator("path")
    @classmethod
    def validate_markdown_path(cls, path: str | None) -> str | None:
        if path is None:
            return None
        if not path.casefold().endswith(".md"):
            raise ValueError("Comandos de leitura por voz aceitam apenas arquivos Markdown (.md).")
        return path

    @model_validator(mode="after")
    def validate_action_arguments(self) -> Self:
        if self.action == "read" and self.path is None:
            raise ValueError("A ação read exige o caminho de um arquivo Markdown.")
        if self.action == "help" and (self.path is not None or self.section is not None):
            raise ValueError("A ação help não aceita path nem section.")
        return self


def _default_voice_commands() -> list[VoiceCommandConfig]:
    return [
        VoiceCommandConfig(
            phrases=["leia o documento", "ler o documento"],
            path="README.md",
        ),
        VoiceCommandConfig(
            phrases=["o que você pode fazer", "o que voce pode fazer", "ajuda"],
            action="help",
        ),
    ]


class VoiceConfig(BaseModel):
    """Comandos locais de voz; não chamam providers de linguagem."""

    commands: list[VoiceCommandConfig] = Field(default_factory=_default_voice_commands)


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
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
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
    '# "code" faz ask/inspect/listen/talk tratarem código como escopo autorizado sem exigir\n'
    "# --scope code/--full-repo a cada chamada. Não muda o bloqueio de segredos/paths.\n"
    "# Prefira `devmate config full-access --enable` a editar esta linha à mão.\n"
    '# default_scope = "code"\n'
    'ignored_patterns = [".env", ".env.*", "*.pem", "*.key", "id_rsa", '
    '"id_ed25519", "credentials*", "secrets*"]\n\n'
    "[speech]\n"
    'provider = "system"\n'
    "rate = 180\n"
    '# Para provider = "system", um trecho do nome (ex.: "Maria").\n'
    '# Para provider = "openai", o id da voz (ex.: "marin"). Use `devmate voices list`.\n'
    '# voice = "marin"\n'
    '# style = "technical_calm"\n\n'
    "[speech.providers.openai]\n"
    'model = "gpt-4o-mini-tts"\n'
    "# Nome da variável de ambiente com a credencial; a chave nunca fica aqui.\n"
    'api_key_env = "OPENAI_API_KEY"\n'
    'response_format = "mp3"\n\n'
    'input_provider = "faster_whisper"\n'
    'input_model = "base"\n'
    'input_language = "pt-BR"\n'
    "input_duration_seconds = 10\n\n"
    "# Acrescente novos blocos para criar comandos de voz locais.\n"
    "[[voice.commands]]\n"
    'phrases = ["leia o documento", "ler o documento"]\n'
    'action = "read"\n'
    'path = "README.md"\n'
    '# section = "Segurança"\n\n'
    "[[voice.commands]]\n"
    'phrases = ["o que você pode fazer", "ajuda"]\n'
    'action = "help"\n\n'
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
