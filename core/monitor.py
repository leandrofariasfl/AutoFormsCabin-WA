"""
core/monitor.py — Monitoramento do WhatsApp Web.

Proteção contra links indesejados (duas camadas):
  1. Filtro "cabine": só age se a mensagem contiver a palavra "cabine".
                      Evita reagir a outros formulários no grupo.
  2. Filtro de data: só age se o timestamp for de hoje (formato HH:MM).
                     Elimina links de dias anteriores com certeza.

Exceções tratadas:
  - QR Code não escaneado a tempo   → LoginTimeoutError
  - Sessão desconectada em runtime  → SessionRevokedError
  - Grupo não encontrado            → GroupNotFoundError com sugestões
  - Janela encerrada sem link       → LinkNotFoundError
"""

import asyncio
import difflib
import re
from datetime import datetime

from playwright.async_api import BrowserContext

from config import whatsapp_cfg
from core.form_filler import fill_form
from utils import log
from utils.exceptions import (
    GroupNotFoundError,
    LinkNotFoundError,
    LoginTimeoutError,
    SessionRevokedError,
)

# ── Constantes ─────────────────────────────────────────────────────────────────

_FORMS_PATTERN = re.compile(
    r'https://(?:docs\.google\.com/forms/[^\s"\'>\]]+|forms\.gle/[^\s"\'>\]]+)'
)

# Palavras-chave que devem estar na mensagem para o link ser considerado válido.
# Basta UMA delas aparecer (case-insensitive).
_KEYWORD_PATTERN = re.compile(r'cabine', re.IGNORECASE)

_WHATSAPP_URL = "https://web.whatsapp.com"

_CHAT_LIST_SELECTOR = (
    'div[aria-label="Lista de conversas"], '
    'div[data-testid="chat-list"]'
)
_QR_CODE_SELECTOR = (
    'canvas[aria-label*="QR"], '
    'div[data-testid="qrcode"], '
    'div[aria-label*="QR code"]'
)
_LOGGED_OUT_SELECTOR = (
    'div[data-testid="intro-title"], '
    'div._3_7SH, '
    'div[data-testid="qrcode"]'
)
_SEARCH_INPUT_SELECTORS = (
    'div[data-testid="chat-list-search"] input',
    'div[aria-label*="Pesquisar"] input',
    'div[aria-label*="Search"] input',
)
_SCROLL_SELECTORS = (
    'div[data-testid="conversation-panel-messages"]',
    'div.copyable-area',
)
_MESSAGE_SELECTORS = (
    'div.copyable-text',
    'div._21Ahp',
    'span.selectable-text',
)

# ── Helpers: WhatsApp ──────────────────────────────────────────────────────────

def _now_hhmm() -> str:
    return datetime.now().strftime("%H:%M")

async def _is_logged_out(page) -> bool:
    try:
        el = await page.query_selector(_LOGGED_OUT_SELECTOR)
        return el is not None
    except Exception:
        return False

async def _wait_for_whatsapp(page) -> None:
    """
    Abre o WhatsApp Web e aguarda login.

    Suporta qualquer método de login do WhatsApp Web:
      - QR Code
      - Número de telefone (tem etapas extras — digitar número, confirmar código)
      - Sessão já ativa (abre direto)

    Detecta se qualquer tela de login está visível e aguarda até o
    chat_list aparecer, independente do método escolhido pelo usuário.
    """
    log("Abrindo WhatsApp Web...")
    await page.goto(_WHATSAPP_URL, wait_until="networkidle", timeout=60000)

    # Tenta detectar se a lista de conversas já está visível (sessão ativa)
    chat_list = await page.query_selector(_CHAT_LIST_SELECTOR)
    if chat_list:
        # Sessão já ativa — não precisa de login
        pass
    else:
        # Qualquer tela de login: QR Code, número de telefone ou tela inicial
        log(
            f"⚠️  Login necessário — use QR Code ou número de telefone "
            f"(aguardando até {whatsapp_cfg.login_timeout}s)..."
        )
        try:
            await page.wait_for_selector(
                _CHAT_LIST_SELECTOR,
                timeout=whatsapp_cfg.login_timeout * 1000,
            )
            log("✓ Login realizado. Sessão salva.")
        except Exception:
            raise LoginTimeoutError(
                f"Login não concluído em {whatsapp_cfg.login_timeout}s.\n"
                f"  Dica: aumente 'login_timeout' em config.py se precisar de mais tempo."
            )

    log("WhatsApp Web pronto.")

