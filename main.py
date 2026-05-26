"""
main.py — Entrypoint da aplicação.

Centraliza o tratamento de todas as exceções customizadas e garante
que o usuário sempre receba uma mensagem clara sobre o que falhou e
como resolver.

Execute com:
    python main.py
"""

import asyncio
import sys

from config import form_data, whatsapp_cfg, app_cfg
from core import get_browser, run_monitor
from utils import log
from utils.exceptions import (
    BrowserError,
    FormClosedError,
    FormFieldError,
    GroupNotFoundError,
    LinkNotFoundError,
    LoginTimeoutError,
    ReservaCabineError,
    SessionRevokedError,
    SubmitError,
)


def _print_banner() -> None:
    mode = "TESTE (não envia)" if app_cfg.apenas_preencher else "REAL (envia formulário)"
    print("\n" + "=" * 54)
    print("   🗂  Reserva Automática de Cabine de Estudo")
    print("=" * 54)
    print(f"  Nome   : {form_data.nome} {form_data.sobrenome}")
    print(f"  Turma  : {form_data.turma}  |  Cabine : {form_data.cabine}")
    if form_data.cabines_fallback:
        print(f"  Fallback: {' → '.join(form_data.cabines_fallback)}")
    print(f"  Grupo  : {whatsapp_cfg.grupo}")
    print(f"  Janela : {whatsapp_cfg.hora_inicio} → {whatsapp_cfg.hora_fim}")
    print(f"  Modo   : {mode}")
    print("=" * 54 + "\n")


async def main() -> None:
    _print_banner()
    try:
        async with get_browser() as browser:
            await run_monitor(browser)

    # ── Exceções com instrução de correção clara ───────────────────────────────
    except BrowserError as e:
        log(f"❌ ERRO DE BROWSER\n{e}")
        sys.exit(1)

    except LoginTimeoutError as e:
        log(f"❌ TIMEOUT DE LOGIN\n{e}")
        sys.exit(1)

    except SessionRevokedError as e:
        log(f"❌ SESSÃO DESCONECTADA\n{e}")
        sys.exit(1)

    except GroupNotFoundError as e:
        log(f"❌ GRUPO NÃO ENCONTRADO\n{e}")
        if e.suggestions:
            log(f"  💡 Sugestões de grupos similares: {', '.join(e.suggestions)}")
            log("  Corrija o campo 'grupo' em config.py e tente novamente.")
        sys.exit(1)

    except LinkNotFoundError as e:
        log(f"⏱  LINK NÃO DETECTADO\n{e}")
        log("  Possíveis causas:")
        log("  • O link foi enviado fora da janela de monitoramento")
        log("  • O formato da URL é diferente do esperado")
        log("  • O grupo estava com a conversa em outra posição")
        sys.exit(1)

    except FormClosedError as e:
        log(f"🔒 FORMULÁRIO INACESSÍVEL\n{e}")
        log("  O formulário pode já estar fechado ou lotado.")
        sys.exit(1)

    except FormFieldError as e:
        log(f"⚠️  CAMPO NÃO PREENCHIDO\n{e}")
        log("  Verifique se o nome do campo no Forms mudou.")
        log("  Use o teste_formulario.py para inspecionar os títulos atuais.")
        sys.exit(1)

    except SubmitError as e:
        log(f"❌ FALHA NO ENVIO\n{e}")
        log("  Verifique o screenshot salvo para diagnóstico.")
        sys.exit(1)

    except ReservaCabineError as e:
        # Qualquer outra exceção do projeto não mapeada acima
        log(f"❌ ERRO INESPERADO\n{e}")
        sys.exit(1)

    except KeyboardInterrupt:
        log("\n⏹  Interrompido pelo usuário.")
        sys.exit(0)

    except Exception as e:
        log(f"❌ ERRO NÃO ESPERADO: {type(e).__name__}: {e}")
        raise  # re-levanta para debug com traceback completo


if __name__ == "__main__":
    asyncio.run(main())