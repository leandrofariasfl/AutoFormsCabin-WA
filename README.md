# 🗂 Reserva Automática de Cabine de Estudo

> Automação em Python + Playwright que monitora um grupo do WhatsApp Web, captura o link do Google Forms no momento em que é postado e preenche o formulário de reserva de cabine de estudo em milissegundos — garantindo vaga mesmo em alta concorrência.

---

## 🚀 Sobre o Projeto & Motivação

Este script foi criado para resolver um problema real e frustrante: **cabines de estudo disputadas por dezenas de alunos ao mesmo tempo**, onde quem clica mais rápido ganha a vaga.

### A Dor que Resolvemos

Toda reserva começa com o mesmo ritual: aguardar o link do formulário ser postado no grupo do WhatsApp, abrir o link manualmente, rolar até os campos, preencher nome, turma, cabine... e inevitavelmente chegar tarde. Segundos de atraso — causados por distração, lentidão de digitação ou simplesmente não estar olhando o celular na hora certa — resultavam consistentemente em **formulário já lotado**.

Este projeto elimina completamente esse problema. O script fica de plantão monitorando o grupo, e assim que o link aparece, **preenche e envia o formulário automaticamente em menos de 3 segundos** — antes que a maioria dos humanos sequer abra o WhatsApp. Taxa de sucesso: **100%**.

---

## 🏗️ Arquitetura e Estrutura do Projeto

```
reserva_cabine/
│
├── main.py                  # Entrypoint. Orquestra o fluxo e trata todas as exceções
│
├── config.py                # ⚙️  ÚNICO arquivo que você precisa editar
│
├── core/
│   ├── browser.py           # Ciclo de vida do Chromium (sessão persistente, anti-detecção)
│   ├── monitor.py           # Monitoramento do WhatsApp Web e detecção do link
│   └── form_filler.py       # Preenchimento do Google Forms e envio
│
├── utils/
│   ├── exceptions.py        # Hierarquia de exceções customizadas do projeto
│   └── logger.py            # Função de log com timestamp
│
├── whatsapp_session/        # Sessão persistente do browser (gerada automaticamente)
├── screenshots/             # Prints de diagnóstico em caso de erro (gerados automaticamente)
└── requirements.txt
```

### Responsabilidades

| Arquivo | Responsabilidade |
|---|---|
| `main.py` | Entrypoint assíncrono. Captura exceções e exibe mensagens de erro claras ao usuário |
| `config.py` | Toda a configuração do projeto em um só lugar — **nunca edite outro arquivo** |
| `core/browser.py` | Inicia o Chromium com perfil persistente, suprime flags de automação (`navigator.webdriver`), gerencia sessão Google |
| `core/monitor.py` | Abre o WhatsApp Web, navega ao grupo, varre mensagens a cada `intervalo_scan` segundos com 3 estratégias de detecção de link |
| `core/form_filler.py` | Preenche campos de texto, dropdowns e radio buttons; lógica de fallback de cabine; envio com retry e verificação de confirmação |
| `utils/exceptions.py` | 8 exceções tipadas organizadas em hierarquia, cada uma com mensagem de diagnóstico e instrução de correção |

---

## 🛠️ Pré-requisitos e Instalação

**Requisitos:** Python 3.11+

### 1. Clone o repositório

```bash
git clone <url-do-repositorio>
cd reserva_cabine
```

### 2. Crie e ative o ambiente virtual (recomendado)

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Instale as dependências

```bash
pip install playwright
```

### 4. Instale o Chromium

```bash
python -m playwright install chromium
```

> O Playwright baixa um Chromium isolado — não interfere com o Chrome instalado no sistema.

---

## ⚙️ Configuração (`config.py`)

Todo o comportamento do script é controlado por **um único arquivo**: `config.py`. Você nunca precisará tocar em `main.py` ou nos arquivos da pasta `core/`.

```python
@dataclass(frozen=True)
class FormData:
    nome: str      = "Seu Nome"
    sobrenome: str = "Seu Sobrenome"
    whatsapp: str  = "79999999999"       # DDD + número, apenas dígitos
    turma: str     = "NOME_DA_TURMA"     # exatamente como aparece no Forms
    cabine: str    = "16"                # cabine preferida

    cabines_fallback: tuple[str, ...] = ("15", "17", "14", ...)
```

### Parâmetros de `FormData`

