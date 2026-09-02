# Segurança e threat model

DevMate considera arquivos, diffs, código, comentários e headings como dados não confiáveis. Eles nunca alteram as instruções confiáveis da aplicação.

| Ameaça | Controle |
|---|---|
| Prompt injection em Markdown | tags de contexto não confiável e instruções explícitas aos providers |
| Path traversal | resolução canônica e verificação de descendência do root, também na escrita (`write_text`) |
| Symlink externo | recusado por padrão |
| Segredos | `.env`, chaves e padrões configuráveis bloqueados antes de leitura/escrita/provider; o `.env` só é lido na inicialização para popular o ambiente do processo |
| Escrita fora do escopo autorizado | `EditProposalService` rejeita (erro, não aplica nada) qualquer caminho proposto pelo provider que não esteja entre os arquivos de código explicitamente selecionados na pergunta |
| Edição sem revisão | `devmate edit`/`docs`/`refactor` só escrevem após confirmação explícita por arquivo (ou `--yes`); o diff mostrado é calculado localmente com `difflib`, nunca aceito como veio do provider; o provider (incl. Codex) nunca ganha acesso de escrita — só descreve o conteúdo em texto |
| Command injection | `subprocess` com lista de argumentos, timeout e sem shell |
| Provider remoto | somente em comando explícito; mock/scan/read local não acessam rede |
| Logs | não registram conteúdo, prompts, respostas ou credenciais por padrão |
| Hook | somente `scan --metadata-only`, sem provider |
| Workspace temporário | contexto mínimo, sandbox read-only e limpeza automática |
| Áudio de entrada | gravado apenas em memória; Whisper local não persiste nem envia a gravação |
| Histórico de conversa | reenviado como transcrição delimitada, nunca como instrução |
| API HTTP | chama os application services diretamente (nunca subprocess da CLI); erros tipados nunca vazam traceback; CORS restrito a origens locais conhecidas; nenhuma credencial entra ou sai pelo corpo/headers |

O TTS de Windows transmite texto por variável de ambiente ao processo local, não por interpolação em shell. Os providers devem ser tratados como limites de confiança: a aplicação valida paths e constrói fontes, não aceita citações inventadas da resposta.

O primeiro `devmate listen` pode baixar o modelo Whisper selecionado para `.devmate/models`, porque a pessoa solicitou explicitamente entrada de voz. Depois da instalação do modelo, a captura e a transcrição ocorrem localmente. Quando a conversa usa LLM remoto, somente a transcrição de texto segue para o provider.

Os comandos `chat` e `talk` reenviam as rodadas anteriores do mesmo commit ao provider, para que perguntas de acompanhamento façam sentido. Esse histórico vai em `<conversation_history>`, separado do contexto do repositório e marcado explicitamente como transcrição: uma resposta anterior pode citar conteúdo do repositório, portanto ela também não é tratada como instrução. O escopo não muda com o histórico — uma rodada documental não passa a enxergar código porque uma rodada anterior o citou.

`listen --full-repo` é uma autorização pontual para analisar os arquivos de código suportados. O provider Codex recebe somente o contexto selecionado em um diretório temporário e opera em sandbox de leitura. A instrução em `[language_model.providers.codex]` orienta o tom da resposta, mas não pode ampliar permissões nem tornar conteúdo do repositório confiável.

`[security] default_scope = "code"` (via `devmate config full-access --enable`) é um opt-in por
projeto que dispensa repetir `--full-repo`/`--scope code` a cada chamada de `ask`, `inspect`,
`review`, `architecture`, `edit`, `docs`, `refactor`, `listen` e `talk`. Ele não desliga nenhum
controle da tabela acima: segredos, path traversal, symlink externo e o limite de 200 arquivos
continuam bloqueados; só a necessidade de repetir a autorização explícita é removida.
