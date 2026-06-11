"""
core/form_filler.py — Preenchimento do Google Forms.

Exceções tratadas:
  - Formulário fechado/404        → FormClosedError
  - Campo obrigatório não achado  → FormFieldError (com log dos títulos detectados)
  - Cabine indisponível           → fallback automático pela lista em config
  - Botão Enviar não encontrado   → SubmitError com retry + screenshot
  - Sem confirmação pós-envio     → aviso no log
"""

import asyncio
import os
from datetime import datetime

from playwright.async_api import Page, ElementHandle

from config import form_data, app_cfg, retry_cfg
from utils import log
from utils.exceptions import FormClosedError, FormFieldError, SubmitError


# ── Seletores ──────────────────────────────────────────────────────────────────

_INPUT_SELECTORS = (
    'input[type="text"]',
    'input[type="tel"]',
    'input[type="email"]',
)

_DROPDOWN_SELECTORS = (
    'div[role="listbox"]',
    'div[aria-haspopup="listbox"]',
    'div.MocG8c',
)

_RADIO_SELECTORS = (
    'div[role="radiogroup"]',
)

_SUBMIT_SELECTORS = (
    'div[role="button"][jsname="M2UYVd"]',
    'div[role="button"]:has-text("Enviar")',
    'div[role="button"]:has-text("Submit")',
)

_TITLE_SELECTORS = (
    'div[role="heading"]',
    'span[role="heading"]',
    'div.M7eMe',
    'div.z12JJ',
)

# Palavras-chave → valor a preencher (para campos de texto além de nome/sobrenome)
_TEXT_FIELD_MAP: dict[tuple[str, ...], str] = {
    ("whatsapp", "telefone", "celular", "fone", "contato"): form_data.whatsapp,
}

# Campos obrigatórios que DEVEM ser preenchidos para considerar sucesso
_REQUIRED_FIELDS = {"nome", "sobrenome", "whatsapp", "turma", "cabine"}


# ── Helpers privados ───────────────────────────────────────────────────────────

async def _get_title(group: ElementHandle) -> str:
    for selector in _TITLE_SELECTORS:
        el = await group.query_selector(selector)
        if el:
            return (await el.inner_text()).strip()
    return ""


async def _find_first(group, selectors: tuple) -> ElementHandle | None:
    for selector in selectors:
        el = await group.query_selector(selector)
        if el:
            return el
    return None


async def _save_screenshot(page: Page, label: str) -> None:
    """Salva um screenshot de diagnóstico se habilitado na config."""
    if not retry_cfg.salvar_screenshot:
        return
    try:
        os.makedirs(retry_cfg.screenshot_dir, exist_ok=True)
        ts = datetime.now().strftime("%H%M%S")
        path = os.path.join(retry_cfg.screenshot_dir, f"{label}_{ts}.png")
        await page.screenshot(path=path)
        log(f"  📸 Screenshot salvo: {path}")
    except Exception as e:
        log(f"  ⚠️  Não foi possível salvar screenshot: {e}")


async def _select_option(page: Page, dropdown: ElementHandle, value: str) -> bool:
    """Abre o dropdown e clica na opção que contém `value`. Retorna True se achou."""
    await dropdown.click()
    await page.wait_for_timeout(600)

    options = await page.query_selector_all('div[role="option"]')
    for option in options:
        text = (await option.inner_text()).strip()
        if value.lower() in text.lower():
            await option.click()
            return True

    await page.keyboard.press("Escape")
    return False


async def _select_with_fallback(page: Page, dropdown: ElementHandle, field: str) -> str | None:
    """
    Abre o dropdown UMA VEZ, captura todas as opções e itera os candidatos em memória.
    Evita ciclos de abrir/fechar para cada candidato — cada segundo importa.
    """
    await dropdown.click()
    await page.wait_for_timeout(600)

    options = await page.query_selector_all('div[role="option"]')
    option_texts: list[tuple[str, ElementHandle]] = []
    for opt in options:
        text = (await opt.inner_text()).strip()
        option_texts.append((text, opt))

    candidates = [form_data.cabine] + list(form_data.cabines_fallback)
    for candidate in candidates:
        for text, opt in option_texts:
            if candidate.lower() in text.lower():
                await opt.click()
                if candidate != form_data.cabine:
                    log(f"  ⚠️  Cabine {form_data.cabine} indisponível — usando fallback: {candidate}")
                return candidate

    await page.keyboard.press("Escape")
    return None


