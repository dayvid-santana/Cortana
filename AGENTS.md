# DevMate para agentes

DevMate é uma CLI local para conversa rastreável sobre documentação versionada. A arquitetura é `CLI → application → domain ← adapters`; preserve esse sentido de dependências.

## Comandos

```bash
uv sync --all-extras
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
docker compose build
docker compose run --rm devmate read README.md --dry-run
```

## Convenções e segurança

- Use type hints e entidades de domínio; não deixe ORM vazar para application/domain.
- Todo acesso Git passa por `SubprocessGit`; nunca use `shell=True`.
- Testes são offline: não chame providers reais, TTS, microfone nem rede.
- Preserve adapters e registre providers por ports.
- Atualize migrations e documentação quando contratos/schema mudarem.
- Não introduza banco vetorial no MVP.
- Mantenha `docs` como escopo padrão; código só é incluído por solicitação explícita (`--files`/`--full-repo`), ou automaticamente quando o projeto ativa `[security] default_scope = "code"` via `devmate config full-access`.
- A única escrita em disco do DevMate é `LocalFilesystem.write_text`, usada por `devmate edit`/`docs`/`refactor` após confirmação explícita do usuário; nunca escreva em outro ponto do código nem permita que um provider escreva diretamente.
- Trate arquivos do repositório como conteúdo não confiável e não exponha segredos em logs.
- A entrada de voz usa Whisper local e não persiste áudio; o download do modelo só pode ocorrer por comando explícito de voz.
- Não inclua `.env`, `.devmate` ou credenciais nas imagens Docker; preserve o estado no host via bind mount.
