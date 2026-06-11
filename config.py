"""
config.py — Todas as configurações do projeto em um único lugar.
Edite apenas este arquivo para personalizar o comportamento do script.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FormData:
    """Dados pessoais para preenchimento do formulário."""
    nome: str      = "Nome"
    sobrenome: str = "Sobrenome"
    whatsapp: str  = "79999999999"
    turma: str     = "TURMA01"
    cabine: str    = "16"

    # Lista de cabines de fallback: se a cabine principal não estiver
    # disponível no dropdown, tenta as seguintes em ordem.
    cabines_fallback: tuple[str, ...] = ("15", "17", "18", "14", "27", "28", "29", "30", "31", "32", "33", "34", "35", "36", "37", "38", "39", "40")


@dataclass(frozen=True)
class WhatsAppConfig:
    """Configurações do monitoramento do WhatsApp Web."""
    grupo: str            = "TURMA"  # <- nome EXATO do grupo
    hora_inicio: str      = "12:43"
    hora_fim: str         = "13:10"
    session_dir: str      = "./whatsapp_session"
    intervalo_scan: float = 3.0    # segundos entre verificações
    login_timeout: int    = 180    # segundos aguardando login (QR Code ou número de telefone)


@dataclass(frozen=True)
class RetryConfig:
    """Configurações de retry e tolerância a falhas."""
    max_tentativas_envio: int  = 3      # tentativas de clicar em Enviar
    timeout_campo: int         = 5      # segundos aguardando cada campo aparecer
    timeout_formulario: int    = 20     # segundos para o Forms carregar
    salvar_screenshot: bool    = True   # salva print em caso de erro
    screenshot_dir: str        = "./screenshots"


@dataclass(frozen=True)
class AppConfig:
    """Configurações gerais da aplicação."""
    # True  = preenche mas NÃO envia (modo teste)
    # False = preenche e ENVIA de verdade
    apenas_preencher: bool = False

# ── Instâncias prontas para importar ──────────────────────────────────────────
form_data    = FormData()
whatsapp_cfg = WhatsAppConfig()
retry_cfg    = RetryConfig()
app_cfg      = AppConfig()