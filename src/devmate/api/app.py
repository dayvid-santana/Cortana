"""API HTTP fina sobre os mesmos application services usados pela CLI.

Nunca chama a CLI por subprocess: monta os mesmos ``ConversationService`` /
``InspectionConversationService`` que ``devmate ask``/``chat`` usam, então as
regras de escopo, segurança e citações são exatamente as mesmas dos dois lados.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from devmate.api.dependencies import get_runtime
from devmate.api.errors import status_for
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
_ALLOWED_ORIGINS = ["http://127.0.0.1:5173", "http://localhost:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


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


def _system_instructions(body: ChatRequest) -> str:
    if body.source == "speech":
        return f"{API_CHAT_SYSTEM}\n\nEntrada: transcrição de voz. Seja mais concisa e direta."
    return API_CHAT_SYSTEM


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