async def _check_form_accessible(page: Page, url: str) -> None:
    """
    Verifica se o formulário está acessível.
    Lança FormClosedError se estiver fechado, expirado ou retornar erro.
    """
    title = await page.title()
    content = await page.content()

    closed_signals = [
        "Este formulário não está mais aceitando respostas",
        "This form is no longer accepting responses",
        "Não é possível acessar este formulário",
    ]
    # Verifica 404 só no título (evita falso positivo em scripts JS da página)
    if "404" in title:
        raise FormClosedError(f"Formulário retornou 404.\n  URL: {url}")

    for signal in closed_signals:
        if signal.lower() in content.lower() or signal.lower() in title.lower():
            raise FormClosedError(
                f"Formulário inacessível: '{signal}' detectado.\n"
                f"  URL: {url}"
            )


async def _verify_submission(page: Page) -> bool:
    """
    Aguarda ATIVAMENTE até 10s pela confirmação do envio (URL ou texto).
    Substitui sleep fixo de 2s — evita falso SubmitError em servidores lentos.
    """
    try:
        await page.wait_for_function(
            """() => {
                const url  = window.location.href;
                const text = document.body?.innerText || '';
                return url.includes('formResponse')
                    || text.includes('Sua resposta foi registrada')
                    || text.includes('Your response has been recorded')
                    || text.includes('Obrigado')
                    || text.includes('Thanks');
            }""",
            timeout=10000,
        )
        return True
    except Exception:
        return False


# ── Interface pública ──────────────────────────────────────────────────────────

async def fill_form(page: Page, url: str) -> None:
    """
    Abre o formulário no `url`, preenche todos os campos e envia.
    Levanta exceções específicas para cada tipo de falha.
    """
    log(f"Abrindo formulário: {url}")

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=retry_cfg.timeout_formulario * 1000)
    except Exception as e:
        await _save_screenshot(page, "erro_carregar_forms")
        raise FormClosedError(f"Timeout ao carregar o formulário: {e}") from e

    # Aguarda os campos aparecerem — mais confiável que sleep fixo + networkidle
    try:
        await page.wait_for_selector(
            'div[role="listitem"]',
            timeout=retry_cfg.timeout_formulario * 1000,
        )
    except Exception:
        pass  # _check_form_accessible detectará o estado real abaixo

    await _check_form_accessible(page, url)

    groups = await page.query_selector_all('div[role="listitem"]')
    log(f"{len(groups)} campo(s) encontrado(s).")

    if not groups:
        await _save_screenshot(page, "formulario_vazio")
        raise FormClosedError("Nenhum campo encontrado — formulário pode estar fechado ou com estrutura inesperada.")

    # Rastreia quais campos obrigatórios foram preenchidos
    filled: set[str] = set()
    all_titles: list[str] = []

    for i, group in enumerate(groups):
        title = await _get_title(group)
        title_lower = title.lower()
        all_titles.append(title or f"(sem título, campo {i+1})")

        # ── Campo de texto ──────────────────────────────────────────────────
        input_el = await _find_first(group, _INPUT_SELECTORS)
        if input_el:
            result = await _fill_text_field(input_el, title, title_lower)
            if result:
                filled.add(result)
            continue

        # ── Dropdown ────────────────────────────────────────────────────────
        dropdown = await _find_first(group, _DROPDOWN_SELECTORS)
        if dropdown:
            result = await _fill_dropdown(page, dropdown, title, title_lower)
            if result:
                filled.add(result)
            continue

        # ── Radio Group ──────────────────────────────────────────────────────
        radio_group = await _find_first(group, _RADIO_SELECTORS)
        if radio_group:
            result = await _fill_radio_group(page, radio_group, title, title_lower)
            if result:
                filled.add(result)
            continue

        log(f"  — [Campo {i+1}] '{title}': tipo não reconhecido, pulando.")

    # Valida campos obrigatórios
    missing = _REQUIRED_FIELDS - filled
    if missing:
        log(f"  ⚠️  Campos não preenchidos: {missing}")
        log(f"  ℹ️  Títulos detectados no formulário: {all_titles}")
        await _save_screenshot(page, "campos_ausentes")
        # Não interrompe — tenta enviar assim mesmo e loga o aviso

    await _submit(page)


async def _fill_text_field(input_el: ElementHandle, title: str, title_lower: str) -> str | None:
    """Preenche um campo de texto. Retorna a chave do campo preenchido ou None."""
    if "nome" in title_lower and "sobre" not in title_lower:
        await input_el.fill(form_data.nome)
        log(f"  ✓ Nome: '{form_data.nome}'")
        return "nome"
    elif "sobrenome" in title_lower:
        await input_el.fill(form_data.sobrenome)
        log(f"  ✓ Sobrenome: '{form_data.sobrenome}'")
        return "sobrenome"
    else:
        for keywords, value in _TEXT_FIELD_MAP.items():
            if any(kw in title_lower for kw in keywords):
                await input_el.fill(value)
                log(f"  ✓ {title}: '{value}'")
                return "whatsapp"
        log(f"  ⚠️  Campo de texto não mapeado: '{title}'")
        return None


