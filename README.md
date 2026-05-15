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
    └── logger.py        # log com timestamp
```

---

## Instalação

```bash
pip install playwright
python -m playwright install chromium
```

---

## Configuração

Abra o `config.py` e edite os três dataclasses:

```python
# Seus dados pessoais
FormData(
    nome      = "Seu nome",
    sobrenome = "Seu sobrenome completo",
    whatsapp  = "79999999999",
    turma     = "OSWALDO CRUZ",
    cabine    = "16",
)

# WhatsApp
WhatsAppConfig(
    grupo       = "Nome Exato do Grupo",  # ← copie do WhatsApp
    hora_inicio = "12:40",
    hora_fim    = "13:10",
)

# Modo de operação
AppConfig(
    apenas_preencher = False,  # False = envia de verdade
)
```

---

## Uso diário

```bash
python main.py
```

Na **primeira execução**, o Chrome vai abrir o WhatsApp Web pedindo o QR Code.  
Após o login, a sessão fica salva em `whatsapp_session/` — nas próximas vezes abre direto.

---

## Modos de operação

| `apenas_preencher` | Comportamento |
|---|---|
| `True` | Preenche os campos mas **não clica em Enviar** — bom para testes |
| `False` | Preenche e **envia o formulário** de verdade |

---

## O que esperar no terminal

```
[12:49:51] Aguardando link... (50 verificações)
[12:50:03] 🔗 Link encontrado: https://docs.google.com/forms/...
[12:50:04] Abrindo formulário...
[12:50:05]   ✓ Nome: 'Seu nome'
[12:50:05]   ✓ Sobrenome: 'Seu sobrenome completo'
[12:50:06]   ✓ WhatsApp: '79999999999'
[12:50:06]   ✓ Turma: 'OSWALDO CRUZ'
[12:50:07]   ✓ Cabine: '16'
[12:50:08] ✅ Formulário ENVIADO com sucesso!
[12:50:11] ✅ Processo concluído!
```

---

## Solução de problemas

| Sintoma | Causa provável | Solução |
|---|---|---|
| Grupo não encontrado | Nome diferente do WhatsApp | Copie o nome exato da lista de conversas |
| Campo `⚠️ não mapeado` | Título do campo mudou no Forms | Rode `teste_formulario.py` para ver os títulos |
| QR Code pedido toda vez | Pasta `whatsapp_session/` apagada | Não delete essa pasta |
| Link não detectado | Formato de URL diferente | Abra uma issue com o formato do link |
