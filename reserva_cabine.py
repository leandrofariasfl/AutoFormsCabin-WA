"""
Automação de Reserva de Cabine de Estudo
-----------------------------------------
Monitora o WhatsApp Web, detecta o link do Google Forms
e preenche o formulário automaticamente.
"""

import asyncio
import re
from datetime import datetime
from playwright.async_api import async_playwright

# ─────────────────────────────────────────
#  CONFIG — edite apenas esta seção
# ─────────────────────────────────────────
NOME       = "Laísa"
SOBRENOME  = "Santos de Souza"
WHATSAPP   = "79999999999"
TURMA      = "OSWALDO"
CABINE     = "16"

GRUPO_WHATSAPP = "</>"  # <- nome EXATO do grupo no WhatsApp Web

HORA_INICIO = "11:02" #12:40
HORA_FIM    = "13:00" #13:10

# True  = preenche mas NÃO envia (para testes)
# False = preenche e ENVIA de verdade
APENAS_PREENCHER = False
# ─────────────────────────────────────────


# ✅ CORRIGIDO: reconhece tanto docs.google.com/forms quanto forms.gle
GOOGLE_FORMS_PATTERN = re.compile(
    r'https://(?:docs\.google\.com/forms/[^\s"\'>\]]+|forms\.gle/[^\s"\'>\]]+)'
)


def log(msg: str):
    agora = datetime.now().strftime("%H:%M:%S")
    print(f"[{agora}] {msg}", flush=True)


async def preencher_formulario(page, url: str):
    log(f"Abrindo formulário: {url}")
    await page.goto(url, wait_until="networkidle", timeout=20000)
    await page.wait_for_timeout(1500)

    grupos = await page.query_selector_all('div[role="listitem"]')
    log(f"{len(grupos)} campo(s) encontrado(s).")

    for i, grupo in enumerate(grupos):
        titulo_el = await grupo.query_selector(
            'div[role="heading"], span[role="heading"], div.M7eMe, div.z12JJ'
        )
        titulo = (await titulo_el.inner_text()).strip() if titulo_el else f"(campo {i+1})"
        titulo_lower = titulo.lower()

        input_el = await grupo.query_selector(
            'input[type="text"], input[type="tel"], input[type="email"]'
        )
        if input_el:
            if "nome" in titulo_lower and "sobre" not in titulo_lower:
                await input_el.fill(NOME)
                log(f"  ✓ Nome preenchido")
            elif "sobrenome" in titulo_lower:
                await input_el.fill(SOBRENOME)
                log(f"  ✓ Sobrenome preenchido")
            elif any(x in titulo_lower for x in ["whatsapp", "telefone", "celular", "fone", "contato"]):
                await input_el.fill(WHATSAPP)
                log(f"  ✓ WhatsApp preenchido")
            else:
                log(f"  ⚠️  Campo de texto não reconhecido: '{titulo}'")
            continue

        dropdown = await grupo.query_selector(
            'div[role="listbox"], div[aria-haspopup="listbox"], div.MocG8c'
        )
        if dropdown:
            if "turma" in titulo_lower:
                ok = await selecionar_opcao(page, dropdown, TURMA)
                log(f"  {'✓ Turma: ' + TURMA if ok else '⚠️  Turma não encontrada'}")
            elif "cabine" in titulo_lower:
                ok = await selecionar_opcao(page, dropdown, CABINE)
                log(f"  {'✓ Cabine: ' + CABINE if ok else '⚠️  Cabine não encontrada'}")
            continue

    if APENAS_PREENCHER:
        log("⏸  MODO TESTE — formulário NÃO enviado. Mude APENAS_PREENCHER = False para enviar.")
        await asyncio.sleep(15)
    else:
        botao = await page.query_selector(
            'div[role="button"][jsname="M2UYVd"], '
            'div[role="button"]:has-text("Enviar"), '
            'div[role="button"]:has-text("Submit")'
        )
        if botao:
            await botao.click()
            await page.wait_for_timeout(2000)
            log("✅ Formulário ENVIADO com sucesso!")
        else:
            log("⚠️  Botão Enviar não encontrado.")


async def selecionar_opcao(page, dropdown, valor: str) -> bool:
    await dropdown.click()
    await page.wait_for_timeout(600)
    opcoes = await page.query_selector_all('div[role="option"]')
    for opcao in opcoes:
        texto = (await opcao.inner_text()).strip()
        if valor.lower() in texto.lower():
            await opcao.click()
            return True
    await page.keyboard.press("Escape")
    return False


