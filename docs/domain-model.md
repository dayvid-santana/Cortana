# Modelo de domínio

```mermaid
erDiagram
  PROJECT ||--o{ COMMIT : possui
  COMMIT ||--o{ DOCUMENT_CHANGE : altera
  COMMIT ||--o{ CONVERSATION_MESSAGE : contextualiza
  PROJECT ||--o{ DECISION : memoriza
  PROJECT ||--o{ OPEN_QUESTION : acompanha
  PROJECT ||--o{ READING_CHECKPOINT : salva
```

`Project` guarda o root canônico e diretório Git comum. `Commit` é único por projeto e hash. `DocumentChange` preserva status (incluindo rename/copy/delete), paths, contagens e diff truncável. Decisões inferidas permanecem candidatas; não são apresentadas como confirmadas. `SourceReference` contém caminho, linhas, hash e heading opcional.
