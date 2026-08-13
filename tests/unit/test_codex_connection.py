from __future__ import annotations

from typing import Any

import pytest

from devmate.application.codex_connection_service import (
    CodexConnectionService,
    CodexLoginPrompt,
)
from devmate.errors import ProviderAuthenticationError


class FakePlanType:
    def __init__(self, value: str) -> None:
        self.value = value


class FakeAccountRoot:
    def __init__(self, kind: str, email: str | None = None, plan: str | None = None) -> None:
        self.type = kind
        self.email = email
        self.plan_type = FakePlanType(plan) if plan else None


class FakeAccount:
    def __init__(self, root: FakeAccountRoot) -> None:
        self.root = root


class FakeAccountResponse:
    def __init__(self, account: FakeAccount | None) -> None:
        self.account = account


class FakeDeviceHandle:
    def __init__(self, verification_url: str, user_code: str) -> None:
        self.verification_url = verification_url
        self.user_code = user_code
        self.waited = False

    def wait(self) -> Any:
        self.waited = True
        return object()


class FakeBrowserHandle:
    def __init__(self, auth_url: str) -> None:
        self.auth_url = auth_url
        self.waited = False

    def wait(self) -> Any:
        self.waited = True
        return object()


class FakeCodexClient:
    def __init__(
        self, response_after_login: FakeAccountResponse, initial: FakeAccountResponse
    ) -> None:
        self.response_after_login = response_after_login
        self.current = initial
        self.logged_out = False
        self.api_key_used: str | None = None
        self.device_handle: FakeDeviceHandle | None = None
        self.browser_handle: FakeBrowserHandle | None = None

    def __enter__(self) -> FakeCodexClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def account(self) -> FakeAccountResponse:
        return self.current

    def login_chatgpt_device_code(self) -> FakeDeviceHandle:
        self.device_handle = FakeDeviceHandle("https://example.test/device", "ABCD-1234")
        self.current = self.response_after_login
        return self.device_handle

    def login_chatgpt(self) -> FakeBrowserHandle:
        self.browser_handle = FakeBrowserHandle("https://example.test/auth")
        self.current = self.response_after_login
        return self.browser_handle

    def login_api_key(self, api_key: str) -> None:
        self.api_key_used = api_key
        self.current = self.response_after_login

    def logout(self) -> None:
        self.logged_out = True
        self.current = FakeAccountResponse(None)


def connected_response(email: str = "dev@example.test", plan: str = "pro") -> FakeAccountResponse:
    return FakeAccountResponse(FakeAccount(FakeAccountRoot("chatgpt", email=email, plan=plan)))


def make_service(client: FakeCodexClient) -> CodexConnectionService:
    return CodexConnectionService(client_factory=lambda: client)


def test_status_reports_disconnected_when_no_account() -> None:
    client = FakeCodexClient(connected_response(), initial=FakeAccountResponse(None))
    service = make_service(client)

    account = service.status()

    assert account.connected is False


def test_status_reports_chatgpt_account_details() -> None:
    client = FakeCodexClient(connected_response(), initial=connected_response("me@x.test", "team"))
    service = make_service(client)

    account = service.status()

    assert account.connected is True
    assert account.method == "chatgpt"
    assert account.email == "me@x.test"
    assert account.plan == "team"


def test_connect_with_device_code_prompts_url_and_code_then_confirms() -> None:
    client = FakeCodexClient(connected_response(), initial=FakeAccountResponse(None))
    service = make_service(client)
    prompts: list[CodexLoginPrompt] = []

    account = service.connect("device", on_prompt=prompts.append)

    assert account.connected is True
    assert client.device_handle is not None
    assert client.device_handle.waited is True
    assert prompts == [
        CodexLoginPrompt(verification_url="https://example.test/device", user_code="ABCD-1234")
    ]


def test_connect_with_browser_prompts_only_the_url() -> None:
    client = FakeCodexClient(connected_response(), initial=FakeAccountResponse(None))
    service = make_service(client)
    prompts: list[CodexLoginPrompt] = []

    service.connect("browser", on_prompt=prompts.append)

    assert prompts == [
        CodexLoginPrompt(verification_url="https://example.test/auth", user_code=None)
    ]


def test_connect_with_api_key_uses_the_given_key() -> None:
    client = FakeCodexClient(connected_response(), initial=FakeAccountResponse(None))
    service = make_service(client)

    service.connect("api_key", api_key="sk-test-value")

    assert client.api_key_used == "sk-test-value"


def test_connect_with_api_key_without_a_key_raises_locally() -> None:
    client = FakeCodexClient(connected_response(), initial=FakeAccountResponse(None))
    service = make_service(client)

    with pytest.raises(ProviderAuthenticationError, match="chave de API"):
        service.connect("api_key", api_key=None)


def test_connect_raises_when_login_does_not_actually_connect() -> None:
    # O `wait()` retorna, mas a conta consultada depois continua desconectada.
    client = FakeCodexClient(FakeAccountResponse(None), initial=FakeAccountResponse(None))
    service = make_service(client)

    with pytest.raises(ProviderAuthenticationError, match="não foi concluído"):
        service.connect("device")


def test_connect_translates_sdk_errors_without_a_traceback() -> None:
    class ExplodingClient(FakeCodexClient):
        def login_chatgpt_device_code(self) -> FakeDeviceHandle:
            raise RuntimeError("transporte fechado")

    client = ExplodingClient(connected_response(), initial=FakeAccountResponse(None))
    service = make_service(client)

    with pytest.raises(ProviderAuthenticationError) as excinfo:
        service.connect("device")
    assert "Traceback" not in str(excinfo.value)
    assert "Falha ao conectar" in str(excinfo.value)


def test_disconnect_calls_logout() -> None:
    client = FakeCodexClient(connected_response(), initial=connected_response())
    service = make_service(client)

    service.disconnect()

    assert client.logged_out is True
