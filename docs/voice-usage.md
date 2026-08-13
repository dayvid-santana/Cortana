# Conversa por voz

A assistente do DevMate se chama **Diana**. Ela aceita uma pergunta pelo microfone com `listen`, ou mantém uma conversa contínua com `talk`. A transcrição é feita por Whisper no próprio computador; a gravação não é salva. A resposta é mostrada no terminal e narrada pela voz do Windows.

## Preparação

No PowerShell, dentro do projeto:

```powershell
cd C:\projects\Cortana
.\.venv\Scripts\python.exe -m devmate init
.\.venv\Scripts\python.exe -m devmate scan
.\.venv\Scripts\python.exe -m devmate doctor
```

`doctor` deve informar `Entrada de voz faster_whisper` como disponível. Confirme também que o microfone desejado é o dispositivo de entrada padrão do Windows.

## Primeira conversa

```powershell
.\.venv\Scripts\python.exe -m devmate listen --provider mock --duration 10
```

1. O terminal mostra `Ouvindo por até 10 segundos. Fale agora.`
2. Faça uma pergunta, por exemplo: **"O que mudou na documentação?"**
3. Aguarde a transcrição e a resposta falada.

Na primeira execução, o modelo local `base` é baixado para `.devmate/models`. Essa é a única chamada de rede do fluxo de voz; nas execuções posteriores, a captura e a transcrição são locais.

## Testar sem reproduzir a resposta

```powershell
.\.venv\Scripts\python.exe -m devmate listen --provider mock --duration 10 --no-speak
```

Use esse modo para conferir a transcrição no terminal antes de ativar a narração.

## Conversa contínua

`listen` responde uma pergunta e termina. Para conversar de verdade, use `talk`: a Diana escuta, responde e volta a escutar, sem repetir o comando a cada pergunta.

```powershell
.\.venv\Scripts\python.exe -m devmate talk --provider mock
```

Cada rodada é persistida no commit selecionado e as rodadas anteriores são reenviadas ao provider, portanto perguntas de acompanhamento funcionam:

```
Você:  O que mudou no README?
Diana: (responde)
Você:  E na parte de segurança?      <- resolvida com base na rodada anterior
```

Para encerrar, diga **"sair"**, **"tchau"**, **"encerrar"** ou **"até logo"**, ou pressione Ctrl+C. Uma rodada em que nada é reconhecido não encerra a conversa: a Diana avisa e volta a escutar, desistindo após três silêncios seguidos.

As mesmas opções de `listen` valem aqui, incluindo `--duration`, `--no-speak`, `--files` e `--full-repo`.

## Providers de resposta

O áudio nunca é enviado ao provider. Apenas o texto transcrito passa para o mesmo fluxo seguro do comando `ask`.

```powershell
# Sem rede e determinístico
.\.venv\Scripts\python.exe -m devmate listen --provider mock

# Requer OPENAI_API_KEY configurada no ambiente
.\.venv\Scripts\python.exe -m devmate listen --provider openai

# Requer sessão autenticada no Codex e autoriza explicitamente o código suportado
.\.venv\Scripts\python.exe -m devmate listen --provider codex --full-repo
```

Com `--full-repo`, o DevMate inclui os arquivos de código suportados no commit selecionado, além da documentação disponível, em um workspace temporário e somente leitura para o Codex. Não é uma autorização permanente: sem `--full-repo` ou `--files`, `listen` continua restrito à documentação. Para limitar o escopo, prefira arquivos específicos:

```powershell
.\.venv\Scripts\python.exe -m devmate listen --provider codex --files src/devmate/cli.py
```

Exemplos de perguntas faladas:

- “Diana, analise as últimas mudanças no repositório e explique como elas impactam a arquitetura geral.”
- “Há algum padrão de projeto predominante ou uma área que precisa de refatoração?”
- “A documentação alterada ainda está em sincronia com o código atual?”

## Ajustes

Edite `.devmate/config.toml` para mudar o idioma, modelo ou duração padrão:

```toml
[speech]
provider = "system"
input_provider = "faster_whisper"
input_model = "base"
input_language = "pt-BR"
input_duration_seconds = 10
```

Modelos menores iniciam mais rapidamente; `base` é o equilíbrio padrão para português em CPU. A opção `--duration` substitui `input_duration_seconds` em uma única execução.

### Comportamento do Codex

O arquivo `.devmate/config.toml` contém a instrução de sistema do provider Codex. Ela é usada como orientação confiável para deixar a resposta técnica, natural e apropriada para narração:

```toml
[language_model.providers.codex]
system_instruction = """
Você é a Diana, uma assistente especialista em engenharia de software integrada ao DevMate.
Analise somente os metadados do Git, documentos e códigos fornecidos no contexto.
Responda em português de forma natural, amigável e concisa, pois a resposta será narrada por voz.
Relacione código, documentação e arquitetura; se não houver evidência suficiente, admita.
"""
```

Não coloque chaves de API, tokens ou informações pessoais nesse campo. A configuração modifica a orientação da resposta, mas não amplia o escopo de arquivos nem remove o sandbox somente leitura.

## Problemas comuns

| Sintoma | Ação |
|---|---|
| `Nenhum microfone padrão disponível` | Em **Configurações > Sistema > Som**, selecione e teste um microfone de entrada. |
| `Nenhuma fala foi reconhecida` | Aumente `--duration`, fale após a mensagem de início e verifique as permissões de microfone para aplicativos de desktop. |
| Erro ao baixar o modelo | Conecte-se à internet apenas para a primeira execução ou copie um modelo já baixado para `.devmate/models`. |
| Resposta não é narrada | Execute `devmate doctor` e confirme que `Fala system` está disponível. |
| Uso no Docker | Execute a conversa de voz no host. O contêiner não tem acesso confiável ao microfone nem ao áudio do Windows. |
