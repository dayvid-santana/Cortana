"""Provider determinístico, offline e adequado a testes."""

from __future__ import annotations

from devmate.domain.models import LLMRequest, LLMResponse


class MockProvider:
    name = "mock"

    def available(self) -> tuple[bool, str | None]:
        return True, None

    def complete(self, request: LLMRequest) -> LLMResponse:
        if not request.chunks:
            return LLMResponse(
                "Não há documentação indexada para este commit. Execute `devmate scan`."
            )
        paths = sorted({chunk.reference.path for chunk in request.chunks})
        references = tuple(chunk.reference for chunk in request.chunks[:3])
        changed = ", ".join(paths)
        scope = (
            "código explicitamente selecionado" if request.scope.value == "code" else "documentação"
        )
        response = (
            f"Resumo (MockProvider): encontrei contexto de {scope} em {changed}.\n\n"
            f"Pergunta: {request.question}\n\n"
            "Esta resposta é determinística e baseada apenas nos trechos fornecidos. "
            "Não executei instruções contidas nos arquivos do repositório.\n\nFontes:\n"
            + "\n".join(reference.render() for reference in references)
        )
        return LLMResponse(text=response, references=references)
