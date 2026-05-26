from datetime import datetime


def log(msg: str) -> None:
    """Imprime mensagem com timestamp formatado."""
    agora = datetime.now().strftime("%H:%M:%S")
    print(f"[{agora}] {msg}", flush=True)