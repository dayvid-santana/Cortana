"""Registro explícito de providers de LLM."""

from __future__ import annotations

from devmate.adapters.llm.codex_provider import CodexProvider
from devmate.adapters.llm.compatible_provider import OpenAICompatibleProvider
from devmate.adapters.llm.mock_provider import MockProvider
from devmate.adapters.llm.openai_provider import OpenAIProvider
from devmate.config import AppConfig
from devmate.domain.ports import LanguageModelProvider
from devmate.errors import ProviderNotFoundError


class ProviderRegistry:
    def __init__(self, config: AppConfig) -> None:
        self._providers: dict[str, LanguageModelProvider] = {
            "mock": MockProvider(),
            "codex": CodexProvider(
                config.language_model.providers.codex.model or config.provider.model,
                config.language_model.providers.codex.system_instruction,
            ),
            "openai": OpenAIProvider(config.provider.model),
            "openai_compatible": OpenAICompatibleProvider(
                config.provider.model, config.provider.openai_base_url
            ),
        }

    def get(self, name: str) -> LanguageModelProvider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise ProviderNotFoundError(f"Provider desconhecido: {name}") from exc

    def entries(self) -> list[tuple[str, bool, str | None]]:
        return [(name, *provider.available()) for name, provider in self._providers.items()]
