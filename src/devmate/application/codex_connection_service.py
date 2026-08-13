"""Conexão com a conta Codex (login/status/logout), separada da inferência.

A autenticação do SDK ``openai-codex`` é da máquina, não do projeto: uma vez
conectada, a mesma sessão vale para qualquer repositório. Este serviço só cuida
dessa conexão; ``CodexProvider`` continua responsável por completar perguntas.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from devmate.errors import ProviderAuthenticationError, ProviderUnavailableError

LoginMethod = Literal["device", "browser", "api_key"]


@dataclass(frozen=True, slots=True)
class CodexAccount:
    connected: bool
    method: str | None = None  # "chatgpt", "apiKey" ou "amazonBedrock"
    email: str | None = None
    plan: str | None = None


@dataclass(frozen=True, slots=True)
class CodexLoginPrompt:
    """O que mostrar à pessoa usuária para concluir o login em outro lugar."""

    verification_url: str | None
    user_code: str | None


class CodexConnectionService:
    def __init__(self, client_factory: Callable[[], Any] | None = None) -> None:
        self._client_factory = client_factory

    def available(self) -> tuple[bool, str | None]:
        if self._client_factory is not None:
            return True, None
        try:
            import openai_codex  # noqa: F401
        except ImportError:
            return False, "Pacote openai-codex não está instalado."
        return True, None

    def _client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory()
        try:
            from openai_codex import Codex
        except ImportError as exc:
            raise ProviderUnavailableError("Pacote openai-codex não está instalado.") from exc
        return Codex()

    def status(self) -> CodexAccount:
        available, reason = self.available()
        if not available:
            raise ProviderUnavailableError(reason or "Provider Codex indisponível.")
        try:
            with self._client() as codex:
                response = codex.account()
        except Exception as exc:
            raise ProviderUnavailableError(
                f"Não foi possível consultar a conta Codex: {exc}"
            ) from exc
        return self._read_account(response)

    def connect(
        self,
        method: LoginMethod = "device",
        api_key: str | None = None,
        on_prompt: Callable[[CodexLoginPrompt], None] | None = None,
    ) -> CodexAccount:
        available, reason = self.available()
        if not available:
            raise ProviderUnavailableError(reason or "Provider Codex indisponível.")
        if method == "api_key" and not api_key:
            raise ProviderAuthenticationError("Informe uma chave de API para o login por api_key.")
        verified_api_key = api_key or ""
        try:
            with self._client() as codex:
                if method == "api_key":
                    codex.login_api_key(verified_api_key)
                elif method == "browser":
                    handle = codex.login_chatgpt()
                    if on_prompt is not None:
                        prompt = CodexLoginPrompt(verification_url=handle.auth_url, user_code=None)
                        on_prompt(prompt)
                    handle.wait()
                else:
                    handle = codex.login_chatgpt_device_code()
                    if on_prompt is not None:
                        on_prompt(
                            CodexLoginPrompt(
                                verification_url=handle.verification_url,
                                user_code=handle.user_code,
                            )
                        )
                    handle.wait()
                response = codex.account()
        except (ProviderAuthenticationError, ProviderUnavailableError):
            raise
        except Exception as exc:
            raise ProviderAuthenticationError(f"Falha ao conectar com o Codex: {exc}") from exc
        account = self._read_account(response)
        if not account.connected:
            raise ProviderAuthenticationError(
                "O login não foi concluído. Tente novamente ou verifique a conta usada."
            )
        return account

    def disconnect(self) -> None:
        available, reason = self.available()
        if not available:
            raise ProviderUnavailableError(reason or "Provider Codex indisponível.")
        try:
            with self._client() as codex:
                codex.logout()
        except Exception as exc:
            raise ProviderUnavailableError(f"Falha ao encerrar a sessão Codex: {exc}") from exc

    @staticmethod
    def _read_account(response: Any) -> CodexAccount:
        account = getattr(response, "account", None)
        if account is None:
            return CodexAccount(connected=False)
        root = getattr(account, "root", account)
        kind = getattr(root, "type", None)
        email = getattr(root, "email", None)
        plan_type = getattr(root, "plan_type", None)
        plan = getattr(plan_type, "value", plan_type) if plan_type is not None else None
        return CodexAccount(connected=True, method=kind, email=email, plan=plan)
