"""Interface Typer do DevMate."""

from __future__ import annotations

import functools
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from devmate import __version__
from devmate.adapters.hotkey.windows_hotkey import WindowsHotkey
from devmate.application import voices_service
from devmate.application.codex_connection_service import (
    CodexAccount,
    CodexConnectionService,
    CodexLoginPrompt,
    LoginMethod,
)
from devmate.application.conversation_service import ConversationService
from devmate.application.daemon_service import DaemonService
from devmate.application.doctor_service import doctor
from devmate.application.hooks_service import hook_installed, install_hook, uninstall_hook
from devmate.application.inspection_service import InspectionContext
from devmate.application.project_service import initialize_project
from devmate.application.voice_service import VoiceHelp, VoiceReading
from devmate.bootstrap import Runtime, load_runtime
from devmate.config_writer import set_default_provider
from devmate.constants import ASSISTANT_NAME
from devmate.domain.enums import Scope
from devmate.domain.models import LLMRequest
from devmate.errors import DevMateError, ProviderUnavailableError
from devmate.logging import configure_logging
from devmate.prompts.code_inspection import CODE_INSPECTION_SYSTEM

app = typer.Typer(
    help="Assistente local e rastreável para documentação versionada.", no_args_is_help=True
)
providers_app = typer.Typer(help="Diagnóstico de providers.")
hooks_app = typer.Typer(help="Gerencie o hook Git local do DevMate.")
config_app = typer.Typer(help="Consulte a configuração local.")
codex_app = typer.Typer(help="Conecte, verifique e desconecte a conta Codex.")
app.add_typer(providers_app, name="providers")
app.add_typer(hooks_app, name="hooks")
app.add_typer(config_app, name="config")
app.add_typer(codex_app, name="codex")
console = Console()


def _run(action: Callable[[], Any], as_json: bool = False) -> Any:
    try:
        return action()
    except DevMateError as exc:
        if as_json:
            typer.echo(
                json.dumps({"error": str(exc), "exit_code": exc.exit_code}, ensure_ascii=False)
            )
        else:
            console.print(f"[red]Erro:[/red] {exc}")
        raise typer.Exit(exc.exit_code) from exc
    except (OSError, ValueError, RuntimeError) as exc:
        if as_json:
            typer.echo(json.dumps({"error": str(exc), "exit_code": 2}, ensure_ascii=False))
        else:
            console.print(f"[red]Erro:[/red] {exc}")
        raise typer.Exit(2) from exc


def _runtime() -> Runtime:
    return load_runtime(Path.cwd())


def _ensure_indexed(runtime: Runtime, commit: str | None = None) -> None:
    indexed_now = _run(functools.partial(runtime.ensure_indexed, commit))
    if indexed_now:
        console.print("[dim]Commit indexado localmente para esta execução.[/dim]")


def _answer_data(commit: str, text: str) -> dict[str, str]:
    return {"commit": commit, "answer": text}


@app.callback()
def root_callback(
    version: Annotated[bool, typer.Option("--version", help="Mostra a versão.")] = False,
    debug: Annotated[bool, typer.Option("--debug", help="Exibe logs técnicos seguros.")] = False,
) -> None:
    configure_logging(debug)
    if version:
        typer.echo(__version__)
        raise typer.Exit()


@app.command()
def init() -> None:
    """Inicializa configuração e banco local no repositório Git atual."""
    result = _run(lambda: initialize_project(Path.cwd()))
    if result is None:
        return
    console.print("[green]DevMate inicializado.[/green]\n")
    console.print(f"Repositório: {result.root}")
    console.print(f"Branch atual: {result.branch or 'HEAD destacado'}")
    console.print(f"Configuração: {result.config_path.relative_to(result.root)}")
    console.print(f"Banco: {result.database_path.relative_to(result.root)}")
    console.print(f"Provider padrão: {result.config.provider.default}")
    console.print(f"Speech provider: {result.config.speech.provider}\n")
    console.print("Próximos passos:\n  devmate doctor\n  devmate scan\n  devmate chat")