async def _check_session_alive(page) -> None:
    """Levanta SessionRevokedError se o WhatsApp tiver desconectado."""
    if await _is_logged_out(page):
        raise SessionRevokedError(
            "Sessão do WhatsApp foi desconectada.\n"
            "  Apague './whatsapp_session/' e execute novamente."
        )

async def _get_all_group_names(page) -> list[str]:
    try:
        spans = await page.query_selector_all('span[title]')
        names = []
        for span in spans:
            title = await span.get_attribute("title")
            if title and title.strip():
                names.append(title.strip())
        return list(dict.fromkeys(names))
    except Exception:
        return []

async def _open_group(page, group_name: str) -> None:
    """Abre o grupo. Levanta GroupNotFoundError com sugestões se não achar."""
    group_el = await page.query_selector(f'span[title="{group_name}"]')
    if group_el:
        await group_el.click()
        await page.wait_for_timeout(1000)
        return

    for selector in _SEARCH_INPUT_SELECTORS:
        search_box = await page.query_selector(selector)
        if search_box:
            await search_box.click()
            await search_box.fill("")
            await search_box.type(group_name, delay=80)
            await page.wait_for_timeout(1200)

            result = await page.query_selector(f'span[title="{group_name}"]')
            if result:
                await result.click()
                await page.wait_for_timeout(1000)
                return

            all_names = await _get_all_group_names(page)
            suggestions = difflib.get_close_matches(group_name, all_names, n=3, cutoff=0.3)
            await search_box.fill("")
            await page.keyboard.press("Escape")
            raise GroupNotFoundError(group_name, suggestions)

    raise GroupNotFoundError(group_name)

async def _scroll_to_bottom(page) -> None:
    for selector in _SCROLL_SELECTORS:
        try:
            await page.eval_on_selector(selector, "el => el.scrollTop = el.scrollHeight")
            return
        except Exception:
            continue

# ── Helpers: detecção de link ──────────────────────────────────────────────────

async def _get_all_visible_texts(page) -> list[str]:
    """Retorna o texto de todas as mensagens visíveis no grupo."""
    try:
        return await page.eval_on_selector_all(
            ", ".join(_MESSAGE_SELECTORS),
            "els => els.map(e => e.innerText).filter(t => t.trim().length > 0)",
        )
    except Exception:
        return []

def _is_today(timestamp_str: str) -> bool:
    """
    Verifica se um timestamp do WhatsApp Web corresponde a hoje.

    O WhatsApp exibe timestamps em formatos variados:
      - Mensagem do dia:        "14:53"         → apenas hora → é hoje
      - Mensagem de ontem:      "ontem"         → não é hoje
      - Mensagem desta semana:  "segunda-feira" → não é hoje
      - Mensagem mais antiga:   "12/05/2025"    → não é hoje

    Estratégia: se a string contém apenas dígitos e ":" (ex: "14:53"),
    é uma mensagem de hoje. Qualquer outro formato é de outro dia.
    """
    if not timestamp_str:
        return True  # sem timestamp → não penaliza, deixa passar

    ts = timestamp_str.strip().lower()

    # Formato "HH:MM" ou "H:MM" → mensagem de hoje
    if re.match(r'^\d{1,2}:\d{2}$', ts):
        return True

    # Qualquer outro formato (ontem, seg., dd/mm/aaaa, etc.) → outro dia
    return False

