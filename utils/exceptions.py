"""
utils/exceptions.py — Exceções customizadas do projeto.

Hierarquia:
  ReservaCabineError          ← base de todas
  ├── BrowserError            ← falha ao iniciar o Playwright/Chrome
  ├── WhatsAppError           ← falha no WhatsApp Web
  │   ├── LoginTimeoutError   ← QR Code não escaneado a tempo
  │   └── SessionRevokedError ← sessão expirou ou foi desconectada
  ├── GroupNotFoundError      ← grupo não encontrado no WhatsApp
  ├── LinkNotFoundError       ← janela encerrada sem detectar link
  ├── FormError               ← falha genérica no formulário
  │   ├── FormClosedError     ← formulário fechado/lotado (404 ou encerrado)
  │   └── FormFieldError      ← campo obrigatório não preenchido
  └── SubmitError             ← botão Enviar não encontrado ou clique falhou
"""


class ReservaCabineError(Exception):
    """Base de todas as exceções do projeto."""


class BrowserError(ReservaCabineError):
    """Falha ao iniciar o browser ou o Playwright não está instalado."""


class WhatsAppError(ReservaCabineError):
    """Falha genérica no WhatsApp Web."""


class LoginTimeoutError(WhatsAppError):
    """QR Code não foi escaneado dentro do tempo limite."""


class SessionRevokedError(WhatsAppError):
    """Sessão do WhatsApp foi desconectada ou revogada."""


class GroupNotFoundError(ReservaCabineError):
    """Grupo configurado não foi encontrado no WhatsApp Web."""
    def __init__(self, group_name: str, suggestions: list[str] | None = None):
        self.group_name = group_name
        self.suggestions = suggestions or []
        msg = f"Grupo '{group_name}' não encontrado."
        if self.suggestions:
            msg += f" Grupos similares encontrados: {', '.join(self.suggestions)}"
        super().__init__(msg)


class LinkNotFoundError(ReservaCabineError):
    """Janela de monitoramento encerrada sem encontrar o link do Forms."""


class FormError(ReservaCabineError):
    """Falha genérica ao processar o formulário."""


class FormClosedError(FormError):
    """Formulário está fechado, lotado ou retornou erro (404/encerrado)."""


class FormFieldError(FormError):
    """Campo obrigatório não foi preenchido."""
    def __init__(self, field_name: str):
        self.field_name = field_name
        super().__init__(f"Campo obrigatório não preenchido: '{field_name}'")


class SubmitError(ReservaCabineError):
    """Botão Enviar não encontrado ou clique falhou."""