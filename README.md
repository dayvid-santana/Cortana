# DevMate

DevMate é uma assistente local para entender a evolução da documentação de um repositório Git. A assistente se chama **Diana**. O contexto central é `repositório → branch → commit → documentos → decisões → perguntas → conversa`, e não apenas uma mensagem isolada.

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

Consulte o [guia completo de uso com Docker](docs/docker-usage.md) para o fluxo de primeiro uso, testes, providers e diagnóstico.

## Providers

O provider padrão é configurado em `.devmate/config.toml`, ou por `DEVMATE_PROVIDER`. Credenciais ficam somente no ambiente, nunca no TOML. Para desenvolvimento local, a CLI também carrega automaticamente o `.env` na raiz do projeto (ele é ignorado pelo Git e bloqueado do contexto enviado aos providers):

```dotenv
# .env
OPENAI_API_KEY=cole_sua_chave_aqui
```

```bash
devmate providers list
devmate ask --provider mock "Explique a documentação"
devmate ask --provider openai "Explique a documentação"
devmate inspect --provider codex --files src/app.py "O código segue docs/auth.md?"
devmate listen --provider codex --full-repo
```

`codex` usa o SDK oficial `openai-codex` em `Sandbox.read_only`, com um workspace temporário que contém apenas o contexto selecionado. O comportamento de voz fica em `[language_model.providers.codex]` no `.devmate/config.toml`; esse prompt é uma instrução local confiável e não deve conter segredos. `openai` usa Responses API. `openai_compatible` exige `provider.openai_base_url` configurado e não pressupõe ferramentas ou capabilities extras.

### Conectar com o Codex

A autenticação do Codex é da máquina, não do projeto — o SDK reaproveita automaticamente uma sessão já existente (por exemplo, de `codex login`). `devmate codex connect` deixa essa conexão explícita e visível pela CLI:

```bash
devmate codex status              # mostra se há conta conectada, sem iniciar login
devmate codex connect             # login por código de dispositivo (padrão)
devmate codex connect --method browser
OPENAI_API_KEY=... devmate codex connect --method api-key
devmate codex disconnect          # logout local
```

Se já existir uma conta conectada, `connect` não repete o login — apenas confirma a conexão (use `--force` para reautenticar). Ao final, ele pergunta se quer definir `codex` como provider padrão do projeto (`--set-default`/`--no-set-default` pulam a pergunta) e lembra que **entender o código exige `--full-repo` ou `--files` explicitamente** — por padrão toda conversa é só sobre documentação:

```bash
devmate talk --provider codex --full-repo
devmate ask --provider codex --scope code --full-repo "Como o hook de scan funciona?"
```

É esse escopo explícito — não a autenticação — que costuma fazer as respostas do Codex parecerem genéricas: sem `--full-repo`/`--files`, ele nunca chega a ver o seu código.

### Acesso total ao código (por projeto)

Se você quer que a Diana sempre trate código como escopo autorizado neste repositório — sem
repetir `--full-repo`/`--scope code` a cada pergunta —, ative uma vez:

```bash
devmate config full-access --enable
devmate ask "o que este módulo faz?"          # já inclui código, sem --scope code
devmate inspect "isso está consistente com docs/architecture.md?"  # sem --full-repo
devmate config full-access --disable          # volta ao padrão (docs) quando quiser
```

Isso grava `[security] default_scope = "code"` em `.devmate/config.toml` **deste** projeto. Os
bloqueios de segredo, path traversal, symlink externo e o limite de 200 arquivos continuam
valendo — o que muda é só a necessidade de repetir a autorização a cada chamada.

### Comandos por atividade

Além de `ask`/`inspect`, existem comandos dedicados para o dia a dia de engenharia, todos sobre
código explicitamente selecionado (`--files`/`--full-repo`, ou automático com `full-access`):

```bash
devmate review --files src/app.py                       # bugs, segurança, design (read-only)
devmate architecture --full-repo                         # módulos, dependências, decisões
devmate docs --files docs/architecture.md --files src/app.py "Atualize este documento"
devmate refactor --files src/app.py "Extraia essa função em um módulo separado"
devmate edit --files src/app.py "Adicione validação de entrada nesta função"
```

`docs`, `refactor` e `edit` **propõem** — a Diana nunca escreve sem revisão. Cada comando mostra
a explicação e o diff calculado localmente por arquivo; você confirma um a um (ou usa `--yes`
para aplicar tudo de uma vez). Nada é gravado fora dos arquivos que você mesmo autorizou no
contexto.

## Leitura em voz alta

```bash
devmate read docs/architecture.md --dry-run
devmate read docs/architecture.md --section "Segurança"
devmate read docs/architecture.md --resume
```

O provider `system` usa o mecanismo local do sistema operacional. `null` é disponível para testes. Checkpoints são guardados no SQLite e uma retomada é recusada se o arquivo mudar.

## Conversa por voz

O comando abaixo grava uma pergunta curta pelo microfone, transcreve-a localmente com Whisper em CPU, responde no escopo documental e narra a resposta:

```bash
uv sync --all-extras
devmate listen --provider mock
```

Para uma conversa contínua, `talk` mantém a Diana escutando entre as rodadas e reenvia o histórico ao provider, de modo que perguntas de acompanhamento como "e na parte de segurança?" são resolvidas com o contexto anterior. Diga "sair" ou "tchau" para encerrar:

```bash
devmate talk --provider mock
```

