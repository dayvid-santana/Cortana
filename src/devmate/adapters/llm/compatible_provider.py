"""Provider para APIs explicitamente configuradas como OpenAI-compatible."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from devmate.adapters.llm.openai_provider import OpenAIProvider


class OpenAICompatibleProvider(OpenAIProvider):
    name = "openai_compatible"

    def __init__(
        self,
        model: str | None,
        base_url: str | None,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__(model=model, client_factory=client_factory, base_url=base_url)

    def available(self) -> tuple[bool, str | None]:
        if not self.base_url and self._client_factory is None:
            return False, "provider.openai_base_url não está configurada."
        return super().available()