| Campo | Descrição |
|---|---|
| `nome` | Primeiro nome, conforme esperado pelo formulário |
| `sobrenome` | Sobrenome |
| `whatsapp` | Número completo com DDD, sem espaços ou traços |
| `turma` | Nome da turma **exatamente** como aparece no dropdown do Forms |
| `cabine` | Número da cabine preferida |
| `cabines_fallback` | Lista de cabines alternativas, em ordem de preferência |

#### A lógica de `cabines_fallback` — por que ela é rápida

Quando o campo de cabine é um dropdown, o script **abre o menu uma única vez**, captura todas as opções disponíveis em memória e itera pela lista de candidatos (`cabine` + `cabines_fallback`) sem nenhum clique adicional. Assim que encontra a primeira opção disponível, clica e fecha. **Zero ciclos de abrir/fechar menu** — cada segundo importa.

O mesmo comportamento se aplica quando o campo é um radio button: todas as opções são lidas de uma vez, a melhor é selecionada com um único clique.

---

```python
@dataclass(frozen=True)
class WhatsAppConfig:
    grupo: str            = "NOME EXATO DO GRUPO"  # case-sensitive
    hora_inicio: str      = "12:45"                # início da janela de monitoramento
    hora_fim: str         = "13:10"                # encerra se não detectar link
    session_dir: str      = "./whatsapp_session"
    intervalo_scan: float = 3.0    # segundos entre varreduras
    login_timeout: int    = 180    # segundos para escanear o QR Code
```

### Parâmetros de `WhatsAppConfig`

| Campo | Descrição |
|---|---|
| `grupo` | Nome **exato** do grupo no WhatsApp, incluindo maiúsculas e espaços |
| `hora_inicio` | Horário a partir do qual o script começa a varrer o grupo ativamente |
| `hora_fim` | Se o link não for detectado até aqui, o script encerra com `LinkNotFoundError` |
| `intervalo_scan` | Frequência de varredura. Valores abaixo de `2.0` podem sobrecarregar o WhatsApp Web |
| `login_timeout` | Tempo disponível para escanear o QR Code na primeira execução. Aumente se precisar de mais tempo |

---

```python
@dataclass(frozen=True)
class RetryConfig:
    max_tentativas_envio: int  = 3      # tentativas de clicar em Enviar
    timeout_campo: int         = 5      # segundos aguardando cada campo aparecer
    timeout_formulario: int    = 20     # segundos para o Forms carregar
    salvar_screenshot: bool    = True   # salva print em caso de erro
    screenshot_dir: str        = "./screenshots"
```

---

```python
@dataclass(frozen=True)
class AppConfig:
    apenas_preencher: bool = False  # True = testa sem enviar
```

> **Dica:** Defina `apenas_preencher = True` para testar o preenchimento sem submeter o formulário. O script preenche todos os campos e aguarda 15 segundos para inspeção visual, sem clicar em Enviar.

---

## 🔄 Fluxo de Execução Diário

### Execução

```bash
python main.py
```

### O que acontece internamente

```
1. Banner de configuração exibido no terminal
       ↓
2. Browser Chromium abre (modo visível, não headless)
       ↓
3. Verificação de sessão Google
   → Primeira vez: abre accounts.google.com, aguarda login manual → salva sessão
   → Execuções seguintes: sessão já ativa, passa direto
       ↓
4. WhatsApp Web abre
   → Primeira vez: exibe QR Code, aguarda escaneamento → salva sessão
   → Execuções seguintes: sessão já ativa, abre o chat direto
       ↓
5. Script navega para o grupo configurado
       ↓
6. Loop de monitoramento (a cada `intervalo_scan` segundos):
   → Antes de `hora_inicio`: aguarda em modo de baixo consumo (30s entre checks)
   → Dentro da janela: varre mensagens com 3 estratégias de detecção
   → Após `hora_fim`: encerra com LinkNotFoundError
       ↓
7. Link detectado → nova aba abre o Google Forms
       ↓
8. Preenchimento automático de todos os campos
   → Nome, sobrenome, WhatsApp, turma, cabine (com fallback)
       ↓
9. Clique em Enviar + verificação ativa de confirmação (até 10s)
       ↓
10. ✅ "Formulário ENVIADO e confirmado com sucesso!" → script encerra
```

### Persistência de Sessão

