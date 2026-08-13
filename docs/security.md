# Segurança e threat model

DevMate considera arquivos, diffs, código, comentários e headings como dados não confiáveis. Eles nunca alteram as instruções confiáveis da aplicação.

| Ameaça | Controle |
|---|---|
| Prompt injection em Markdown | tags de contexto não confiável e instruções explícitas aos providers |
| Path traversal | resolução canônica e verificação de descendência do root |
| Symlink externo | recusado por padrão |
| Segredos | `.env`, chaves e padrões configuráveis bloqueados antes de leitura/provider |
| Command injection | `subprocess` com lista de argumentos, timeout e sem shell |
| Provider remoto | somente em comando explícito; mock/scan/read local não acessam rede |
| Logs | não registram conteúdo, prompts, respostas ou credenciais por padrão |
| Hook | somente `scan --metadata-only`, sem provider |
| Workspace temporário | contexto mínimo, sandbox read-only e limpeza automática |

O TTS de Windows transmite texto por variável de ambiente ao processo local, não por interpolação em shell. Os providers devem ser tratados como limites de confiança: a aplicação valida paths e constrói fontes, não aceita citações inventadas da resposta.