Durante a conversa, diga **"Diana, leia o documento"** para narrar `README.md` localmente, ou **"Diana, o que você pode fazer?"** para ouvir as capacidades principais. Nenhum dos dois chama o provider de linguagem. Você pode acrescentar outros comandos em `[[voice.commands]]` no `.devmate/config.toml` e consultá-los com `diana commands`.

No primeiro uso, o modelo configurado (`base`) é baixado para `.devmate/models`; depois, a captura e a transcrição permanecem locais e o áudio não é salvo. Para mudar a janela de captura, use `--duration 15`. `--no-speak` mantém a transcrição e a resposta no terminal sem reproduzir áudio. Se for usado um provider remoto, somente a pergunta já transcrita — nunca a gravação — é enviada ao provider.

Consulte o [guia de conversa por voz](docs/voice-usage.md) para a preparação no Windows e solução de problemas.

## Escolhendo uma voz

Por padrão a Diana narra com o mecanismo do sistema operacional (`speech.provider = "system"`). Para usar as vozes remotas da OpenAI:

```bash
export OPENAI_API_KEY="..."

devmate voices list --provider openai
devmate voices preview marin
devmate voices preview cedar
devmate voices set marin
devmate read docs/architecture.md
```

No Windows PowerShell:

```powershell
$env:OPENAI_API_KEY = "..."
```

`devmate voices set marin` grava `[speech].voice` em `.devmate/config.toml` preservando o resto do arquivo. Depois disso, `devmate read` e `devmate talk` usam `marin` automaticamente. Para uma execução avulsa sem alterar a configuração:

```bash
devmate read docs/architecture.md --voice cedar
```

Para comparar todas as vozes de um provider antes de escolher:

```bash
devmate voices preview --all
devmate voices choose
```

Quando `speech.provider = "openai"`, a síntese acontece inteiramente na API da OpenAI e o áudio resultante é apenas reproduzido localmente — as vozes instaladas no Windows não participam da narração nesse modo. `devmate voices current` mostra o provider, a voz, o modelo e o ritmo em uso; `devmate doctor` inclui uma seção de fala com o status da credencial (nunca o valor) e do player de áudio.

## API HTTP

Uma camada HTTP fina expõe os mesmos application services usados pela CLI, para um frontend externo consumir. Ela nunca chama a CLI por subprocess nem duplica regras — monta `ConversationService`/`InspectionConversationService` diretamente, então escopo, segurança e citações são idênticos aos do `devmate ask`/`chat`.

```bash
devmate serve                 # http://127.0.0.1:8000/api/v1
devmate serve --port 8080 --reload
```

```bash
curl http://127.0.0.1:8000/api/v1/health
curl http://127.0.0.1:8000/api/v1/status
curl -X POST http://127.0.0.1:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "O que mudou?", "provider": "mock", "scope": "docs"}'
```

`scope` é `"docs"` por padrão; `"code"` exige `files` ou `full_repo: true` no corpo da requisição, com a mesma autorização explícita do `inspect --full-repo`. A resposta traz `sources` estruturadas (`path`, `start_line`, `end_line`, `commit_hash`, `heading`) para o frontend linkar direto ao trecho citado, nunca inventadas a partir do texto. `source: "speech"` no corpo pede uma resposta mais concisa, para perguntas que vieram de voz transcrita.

CORS aceita o dev server padrão em `http://127.0.0.1:5174`/`http://localhost:5174` (e mantém `5173` por compatibilidade); `--host` continua `127.0.0.1` por padrão — não exponha em `0.0.0.0` fora de uma rede confiável. O schema OpenAPI fica disponível em `/openapi.json` para gerar um cliente tipado.

Para subir a API em Docker e um frontend (ex.: `devmate-web`) acessá-la pela rede do Compose, veja [docs/docker-usage.md](docs/docker-usage.md#10-conectar-com-o-frontend-devmate-web).

## Segurança

- Escopo padrão é `docs`: código só entra em `inspect`, `ask --scope code` ou uma seleção explícita — inclusive pela API. `devmate config full-access --enable` torna esse escopo automático **por projeto**, sem afetar os bloqueios abaixo.
- Caminhos, symlinks externos e padrões de segredos são bloqueados antes da leitura **e da escrita** (`devmate edit`/`docs`/`refactor`).
- O conteúdo do repositório é marcado como não confiável nos prompts.
- Git e TTS usam argumentos explícitos, timeout e nunca `shell=True`.
- Hooks só executam `scan --metadata-only`; não chamam providers.
- A escrita em disco é a única exceção ao modo somente leitura: só acontece em `devmate edit/docs/refactor`, um arquivo por vez, com diff calculado localmente e confirmação explícita (ou `--yes`). O provider nunca ganha acesso de escrita — ele só descreve o conteúdo proposto em texto; o Codex continua rodando em sandbox `read_only`.
- A API nunca recebe nem devolve credenciais; CORS restrito a origens locais conhecidas.

Consulte [o threat model](docs/security.md).

## Desenvolvimento

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

## Limitações do MVP e roadmap

Edição de código existe apenas como proposta revisável (`devmate edit`/`docs`/`refactor`): a
Diana nunca escreve sem confirmação explícita por arquivo. Não há embeddings, banco vetorial,
interface web, edição **autônoma** (sem revisão), geração de pull requests, execução de testes
por agentes, PDFs nem sincronização em nuvem. Veja [o roadmap](docs/roadmap.md).
