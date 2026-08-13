# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Git é requisito de runtime: o DevMate nunca usa GitPython.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "uv==0.12.3"

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

# A imagem de runtime não inclui ferramentas de desenvolvimento.
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}"

ENTRYPOINT ["devmate"]
CMD ["--help"]


FROM base AS development

# O Compose monta o código em /workspace. PYTHONPATH garante que a CLI use a
# árvore montada, enquanto as dependências permanecem imutáveis em /app/.venv.
WORKDIR /workspace
ENV PYTHONPATH=/workspace/src
ENTRYPOINT ["python", "-m", "devmate"]
CMD ["--help"]
