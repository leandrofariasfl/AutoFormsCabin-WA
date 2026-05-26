"""
core/browser.py — Gerenciamento do ciclo de vida do browser.

Exceções tratadas:
  - Playwright não instalado → BrowserError com instrução de instalação
  - Browser fecha inesperadamente → BrowserError com contexto

Sessão persistente:
  - WhatsApp Web e Google Account ficam salvos na mesma pasta (session_dir).
  - Na primeira execução o script abre o Google para login antes do WhatsApp.
  - Nas execuções seguintes ambas as sessões já estão ativas.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from playwright.async_api import async_playwright, BrowserContext

from config import whatsapp_cfg
from utils import log
from utils.exceptions import BrowserError, ReservaCabineError

_GOOGLE_URL       = "https://accounts.google.com"
_GOOGLE_LOGGED_IN = "https://myaccount.google.com"


async def _ensure_google_logged_in(browser: BrowserContext) -> None:
    """
    Verifica se já existe uma sessão Google ativa no browser.
    - Se sim: segue em frente silenciosamente.
    - Se não: abre accounts.google.com e aguarda o usuário fazer login manualmente.
      Após o login a sessão fica salva na pasta whatsapp_session/ junto com
      a sessão do WhatsApp — nunca mais será pedida.
    """
    page = await browser.new_page()
    try:
        await page.goto(_GOOGLE_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(1000)

        # Se redirecionou para myaccount → já está logado
        if "myaccount.google.com" in page.url:
            log("✓ Sessão Google ativa.")
            return

        # Verifica pelo avatar/nome de usuário no DOM
        logged_in = await page.query_selector(
            'a[href*="myaccount.google.com"], '
            'div[data-ogsr-up], '
            'img[data-noaft]'
        )
        if logged_in:
            log("✓ Sessão Google ativa.")
            return

        # Não está logado — pede ao usuário para fazer login
        log("⚠️  Login Google necessário — faça login no Chrome que abriu.")
        log("    Após o login a sessão será salva e nunca mais será pedida.")

        # Aguarda até 120s pelo redirecionamento para myaccount
        await page.wait_for_url("**/myaccount.google.com/**", timeout=120000)
        log("✓ Login Google realizado. Sessão salva.")

    except Exception as e:
        # Login Google não é crítico — apenas avisa e continua
        # (alguns Forms não exigem login)
        log(f"  ℹ️  Não foi possível verificar sessão Google: {e}")
    finally:
        await page.close()


@asynccontextmanager
async def get_browser() -> AsyncGenerator[BrowserContext, None]:
    """
    Context manager que entrega um BrowserContext persistente e garante
    fechamento seguro mesmo em caso de exceção.

    Na primeira execução:
      1. Abre o Chrome
      2. Verifica/faz login no Google (salva sessão)
      3. Entrega o browser para o monitor (que fará login no WhatsApp)

    Nas execuções seguintes:
      - Ambas as sessões já estão ativas — abre direto.
    """
    try:
        from playwright.async_api import async_playwright  # noqa: F811
    except ImportError:
        raise BrowserError(
            "Playwright não encontrado.\n"
            "  Instale com:\n"
            "    pip install playwright\n"
            "    python -m playwright install chromium"
        )

    try:
        async with async_playwright() as playwright:
            log("Iniciando browser...")
            try:
                browser = await playwright.chromium.launch_persistent_context(
                    user_data_dir=whatsapp_cfg.session_dir,
                    headless=False,
                    args=["--start-maximized"],
                )
            except Exception as e:
                raise BrowserError(
                    f"Não foi possível iniciar o Chrome.\n"
                    f"  Detalhe: {e}\n"
                    f"  Tente: python -m playwright install chromium"
                ) from e

            # Garante sessão Google antes de qualquer coisa
            await _ensure_google_logged_in(browser)

            try:
                yield browser
            finally:
                try:
                    await browser.close()
                    log("Browser encerrado.")
                except Exception:
                    pass
    except ReservaCabineError:
        raise
    except Exception as e:
        raise BrowserError(f"Erro inesperado no browser: {e}") from e