# Conversa por voz

O DevMate aceita uma pergunta pelo microfone com `listen`. A transcrição é feita por Whisper no próprio computador; a gravação não é salva. A resposta é mostrada no terminal e narrada pela voz do Windows.

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

## Providers de resposta

O áudio nunca é enviado ao provider. Apenas o texto transcrito passa para o mesmo fluxo seguro do comando `ask`.

```powershell
# Sem rede e determinístico
.\.venv\Scripts\python.exe -m devmate listen --provider mock

# Requer OPENAI_API_KEY configurada no ambiente
.\.venv\Scripts\python.exe -m devmate listen --provider openai
```

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

## Problemas comuns

| Sintoma | Ação |
|---|---|
| `Nenhum microfone padrão disponível` | Em **Configurações > Sistema > Som**, selecione e teste um microfone de entrada. |
| `Nenhuma fala foi reconhecida` | Aumente `--duration`, fale após a mensagem de início e verifique as permissões de microfone para aplicativos de desktop. |
| Erro ao baixar o modelo | Conecte-se à internet apenas para a primeira execução ou copie um modelo já baixado para `.devmate/models`. |
| Resposta não é narrada | Execute `devmate doctor` e confirme que `Fala system` está disponível. |
| Uso no Docker | Execute a conversa de voz no host. O contêiner não tem acesso confiável ao microfone nem ao áudio do Windows. |
