"""Cliente HTTP para a API local do dev-agent (127.0.0.1:8765 por padrão).

O dev-agent é uma ferramenta separada que planeja e executa edições em um
worktree Git isolado, em background, com acompanhamento por job. Este adapter
só fala REST com ela; nunca importa o pacote `dev_agent` diretamente, para
manter os dois projetos independentes.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from devmate.errors import DevAgentUnavailableError

DEFAULT_BASE_URL = "http://127.0.0.1:8765"
TERMINAL_JOB_STATUSES = frozenset(
    {"completed", "partially_completed", "failed", "cancelled", "blocked"}
)


class DevAgentClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 30.0,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client_factory = client_factory

    def _client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory()
        import httpx

        return httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds)

    def available(self) -> tuple[bool, str | None]:
        try:
            import httpx
        except ImportError:
            return False, "Pacote httpx não está instalado."
        try:
            self._client().get("/")
        except httpx.ConnectError:
            return False, (
                f"dev-agent não está respondendo em {self.base_url}. "
                "Rode `dev-agent start` primeiro."
            )
        except Exception as exc:  # servidor pode responder com erro em "/"; ainda está de pé
            _ = exc
            return True, None
        return True, None

    def _request(self, method: str, path: str, json: dict[str, Any] | None = None) -> Any:
        import httpx

        try:
            response = self._client().request(method, path, json=json)
        except httpx.ConnectError as exc:
            raise DevAgentUnavailableError(
                f"dev-agent não está respondendo em {self.base_url}. "
                "Rode `dev-agent start` primeiro."
            ) from exc
        except httpx.TimeoutException as exc:
            raise DevAgentUnavailableError(
                f"dev-agent excedeu o timeout de {self.timeout_seconds}s em {path}."
            ) from exc
        if response.status_code >= 400:
            detail = self._error_detail(response)
            raise DevAgentUnavailableError(f"dev-agent respondeu {response.status_code}: {detail}")
        return response.json()

    @staticmethod
    def _error_detail(response: Any) -> str:
        try:
            payload = response.json()
        except Exception:
            return response.text.strip() or "sem detalhe"
        detail = payload.get("detail") if isinstance(payload, dict) else None
        return str(detail) if detail else response.text.strip() or "sem detalhe"

    def create_plan(self, cwd: Path, objective: str) -> dict[str, Any]:
        """Cria um plano revisável; não escreve nada ainda."""
        plan: dict[str, Any] = self._request(
            "POST", "/assistant/task-plans", json={"cwd": str(cwd), "objective": objective}
        )
        return plan

    def start(self, plan_id: str, confirmed_write: bool) -> dict[str, Any]:
        """Inicia a execução do plano em background, num worktree isolado."""
        job: dict[str, Any] = self._request(
            "POST",
            f"/assistant/task-plans/{plan_id}/start",
            json={"confirmed_write": confirmed_write},
        )
        return job

    def headers(
        self, cwd: Path, confirmed_apply: bool = False, suggest_purposes: bool = False
    ) -> dict[str, Any]:
        """Atalho direto pro comando dedicado do dev-agent (`dev-agent headers`) — mais
        rápido e confiável que delegar como um objetivo livre pro `task`/`run` genérico,
        já que essa tarefa específica já tem seu próprio endpoint no dev-agent.

        Sem `confirmed_apply`, só lista os arquivos elegíveis (nada é escrito).
        """
        result: dict[str, Any] = self._request(
            "POST",
            "/headers",
            json={
                "cwd": str(cwd),
                "confirmed_apply": confirmed_apply,
                "suggest_purposes": suggest_purposes,
            },
        )
        return result

    def job(self, job_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._request("GET", f"/assistant/jobs/{job_id}")
        return result

    def wait_for_completion(
        self, job_id: str, poll_seconds: float = 2.0, timeout_seconds: float = 600.0
    ) -> dict[str, Any]:
        """Consulta o job periodicamente até um status terminal ou o timeout."""
        deadline = time.monotonic() + timeout_seconds
        while True:
            state = self.job(job_id)
            if state.get("status") in TERMINAL_JOB_STATUSES:
                return state
            if time.monotonic() >= deadline:
                raise DevAgentUnavailableError(
                    f"O job {job_id} não terminou em {timeout_seconds:.0f}s; "
                    f"último status: {state.get('status')}. Consulte `dev-agent job {job_id}`."
                )
            time.sleep(poll_seconds)

    def cleanup(self, job_id: str) -> None:
        """Remove o worktree do job; falha aqui não deve interromper o fluxo principal."""
        with contextlib.suppress(DevAgentUnavailableError):
            self._request("POST", f"/assistant/jobs/{job_id}/cleanup")