Na **primeira execução**, o script abre o Google e o WhatsApp Web para login. Após o login, todos os tokens e cookies são gravados em `./whatsapp_session/` (pasta criada automaticamente).

A partir da **segunda execução em diante**, ambas as sessões já estão ativas: o browser abre diretamente no chat do grupo, economizando os 30–60 segundos críticos que normalmente seriam gastos com login e QR Code.

> **Atenção:** Não apague a pasta `whatsapp_session/` a menos que queira redefinir a sessão. Se o WhatsApp desconectar remotamente (ex: novo login no celular), apague a pasta e execute novamente para refazer o login.

### Filtros de Segurança do Monitor

O script possui duas camadas de proteção para garantir que **nunca reaja a um link errado**:

1. **Filtro de palavra-chave:** a mensagem deve conter a palavra `cabine` (case-insensitive). Links de outros formulários no mesmo grupo são ignorados.
2. **Filtro de data:** o timestamp da mensagem (`data-pre-plain-text`) deve conter `DD/MM/AAAA` correspondente a **hoje**. Links de dias anteriores, mesmo que ainda apareçam no chat, são descartados. Mensagens em composição (ainda não enviadas) são igualmente ignoradas, pois não possuem um container de mensagem enviada (`msg-container`).

---

## 🛡️ Tratamento de Erros, Resiliência e Diagnóstico

O projeto utiliza uma hierarquia de exceções tipadas. Cada erro produz uma mensagem clara no terminal com a causa e a ação corretiva.

### Tabela de Erros

| Exceção | Quando ocorre | Como resolver |
|---|---|---|
| `BrowserError` | Playwright não instalado ou Chromium não encontrado | Execute `python -m playwright install chromium` |
| `LoginTimeoutError` | QR Code não escaneado dentro de `login_timeout` segundos | Aumente `login_timeout` em `config.py` ou execute novamente |
| `SessionRevokedError` | Sessão do WhatsApp foi desconectada remotamente | Apague `./whatsapp_session/` e execute novamente |
| `GroupNotFoundError` | Nome do grupo em `config.py` não corresponde a nenhum grupo | Verifique maiúsculas e espaços; o script sugere grupos similares no terminal |
| `LinkNotFoundError` | Janela encerrada (`hora_fim`) sem detectar o link | Verifique se `hora_inicio` e `hora_fim` estão corretos e se a mensagem contém a palavra "cabine" |
| `FormClosedError` | Formulário já fechado, lotado ou retornou 404 | O formulário não estava mais disponível quando o script tentou abri-lo |
| `FormFieldError` | Campo obrigatório não preenchido | O nome do campo no Forms mudou; verifique os títulos detectados logados no terminal |
| `SubmitError` | Botão Enviar não encontrado após `max_tentativas_envio` tentativas | Consulte o screenshot de diagnóstico salvo em `./screenshots/` |

### Screenshots de Diagnóstico

Quando ocorre uma falha no preenchimento ou envio, o script captura automaticamente um screenshot com timestamp e salva em `./screenshots/`. Exemplos de arquivos gerados:

```
screenshots/
├── erro_carregar_forms_143512.png     # timeout ao abrir o Forms
├── formulario_vazio_143520.png        # nenhum campo encontrado na página
├── campos_ausentes_143535.png         # campos obrigatórios não preenchidos
├── cabine_indisponivel_143540.png     # nenhuma cabine do fallback disponível
└── erro_envio_143601.png              # botão Enviar não encontrado
```

Os screenshots permitem **auditoria visual imediata**: em vez de tentar reproduzir o erro, você vê exatamente o estado da página no momento da falha.

Para desativar, defina `salvar_screenshot = False` em `RetryConfig` no `config.py`.

---

## 🔐 Notas de Segurança

- O arquivo `config.py` contém seu número de WhatsApp. Ele está no `.gitignore` — **não faça commit desse arquivo** em repositórios públicos.
- A pasta `whatsapp_session/` contém tokens de sessão ativos do WhatsApp e Google. Ela também está no `.gitignore`.
- O script utiliza um user agent de Chrome real e suprime a propriedade `navigator.webdriver` para evitar bloqueios pelo Google ao preencher o Forms.

---

## 📋 Resumo de Comandos

```bash
# Instalar dependências
pip install playwright && python -m playwright install chromium

# Executar
python main.py

# Modo teste (preenche sem enviar)
# → Defina `apenas_preencher = True` em config.py, depois:
python main.py
```