async def _find_new_forms_link(page) -> str | None:
    """
    Busca um link de formulário válido nas mensagens visíveis.

    Duas condições para processar o link:
      1. A mensagem contém "cabine" (case-insensitive) — filtra outros formulários.
      2. O timestamp é de hoje (formato HH:MM) — filtra links de dias anteriores.

    Por que buscar no container da mensagem e não só no elemento do link:
    O WhatsApp Web renderiza o preview num bloco separado do texto original —
    verificar o container pai garante que "cabine" seja detectado mesmo quando
    o link está num elemento irmão.
    """
    # Estratégia 1: tags <a> — mais confiável
    try:
        entries = await page.eval_on_selector_all(
            'a[href*="docs.google.com/forms"], a[href*="forms.gle"]',
            """els => els.map(e => {
                const container = e.closest('[data-testid="msg-container"], .copyable-area, div.copyable-text');
                return {
                    href: e.href,
                    context: container?.innerText ?? '',
                    timestamp: container?.querySelector('[data-pre-plain-text]')
                                ?.getAttribute('data-pre-plain-text') ?? ''
                };
            })""",
        )
        for entry in reversed(entries):
            href = entry.get("href", "")
            ctx  = entry.get("context", "")
            ts   = entry.get("timestamp", "")
            # Extrai "HH:MM" do data-pre-plain-text "[HH:MM, DD/MM/AAAA] Nome:"
            ts_match = re.search(r'\[(\d{1,2}:\d{2})', ts)
            ts_clean = ts_match.group(1) if ts_match else ts
            if href and _KEYWORD_PATTERN.search(ctx) and _is_today(ts_clean):
                return href
    except Exception:
        pass

    # Estratégia 2: data-url
    try:
        entries = await page.eval_on_selector_all(
            'span[data-url*="docs.google.com/forms"], span[data-url*="forms.gle"]',
            """els => els.map(e => {
                const container = e.closest('[data-testid="msg-container"], .copyable-area, div.copyable-text');
                return {
                    href: e.getAttribute('data-url'),
                    context: container?.innerText ?? '',
                    timestamp: container?.querySelector('[data-pre-plain-text]')
                                ?.getAttribute('data-pre-plain-text') ?? ''
                };
            })""",
        )
        for entry in reversed(entries):
            href = entry.get("href") or ""
            ctx  = entry.get("context", "")
            ts   = entry.get("timestamp", "")
            ts_match = re.search(r'\[(\d{1,2}:\d{2})', ts)
            ts_clean = ts_match.group(1) if ts_match else ts
            if href and _KEYWORD_PATTERN.search(ctx) and _is_today(ts_clean):
                return href
    except Exception:
        pass

    # Estratégia 3: regex no texto + timestamp via data-pre-plain-text (fallback)
    try:
        entries = await page.eval_on_selector_all(
            'div.copyable-text[data-pre-plain-text], div.copyable-text, div._21Ahp, span.selectable-text',
            """els => els.map(e => ({
                text: e.innerText,
                timestamp: e.getAttribute?.('data-pre-plain-text') ?? ''
            })).filter(e => e.text.trim().length > 0)""",
        )
        for entry in reversed(entries):
            text = entry.get("text", "")
            ts   = entry.get("timestamp", "")
            clean = text.replace("\n", "").replace("\r", "")
            match = _FORMS_PATTERN.search(clean)
            if match:
                href = match.group(0)
                ts_match = re.search(r'\[(\d{1,2}:\d{2})', ts)
                ts_clean = ts_match.group(1) if ts_match else ts
                if href and _KEYWORD_PATTERN.search(text) and _is_today(ts_clean):
                    return href
    except Exception:
        pass

    return None

async def _log_last_message(page) -> None:
    """Loga a última mensagem visível para diagnóstico."""
    texts = await _get_all_visible_texts(page)
    if texts:
        last = texts[-1].strip()[:200]
        log(f"  ℹ️  Última mensagem visível: {repr(last)}")

# ── Interface pública ──────────────────────────────────────────────────────────

async def run_monitor(browser: BrowserContext) -> None:
    """
    Abre o WhatsApp Web, navega ao grupo e monitora novas mensagens.

    Só processa um link se:
      1. A mensagem contém "cabine" (filtra outros formulários).
      2. O timestamp é de hoje — formato HH:MM (filtra links de dias anteriores).
    """
    page = await browser.new_page()

    await _wait_for_whatsapp(page)

    log(f"Abrindo grupo: '{whatsapp_cfg.grupo}'")
    await _open_group(page, whatsapp_cfg.grupo)

    log(f"Pronto. Monitorando entre {whatsapp_cfg.hora_inicio} e "
        f"{whatsapp_cfg.hora_fim} (a cada {whatsapp_cfg.intervalo_scan}s)...")

    attempts = 0
    SESSION_CHECK_EVERY = 20

    while True:
        now = _now_hhmm()

        if now > whatsapp_cfg.hora_fim:
            log("Janela de monitoramento encerrada.")
            await _log_last_message(page)
            raise LinkNotFoundError(
                f"Nenhum link válido encontrado entre "
                f"{whatsapp_cfg.hora_inicio} e {whatsapp_cfg.hora_fim}."
            )

        if now < whatsapp_cfg.hora_inicio:
            await asyncio.sleep(30)
            continue

        if attempts % SESSION_CHECK_EVERY == 0 and attempts > 0:
            await _check_session_alive(page)

        await _scroll_to_bottom(page)
        link = await _find_new_forms_link(page)

        if link:
            log(f"🔗 Link detectado: {link}")
            form_page = await browser.new_page()
            try:
                await fill_form(form_page, link)
            finally:
                await asyncio.sleep(3)
                await form_page.close()
            log("✅ Processo concluído!")
            return

        attempts += 1
        if attempts % 10 == 0:
            log(f"Aguardando link... ({attempts} verificações)")

        await asyncio.sleep(whatsapp_cfg.intervalo_scan)