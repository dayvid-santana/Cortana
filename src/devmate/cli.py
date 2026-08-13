"""Interface Typer do DevMate."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from devmate import __version__
from devmate.application.conversation_service import ConversationService
from devmate.application.doctor_service import doctor
from devmate.application.hooks_service import hook_installed, install_hook, uninstall_hook
from devmate.application.inspection_service import InspectionContext
from devmate.application.project_service import initialize_project
from devmate.bootstrap import Runtime, load_runtime
from devmate.domain.enums import Scope
from devmate.domain.models import LLMRequest
from devmate.errors import DevMateError
from devmate.logging import configure_logging
from devmate.prompts.code_inspection import CODE_INSPECTION_SYSTEM

app = typer.Typer(
    help="Assistente local e rastreável para documentação versionada.", no_args_is_help=True
)
providers_app = typer.Typer(help="Diagnóstico de providers.")
hooks_app = typer.Typer(help="Gerencie o hook Git local do DevMate.")
config_app = typer.Typer(help="Consulte a configuração local.")
app.add_typer(providers_app, name="providers")
app.add_typer(hooks_app, name="hooks")
app.add_typer(config_app, name="config")
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
    service = ConversationService(runtime.store, runtime.context_service(), runtime.providers)
    selected = _run(lambda: runtime.context_service().selected_commit(runtime.project_id, commit))
    if selected is None:
        return
    console.print(f"Conversa no commit [bold]{selected.short_hash}[/bold]. Digite /exit para sair.")
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
            console.print(f"\n{answer.response.text}\n")


@app.command()
def listen(
    provider: Annotated[str | None, typer.Option("--provider")] = None,
    commit: Annotated[str | None, typer.Option("--commit")] = None,
    model: Annotated[str | None, typer.Option("--model")] = None,
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
    """Ouve uma pergunta, responde sobre a documentação e narra o resultado."""
    runtime = _run(_runtime, as_json)
    if runtime is None:
        return
    seconds = duration or runtime.config.speech.input_duration_seconds
    console.print(f"[cyan]Ouvindo por até {seconds} segundos. Fale agora.[/cyan]")
    result = _run(
        lambda: runtime.voice_service().listen_and_ask(
            project_id=runtime.project_id,
            provider_name=provider or runtime.config.provider.default,
            commit_ref=commit,
            model=model,
            duration_seconds=duration,
            speak_response=not no_speak,
        ),
        as_json,
    )
    if result is None:
        return
    data = {
        "transcript": result.transcript,
        "commit": result.answer.commit_hash,
        "answer": result.answer.response.text,
    }
    if as_json:
        typer.echo(json.dumps(data, ensure_ascii=False))
        return
    console.print(f"[bold]Você:[/bold] {result.transcript}\n")
    console.print(
        f"[bold]Commit {result.answer.commit_hash[:7]}[/bold]\n\n{result.answer.response.text}"
    )


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
) -> None:
    """Narra um Markdown local ou mostra os segmentos em modo dry-run."""
    runtime = _run(_runtime)
    if runtime is None:
        return
    result = _run(
        lambda: runtime.reading_service().read(runtime.project_id, path, section, dry_run, resume)
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