async def extrair_link_forms(page) -> str | None:
    """
    Tenta extrair link do Google Forms das mensagens visíveis.
    Usa 3 estratégias em ordem de confiabilidade.
    """
    # Estratégia 1: links <a> clicáveis no DOM (mais confiável)
    # ✅ CORRIGIDO: inclui forms.gle
    try:
        links = await page.eval_on_selector_all(
            'a[href*="docs.google.com/forms"], a[href*="forms.gle"]',
            "els => els.map(e => e.href)"
        )
        if links:
            return links[-1]
    except Exception:
        pass

    # Estratégia 2: atributo data-url em spans de link do WhatsApp
    # ✅ CORRIGIDO: inclui forms.gle
    try:
        links = await page.eval_on_selector_all(
            'span[data-url*="docs.google.com/forms"], span[data-url*="forms.gle"]',
            "els => els.map(e => e.getAttribute('data-url'))"
        )
        if links:
            return links[-1]
    except Exception:
        pass

    # Estratégia 3: regex no texto visível das mensagens
    # ✅ CORRIGIDO: remove quebras de linha que cortam a URL
    try:
        textos = await page.eval_on_selector_all(
            'div.copyable-text, div._21Ahp, span.selectable-text',
            "els => els.map(e => e.innerText)"
        )
        for texto in reversed(textos):
            texto_limpo = texto.replace('\n', '').replace('\r', '')
            match = GOOGLE_FORMS_PATTERN.search(texto_limpo)
            if match:
                return match.group(0)
    except Exception:
        pass

    return None


async def abrir_grupo(page, nome_grupo: str) -> bool:
    """Busca e abre o grupo no WhatsApp Web."""
    try:
        grupo_el = await page.query_selector(f'span[title="{nome_grupo}"]')
        if grupo_el:
            await grupo_el.click()
            await page.wait_for_timeout(1000)
            return True

        caixa = await page.query_selector(
            'div[data-testid="chat-list-search"] input, '
            'div[aria-label*="Pesquisar"] input, '
            'div[aria-label*="Search"] input'
        )
        if caixa:
            await caixa.click()
            await caixa.fill("")
            await caixa.type(nome_grupo, delay=80)
            await page.wait_for_timeout(1200)
            resultado = await page.query_selector(f'span[title="{nome_grupo}"]')
            if resultado:
                await resultado.click()
                await page.wait_for_timeout(1000)
                return True
    except Exception as e:
        log(f"Erro ao abrir grupo: {e}")

    return False


async def monitorar_whatsapp(playwright):
    browser = await playwright.chromium.launch_persistent_context(
        user_data_dir="./whatsapp_session",
        headless=False,
        args=["--start-maximized"],
    )

    page = await browser.new_page()
    log("Abrindo WhatsApp Web...")
    await page.goto("https://web.whatsapp.com", wait_until="networkidle", timeout=60000)
    await page.wait_for_selector(
        'div[aria-label="Lista de conversas"], div[data-testid="chat-list"]',
        timeout=90000
    )
    log("WhatsApp Web pronto.")

    log(f"Abrindo grupo: '{GRUPO_WHATSAPP}'")
    achou = await abrir_grupo(page, GRUPO_WHATSAPP)
    if not achou:
        log(f"⚠️  Grupo '{GRUPO_WHATSAPP}' não encontrado. Verifique o nome exato.")

    log(f"Monitorando entre {HORA_INICIO} e {HORA_FIM}. Aguardando link do Forms...")

    ultimo_link = None
    tentativas = 0

    while True:
        agora = datetime.now().strftime("%H:%M")

        if agora > HORA_FIM:
            log("Janela de monitoramento encerrada.")
            break

        if agora < HORA_INICIO:
            await asyncio.sleep(30)
            continue

        # Rola para o fim para garantir mensagens novas visíveis
        try:
            await page.eval_on_selector(
                'div[data-testid="conversation-panel-messages"], div.copyable-area',
                "el => el.scrollTop = el.scrollHeight"
            )
        except Exception:
            pass

        link = await extrair_link_forms(page)

        if link and link != ultimo_link:
            ultimo_link = link
            log(f"🔗 Link encontrado: {link}")
            nova_aba = await browser.new_page()
            await preencher_formulario(nova_aba, link)
            await asyncio.sleep(3)
            await nova_aba.close()
            log("✅ Processo concluído!")
            await browser.close()
            return

        tentativas += 1
        if tentativas % 10 == 0:
            log(f"Aguardando link... ({tentativas} verificações)")
        await asyncio.sleep(3)

    await browser.close()


async def main():
    print("\n" + "=" * 50)
    print("  Reserva Automática de Cabine")
    print("=" * 50)
    print(f"  Nome   : {NOME} {SOBRENOME}")
    print(f"  Turma  : {TURMA}  |  Cabine: {CABINE}")
    print(f"  Grupo  : {GRUPO_WHATSAPP}")
    print(f"  Janela : {HORA_INICIO} → {HORA_FIM}")
    print(f"  Modo   : {'TESTE (não envia)' if APENAS_PREENCHER else 'REAL (envia formulário)'}")
    print("=" * 50 + "\n")

    async with async_playwright() as playwright:
        await monitorar_whatsapp(playwright)

    log("Script finalizado.")


if __name__ == "__main__":
    asyncio.run(main())