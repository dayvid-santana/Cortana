# Uso do DevMate com Docker

Este guia explica como executar e testar o DevMate sem instalar Python ou uv na máquina host. É necessário ter Git e Docker Desktop instalados.

## 1. Inicie o Docker Desktop

Antes de usar os comandos, confirme que o daemon Docker está em execução:

```powershell
docker version
docker compose version
```

Se aparecer uma mensagem sobre `docker_engine` não encontrado, abra o Docker Desktop e espere o serviço iniciar.

## 2. Construa a imagem

No diretório do projeto DevMate:

```powershell
docker compose build
docker compose run --rm devmate --help
```

O Compose monta o repositório atual em `/workspace`. Por isso, a configuração `.devmate/`, o banco SQLite e os checkpoints permanecem no computador host.

## 3. Primeiro uso em um repositório

Execute os comandos abaixo no diretório do repositório que será analisado:

```powershell
docker compose run --rm devmate init
docker compose run --rm devmate doctor
docker compose run --rm devmate scan
docker compose run --rm devmate status
```

`init` cria `.devmate/config.toml` e `.devmate/state.db`. `scan` indexa commits e alterações Markdown localmente; ele não chama providers remotos.

## 4. Perguntas offline com MockProvider

O MockProvider é determinístico e não usa rede. Ele é o melhor modo para testar o fluxo completo:

```powershell
docker compose run --rm devmate ask --provider mock "O que mudou na documentação?"
docker compose run --rm devmate timeline
docker compose run --rm devmate decisions
docker compose run --rm devmate questions
```

Para conversar interativamente:

```powershell
docker compose run --rm -it devmate chat --provider mock
```

Digite `/exit` para encerrar a conversa.

## 5. Leitura de Markdown

Em contêiner, o provider de fala não acessa o áudio do host. Use `--dry-run` para revisar exatamente os segmentos que seriam narrados:

```powershell
docker compose run --rm devmate read README.md --dry-run
docker compose run --rm devmate read docs/architecture.md --section "Arquitetura" --dry-run
```

Da mesma forma, a captura do microfone para `devmate listen` deve ser executada no host, não no contêiner Docker.

## 6. Inspeção explícita de código

O contexto padrão do DevMate contém somente documentação. Para incluir código, escolha os arquivos de maneira explícita:

```powershell
docker compose run --rm devmate inspect --provider mock --files src/app.py "O código segue a documentação?"
```

Alternativamente:

```powershell
docker compose run --rm devmate ask --scope code --files src/app.py --provider mock "Verifique a consistência com a documentação."
```

`--full-repo` inclui os arquivos de código suportados, mas deve ser usado apenas quando esse escopo amplo for realmente necessário.

## 7. Providers remotos

Providers remotos são opt-in. Nunca grave chaves em `.devmate/config.toml` ou no repositório.

Exemplo com OpenAI, fornecendo a variável somente na execução:

```powershell
docker compose run --rm -e OPENAI_API_KEY devmate ask --provider openai "Explique as mudanças"
```

Para verificar a configuração sem fazer uma chamada paga:

```powershell
docker compose run --rm devmate providers list
docker compose run --rm devmate providers doctor openai
```

O provider `codex` roda com sandbox somente leitura e recebe apenas o contexto selecionado em um workspace temporário.

## 8. Testes e verificações de qualidade

Execute todos os checks dentro da imagem:

```powershell
docker compose run --rm --entrypoint sh devmate -lc "uv sync --frozen --all-extras && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest"
```

Para entrar em um shell de desenvolvimento:

```powershell
docker compose run --rm --entrypoint sh devmate
```

## 9. Usar a imagem em outro repositório

Primeiro, construa a imagem a partir deste projeto:

```powershell
docker build -t devmate:local .
```

Depois, no diretório do repositório alvo:

```powershell
docker run --rm -it -v "${PWD}:/workspace" -w /workspace devmate:local init
docker run --rm -it -v "${PWD}:/workspace" -w /workspace devmate:local scan
docker run --rm -it -v "${PWD}:/workspace" -w /workspace devmate:local ask --provider mock "Quais decisões aparecem neste commit?"
```

No PowerShell, `${PWD}` representa o diretório atual. O repositório deve estar disponível ao Docker Desktop para que o bind mount funcione.

## 10. Solução de problemas

| Sintoma | Ação |
|---|---|
| Erro de conexão com `docker_engine` | Inicie o Docker Desktop. |
| `DevMate não foi inicializado` | Execute `devmate init` no mesmo diretório do repositório. |
| Nenhum commit indexado | Execute `devmate scan`. |
| Provider OpenAI indisponível | Passe `-e OPENAI_API_KEY` e confirme com `providers doctor openai`. |
| Fala não disponível no contêiner | Use `read --dry-run`. |
| Arquivo recusado | Confirme que o path está dentro do repositório e não corresponde a padrões sensíveis, como `.env` ou `*.key`. |
