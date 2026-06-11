"""
core/monitor.py — Monitoramento do WhatsApp Web.

Proteção contra links indesejados (duas camadas):
  1. Filtro "cabine": só age se a mensagem contiver a palavra "cabine".
                      Evita reagir a outros formulários no grupo.
  2. Filtro de data: só age se o data-pre-plain-text contiver DD/MM/AAAA de hoje.
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
from datetime import date, datetime

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
    if _WHATSAPP_URL not in page.url:
        raise SessionRevokedError(
            f"Página saiu do WhatsApp Web (URL: {page.url}).\n"
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

_CONV_PANEL_SELECTOR = (
    'div[data-testid="conversation-panel-messages"], '
    'div.copyable-area'
)


async def _wait_conv_panel(page) -> None:
    """Aguarda o painel de mensagens aparecer; fallback para sleep se não achar."""
    try:
        await page.wait_for_selector(_CONV_PANEL_SELECTOR, timeout=6000)
    except Exception:
        await page.wait_for_timeout(1500)


async def _open_group(page, group_name: str) -> None:
    """Abre o grupo. Levanta GroupNotFoundError com sugestões se não achar."""
    group_el = await page.query_selector(f'span[title="{group_name}"]')
    if group_el:
        await group_el.click()
        await _wait_conv_panel(page)
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
                await _wait_conv_panel(page)
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
    # Fallback se os seletores principais falharem (WhatsApp atualizou data-testid)
    try:
        await page.evaluate("""
            [
                ...document.querySelectorAll('[data-testid="conversation-panel-messages"]'),
                ...document.querySelectorAll('.copyable-area'),
            ].forEach(el => { el.scrollTop = el.scrollHeight; });
        """)
    except Exception:
        pass

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

# ── Modificação na função _is_today ──────────────────────────────────────────

def _is_today(timestamp_str: str) -> bool:
    """
    Verifica se um timestamp do WhatsApp Web corresponde a hoje.

    Exige data confirmada no formato DD/MM/AAAA (presente no data-pre-plain-text).
    Apenas HH:MM sem data → False (não é possível confirmar o dia).
    """
    if not timestamp_str:
        return False

    date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{2,4})', timestamp_str)
    if not date_match:
        return False

    try:
        parts = date_match.group(1).split('/')
        day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
        if year < 100:
            year += 2000
        return date(year, month, day) == date.today()
    except (ValueError, IndexError):
        return False


# ── Modificação na função _find_new_forms_link ─────────────────────────────────

async def _find_new_forms_link(page) -> str | None:
    """
    Busca um link de formulário válido nas mensagens visíveis.
    Lógica corrigida para evitar falsos positivos de mensagens sem timestamp.
    """
    
    # Só processa links dentro de bolhas de mensagens enviadas (msg-container).
    # Isso evita capturar previews gerados enquanto alguém ainda está digitando.
    _JS_EXTRACTOR = """els => els.map(e => {
        const msgContainer = e.closest('[data-testid="msg-container"]');
        if (!msgContainer) return null;  // ignora links fora de mensagens enviadas

        // Tenta 1: Atributo padrão copyable-text
        let ts = msgContainer.querySelector('[data-pre-plain-text]')?.getAttribute('data-pre-plain-text') ?? '';

        // Tenta 2: Hora impressa na bolha (quando data-pre-plain-text sumiu por scroll)
        if (!ts) {
            const timeEl = msgContainer.querySelector('span[data-testid="msg-time"]')
                           || (() => {
                               const spans = Array.from(msgContainer.querySelectorAll('span[dir="auto"]'));
                               return spans.find(s => /^\\d{1,2}:\\d{2}$/.test(s.innerText.trim())) || null;
                           })();
            if (timeEl && /^\\d{1,2}:\\d{2}$/.test(timeEl.innerText.trim())) {
                ts = timeEl.innerText.trim();
            }
        }

        return {
            href: e.href || e.getAttribute('data-url') || '',
            context: msgContainer.innerText ?? '',
            timestamp: ts
        };
    }).filter(Boolean)"""

    # Estratégia 1: tags <a>
    try:
        entries = await page.eval_on_selector_all(
            'a[href*="docs.google.com/forms"], a[href*="forms.gle"]',
            _JS_EXTRACTOR,
        )
        for entry in reversed(entries):
            href = entry.get("href", "")
            ctx  = entry.get("context", "")
            ts   = entry.get("timestamp", "")
            if href and _KEYWORD_PATTERN.search(ctx) and _is_today(ts):
                return href
    except Exception:
        pass

    # Estratégia 2: data-url (Previews de links)
    try:
        entries = await page.eval_on_selector_all(
            'span[data-url*="docs.google.com/forms"], span[data-url*="forms.gle"]',
            _JS_EXTRACTOR,
        )
        for entry in reversed(entries):
            href = entry.get("href") or ""
            ctx  = entry.get("context", "")
            ts   = entry.get("timestamp", "")
            if href and _KEYWORD_PATTERN.search(ctx) and _is_today(ts):
                return href
    except Exception:
        pass

    # Estratégia 3: Regex puro no texto (Fallback do Fallback)
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
            match = _FORMS_PATTERN.search(text)  # busca no texto original para não concatenar URL com palavra seguinte
            if match:
                href = match.group(0)
                if href and _KEYWORD_PATTERN.search(text) and _is_today(ts):
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
    pre_window_checks = 0
    SESSION_CHECK_EVERY = 5   # verifica sessão a cada ~15s (5 × 3s intervalo_scan)

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
            pre_window_checks += 1
            if pre_window_checks % 4 == 0:  # a cada ~2min (4 × 30s) — detecta logout antes do horário
                await _check_session_alive(page)
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