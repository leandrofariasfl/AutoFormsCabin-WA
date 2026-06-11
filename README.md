# 🗂 Reserva Automática de Cabine de Estudo

Monitora um grupo do WhatsApp Web, detecta o link do Google Forms assim que é enviado e preenche o formulário automaticamente.

---

## Estrutura do projeto

```
reserva_cabine/
├── main.py              # entrypoint — execute este arquivo
├── config.py            # ✏️  EDITE AQUI: seus dados e configurações
├── core/
│   ├── browser.py       # setup/teardown do Playwright
│   ├── monitor.py       # monitoramento do WhatsApp Web
│   └── form_filler.py   # preenchimento do Google Forms
└── utils/
    ├── logger.py        # log com timestamp
    └── exceptions.py    # exceções customizadas do projeto
```

---

## Instalação

```bash
pip install playwright
python -m playwright install chromium
```

---

## Configuração (`config.py`)

```python
FormData(
    nome      = "Nome",
    sobrenome = "Sobrenome",
    whatsapp  = "79999999999",
    turma     = "TURMA01",
    cabine    = "16",
    cabines_fallback = ("15", "17", "18", "14"),  # tenta em ordem se a 16 não estiver disponível
)

WhatsAppConfig(
    grupo       = "Nome Exato do Grupo",
    hora_inicio = "12:40",
    hora_fim    = "13:10",
    login_timeout = 90,   # segundos para escanear o QR Code
)

RetryConfig(
    max_tentativas_envio = 3,      # retries no botão Enviar
    salvar_screenshot    = True,   # salva prints de erro em ./screenshots/
)

AppConfig(
    apenas_preencher = False,  # False = envia de verdade
)
```

---

## Uso diário

```bash
python main.py
```

Na **primeira execução** o Chrome abre o WhatsApp Web pedindo o QR Code.
Após o login, a sessão fica salva em `whatsapp_session/` — próximas execuções abrem direto.

---

## Exceções e o que fazer

| Mensagem no terminal | Causa | Solução |
|---|---|---|
| `❌ ERRO DE BROWSER` | Playwright não instalado ou Chrome não encontrado | `pip install playwright && python -m playwright install chromium` |
| `❌ TIMEOUT DE LOGIN` | QR Code não foi escaneado a tempo | Execute novamente e escaneie mais rápido |
| `❌ SESSÃO DESCONECTADA` | WhatsApp deslogou durante o monitoramento | Apague `./whatsapp_session/` e execute novamente |
| `❌ GRUPO NÃO ENCONTRADO` | Nome do grupo diferente do WhatsApp | Copie o nome exato e corrija em `config.py` |
| `⏱ LINK NÃO DETECTADO` | Link enviado fora da janela ou formato diferente | Ajuste `hora_inicio`/`hora_fim` em `config.py` |
| `🔒 FORMULÁRIO INACESSÍVEL` | Forms fechado ou lotado | Nada a fazer — chegou tarde |
| `⚠️ CAMPO NÃO PREENCHIDO` | Título do campo mudou no Forms | Rode `teste_formulario.py` para ver os títulos atuais |
| `❌ FALHA NO ENVIO` | Botão Enviar não encontrado após 3 tentativas | Veja o screenshot em `./screenshots/` |

---

## Screenshots de diagnóstico

Em caso de erro, o script salva automaticamente prints em `./screenshots/`:

| Arquivo | Quando é gerado |
|---|---|
| `erro_carregar_forms_HHMMSS.png` | Timeout ao abrir o formulário |
| `formulario_vazio_HHMMSS.png` | Nenhum campo encontrado |
| `campos_ausentes_HHMMSS.png` | Campo obrigatório não preenchido |
| `cabine_indisponivel_HHMMSS.png` | Nenhuma cabine do fallback disponível |
| `erro_envio_HHMMSS.png` | Falha ao clicar em Enviar |