# Desenvolvimento de providers

Implemente `LanguageModelProvider` com `name`, `available()` e `complete(LLMRequest)`. O provider recebe chunks já selecionados, cada um com `SourceReference`, e deve devolver `LLMResponse`. Não leia arquivos diretamente nem altere regras de escopo.

Registre a implementação em `ProviderRegistry`, informe indisponibilidade sem revelar credenciais e teste com factory/fake — nunca com rede. Um provider de fala implementa `name`, `available()` e `speak(text)`; ele deve receber texto normalizado e nunca montar comandos por interpolação.

Capabilities remotas são opt-in: uma API OpenAI-compatible não é presumida compatível com ferramentas, threads ou structured output.