@app.command()
def scan(
    commit: Annotated[str | None, typer.Option("--commit")] = None,
    since: Annotated[str | None, typer.Option("--since")] = None,
    revision_range: Annotated[str | None, typer.Option("--range")] = None,
    all_reachable: Annotated[bool, typer.Option("--all-reachable")] = False,
    first_parent: Annotated[bool, typer.Option("--first-parent")] = False,
    metadata_only: Annotated[bool, typer.Option("--metadata-only")] = False,
    analyze: Annotated[bool, typer.Option("--analyze")] = False,
    provider: Annotated[str | None, typer.Option("--provider")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Indexa commits e mudanças Markdown sem rede por padrão."""
    del force
    runtime = _run(_runtime, as_json)
    if runtime is None:
        return
    revision = (
        commit
        or revision_range
        or (f"{since}..HEAD" if since else "--all" if all_reachable else "HEAD")
    )
    result = _run(
        lambda: runtime.scan_service().scan(runtime.project_id, revision, first_parent), as_json
    )
    if result is None:
        return
    if analyze and not metadata_only:
        name = provider or runtime.config.provider.default
        _run(
            lambda: ConversationService(
                runtime.store, runtime.context_service(), runtime.providers
            ).ask(
                runtime.project_id,
                "Resuma as mudanças documentais deste commit.",
                name,
                commit_ref=commit,
            ),
            as_json,
        )
    data = {
        "commits_seen": result.commits_seen,
        "commits_new": result.commits_created,
        "documents_changed": result.documents_changed,
        "network_called": bool(analyze and not metadata_only),
    }
    if as_json:
        typer.echo(json.dumps(data, ensure_ascii=False))
    elif not quiet:
        console.print(f"{result.commits_created} commits novos encontrados.")
        console.print(f"{result.documents_changed} documentos alterados.")
        console.print("Metadados armazenados.")
        if not analyze or metadata_only:
            console.print("Nenhuma chamada de LLM foi realizada.")


@app.command()
def status(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Mostra o estado local do projeto."""
    runtime = _run(_runtime, as_json)
    if runtime is None:
        return

    def build() -> dict[str, Any]:
        project_id = runtime.project_id
        latest = runtime.store.latest_commit(project_id)
        head = runtime.git.head()
        return {
            "repo": str(runtime.root),
            "branch": runtime.git.current_branch(),
            "head": head,
            "last_processed": latest.short_hash if latest else None,
            "documents_head": len(
                runtime.git.markdown_changes(
                    runtime.git.commit_metadata(head), runtime.config.security.max_diff_chars
                )
            ),
            "active_decisions": len(runtime.store.decisions(project_id, active_only=True)),
            "open_questions": len(runtime.store.questions(project_id, open_only=True)),
            "provider": runtime.config.provider.default,
            "speech_provider": runtime.config.speech.provider,
            "database": str(runtime.root / ".devmate" / "state.db"),
            "hook": hook_installed(runtime.git.common_dir()),
        }

    data = _run(build, as_json)
    if data is None:
        return
    if as_json:
        typer.echo(json.dumps(data, ensure_ascii=False, default=str))
        return
    table = Table(title="Status DevMate")
    table.add_column("Item")
    table.add_column("Valor")
    for key, value in data.items():
        table.add_row(key.replace("_", " "), str(value or "—"))
    console.print(table)


@app.command()
def ask(
    question: str,
    provider: Annotated[str | None, typer.Option("--provider")] = None,
    commit: Annotated[str | None, typer.Option("--commit")] = None,
    model: Annotated[str | None, typer.Option("--model")] = None,
    scope: Annotated[Scope, typer.Option("--scope")] = Scope.DOCS,
    files: Annotated[list[str] | None, typer.Option("--files")] = None,
    full_repo: Annotated[bool, typer.Option("--full-repo")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Faz uma pergunta sobre a documentação do commit indexado."""
    if scope is Scope.CODE:
        inspect(
            question,
            commit=commit,
            files=files,
            provider=provider,
            model=model,
            full_repo=full_repo or not files,
            as_json=as_json,
        )
        return
    runtime = _run(_runtime, as_json)
    if runtime is None:
        return
    _ensure_indexed(runtime, commit)
    answer = _run(
        lambda: ConversationService(
            runtime.store, runtime.context_service(), runtime.providers
        ).ask(
            runtime.project_id, question, provider or runtime.config.provider.default, commit, model
        ),
        as_json,
    )
    if answer is None:
        return
    data = _answer_data(answer.commit_hash, answer.response.text)
    if as_json:
        typer.echo(json.dumps(data, ensure_ascii=False))
    else:
        console.print(f"[bold]Commit {answer.commit_hash[:7]}[/bold]\n\n{answer.response.text}")


@app.command()
def chat(
    provider: Annotated[str | None, typer.Option("--provider")] = None,
    commit: Annotated[str | None, typer.Option("--commit")] = None,
) -> None:
    """Abre conversa interativa persistida no commit atual."""
    runtime = _run(_runtime)
    if runtime is None:
        return
    _ensure_indexed(runtime, commit)
    service = ConversationService(runtime.store, runtime.context_service(), runtime.providers)
    selected = _run(lambda: runtime.context_service().selected_commit(runtime.project_id, commit))
    if selected is None:
        return
    console.print(
        f"Conversa com [bold]{ASSISTANT_NAME}[/bold] no commit [bold]{selected.short_hash}[/bold]. "
        "Digite /exit para sair."
    )
    while True:
        try:
            question = typer.prompt("Você")
        except (EOFError, KeyboardInterrupt):
            console.print()
            return
        if question.strip().casefold() in {"/exit", "/quit", "sair"}:
            return

        def submit(text: str = question) -> Any:
            return service.ask(
                runtime.project_id,
                text,
                provider or runtime.config.provider.default,
                selected.commit_hash,
            )

        answer = _run(submit)
        if answer:
            console.print(f"\n[bold]{ASSISTANT_NAME}:[/bold] {answer.response.text}\n")


@app.command()
def listen(
    provider: Annotated[str | None, typer.Option("--provider")] = None,
    commit: Annotated[str | None, typer.Option("--commit")] = None,
    model: Annotated[str | None, typer.Option("--model")] = None,
    files: Annotated[
        list[str] | None,
        typer.Option("--files", help="Arquivos de código autorizados para a resposta."),
    ] = None,
    full_repo: Annotated[
        bool,
        typer.Option(
            "--full-repo", help="Autoriza a análise read-only dos arquivos de código suportados."
        ),
    ] = False,
    duration: Annotated[
        int | None,
        typer.Option("--duration", min=1, max=60, help="Segundos de captura do microfone."),
    ] = None,
    no_speak: Annotated[
        bool,
        typer.Option("--no-speak", help="Exibe a resposta sem narrá-la."),
    ] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Ouve uma pergunta e narra a resposta; código exige --files ou --full-repo."""
    runtime = _run(_runtime, as_json)
    if runtime is None:
        return
    _ensure_indexed(runtime, commit)
    seconds = duration or runtime.config.speech.input_duration_seconds
    scope_message = "com código selecionado" if files or full_repo else "com documentação"
    console.print(f"[cyan]Ouvindo por até {seconds} segundos ({scope_message}). Fale agora.[/cyan]")
    result = _run(
        lambda: runtime.voice_service().listen_and_ask(
            project_id=runtime.project_id,
            provider_name=provider or runtime.config.provider.default,
            commit_ref=commit,
            model=model,
            duration_seconds=duration,
            speak_response=not no_speak,
            code_files=files,
            full_repo=full_repo,
        ),
        as_json,
    )
    if result is None:
        return
    data: dict[str, Any]
    if isinstance(result, VoiceHelp):
        data = {
            "transcript": result.transcript,
            "action": "help",
            "answer": result.text,
        }
    elif isinstance(result, VoiceReading):
        data = {
            "transcript": result.transcript,
            "action": "read",
            "path": result.result.path,
            "segments": len(result.result.segments),
        }
    else:
        data = {
            "transcript": result.transcript,
            "commit": result.answer.commit_hash,
            "answer": result.answer.response.text,
        }
    if as_json:
        typer.echo(json.dumps(data, ensure_ascii=False))
        return
    console.print(f"[bold]Você:[/bold] {result.transcript}\n")
    if isinstance(result, VoiceHelp):
        console.print(f"[bold]{ASSISTANT_NAME}:[/bold] {result.text}")
        return
    if isinstance(result, VoiceReading):
        console.print(
            f"[bold]{ASSISTANT_NAME}:[/bold] Leitura local de {result.result.path} concluída."
        )
        return
    console.print(
        f"[bold]Commit {result.answer.commit_hash[:7]}[/bold]\n\n{result.answer.response.text}"
    )


@app.command()
def talk(
    provider: Annotated[str | None, typer.Option("--provider")] = None,
    commit: Annotated[str | None, typer.Option("--commit")] = None,
    model: Annotated[str | None, typer.Option("--model")] = None,
    files: Annotated[
        list[str] | None,
        typer.Option("--files", help="Arquivos de código autorizados para a resposta."),
    ] = None,
    full_repo: Annotated[
        bool,
        typer.Option(
            "--full-repo", help="Autoriza a análise read-only dos arquivos de código suportados."
        ),
    ] = False,
    duration: Annotated[
        int | None,
        typer.Option("--duration", min=1, max=60, help="Segundos de captura por rodada."),
    ] = None,
    no_speak: Annotated[
        bool,
        typer.Option("--no-speak", help="Exibe as respostas sem narrá-las."),
    ] = False,
) -> None:
    """Conversa contínua por voz; diga "sair" ou "tchau" para encerrar."""
    runtime = _run(_runtime)
    if runtime is None:
        return
    _ensure_indexed(runtime, commit)
    seconds = duration or runtime.config.speech.input_duration_seconds
    scope_message = "com código selecionado" if files or full_repo else "com documentação"
    console.print(
        f"[bold]{ASSISTANT_NAME}[/bold] está ouvindo {scope_message}, "
        f"{seconds}s por rodada.\n"
        f'Diga "sair" ou "tchau" para encerrar, ou use Ctrl+C.\n'
    )

    def rounds() -> Any:
        return runtime.voice_service().converse(
            project_id=runtime.project_id,
            provider_name=provider or runtime.config.provider.default,
            commit_ref=commit,
            model=model,
            duration_seconds=duration,
            speak_response=not no_speak,
            code_files=files,
            full_repo=full_repo,
            on_notice=lambda message: console.print(f"[yellow]{message}[/yellow]"),
        )

    stream = _run(rounds)
    if stream is None:
        return
    try:
        while True:
            console.print("[cyan]Ouvindo...[/cyan]")
            turn = _run(lambda: next(stream, None))
            if turn is None:
                break
            console.print(f"[bold]Você:[/bold] {turn.transcript}")
            if isinstance(turn, VoiceHelp):
                console.print(f"[bold]{ASSISTANT_NAME}:[/bold] {turn.text}\n")
                continue
            if isinstance(turn, VoiceReading):
                console.print(
                    f"[bold]{ASSISTANT_NAME}:[/bold] Leitura local de "
                    f"{turn.result.path} concluída.\n"
                )
                continue
            console.print(f"[bold]{ASSISTANT_NAME}:[/bold] {turn.answer.response.text}\n")
    except (EOFError, KeyboardInterrupt):
        console.print()
    console.print("[dim]Conversa encerrada.[/dim]")


@app.command()
def daemon(
    provider: Annotated[str | None, typer.Option("--provider")] = None,
    commit: Annotated[str | None, typer.Option("--commit")] = None,
    model: Annotated[str | None, typer.Option("--model")] = None,
    hotkey: Annotated[
        str | None, typer.Option("--hotkey", help="Combinação global, ex.: ctrl+alt+d.")
    ] = None,
    duration: Annotated[
        int | None,
        typer.Option("--duration", min=1, max=60, help="Segundos de captura por rodada."),
    ] = None,
    no_speak: Annotated[bool, typer.Option("--no-speak", help="Não narra as respostas.")] = False,
) -> None:
    """Mantém a Diana residente; o microfone só abre no atalho global."""
    runtime = _run(_runtime)
    if runtime is None:
        return
    combination = hotkey or runtime.config.daemon.hotkey
    trigger = WindowsHotkey(combination)
    available, reason = trigger.available()
    if not available:
        console.print(f"[red]Erro:[/red] {reason}")
        raise typer.Exit(6)

    input_provider = _run(runtime.speech_input)
    if input_provider is None:
        return
    if runtime.config.daemon.preload_model and hasattr(input_provider, "preload"):
        console.print("[dim]Carregando o modelo de voz...[/dim]")
        _run(input_provider.preload)

    service = DaemonService(
        trigger,
        runtime.voice_service(input_provider),
        before_round=lambda: _ensure_indexed(runtime, commit),
    )
    lock = runtime.daemon_lock()
    _run(lock.acquire)
    console.print(
        f"[bold]{ASSISTANT_NAME}[/bold] está ativa. Pressione "
        f"[bold]{combination}[/bold] para falar; Ctrl+C encerra."
    )
    try:
        with trigger:
            for round_result in service.run(
                project_id=runtime.project_id,
                provider_name=provider or runtime.config.provider.default,
                commit_ref=commit,
                model=model,
                duration_seconds=duration,
                speak_response=not no_speak,
            ):
                if round_result.error is not None:
                    console.print(f"[yellow]{round_result.error}[/yellow]")
                    continue
                answer = round_result.answer
                if answer is None:
                    continue
                console.print(f"[bold]Você:[/bold] {answer.transcript}")
                if isinstance(answer, VoiceHelp):
                    console.print(f"[bold]{ASSISTANT_NAME}:[/bold] {answer.text}\n")
                    continue
                if isinstance(answer, VoiceReading):
                    console.print(
                        f"[bold]{ASSISTANT_NAME}:[/bold] Leitura local de "
                        f"{answer.result.path} concluída.\n"
                    )
                    continue
                console.print(f"[bold]{ASSISTANT_NAME}:[/bold] {answer.answer.response.text}\n")
    except KeyboardInterrupt:
        console.print()
    finally:
        lock.release()
    console.print("[dim]Diana encerrada.[/dim]")


@app.command()
def inspect(
    question: str,
    commit: Annotated[str | None, typer.Option("--commit")] = None,
    files: Annotated[list[str] | None, typer.Option("--files")] = None,
    provider: Annotated[str | None, typer.Option("--provider")] = None,
    model: Annotated[str | None, typer.Option("--model")] = None,
    full_repo: Annotated[bool, typer.Option("--full-repo")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Inspeciona código somente sob solicitação explícita e read-only."""
    runtime = _run(_runtime, as_json)
    if runtime is None:
        return
    _ensure_indexed(runtime, commit)
    context = _run(
        lambda: runtime.inspection_service().build(
            runtime.project_id, commit, files or [], full_repo
        ),
        as_json,
    )
    if context is None:
        return
    response = _run(lambda: _inspect_response(runtime, context, question, provider, model), as_json)
    if response is None:
        return
    data = _answer_data(context.commit_hash, response.text)
    if as_json:
        typer.echo(json.dumps(data, ensure_ascii=False))
    else:
        console.print(
            f"[bold]Inspeção read-only — {context.commit_hash[:7]}[/bold]\n\n{response.text}"
        )


def _inspect_response(
    runtime: Runtime,
    context: InspectionContext,
    question: str,
    provider: str | None,
    model: str | None,
) -> Any:
    return runtime.providers.get(provider or runtime.config.provider.default).complete(
        LLMRequest(
            task="code_inspection",
            question=question,
            scope=Scope.CODE,
            chunks=context.chunks,
            system_instructions=CODE_INSPECTION_SYSTEM,
            model=model,
        )
    )


@app.command("read")
def read_document(
    path: str,
    section: Annotated[str | None, typer.Option("--section")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    resume: Annotated[bool, typer.Option("--resume")] = False,
    voice: Annotated[
        str | None,
        typer.Option("--voice", help="Sobrepõe a voz apenas nesta execução; não persiste."),
    ] = None,
    speech_provider: Annotated[
        str | None, typer.Option("--speech-provider", help="Sobrepõe o provider de fala.")
    ] = None,
) -> None:
    """Narra um Markdown local ou mostra os segmentos em modo dry-run."""
    runtime = _run(_runtime)
    if runtime is None:
        return
    result = _run(
        lambda: runtime.reading_service(speech_provider, voice).read(
            runtime.project_id, path, section, dry_run, resume
        )
    )
    if result is None:
        return
    console.print(f"Arquivo: {result.path}")
    console.print(f"Modo: {'dry-run' if dry_run else 'narrate'}")
    console.print(f"Seção: {section or 'documento completo'}")
    console.print(f"Segmentos: {len(result.segments)}\n")
    if dry_run:
        for segment in result.segments:
            console.print(f"[{segment.ordinal}/{len(result.segments)}] {segment.text}")


@app.command()
def timeline(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Lista a evolução indexada de commits e documentação."""
    runtime = _run(_runtime, as_json)
    if runtime is None:
        return
    commits = _run(lambda: runtime.store.commits(runtime.project_id), as_json)
    if commits is None:
        return
    if as_json:
        typer.echo(
            json.dumps(
                [
                    {
                        "commit": item.short_hash,
                        "subject": item.subject,
                        "documents": len(item.changes),
                    }
                    for item in commits
                ],
                ensure_ascii=False,
            )
        )
        return
    table = Table(title="Timeline")
    table.add_column("Commit")
    table.add_column("Data")
    table.add_column("Assunto")
    table.add_column("Docs")
    for item in commits:
        table.add_row(
            item.short_hash, item.committed_at.isoformat(), item.subject, str(len(item.changes))
        )
    console.print(table)


@app.command()
def decisions(
    active: Annotated[bool, typer.Option("--active")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Lista decisões extraídas conservadoramente da documentação."""
    runtime = _run(_runtime, as_json)
    if runtime is None:
        return
    items = _run(lambda: runtime.store.decisions(runtime.project_id, active), as_json)
    if items is None:
        return
    data = [asdict(item) for item in items]
    if as_json:
        typer.echo(json.dumps(data, ensure_ascii=False))
        return
    table = Table(title="Decisões")
    table.add_column("ID")
    table.add_column("Status")
    table.add_column("Título")
    table.add_column("Fonte")
    for item in items:
        source = f"{item.source_path}:L{item.source_start_line}@{(item.source_commit or '')[:7]}"
        table.add_row(str(item.id), f"{item.status}/{item.explicitness}", item.title, source)
    console.print(table)


@app.command()
def questions(
    open_only: Annotated[bool, typer.Option("--open")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Lista perguntas abertas encontradas na documentação."""
    runtime = _run(_runtime, as_json)
    if runtime is None:
        return
    items = _run(lambda: runtime.store.questions(runtime.project_id, open_only), as_json)
    if items is None:
        return
    data = [asdict(item) for item in items]
    if as_json:
        typer.echo(json.dumps(data, ensure_ascii=False))
        return
    table = Table(title="Perguntas")
    table.add_column("ID")
    table.add_column("Status")
    table.add_column("Pergunta")
    for item in items:
        table.add_row(str(item.id), item.status, item.question)
    console.print(table)


@providers_app.command("list")
def providers_list(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    runtime = _run(_runtime, as_json)
    if runtime is None:
        return
    entries = runtime.providers.entries()
    if as_json:
        typer.echo(
            json.dumps(
                [{"name": n, "available": a, "detail": d} for n, a, d in entries],
                ensure_ascii=False,
            )
        )
        return
    table = Table(title="Providers")
    table.add_column("Nome")
    table.add_column("Disponível")
    table.add_column("Detalhe")
    for name, available, detail in entries:
        table.add_row(name, "sim" if available else "não", detail or "—")
    console.print(table)


@providers_app.command("doctor")
def providers_doctor(name: str) -> None:
    runtime = _run(_runtime)
    if runtime is None:
        return
    provider = _run(lambda: runtime.providers.get(name))
    if provider is None:
        return
    available, detail = provider.available()
    console.print(
        f"{name}: {'disponível' if available else 'indisponível'} — {detail or 'configurado'}"
    )


voices_app = typer.Typer(help="Liste, compare e escolha a voz de narração.")
app.add_typer(voices_app, name="voices")


def _voice_provider_and_list(
    runtime: Runtime, provider_name: str | None
) -> tuple[str, Any, list[Any]]:
    name = provider_name or runtime.config.speech.provider
    provider = runtime.speech_provider(name)
    return name, provider, provider.list_voices()


@voices_app.command("list")
def voices_list(
    provider: Annotated[
        str | None, typer.Option("--provider", help="system, openai ou null.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Lista as vozes que o provider selecionado consegue descobrir."""
    runtime = _run(_runtime, as_json)
    if runtime is None:
        return
    result = _run(lambda: _voice_provider_and_list(runtime, provider), as_json)
    if result is None:
        return
    name, _speech, found = result
    selected = runtime.config.speech.voice
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "provider": name,
                    "selected": selected,
                    "voices": [
                        {
                            "id": voice.id,
                            "provider": voice.provider,
                            "selected": voice.id == selected,
                            "preview_supported": voice.preview_supported,
                        }
                        for voice in found
                    ],
                },
                ensure_ascii=False,
            )
        )
        return
    if not found:
        console.print(f"[yellow]O provider '{name}' não expôs nenhuma voz.[/yellow]")
        return
    table = Table(title=f"{name.capitalize()} voices")
    table.add_column("Voice")
    table.add_column("Provider")
    table.add_column("Selected")
    table.add_column("Description")
    for voice in found:
        is_selected = "✓" if voice.id == selected else ""
        table.add_row(voice.id, voice.provider, is_selected, voice.description or "")
    console.print(table)
    console.print(f"\nCurrent voice: {selected or '(padrão do provider)'}")


@voices_app.command("current")
def voices_current(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Mostra o provider, a voz, o modelo e o ritmo configurados."""
    runtime = _run(_runtime, as_json)
    if runtime is None:
        return
    current = voices_service.current_voice(runtime.config)
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "provider": current.provider,
                    "voice": current.voice,
                    "model": current.model,
                    "language": current.language,
                    "rate": current.rate,
                    "style": current.style,
                },
                ensure_ascii=False,
            )
        )
        return
    console.print(f"Speech provider: {current.provider}")
    console.print(f"Voice: {current.voice or '(padrão do provider)'}")
    if current.model:
        console.print(f"Model: {current.model}")
    console.print(f"Language: {current.language}")
    console.print(f"Rate: {current.rate}")
    if current.style:
        console.print(f"Style: {current.style}")


@voices_app.command("set")
def voices_set(
    voice: str,
    provider: Annotated[
        str | None, typer.Option("--provider", help="Também grava [speech].provider.")
    ] = None,
    project: Annotated[
        bool, typer.Option("--project", help="Escopo do projeto (único disponível hoje).")
    ] = True,
    global_scope: Annotated[
        bool,
        typer.Option(
            "--global", help="Ainda não suportado; ver docs/voice-usage.md#escopos-de-voz."
        ),
    ] = False,
) -> None:
    """Define a voz padrão em `.devmate/config.toml`, preservando o resto do arquivo."""
    del project
    if global_scope:
        console.print(
            "[yellow]--global ainda não é suportado.[/yellow] "
            "Hoje só existe configuração por projeto; "
            "veja docs/voice-usage.md#escopos-de-voz para o plano de evolução."
        )
        raise typer.Exit(2)
    runtime = _run(_runtime)
    if runtime is None:
        return
    target_provider = provider or runtime.config.speech.provider
    _run(
        lambda: voices_service.persist_voice(
            runtime.root / ".devmate" / "config.toml", target_provider, voice, provider is not None
        )
    )
    console.print(f"Voice '{voice}' definida como voz padrão do projeto.")


@voices_app.command("preview")
def voices_preview(
    voice: Annotated[str | None, typer.Argument()] = None,
    all_voices: Annotated[bool, typer.Option("--all", help="Compara todas as vozes.")] = False,
    text: Annotated[str | None, typer.Option("--text", help="Frase personalizada.")] = None,
    file: Annotated[
        str | None, typer.Option("--file", help="Lê a frase de um Markdown do repositório.")
    ] = None,
    provider: Annotated[str | None, typer.Option("--provider")] = None,
    pause_between: Annotated[
        float, typer.Option("--pause-between", help="Segundos entre uma voz e a próxima.")
    ] = 1.0,
    yes: Annotated[bool, typer.Option("--yes", help="Não pede confirmação de custo.")] = False,
) -> None:
    """Gera e reproduz uma amostra por voz, uma de cada vez."""
    if voice is None and not all_voices:
        console.print("[red]Erro:[/red] informe uma voz ou use --all.")
        raise typer.Exit(2)
    runtime = _run(_runtime)
    if runtime is None:
        return
    provider_name = provider or runtime.config.speech.provider
    speech = runtime.speech_provider(provider_name)
    known = _run(speech.list_voices)
    if known is None:
        return
    targets = _run(lambda: voices_service.resolve_voice_target(voice or "", all_voices, known))
    if targets is None:
        return

    phrase = text
    if file is not None:
        _, content, _ = runtime.filesystem.read_text(file)
        phrase = content

    openai_model = runtime.config.speech.providers.openai.model
    plans = voices_service.build_preview_plan(
        speech, targets, phrase, runtime.config.speech.rate, openai_model
    )
    pending = voices_service.uncached_count(plans)
    capabilities = speech.capabilities()
    if capabilities.remote and pending and not yes:
        console.print(
            f"{pending} amostra(s) serão geradas usando o provider {provider_name}.\n"
            "Isso realizará chamadas à API.\n"
        )
        if not typer.confirm("Continuar?", default=True):
            raise typer.Exit(0)

    total = len(plans)
    for index, plan in enumerate(plans, start=1):
        console.print(f"Voice {index}/{total}: {plan.voice.id}")
        _synthesize_and_play(speech, plan.request)
        if index < total and pause_between > 0:
            time.sleep(pause_between)
        console.print()


def _synthesize_and_play(speech: Any, request: Any) -> None:
    outcome = _run(functools.partial(speech.synthesize, request))
    if outcome is None:
        return
    console.print("Playing..." if not outcome.cached else "Playing (cache)...")
    player = getattr(speech, "player", None)
    if outcome.audio_path is not None and player is not None:
        _run(functools.partial(player.play, outcome.audio_path))


@voices_app.command("choose")
def voices_choose(
    provider: Annotated[str | None, typer.Option("--provider")] = None,
) -> None:
    """Fluxo interativo: listar, ouvir uma prévia e confirmar a escolha."""
    runtime = _run(_runtime)
    if runtime is None:
        return
    provider_name = provider or runtime.config.speech.provider
    speech = runtime.speech_provider(provider_name)
    known = _run(speech.list_voices)
    if known is None or not known:
        console.print(f"[yellow]O provider '{provider_name}' não expôs nenhuma voz.[/yellow]")
        return
    console.print(f"Escolha uma voz {provider_name.capitalize()}\n")
    for index, info in enumerate(known, start=1):
        console.print(f"[{index}] {info.id}")
    console.print()
    choice = typer.prompt("Digite o número da voz", type=int, default=0, show_default=False)
    if choice < 1 or choice > len(known):
        console.print("[red]Número inválido.[/red]")
        raise typer.Exit(2)
    selected = known[choice - 1]
    console.print(f"\nVoice: {selected.id}\n")
    while True:
        prompt = "[P] Preview  [S] Select  [B] Back  [Q] Quit"
        action = typer.prompt(prompt, default="s").strip().casefold()
        if action == "p":
            plans = voices_service.build_preview_plan(
                speech, [selected], None, runtime.config.speech.rate, None
            )
            _synthesize_and_play(speech, plans[0].request)
            continue
        if action == "b":
            voices_choose(provider=provider)
            return
        if action == "q":
            return
        _run(
            lambda: voices_service.persist_voice(
                runtime.root / ".devmate" / "config.toml", provider_name, selected.id, False
            )
        )
        console.print(f"Voice '{selected.id}' definida como voz padrão do projeto.")
        return


@app.command("commands")
def voice_commands(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Lista os comandos especiais que a Diana reconhece por voz."""
    runtime = _run(_runtime, as_json)
    if runtime is None:
        return
    commands = runtime.config.voice.commands
    data = [
        {
            "phrases": command.phrases,
            "action": command.action,
            "path": command.path,
            "section": command.section,
        }
        for command in commands
    ]
    if as_json:
        typer.echo(json.dumps({"commands": data}, ensure_ascii=False))
        return
    table = Table(title="Comandos especiais de voz")
    table.add_column("Frases")
    table.add_column("Ação")
    table.add_column("Destino")
    for command in commands:
        destination = command.path or "orientação local"
        if command.section:
            destination = f"{destination} — {command.section}"
        table.add_row(", ".join(command.phrases), command.action, destination)
    console.print(table)
    console.print(
        "\n[dim]Edite a seção voice.commands em .devmate/config.toml e reinicie a Diana "
        "para aplicar alterações.[/dim]"
    )


_LOGIN_METHODS: dict[str, LoginMethod] = {
    "device": "device",
    "browser": "browser",
    "api-key": "api_key",
}


def _print_codex_account(account: CodexAccount) -> None:
    if not account.connected:
        console.print("Não conectada.")
        return
    if account.method == "chatgpt":
        console.print(f"Conta: {account.email or '(sem e-mail informado)'}")
        if account.plan:
            console.print(f"Plano: {account.plan}")
    elif account.method == "apiKey":
        console.print("Login via chave de API.")
    elif account.method == "amazonBedrock":
        console.print("Login via Amazon Bedrock.")
    else:
        console.print(f"Conectada ({account.method or 'método desconhecido'}).")


@app.command()
def serve(
    host: Annotated[
        str,
        typer.Option("--host", help="127.0.0.1 por padrão; evite 0.0.0.0 fora de rede confiável."),
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8000,
    reload: Annotated[bool, typer.Option("--reload", help="Recarrega ao editar o código.")] = False,
) -> None:
    """Sobe a API HTTP local para um frontend, sem passar pela CLI via subprocess."""
    import uvicorn

    console.print(f"[bold]{ASSISTANT_NAME}[/bold] API em http://{host}:{port}/api/v1")
    uvicorn.run("devmate.api.app:app", host=host, port=port, reload=reload)


@codex_app.command("status")
def codex_status(
    refresh: Annotated[
        bool,
        typer.Option(
            "--refresh",
            help="Valida o token contra a API em vez de só ler a sessão em cache.",
        ),
    ] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Mostra se há uma conta Codex conectada nesta máquina, sem iniciar login.

    Por padrão lê apenas a sessão em cache: pode mostrar "conectada" mesmo com o
    token expirado. Use --refresh antes de confiar na resposta para diagnosticar
    um erro 401 em chamadas reais.
    """
    service = CodexConnectionService()
    available, reason = service.available()
    if not available:
        if as_json:
            typer.echo(json.dumps({"connected": False, "reason": reason}, ensure_ascii=False))
        else:
            console.print(f"[yellow]{reason}[/yellow]")
        return
    account = _run(functools.partial(service.status, refresh), as_json)
    if account is None:
        return
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "connected": account.connected,
                    "method": account.method,
                    "email": account.email,
                    "plan": account.plan,
                },
                ensure_ascii=False,
            )
        )
        return
    _print_codex_account(account)


def _offer_codex_as_default(set_default: bool | None) -> None:
    if set_default is False:
        return
    runtime = _run(_runtime)
    if runtime is None:
        return
    if runtime.config.provider.default == "codex":
        return
    if set_default is None and not typer.confirm(
        "\nDefinir codex como provider padrão deste projeto?", default=True
    ):
        return
    config_path = runtime.root / ".devmate" / "config.toml"
    _run(functools.partial(set_default_provider, config_path, "codex"))
    console.print("Provider padrão definido como codex.")


def _print_full_repo_tip() -> None:
    console.print(
        "\nPara respostas com contexto de código (não só documentação), autorize "
        "explicitamente o escopo:\n"
        "  devmate talk --provider codex --full-repo\n"
        '  devmate ask --provider codex --scope code --full-repo "..."'
    )


@codex_app.command("connect")
def codex_connect(
    method: Annotated[str, typer.Option("--method", help="device, browser ou api-key.")] = "device",
    api_key_env: Annotated[
        str, typer.Option("--api-key-env", help="Variável lida quando --method api-key.")
    ] = "OPENAI_API_KEY",
    force: Annotated[
        bool, typer.Option("--force", help="Refaz o login mesmo se já houver uma conta conectada.")
    ] = False,
    set_default: Annotated[
        bool | None,
        typer.Option(
            "--set-default/--no-set-default",
            help="Define codex como provider padrão sem perguntar.",
        ),
    ] = None,
) -> None:
    """Conecta esta máquina à sua conta Codex, para que a Diana leia o projeto com sentido."""
    resolved = _LOGIN_METHODS.get(method)
    if resolved is None:
        console.print(
            f"[red]Erro:[/red] método desconhecido '{method}'. Use device, browser ou api-key."
        )
        raise typer.Exit(2)

    service = CodexConnectionService()
    if not force:
        # refresh=True porque a leitura em cache pode dizer "conectada" com um
        # token de acesso já expirado; sem validar, o --full-repo falharia depois
        # com 401 mesmo tendo passado por aqui. Uma falha na validação (sessão
        # realmente morta) não deve abortar o comando: cai para o login normal.
        try:
            current: CodexAccount | None = service.status(refresh=True)
        except ProviderUnavailableError:
            current = None
        if current is not None and current.connected:
            console.print("[green]Diana já está conectada ao Codex.[/green]")
            _print_codex_account(current)
            _print_full_repo_tip()
            _offer_codex_as_default(set_default)
            return

    api_key = os.getenv(api_key_env) if resolved == "api_key" else None
    if resolved == "api_key" and not api_key:
        console.print(f"[red]Erro:[/red] a variável {api_key_env} não está configurada.")
        raise typer.Exit(2)

    def prompt(login_prompt: CodexLoginPrompt) -> None:
        if login_prompt.user_code:
            console.print(
                f"Acesse {login_prompt.verification_url} e informe o código "
                f"[bold]{login_prompt.user_code}[/bold]."
            )
        elif login_prompt.verification_url:
            console.print(f"Abra {login_prompt.verification_url} para concluir o login.")
        console.print("[dim]Aguardando confirmação...[/dim]")

    account = _run(functools.partial(service.connect, resolved, api_key, prompt))
    if account is None:
        return
    console.print("[green]Diana conectada ao Codex.[/green]")
    _print_codex_account(account)
    _print_full_repo_tip()
    _offer_codex_as_default(set_default)


@codex_app.command("disconnect")
def codex_disconnect() -> None:
    """Encerra a sessão Codex local desta máquina (equivalente a um logout)."""
    service = CodexConnectionService()
    result = _run(service.disconnect)
    if result is None:
        return
    console.print("Sessão Codex encerrada.")


@app.command("doctor")
def doctor_command() -> None:
    """Diagnostica ambiente local sem executar providers remotos."""
    runtime = _run(_runtime)
    if runtime is None:
        return
    checks = _run(lambda: doctor(runtime))
    if checks is None:
        return
    table = Table(title="DevMate doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detalhe")
    for check in checks:
        table.add_row(check.name, "ok" if check.ok else "atenção", check.detail)
    console.print(table)


@hooks_app.command("install")
def hooks_install() -> None:
    runtime = _run(_runtime)
    if runtime:
        path = _run(lambda: install_hook(runtime.git.common_dir()))
        if path:
            console.print(f"Hook instalado: {path}")


@hooks_app.command("uninstall")
def hooks_uninstall() -> None:
    runtime = _run(_runtime)
    if runtime:
        removed = _run(lambda: uninstall_hook(runtime.git.common_dir()))
        console.print("Hook removido." if removed else "Hook DevMate não estava instalado.")


@hooks_app.command("status")
def hooks_status() -> None:
    runtime = _run(_runtime)
    if runtime:
        console.print("instalado" if hook_installed(runtime.git.common_dir()) else "não instalado")


@config_app.command("show")
def config_show() -> None:
    runtime = _run(_runtime)
    if runtime:
        typer.echo(runtime.config.model_dump_json(indent=2))


@config_app.command("path")
def config_show_path() -> None:
    runtime = _run(_runtime)
    if runtime:
        typer.echo(str(runtime.root / ".devmate" / "config.toml"))


@config_app.command("validate")
def config_validate() -> None:
    runtime = _run(_runtime)
    if runtime:
        console.print("Configuração válida.")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    app()


def talk_main() -> None:
    """Atalho ``diana``: conversa por voz direto, sem subcomando.

    Qualquer outro subcomando continua acessível (``diana scan``, ``diana doctor``),
    portanto o atalho não esconde o resto da CLI.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    known = {
        command.name or (command.callback.__name__ if command.callback else "")
        for command in app.registered_commands
    }
    known.update({"providers", "hooks", "config", "--help", "-h", "--version"})
    arguments = sys.argv[1:]
    if not arguments or arguments[0] not in known:
        sys.argv = [sys.argv[0], "talk", *arguments]
    app()
