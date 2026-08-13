# DevMate

DevMate é uma assistente local para entender a evolução da documentação de um repositório Git. O contexto central é `repositório → branch → commit → documentos → decisões → perguntas → conversa`, e não apenas uma mensagem isolada.

## Estado atual

Este MVP é uma CLI local, read-only por padrão. Ele indexa mudanças em Markdown, armazena metadados e conversas em SQLite, responde com fontes, narra documentos localmente e só inclui código quando a pessoa pede uma inspeção explícita.

## Requisitos e instalação

O requisito oficial é Python 3.12+, Git e [uv](https://docs.astral.sh/uv/). O runtime não depende de uv após a instalação.

```bash
git clone ...
cd projeto
uv sync --all-extras
```

## Fluxo rápido (offline)

```bash
devmate init
devmate doctor
devmate scan
devmate ask --provider mock "O que mudou neste commit?"
devmate read README.md --dry-run
```

`scan` não faz rede; `mock` é determinístico e não chama uma LLM. Use `devmate status`, `timeline`, `decisions` e `questions` para consultar o estado local.

## Docker

O ambiente Docker inclui Python 3.12, Git, dependências bloqueadas em `uv.lock` e a CLI. A imagem não incorpora `.git`, `.devmate`, `.env` nem caches; o Compose monta o repositório atual, portanto o estado local continua no host.

```bash
docker compose build
docker compose run --rm devmate init
docker compose run --rm devmate scan
docker compose run --rm devmate ask --provider mock "O que mudou?"
docker compose run --rm devmate read README.md --dry-run
```

Para abrir o shell da imagem ou executar as verificações:

```bash
docker compose run --rm --entrypoint sh devmate
docker compose run --rm --entrypoint sh devmate -lc "uv sync --all-extras && uv run pytest"
```

Em contêiner, o provider de fala do sistema não acessa a voz do host; use `read --dry-run` ou altere o provider para `null` em testes. Providers remotos continuam opt-in e exigem as credenciais configuradas no ambiente do contêiner.

## Providers

O provider padrão é configurado em `.devmate/config.toml`, ou por `DEVMATE_PROVIDER`. Credenciais ficam somente no ambiente, nunca no TOML.

```bash
devmate providers list
devmate ask --provider mock "Explique a documentação"
OPENAI_API_KEY=... devmate ask --provider openai "Explique a documentação"
devmate inspect --provider codex --files src/app.py "O código segue docs/auth.md?"
```

`codex` usa o SDK oficial `openai-codex` em `Sandbox.read_only`, com um workspace temporário que contém apenas o contexto selecionado. `openai` usa Responses API. `openai_compatible` exige `provider.openai_base_url` configurado e não pressupõe ferramentas ou capabilities extras.

## Leitura em voz alta

```bash
devmate read docs/architecture.md --dry-run
devmate read docs/architecture.md --section "Segurança"
devmate read docs/architecture.md --resume
```

O provider `system` usa o mecanismo local do sistema operacional. `null` é disponível para testes. Checkpoints são guardados no SQLite e uma retomada é recusada se o arquivo mudar.

## Segurança

- Escopo padrão é `docs`: código só entra em `inspect`, `ask --scope code` ou uma seleção explícita.
- Caminhos, symlinks externos e padrões de segredos são bloqueados antes da leitura.
- O conteúdo do repositório é marcado como não confiável nos prompts.
- Git e TTS usam argumentos explícitos, timeout e nunca `shell=True`.
- Hooks só executam `scan --metadata-only`; não chamam providers.

Consulte [o threat model](docs/security.md).

## Desenvolvimento

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

## Limitações do MVP e roadmap

Não há embeddings, banco vetorial, interface web, edição automática, execução de testes por agentes, entrada por voz, PDFs nem sincronização em nuvem. Veja [o roadmap](docs/roadmap.md).
