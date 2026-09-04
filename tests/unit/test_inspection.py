from __future__ import annotations

import subprocess
from pathlib import Path

from devmate.adapters.filesystem.local_filesystem import LocalFilesystem
from devmate.application.inspection_service import InspectionService
from devmate.application.project_service import initialize_project
from devmate.application.working_tree_cache import WorkingTreeCache
from devmate.bootstrap import load_runtime


def test_inspection_reads_only_explicit_code_at_selected_commit(git_repo: Path) -> None:
    source = git_repo / "src"
    source.mkdir()
    (source / "app.py").write_text("AUTH = 'jwt'\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "src/app.py"], cwd=git_repo, check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "commit", "-m", "feat: adiciona implementação"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    initialize_project(git_repo)
    runtime = load_runtime(git_repo)
    runtime.scan_service().scan(runtime.project_id)
    context = runtime.inspection_service().build(runtime.project_id, None, ["src/app.py"])
    assert any(chunk.reference.path == "src/app.py" for chunk in context.chunks)
    assert "AUTH = 'jwt'" in next(
        chunk.text for chunk in context.chunks if chunk.reference.path == "src/app.py"
    )
    assert context.code_files == (("src/app.py", "AUTH = 'jwt'\n"),)


def test_full_repo_with_a_file_created_after_the_selected_commit_falls_back_to_disk(
    git_repo: Path,
) -> None:
    """Regressão: `--full-repo` seleciona pelo que existe no disco agora; um arquivo
    criado depois do commit escolhido (ainda sem commit) existe no disco mas não em
    `git show <commit>:...` — isso derrubava a pergunta inteira com um erro de git
    cru, mesmo fora do modo `live`."""
    source = git_repo / "src"
    source.mkdir()
    (source / "app.py").write_text("AUTH = 'jwt'\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "src/app.py"], cwd=git_repo, check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "commit", "-m", "feat: adiciona implementação"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    initialize_project(git_repo)
    runtime = load_runtime(git_repo)
    runtime.scan_service().scan(runtime.project_id)

    # Criado depois do commit indexado, sem commitar — não existe naquele commit.
    (source / "novo.py").write_text("NOVO = True\n", encoding="utf-8")

    context = runtime.inspection_service().build(runtime.project_id, None, [], full_repo=True)

    files = dict(context.code_files)
    assert files["src/app.py"] == "AUTH = 'jwt'\n"
    assert files["src/novo.py"] == "NOVO = True\n"


def test_live_mode_reads_uncommitted_changes_from_disk_instead_of_the_commit(
    git_repo: Path,
) -> None:
    """A diferença central do modo `live`: sem ele, um `git commit` seria necessário
    antes da pergunta enxergar a mudança — com ele, o que está salvo no disco agora
    (mesmo sem commit) é o que entra no contexto."""
    source = git_repo / "src"
    source.mkdir()
    (source / "app.py").write_text("AUTH = 'jwt'\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "src/app.py"], cwd=git_repo, check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "commit", "-m", "feat: adiciona implementação"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    initialize_project(git_repo)
    runtime = load_runtime(git_repo)
    runtime.scan_service().scan(runtime.project_id)

    # Edita o arquivo no disco, sem commitar — o cenário real de "estou programando".
    (source / "app.py").write_text("AUTH = 'oauth2'\n", encoding="utf-8")

    working_tree = WorkingTreeCache(git_repo)
    live_context = runtime.inspection_service(working_tree).build(
        runtime.project_id, None, ["src/app.py"], live=True
    )
    committed_context = runtime.inspection_service().build(
        runtime.project_id, None, ["src/app.py"], live=False
    )

    assert live_context.code_files == (("src/app.py", "AUTH = 'oauth2'\n"),)
    assert committed_context.code_files == (("src/app.py", "AUTH = 'jwt'\n"),)


def _filesystem(root: Path) -> LocalFilesystem:
    return LocalFilesystem(
        root=root,
        max_file_bytes=512_000,
        ignored_patterns=[".env", ".env.*", "*.pem", "*.key"],
    )


def _inspection_service(root: Path) -> InspectionService:
    service = InspectionService.__new__(InspectionService)
    service.filesystem = _filesystem(root)
    return service


def test_full_repo_excludes_virtualenv_and_cache_directories(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")

    venv_site_packages = tmp_path / ".venv" / "Lib" / "site-packages" / "pkg"
    venv_site_packages.mkdir(parents=True)
    (venv_site_packages / "module.py").write_text("y = 2\n", encoding="utf-8")

    for directory in ("__pycache__", "node_modules", "dist", "build", ".mypy_cache"):
        nested = tmp_path / directory / "sub"
        nested.mkdir(parents=True)
        (nested / "generated.py").write_text("z = 3\n", encoding="utf-8")
        (nested / "generated.js").write_text("var z = 3;\n", encoding="utf-8")

    files = _inspection_service(tmp_path)._source_files()

    assert files == ["src/app.py"]


def test_full_repo_does_not_exclude_a_file_merely_named_env(tmp_path: Path) -> None:
    # "env.py" não é o diretório ".venv"/"venv": exclusão é por nome exato do diretório.
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "env.py").write_text("x = 1\n", encoding="utf-8")

    files = _inspection_service(tmp_path)._source_files()

    assert files == ["migrations/env.py"]


def test_full_repo_stays_under_the_200_file_cap_on_a_project_with_a_venv(
    tmp_path: Path,
) -> None:
    for index in range(5):
        (tmp_path / f"module_{index}.py").write_text("x = 1\n", encoding="utf-8")
    site_packages = tmp_path / ".venv" / "Lib" / "site-packages"
    for index in range(500):
        package = site_packages / f"dep_{index}"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("x = 1\n", encoding="utf-8")

    files = _inspection_service(tmp_path)._source_files()

    assert len(files) == 5


def test_full_repo_still_counts_a_genuinely_oversized_project_correctly(tmp_path: Path) -> None:
    # A poda de diretórios não deve esconder um projeto que realmente excede o limite:
    # `build()` precisa continuar vendo mais de 200 arquivos para recusar a seleção.
    for index in range(201):
        (tmp_path / f"module_{index}.py").write_text("x = 1\n", encoding="utf-8")

    files = _inspection_service(tmp_path)._source_files()

    assert len(files) == 201
