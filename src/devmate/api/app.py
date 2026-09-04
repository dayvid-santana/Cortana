"""API HTTP fina sobre os mesmos application services usados pela CLI.

Nunca chama a CLI por subprocess: monta os mesmos ``ConversationService`` /
``InspectionConversationService`` que ``devmate ask``/``chat`` usam, então as
regras de escopo, segurança e citações são exatamente as mesmas dos dois lados.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, cast
from uuid import uuid4

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from devmate.adapters.speech.registry import get_speech_provider
from devmate.api.dependencies import get_runtime
from devmate.api.errors import status_for
from devmate.api.project_registry import ProjectRegistry, RegisteredProject
from devmate.api.schemas import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    HealthResponse,
    SourceReferenceOut,
    SpeechSettingsUpdate,
    StatusResponse,
)
from devmate.application.conversation_service import ConversationService
from devmate.application.doctor_service import doctor
from devmate.application.inspection_conversation_service import InspectionConversationService
from devmate.application.reading_session_service import (
    ReadingSegment,
    build_segments,
    changed_line_ranges,
    filter_by_ranges,
)
from devmate.bootstrap import Runtime
from devmate.config import database_path
from devmate.config_writer import (
    set_default_model,
    set_default_provider,
    set_speech_rate,
    set_speech_voice,
    set_task_routing,
)
from devmate.domain.ports import LanguageModelProvider, SpeechProvider
from devmate.domain.speech import DEFAULT_VOICE_PREVIEW_TEXT, SpeechRequest, VoiceInfo
from devmate.errors import DevMateError, UnsafePathError
from devmate.prompts.api_chat import API_CHAT_SYSTEM

_KNOWN_LLM_PROVIDERS = ("mock", "codex", "openai", "openai_compatible")
_KNOWN_SPEECH_PROVIDERS = ("system", "openai", "elevenlabs", "edge")

# Metadados estáticos por provider de LLM (taxonomia), combinados com o estado real
# (disponibilidade, modelo, tarefas roteadas) calculado por request em
# ``_llm_provider_payload``. O contrato de capacidades é o mesmo enum usado pelo
# frontend para ambos providers de LLM e de fala (não há um enum mais fino).
_PROVIDER_METADATA: dict[str, dict[str, object]] = {
    "mock": {
        "type": "local",
        "local": True,
        "capabilities": ["conversation", "repository_access", "citations"],
    },
    "codex": {
        "type": "local",
        "local": True,
        "capabilities": [
            "conversation",
            "repository_access",
            "tool_use",
            "code_inspection",
            "citations",
        ],
    },
    "openai": {
        "type": "remote",
        "local": False,
        "capabilities": ["conversation", "structured_output", "streaming", "citations"],
    },
    "openai_compatible": {
        "type": "remote",
        "local": False,
        "capabilities": ["conversation", "structured_output", "citations"],
    },
}

_AUDIO_MEDIA_TYPES = {
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "audio/L16",
}

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
    allow_methods=["GET", "POST", "PUT"],
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
        "defaultRate": runtime.config.speech.rate,
        "activeBranch": data["activeBranch"],
        "activeCommitHash": data["activeCommitHash"],
    }


def _runtime(project_id: str) -> tuple[RegisteredProject, Runtime]:
    return projects.runtime(project_id)


def _shared_runtime() -> Runtime:
    """Runtime para endpoints não específicos de projeto (diagnostics, catálogo de
    providers/vozes): o primeiro projeto registrado no modo multi-projeto, com o
    diretório de trabalho do processo como fallback (modo single-repo, ``devmate
    serve`` executado dentro de um projeto — igual a como ``/status``/``/chat`` já
    resolvem). Sem isso, esses endpoints ignorariam por completo o projeto que a
    pessoa usuária registrou pela API web e refletiriam um repositório não
    relacionado (o diretório onde o processo da API por acaso foi iniciado).
    """
    registered = projects.list()
    if registered:
        _, runtime = projects.runtime(registered[0].id)
        return runtime
    return get_runtime()


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
        # A registered project's directory can be moved or deleted after registration
        # (e.g. a disposable/temp checkout). Skip it instead of letting git discovery's
        # subprocess call fail with an unhandled OSError that 500s the whole listing.
        if not project.root.is_dir():
            continue
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


def _llm_provider_payload(name: str, runtime: Runtime) -> dict[str, object]:
    provider = runtime.providers.get(name)
    available, _detail = provider.available()
    meta = _PROVIDER_METADATA[name]
    model: str | None = None
    if name == "codex":
        model = runtime.config.language_model.providers.codex.model
    elif name == runtime.config.provider.default:
        model = runtime.config.provider.model
    routed_tasks = [
        task
        for task, routed_name in runtime.config.provider.task_routing.items()
        if routed_name == name
    ]
    payload: dict[str, object] = {
        "name": name,
        "type": meta["type"],
        "local": meta["local"],
        "availability": "available" if available else "unavailable",
        "authConfigured": available,
        "capabilities": meta["capabilities"],
        "routedTasks": routed_tasks,
    }
    if model:
        payload["model"] = model
    return payload


def _speech_provider_payload(name: str, runtime: Runtime) -> dict[str, object]:
    provider = get_speech_provider(name, runtime.config, runtime.root)
    available, _detail = provider.available()
    capabilities = provider.capabilities()
    auth_configured = (
        provider.api_key_configured() if hasattr(provider, "api_key_configured") else True
    )
    payload: dict[str, object] = {
        "name": name,
        "type": "remote" if capabilities.remote else "local",
        "local": not capabilities.remote,
        "availability": "available" if available else "unavailable",
        "authConfigured": bool(auth_configured),
        # O contrato compartilha um único enum de capacidades entre providers de LLM e
        # de fala; "conversation" é o único membro que descreve corretamente síntese
        # de voz, então é o único usado aqui.
        "capabilities": ["conversation"],
        "routedTasks": [],
    }
    if name == "openai":
        payload["model"] = runtime.config.speech.providers.openai.model
    if name == "elevenlabs":
        payload["model"] = runtime.config.speech.providers.elevenlabs.model
    return payload


def _voice_payload(voice: VoiceInfo) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": voice.id,
        "name": voice.name,
        "provider": voice.provider,
        # Vozes do sistema operacional não relatam idioma; "pt-BR" reflete o padrão
        # de entrada de voz do próprio DevMate (`speech.input_language`), não um dado
        # inventado por voz.
        "language": voice.language or "pt-BR",
        "recommended": voice.recommended,
        "availability": "available",
    }
    if voice.description:
        payload["description"] = voice.description
    return payload


def _find_voice_provider(runtime: Runtime, voice_id: str) -> tuple[str, SpeechProvider, VoiceInfo]:
    for name in _KNOWN_SPEECH_PROVIDERS:
        speech = get_speech_provider(name, runtime.config, runtime.root)
        available, _detail = speech.available()
        if not available:
            continue
        try:
            candidates = speech.list_voices()
        except DevMateError:
            continue
        for voice in candidates:
            if voice.id == voice_id:
                return name, speech, voice
    raise UnsafePathError(f"Voz desconhecida: {voice_id}")


@app.get("/api/v1/providers")
def list_providers(
    runtime: Runtime = Depends(_shared_runtime),
) -> dict[str, list[dict[str, object]]]:
    return {"items": [_llm_provider_payload(name, runtime) for name in _KNOWN_LLM_PROVIDERS]}


@app.get("/api/v1/providers/{provider_name}")
def read_provider(
    provider_name: str, runtime: Runtime = Depends(_shared_runtime)
) -> dict[str, object]:
    runtime.providers.get(provider_name)  # levanta ProviderNotFoundError (404) se desconhecido
    return _llm_provider_payload(provider_name, runtime)


@app.put("/api/v1/projects/{project_id}/settings/providers")
def update_provider_settings(project_id: str, body: dict[str, object]) -> dict[str, object]:
    project, runtime = _runtime(project_id)
    config_path = runtime.root / ".devmate" / "config.toml"

    default_provider = body.get("defaultProvider")
    if default_provider is not None:
        if not isinstance(default_provider, str) or default_provider not in _KNOWN_LLM_PROVIDERS:
            raise UnsafePathError(f"Provider desconhecido: {default_provider!r}")
        set_default_provider(config_path, default_provider)

    default_model = body.get("defaultModel")
    if default_model is not None:
        if not isinstance(default_model, str):
            raise UnsafePathError("defaultModel deve ser texto.")
        set_default_model(config_path, default_model)

    task_routing = body.get("taskRouting")
    if task_routing is not None:
        if not isinstance(task_routing, dict):
            raise UnsafePathError("taskRouting deve ser um objeto {tarefa: provider}.")
        for routed_name in task_routing.values():
            if routed_name not in _KNOWN_LLM_PROVIDERS:
                raise UnsafePathError(f"Provider desconhecido em taskRouting: {routed_name!r}")
        set_task_routing(config_path, cast(dict[str, str], task_routing))

    _, refreshed = _runtime(project_id)
    return _project_status(project, refreshed)


@app.get("/api/v1/diagnostics")
def get_diagnostics(runtime: Runtime = Depends(_shared_runtime)) -> dict[str, object]:
    checks = doctor(runtime)
    failed = [check for check in checks if not check.ok]
    database_status = (
        "ready" if (runtime.root / ".devmate" / "state.db").exists() else "unavailable"
    )
    result: dict[str, object] = {
        "backendVersion": app.version,
        "uptimeSeconds": int(time.monotonic() - _started_at),
        "database": {"status": database_status, "path": str(database_path(runtime.root))},
        "providers": [_llm_provider_payload(name, runtime) for name in _KNOWN_LLM_PROVIDERS],
        "speechProviders": [
            _speech_provider_payload(name, runtime) for name in _KNOWN_SPEECH_PROVIDERS
        ],
    }
    if failed:
        result["lastError"] = "; ".join(f"{check.name}: {check.detail}" for check in failed)
    return result


@app.get("/api/v1/speech/providers")
def list_speech_providers(
    runtime: Runtime = Depends(_shared_runtime),
) -> dict[str, list[dict[str, object]]]:
    return {"items": [_speech_provider_payload(name, runtime) for name in _KNOWN_SPEECH_PROVIDERS]}


@app.get("/api/v1/speech/voices")
def list_speech_voices(
    provider: str | None = None, runtime: Runtime = Depends(_shared_runtime)
) -> dict[str, list[dict[str, object]]]:
    names = (provider,) if provider else _KNOWN_SPEECH_PROVIDERS
    items: list[dict[str, object]] = []
    for name in names:
        if name not in _KNOWN_SPEECH_PROVIDERS:
            continue
        speech = get_speech_provider(name, runtime.config, runtime.root)
        available, _detail = speech.available()
        if not available:
            continue
        try:
            voices = speech.list_voices()
        except DevMateError:
            continue
        items.extend(_voice_payload(voice) for voice in voices)
    return {"items": items}


@app.post("/api/v1/speech/voices/preview")
def preview_voice(
    body: dict[str, str], runtime: Runtime = Depends(_shared_runtime)
) -> dict[str, object]:
    voice_id = str(body.get("voiceId", "")).strip()
    if not voice_id:
        raise UnsafePathError("voiceId é obrigatório.")
    provider_name, speech, voice = _find_voice_provider(runtime, voice_id)
    if not speech.capabilities().produces_audio_files:
        raise UnsafePathError(
            f"O provider de fala '{provider_name}' fala direto no dispositivo local e não "
            "gera um arquivo de áudio para pré-visualizar no navegador."
        )
    # Sintetiza agora para falhar cedo (credencial ausente, voz inválida) em vez de só
    # quando o navegador buscar o áudio.
    speech.synthesize(
        SpeechRequest(
            text=DEFAULT_VOICE_PREVIEW_TEXT, voice=voice.id, rate=runtime.config.speech.rate
        )
    )
    return {
        "voiceId": voice.id,
        "audioUrl": f"/api/v1/speech/voices/preview/audio?voiceId={voice.id}",
    }


@app.get("/api/v1/speech/voices/preview/audio")
def preview_voice_audio(voiceId: str, runtime: Runtime = Depends(_shared_runtime)) -> Response:
    provider_name, speech, voice = _find_voice_provider(runtime, voiceId)
    if not speech.capabilities().produces_audio_files:
        raise UnsafePathError(
            f"O provider de fala '{provider_name}' fala direto no dispositivo local e não "
            "gera um arquivo de áudio para pré-visualizar no navegador."
        )
    result = speech.synthesize(
        SpeechRequest(
            text=DEFAULT_VOICE_PREVIEW_TEXT, voice=voice.id, rate=runtime.config.speech.rate
        )
    )
    if result.audio_path is None:
        raise UnsafePathError("O provider de fala não retornou um arquivo de áudio.")
    media_type = _AUDIO_MEDIA_TYPES.get(
        getattr(speech, "response_format", "mp3"), "application/octet-stream"
    )
    return Response(content=result.audio_path.read_bytes(), media_type=media_type)


@app.put("/api/v1/projects/{project_id}/settings/speech")
def update_speech_settings(project_id: str, body: SpeechSettingsUpdate) -> dict[str, object]:
    project, runtime = _runtime(project_id)
    del project
    config_path = runtime.root / ".devmate" / "config.toml"

    if body.provider not in _KNOWN_SPEECH_PROVIDERS:
        raise UnsafePathError(f"Provider de fala desconhecido: {body.provider!r}")
    provider_name = body.provider
    voice_id = body.voiceId
    set_speech_voice(config_path, voice_id, provider_name)

    # `rate` é opcional: omitido, preserva o valor já configurado em vez de
    # sobrescrevê-lo — trocar de voz não deveria mexer no ritmo de fala.
    if body.rate is not None:
        set_speech_rate(config_path, body.rate)

    _, refreshed = _runtime(project_id)
    speech = get_speech_provider(provider_name, refreshed.config, refreshed.root)
    matched_voice = next((voice for voice in speech.list_voices() if voice.id == voice_id), None)
    payload: dict[str, object] = {
        "provider": provider_name,
        "voiceId": voice_id,
        "language": (matched_voice.language if matched_voice else None) or "pt-BR",
        "rate": refreshed.config.speech.rate,
        "capabilities": ["conversation"],
    }
    if provider_name == "openai":
        payload["model"] = refreshed.config.speech.providers.openai.model
    return payload


_reading_sessions: dict[str, dict[str, Any]] = {}
_reading_sessions_lock = Lock()


def _reading_session_payload(session: dict[str, Any], runtime: Runtime) -> dict[str, object]:
    try:
        head = runtime.git.resolve_commit("HEAD")
        current_content = runtime.git.file_at_commit(head, session["filePath"])
        stale = (
            hashlib.sha256(current_content.encode("utf-8")).hexdigest() != session["contentHash"]
        )
    except DevMateError:
        stale = True
    segments = cast(list[ReadingSegment], session["segments"])
    session_id = session["id"]
    return {
        "id": session_id,
        "projectId": session["projectId"],
        "filePath": session["filePath"],
        "commitHash": session["commitHash"],
        "voice": session["voice"],
        "mode": session["mode"],
        "segments": [
            {
                "index": segment.index,
                "text": segment.text,
                **({"heading": segment.heading} if segment.heading else {}),
                "audioUrl": f"/api/v1/reading-sessions/{session_id}/segments/{segment.index}/audio",
            }
            for segment in segments
        ],
        "createdAt": session["createdAt"],
        "stale": stale,
    }


@app.post("/api/v1/projects/{project_id}/reading-sessions", status_code=201)
def create_reading_session(project_id: str, body: dict[str, object]) -> dict[str, object]:
    _, runtime = _runtime(project_id)

    file_path = str(body.get("filePath", "")).strip()
    if not file_path:
        raise UnsafePathError("filePath é obrigatório.")
    _visible_path(runtime, file_path)

    mode = str(body.get("mode", "narrate"))
    if mode not in {"verbatim", "narrate", "explain"}:
        raise UnsafePathError("mode deve ser verbatim, narrate ou explain.")
    skip_code = bool(body.get("skipCode", True))
    changes_only = bool(body.get("changesOnly", False))
    start_line = body.get("startLine")
    end_line = body.get("endLine")

    resolved_commit = runtime.git.resolve_commit(str(body.get("commitHash") or "HEAD"))
    content = runtime.git.file_at_commit(resolved_commit, file_path)

    requested_voice = body.get("voice")
    if isinstance(requested_voice, str) and requested_voice:
        provider_name, _speech, voice = _find_voice_provider(runtime, requested_voice)
        voice_id = voice.id
    else:
        provider_name = runtime.config.speech.provider
        voice_id = runtime.config.speech.voice or ""

    explain_provider: LanguageModelProvider | None = None
    if mode == "explain":
        explain_provider = runtime.providers.get(runtime.config.provider.default)

    segments = build_segments(
        content,
        cast(Any, mode),
        skip_code,
        int(start_line) if isinstance(start_line, int | float) else None,
        int(end_line) if isinstance(end_line, int | float) else None,
        explain_provider,
        file_path,
        resolved_commit,
    )

    if changes_only:
        record = runtime.git.commit_metadata(resolved_commit)
        diff_text = runtime.git._diff(record, file_path, runtime.config.security.max_diff_chars)
        segments = filter_by_ranges(segments, changed_line_ranges(diff_text))

    session_id = f"reading_{uuid4().hex}"
    session: dict[str, Any] = {
        "id": session_id,
        "projectId": project_id,
        "filePath": file_path,
        "commitHash": resolved_commit,
        "voice": voice_id,
        "mode": mode,
        "segments": segments,
        "createdAt": datetime.now(UTC).isoformat(),
        "providerName": provider_name,
        "contentHash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "stopped": False,
    }
    with _reading_sessions_lock:
        _reading_sessions[session_id] = session
    return _reading_session_payload(session, runtime)


@app.get("/api/v1/reading-sessions/{session_id}")
def read_reading_session(session_id: str) -> dict[str, object]:
    with _reading_sessions_lock:
        session = _reading_sessions.get(session_id)
    if session is None:
        raise UnsafePathError("Sessão de leitura não encontrada.")
    _, runtime = projects.runtime(session["projectId"])
    return _reading_session_payload(session, runtime)


@app.post("/api/v1/reading-sessions/{session_id}/stop", status_code=204)
def stop_reading_session(session_id: str) -> Response:
    with _reading_sessions_lock:
        session = _reading_sessions.get(session_id)
        if session is None:
            raise UnsafePathError("Sessão de leitura não encontrada.")
        session["stopped"] = True
    return Response(status_code=204)


@app.get("/api/v1/reading-sessions/{session_id}/segments/{index}/audio")
def reading_session_segment_audio(session_id: str, index: int) -> Response:
    with _reading_sessions_lock:
        session = _reading_sessions.get(session_id)
    if session is None:
        raise UnsafePathError("Sessão de leitura não encontrada.")
    segments = cast(list[ReadingSegment], session["segments"])
    if index < 0 or index >= len(segments):
        raise UnsafePathError("Segmento não encontrado.")

    _, runtime = projects.runtime(session["projectId"])
    provider_name = cast(str, session["providerName"])
    voice_id = cast(str, session["voice"]) or None
    speech = get_speech_provider(provider_name, runtime.config, runtime.root, voice_id)
    if not speech.capabilities().produces_audio_files:
        raise UnsafePathError(
            f"O provider de fala '{provider_name}' fala direto no dispositivo local e não gera "
            "um arquivo de áudio para o navegador; configure um provider remoto (ex.: openai) "
            "para ouvir sessões de leitura pelo navegador."
        )
    result = speech.synthesize(
        SpeechRequest(text=segments[index].text, voice=voice_id, rate=runtime.config.speech.rate)
    )
    if result.audio_path is None:
        raise UnsafePathError("O provider de fala não retornou um arquivo de áudio.")
    media_type = _AUDIO_MEDIA_TYPES.get(
        getattr(speech, "response_format", "mp3"), "application/octet-stream"
    )
    return Response(content=result.audio_path.read_bytes(), media_type=media_type)


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
                lambda delta: (
                    _emit(state, {"type": "assistant.delta", "runId": run_id, "delta": delta})
                    if not cancelled.is_set()
                    else None
                ),
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
            message_id,
            thread_id,
            "assistant",
            result.response.text,
            scope,
            "complete",
            provider,
            None,
            json.dumps(sources),
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