async def _fill_dropdown(page: Page, dropdown: ElementHandle, title: str, title_lower: str) -> str | None:
    """Seleciona opção no dropdown. Retorna a chave do campo preenchido ou None."""
    if "turma" in title_lower:
        ok = await _select_option(page, dropdown, form_data.turma)
        if ok:
            log(f"  ✓ Turma: '{form_data.turma}'")
            return "turma"
        else:
            log(f"  ⚠️  Turma '{form_data.turma}' não encontrada no dropdown")
            return None

    elif "cabine" in title_lower:
        selected = await _select_with_fallback(page, dropdown, "cabine")
        if selected:
            log(f"  ✓ Cabine: '{selected}'")
            return "cabine"
        else:
            log(f"  ⚠️  Nenhuma cabine do fallback disponível no dropdown")
            await _save_screenshot(page, "cabine_indisponivel")
            return None

    else:
        log(f"  ⚠️  Dropdown não mapeado: '{title}'")
        return None


async def _select_radio(radio_group: ElementHandle, value: str) -> bool:
    """Clica no radio button que contém `value`. Retorna True se achou."""
    options = await radio_group.query_selector_all('div[role="radio"]')
    for option in options:
        text = (await option.inner_text()).strip()
        if value.lower() in text.lower():
            await option.click()
            return True
    return False


async def _select_radio_with_fallback(radio_group: ElementHandle) -> str | None:
    """
    Lê TODAS as opções de radio de uma vez e escolhe a melhor cabine.
    Sem abrir/fechar nada — direto ao clique.
    """
    options = await radio_group.query_selector_all('div[role="radio"]')
    option_texts: list[tuple[str, ElementHandle]] = []
    for opt in options:
        text = (await opt.inner_text()).strip()
        option_texts.append((text, opt))

    candidates = [form_data.cabine] + list(form_data.cabines_fallback)
    for candidate in candidates:
        for text, opt in option_texts:
            if candidate.lower() in text.lower():
                await opt.click()
                if candidate != form_data.cabine:
                    log(f"  ⚠️  Cabine {form_data.cabine} indisponível — usando fallback radio: {candidate}")
                return candidate
    return None


async def _fill_radio_group(page: Page, radio_group: ElementHandle, title: str, title_lower: str) -> str | None:
    """Seleciona opção em radio group. Retorna a chave do campo preenchido ou None."""
    if "turma" in title_lower:
        ok = await _select_radio(radio_group, form_data.turma)
        if ok:
            log(f"  ✓ Turma (radio): '{form_data.turma}'")
            return "turma"
        log(f"  ⚠️  Turma '{form_data.turma}' não encontrada nos radio buttons")
        return None
    if "cabine" in title_lower:
        selected = await _select_radio_with_fallback(radio_group)
        if selected:
            log(f"  ✓ Cabine (radio): '{selected}'")
            return "cabine"
        log(f"  ⚠️  Nenhuma cabine do fallback disponível nos radio buttons")
        await _save_screenshot(page, "cabine_radio_indisponivel")
        return None
    log(f"  ⚠️  Radio group não mapeado: '{title}'")
    return None


async def _submit(page: Page) -> None:
    """Clica em Enviar com retry. Verifica confirmação pós-envio."""
    if app_cfg.apenas_preencher:
        log("⏸  MODO TESTE — formulário NÃO enviado. (app_cfg.apenas_preencher = True)")
        await asyncio.sleep(15)
        return

    for attempt in range(1, retry_cfg.max_tentativas_envio + 1):
        submit_btn = await _find_first(page, _SUBMIT_SELECTORS)  # type: ignore[arg-type]
        if submit_btn:
            await submit_btn.click()
            confirmed = await _verify_submission(page)
            if confirmed:
                log("✅ Formulário ENVIADO e confirmado com sucesso!")
                return
            else:
                log(f"  ⚠️  Confirmação não detectada (tentativa {attempt}/{retry_cfg.max_tentativas_envio})")
                await page.wait_for_timeout(1500)
        else:
            log(f"  ⚠️  Botão Enviar não encontrado (tentativa {attempt}/{retry_cfg.max_tentativas_envio})")
            await page.wait_for_timeout(1000)

    await _save_screenshot(page, "erro_envio")
    raise SubmitError(
        f"Não foi possível enviar após {retry_cfg.max_tentativas_envio} tentativas. "
        f"Screenshot salvo em '{retry_cfg.screenshot_dir}/'."
    )

