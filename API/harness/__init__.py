"""Hand-written agent harness: one module per responsibility."""
from pathlib import Path


def logger(file: str):
    """Every runtime action is printed with the name of the file that did it."""
    name = Path(file).name

    def log(msg: str) -> None:
        print(f"[{name}] {msg}", flush=True)

    return log
