# Contribuindo

Use Python 3.12+ e uv. Antes de abrir uma mudança, execute `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src` e `uv run pytest`.

Mantenha o domínio independente de Typer, SQLAlchemy, SDKs de LLM e comandos do sistema. Adapters ficam nas bordas; mudanças de schema exigem migration e testes. Testes não podem acessar rede nem invocar fala/LLM reais.
