"""API HTTP fina sobre os mesmos application services usados pela CLI.

Nunca chama a CLI por subprocess: monta os mesmos ``ConversationService`` /
``InspectionConversationService`` que ``devmate ask``/``chat`` usam, então as
regras de escopo, segurança e citações são exatamente as mesmas dos dois lados.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, cast
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from devmate.api.dependencies import get_runtime
from devmate.api.errors import status_for
from devmate.api.project_registry import ProjectRegistry, RegisteredProject
from devmate.api.schemas import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    HealthResponse,
    SourceReferenceOut,
    StatusResponse,
)
from devmate.application.conversation_service import ConversationService
from devmate.application.inspection_conversation_service import InspectionConversationService
from devmate.bootstrap import Runtime
from devmate.errors import DevMateError, UnsafePathError
from devmate.prompts.api_chat import API_CHAT_SYSTEM

app = FastAPI(
    title="DevMate API",
    version="1",
    description="Camada HTTP fina sobre os application services do DevMate.",
)

# Local-first (seção 4.1/40.2 do plano de frontend): nenhuma origem remota por
# padrão, só o servidor de desenvolvimento do Vite rodando na mesma máquina.
_ALLOWED_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:5174",
    "http://localhost:5174",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

projects = ProjectRegistry()
_started_at = time.monotonic()
_runs: dict[str, dict[str, Any]] = {}
_runs_lock = Lock()


@app.exception_handler(DevMateError)
async def handle_devmate_error(request: Request, exc: DevMateError) -> JSONResponse:
    del request
    return JSONResponse(
        status_code=status_for(exc),
        content=ErrorResponse(detail=str(exc), code=type(exc).__name__).model_dump(),
    )


@app.get("/api/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/api/v1/status", response_model=StatusResponse)
def read_status(runtime: Runtime = Depends(get_runtime)) -> StatusResponse:
    project_id = runtime.project_id
    latest = runtime.store.latest_commit(project_id)
    return StatusResponse(
        repo=str(runtime.root),
        branch=runtime.git.current_branch(),
        head=runtime.git.head(),
        last_processed=latest.short_hash if latest else None,
    )


def _project_payload(project: RegisteredProject, runtime: Runtime) -> dict[str, object]:
    latest = runtime.store.latest_commit(runtime.project_id)
    branch = runtime.git.current_branch() or "HEAD"
    created_at = datetime.fromtimestamp(
        (runtime.root / ".devmate").stat().st_mtime, tz=UTC
    ).isoformat()
    return {
        "id": project.id,
        "name": project.name,
        "displayPath": str(project.root),
        "defaultBranch": branch,
        "activeBranch": branch,
        "activeCommitHash": latest.commit_hash if latest else runtime.git.head(),
        "lastScanAt": latest.committed_at.isoformat() if latest else None,
        "decisionsActiveCount": len(runtime.store.decisions(runtime.project_id, active_only=True)),
        "questionsOpenCount": len(runtime.store.questions(runtime.project_id, open_only=True)),
        "dbStatus": "ready",
        "createdAt": created_at,
    }


def _project_status(project: RegisteredProject, runtime: Runtime) -> dict[str, object]:
    data = _project_payload(project, runtime)
    return {
        "projectId": project.id,
        "connection": "connected",
        "scanning": False,
        "lastScanAt": data["lastScanAt"],
        "defaultProvider": runtime.config.provider.default,
        "defaultVoice": runtime.config.speech.voice,
        "activeBranch": data["activeBranch"],
        "activeCommitHash": data["activeCommitHash"],
    }


def _runtime(project_id: str) -> tuple[RegisteredProject, Runtime]:
    return projects.runtime(project_id)


def _source_payload(reference: SourceReferenceOut) -> dict[str, object]:
    return {
        "id": f"{reference.commit_hash}:{reference.path}:{reference.start_line}",
        "kind": "document" if Path(reference.path).suffix.lower() in {".md", ".mdx"} else "code",
        "path": reference.path,
        "commitHash": reference.commit_hash,
        "startLine": reference.start_line,
        "endLine": reference.end_line,
        "heading": reference.heading,
        "label": reference.label,
        "valid": True,
    }


def _visible_path(runtime: Runtime, path: str) -> Path:
    resolved = runtime.filesystem.resolve(path)
    if runtime.filesystem.is_sensitive(resolved):
        raise UnsafePathError("Arquivos potencialmente sensíveis não podem ser lidos pelo DevMate.")
    return resolved


def _language(path: str) -> str:
    extensions = {
        ".css": "css",
        ".html": "html",
        ".java": "java",
        ".js": "javascript",
        ".json": "json",
        ".md": "markdown",
        ".py": "python",
        ".rs": "rust",
        ".sh": "shell",
        ".sql": "sql",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".yaml": "yaml",
        ".yml": "yaml",
    }
    return extensions.get(Path(path).suffix.lower(), "text")


@app.get("/api/v1/projects")
def list_projects() -> dict[str, list[dict[str, object]]]:
    items: list[dict[str, object]] = []
    for project in projects.list():
        try:
            _, runtime = projects.runtime(project.id)
            items.append(_project_payload(project, runtime))
        except DevMateError:
            continue
    return {"items": items}


@app.post("/api/v1/projects", status_code=201)
def create_project(body: dict[str, str]) -> dict[str, object]:
    requested_path = body.get("path", "").strip()
    if not requested_path:
        raise UnsafePathError("O caminho do repositório é obrigatório.")
    name = body.get("name") or None
    project = projects.register(requested_path, name)
    _, runtime = projects.runtime(project.id)
    return _project_payload(project, runtime)


@app.get("/api/v1/projects/{project_id}")
def read_project(project_id: str) -> dict[str, object]:
    project, runtime = _runtime(project_id)
    return _project_payload(project, runtime)


@app.get("/api/v1/projects/{project_id}/status")
def read_project_status(project_id: str) -> dict[str, object]:
    project, runtime = _runtime(project_id)
    return _project_status(project, runtime)


@app.post("/api/v1/projects/{project_id}/scan", status_code=202)
def scan_project(project_id: str) -> dict[str, object]:
    project, runtime = _runtime(project_id)
    runtime.scan_service().scan(runtime.project_id)
    return _project_status(project, runtime)


@app.get("/api/v1/projects/{project_id}/commits/{commit_hash}")
def read_commit(project_id: str, commit_hash: str) -> dict[str, object]:
    _, runtime = _runtime(project_id)
    record = runtime.git.commit_metadata(commit_hash)
    changed_files = runtime.git.changed_files(record.commit_hash)
    return {
        "hash": record.commit_hash,
        "shortHash": record.short_hash,
        "subject": record.subject,
        "message": record.body or record.subject,
        "author": record.author_name,
        "authoredAt": record.authored_at.isoformat(),
        "branch": record.branch_name or "HEAD",
        "changedDocPaths": [
            path for path in changed_files if Path(path).suffix.lower() in {".md", ".mdx"}
        ],
        "changedCodePaths": [
            path for path in changed_files if Path(path).suffix.lower() not in {".md", ".mdx"}
        ],
        "analysisStatus": "pending",
    }


@app.get("/api/v1/projects/{project_id}/files")
def list_files(project_id: str, commit: str) -> dict[str, list[dict[str, object]]]:
    _, runtime = _runtime(project_id)
    entries: dict[str, dict[str, object]] = {}
    for path in runtime.git.tracked_files(commit):
        try:
            _visible_path(runtime, path)
        except UnsafePathError:
            continue
        entries[path] = {"path": path, "type": "file"}
        parent = Path(path).parent
        while str(parent) not in {"", "."}:
            directory = parent.as_posix()
            entries.setdefault(directory, {"path": directory, "type": "directory"})
            parent = parent.parent
    return {"items": [entries[key] for key in sorted(entries)]}


@app.get("/api/v1/projects/{project_id}/files/content")
def read_file_content(
    project_id: str,
    commit: str,
    path: str,
    startLine: int | None = None,
    endLine: int | None = None,
) -> dict[str, object]:
    _, runtime = _runtime(project_id)
    _visible_path(runtime, path)
    resolved_commit = runtime.git.resolve_commit(commit)
    content = runtime.git.file_at_commit(resolved_commit, path)
    if len(content.encode("utf-8")) > runtime.config.security.max_file_bytes:
        raise UnsafePathError("Arquivo excede o limite de leitura configurado.")
    lines = content.splitlines()
    first = max(1, startLine or 1)
    last = min(len(lines), endLine or len(lines))
    selected = "\n".join(lines[first - 1 : last])
    return {
        "path": path,
        "commitHash": resolved_commit,
        "language": _language(path),
        "sizeBytes": len(content.encode("utf-8")),
        "lineCount": len(lines),
        "truncated": False,
        "content": selected,
        "startLine": first,
        "endLine": last,
    }


@app.get("/api/v1/projects/{project_id}/decisions")
def list_decisions(
    project_id: str, status: str | None = None
) -> dict[str, list[dict[str, object]]]:
    _, runtime = _runtime(project_id)
    items: list[dict[str, object]] = []
    for decision in runtime.store.decisions(runtime.project_id, active_only=status == "active"):
        items.append(
            {
                "id": str(decision.id),
                "title": decision.title,
                "description": decision.description,
                "status": decision.status,
                "explicitness": decision.explicitness,
                "confidence": "medium",
                "commitHash": decision.source_commit or "",
                "filePath": decision.source_path,
                "startLine": decision.source_start_line,
                "endLine": decision.source_end_line,
                "createdAt": datetime.now(UTC).isoformat(),
            }
        )
    return {"items": items}


@app.get("/api/v1/projects/{project_id}/questions")
def list_questions(
    project_id: str, status: str | None = None
) -> dict[str, list[dict[str, object]]]:
    _, runtime = _runtime(project_id)
    items: list[dict[str, object]] = []
    for question in runtime.store.questions(runtime.project_id, open_only=status == "open"):
        items.append(
            {
                "id": str(question.id),
                "question": question.question,
                "status": question.status,
                "commitHash": question.source_commit or "",
                "filePath": question.source_path,
                "startLine": question.source_start_line,
                "endLine": question.source_end_line,
                "createdAt": datetime.now(UTC).isoformat(),
            }
        )
    return {"items": items}


@app.get("/api/v1/projects/{project_id}/threads")
def list_threads(project_id: str, commit: str | None = None) -> dict[str, list[dict[str, object]]]:
    _, runtime = _runtime(project_id)
    return {
        "items": [
            {
                "id": item.id,
                "projectId": project_id,
                "commitHash": item.commit_hash,
                "scope": item.scope,
                "createdAt": item.created_at.isoformat(),
                "updatedAt": item.updated_at.isoformat(),
                "messageCount": item.message_count,
            }
            for item in runtime.store.threads(runtime.project_id, commit)
        ]
    }


@app.get("/api/v1/projects/{project_id}/threads/{thread_id}/messages")
def list_thread_messages(project_id: str, thread_id: str, limit: int = 30) -> dict[str, object]:
    _, runtime = _runtime(project_id)
    if runtime.store.thread(runtime.project_id, thread_id) is None:
        raise UnsafePathError("Thread não encontrada neste projeto.")
    return {
        "items": [
            {
                "id": item.id,
                "threadId": item.thread_id,
                "role": item.role,
                "content": item.content,
                "createdAt": item.created_at.isoformat(),
                "scope": item.scope,
                "provider": item.provider_name,
                "model": item.model_name,
                "sources": json.loads(item.sources_json),
                "status": item.status,
            }
            for item in runtime.store.web_messages(runtime.project_id, thread_id, limit)
        ]
    }


@app.get("/api/v1/providers")
def list_providers() -> dict[str, list[dict[str, object]]]:
    names: set[str] = set()
    for project in projects.list():
        _, runtime = projects.runtime(project.id)
        names.add(runtime.config.provider.default)
    return {
        "items": [
            {
                "name": name,
                "type": name,
                "local": name == "mock",
                "availability": "available",
                "authConfigured": name == "mock",
                "capabilities": ["conversation", "repository_access", "citations"],
            }
            for name in names
        ]
    }


def _system_instructions(body: ChatRequest) -> str:
    if body.source == "speech":
        return f"{API_CHAT_SYSTEM}\n\nEntrada: transcrição de voz. Seja mais concisa e direta."
    return API_CHAT_SYSTEM


@app.get("/api/v1/projects/{project_id}/commits")
def list_commits(project_id: str, branch: str | None = None, limit: int = 30) -> dict[str, object]:
    _, runtime = _runtime(project_id)
    records = list(reversed(runtime.git.commits(branch or "HEAD")))[:limit]
    return {"items": [read_commit(project_id, record.commit_hash) for record in records]}


@app.get("/api/v1/projects/{project_id}/files/diff")
def read_file_diff(project_id: str, commit: str, path: str) -> dict[str, object]:
    _, runtime = _runtime(project_id)
    _visible_path(runtime, path)
    record = runtime.git.commit_metadata(commit)
    raw = runtime.git._diff(record, path, runtime.config.security.max_diff_chars)
    return {
        "newPath": path,
        "status": "modified",
        "commitHash": record.commit_hash,
        "parentHash": record.first_parent_hash,
        "additions": sum(
            line.startswith("+") and not line.startswith("+++") for line in raw.splitlines()
        ),
        "deletions": sum(
            line.startswith("-") and not line.startswith("---") for line in raw.splitlines()
        ),
        "hunks": [
            {"header": line, "lines": []} for line in raw.splitlines() if line.startswith("@@")
        ],
    }


@app.post("/api/v1/projects/{project_id}/chat/runs", status_code=202)
def create_chat_run(project_id: str, body: dict[str, object]) -> dict[str, str]:
    _, runtime = _runtime(project_id)
    message = str(body.get("message", "")).strip()
    scope = str(body.get("scope", "docs"))
    if not message or scope not in {"docs", "code"}:
        raise UnsafePathError("message e scope (docs/code) são obrigatórios.")
    commit = runtime.git.resolve_commit(str(body.get("commitHash") or "HEAD"))
    thread_id = str(body.get("threadId") or uuid4().hex)
    thread = runtime.store.thread(runtime.project_id, thread_id)
    if thread is None:
        runtime.store.create_thread(thread_id, runtime.project_id, commit, scope)
    elif thread.commit_hash != commit or thread.scope != scope:
        raise UnsafePathError("A thread pertence a outro commit ou escopo.")
    run_id, provider = uuid4().hex, str(body.get("provider") or runtime.config.provider.default)
    runtime.store.add_web_message(
        uuid4().hex, thread_id, "user", message, scope, "complete", None, None
    )
    state: dict[str, Any] = {
        "id": run_id,
        "threadId": thread_id,
        "status": "queued",
        # Append-only log, not a consumable queue: a reconnecting EventSource opens a
        # second GET to the same run, and a destructive queue.get() would split events
        # between whichever connection happened to win each item, silently dropping the
        # ones delivered to a connection that then failed. A log lets every connection
        # replay from the index it already has (see stream_run_events's Last-Event-ID).
        "events": [],
        "events_lock": Lock(),
        "cancelled": Event(),
        "terminal": Event(),
    }
    with _runs_lock:
        _runs[run_id] = state
    Thread(
        target=_execute_chat_run,
        args=(state, runtime, message, scope, provider, commit),
        daemon=True,
        name=f"devmate-run-{run_id[:8]}",
    ).start()
    return {"id": run_id, "threadId": thread_id, "status": "queued"}


def _emit(state: dict[str, Any], event: dict[str, object]) -> None:
    """Acrescenta ao log do run; cada conexão SSE (inicial ou reconexão) faz polling
    e lê o log a partir do índice que já recebeu — ver stream_run_events."""
    with cast(Lock, state["events_lock"]):
        cast(list[dict[str, object]], state["events"]).append(event)


def _execute_chat_run(
    state: dict[str, Any], runtime: Runtime, message: str, scope: str, provider: str, commit: str
) -> None:
    run_id = cast(str, state["id"])
    cancelled = cast(Event, state["cancelled"])
    terminal = cast(Event, state["terminal"])
    try:
        state["status"] = "running"
        _emit(state, {"type": "run.started", "runId": run_id})
        _emit(state, {"type": "tool.started", "runId": run_id, "tool": "repository_context"})
        if cancelled.is_set():
            return
        if scope == "docs":
            result = ConversationService(
                runtime.store, runtime.context_service(), runtime.providers
            ).ask_stream(
                runtime.project_id,
                message,
                provider,
                lambda delta: _emit(
                    state, {"type": "assistant.delta", "runId": run_id, "delta": delta}
                )
                if not cancelled.is_set()
                else None,
                commit,
                None,
                API_CHAT_SYSTEM,
            )
        else:
            result = InspectionConversationService(
                runtime.inspection_service(), runtime.store, runtime.providers
            ).ask(runtime.project_id, message, provider, commit, None, None, True, API_CHAT_SYSTEM)
        _emit(state, {"type": "tool.completed", "runId": run_id, "tool": "repository_context"})
        if cancelled.is_set():
            return
        sources: list[dict[str, object]] = [
            _source_payload(SourceReferenceOut.from_domain(item))
            for item in result.response.references
        ]
        if scope == "code":
            # O provider de inspeção ainda é síncrono; preserve o contrato SSE
            # até ele ganhar suporte nativo a tokens, como o chat de documentos.
            _emit(
                state,
                {"type": "assistant.delta", "runId": run_id, "delta": result.response.text},
            )
        for source in sources:
            _emit(state, {"type": "source.reference", "runId": run_id, "source": source})
        message_id = uuid4().hex
        thread_id = cast(str, state["threadId"])
        created_at = datetime.now(UTC).isoformat()
        runtime.store.add_web_message(
            message_id, thread_id, "assistant", result.response.text,
            scope, "complete", provider, None, json.dumps(sources),
        )
        state["status"] = "completed"
        # The frontend's contract (RunEvent's run.completed) requires the persisted
        # message here — without it, use-chat-run.ts's onEvent throws reading
        # event.message.threadId, which silently aborts the messages-query
        # invalidation that follows it, so the answer never appears in the transcript
        # even though it was correctly saved.
        _emit(
            state,
            {
                "type": "run.completed",
                "runId": run_id,
                "message": {
                    "id": message_id,
                    "threadId": thread_id,
                    "role": "assistant",
                    "content": result.response.text,
                    "createdAt": created_at,
                    "scope": scope,
                    "provider": provider,
                    "model": None,
                    "sources": sources,
                    "status": "complete",
                },
            },
        )
    except DevMateError as exc:
        if not cancelled.is_set():
            state["status"] = "failed"
            # The frontend's contract expects `error` shaped like ApiProblem
            # ({title, status, detail}), not a bare string — StreamingMessage renders
            # error.title/error.detail directly.
            _emit(
                state,
                {
                    "type": "run.failed",
                    "runId": run_id,
                    "error": {"title": "A conversa falhou", "status": 502, "detail": str(exc)},
                },
            )
    finally:
        if cancelled.is_set():
            state["status"] = "cancelled"
            _emit(state, {"type": "run.completed", "runId": run_id, "cancelled": True})
        terminal.set()


@app.get("/api/v1/runs/{run_id}")
def read_run(run_id: str) -> dict[str, object]:
    with _runs_lock:
        run = _runs.get(run_id)
    if run is None:
        raise UnsafePathError("Run não encontrada.")
    return {key: run[key] for key in ("id", "threadId", "status")}


@app.get("/api/v1/runs/{run_id}/events")
def stream_run_events(run_id: str, request: Request) -> StreamingResponse:
    with _runs_lock:
        run = _runs.get(run_id)
    if run is None:
        raise UnsafePathError("Run não encontrada.")

    # Browsers resume a dropped EventSource by sending back the last `id:` line they
    # saw. Replaying from there — instead of always starting at 0 — is what actually
    # makes reconnection work, rather than just not crash.
    last_event_id = request.headers.get("last-event-id")
    start_index = 0
    if last_event_id is not None:
        try:
            start_index = int(last_event_id) + 1
        except ValueError:
            start_index = 0

    def frames() -> Iterator[str]:
        events = cast(list[dict[str, object]], run["events"])
        lock = cast(Lock, run["events_lock"])
        index = start_index
        last_activity = time.monotonic()
        yield ": heartbeat\n\n"
        while True:
            # Deliberately never end the response just because the run reached a
            # terminal status: EventSource treats any response ending — even a clean
            # one — as a dropped connection and auto-reconnects on its own default
            # schedule (~3s in Chromium), with nothing here to tell it to stop. Once
            # caught up, a reconnect would get an instantly-empty response every time,
            # which never gives it a reason to stop retrying — an infinite loop, not a
            # handful of retries. The client closes this subscription itself once it
            # has processed the terminal event (run.completed/run.failed in
            # use-chat-run.ts). This loop only ends when the client actually
            # disconnects: the next attempt to send a chunk over a closed connection
            # fails, and the ASGI server raises GeneratorExit into this generator —
            # explicitly polling for disconnection isn't needed (and, tried here,
            # deadlocked under Starlette's TestClient).
            with lock:
                pending = events[index:]
            if not pending:
                time.sleep(0.3)
                if time.monotonic() - last_activity > 10:
                    yield ": heartbeat\n\n"
                    last_activity = time.monotonic()
                continue
            for event in pending:
                yield (
                    f"id: {index}\nevent: {event['type']}\n"
                    f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                )
                index += 1
            last_activity = time.monotonic()

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={
            # Without these, an intermediate proxy (Vite's dev-server proxy included) can
            # buffer the streaming response and deliver it in one short-lived burst instead
            # of live — the browser then sees the connection end almost immediately and
            # EventSource reconnects in a tight loop, never catching up to a live run.
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/v1/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict[str, object]:
    with _runs_lock:
        run = _runs.get(run_id)
    if run is None:
        raise UnsafePathError("Run não encontrada.")
    if not cast(Event, run["terminal"]).is_set():
        cast(Event, run["cancelled"]).set()
    return {key: run[key] for key in ("id", "threadId", "status")}


@app.post("/api/v1/chat", response_model=ChatResponse)
def chat(body: ChatRequest, runtime: Runtime = Depends(get_runtime)) -> ChatResponse:
    provider_name = body.provider or runtime.config.provider.default
    instructions = _system_instructions(body)
    # Mesma conveniência da CLI: um commit novo não deve virar um erro manual
    # pedindo scan, já que a indexação é local e não chama provider nem rede.
    runtime.ensure_indexed(body.commit)

    if body.scope == "code":
        inspection_conversation = InspectionConversationService(
            runtime.inspection_service(), runtime.store, runtime.providers
        )
        answer = inspection_conversation.ask(
            runtime.project_id,
            body.question,
            provider_name,
            body.commit,
            body.model,
            body.files,
            body.full_repo,
            instructions,
        )
    else:
        if body.files or body.full_repo:
            # Falha explícita em vez de ignorar em silêncio: evita que a pessoa
            # usuária pense que autorizou código quando só pediu documentação.
            raise UnsafePathError(
                "files/full_repo exigem scope=code; scope=docs nunca inclui código."
            )
        conversation = ConversationService(
            runtime.store, runtime.context_service(), runtime.providers
        )
        answer = conversation.ask(
            runtime.project_id,
            body.question,
            provider_name,
            body.commit,
            body.model,
            instructions,
        )

    return ChatResponse(
        commit=answer.commit_hash,
        scope=body.scope,
        provider=provider_name,
        model=body.model,
        text=answer.response.text,
        sources=[SourceReferenceOut.from_domain(ref) for ref in answer.response.references],
    )
