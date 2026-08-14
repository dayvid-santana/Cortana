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
        if request.task in {"code_edit", "docs_generation", "refactor"}:
            return _mock_edit_response(request)
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


def _mock_edit_response(request: LLMRequest) -> LLMResponse:
    """Proposta determinística: acrescenta um comentário de teste ao último arquivo do contexto.

    `InspectionService.build` sempre anexa os arquivos explicitamente selecionados (code_files)
    por último, depois dos trechos de documentação do commit — então o último chunk do pedido é
    sempre um arquivo autorizado para edição, tenha ele extensão de código ou não (ex.: um .md
    passado a `devmate docs --files`). Sem isso não haveria como exercitar offline o fluxo
    propor -> diff -> aplicar, o que viola a política de testes do projeto (nenhum provider real
    em teste).
    """
    if not request.chunks:
        return LLMResponse("Resposta determinística (MockProvider): nada para propor.")
    target = request.chunks[-1]
    proposed = target.text.rstrip("\n") + "\n# devmate: alteração de teste (MockProvider)\n"
    body = (
        "Resposta determinística (MockProvider): adicionei um comentário de exemplo ao final "
        f"de {target.reference.path}.\n\n"
        f">>> FILE: {target.reference.path}\n{proposed}\n<<< END FILE\n"
    )
    return LLMResponse(text=body, references=(target.reference,))
