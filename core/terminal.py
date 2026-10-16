"""
core/terminal.py
================
Helpers de apresentação em terminal.

Separados de `main.py` de propósito: o modelo (`CyberWarModel`) deve poder ser
executado em testes, batch runs ou num dashboard Mesa sem herdar amarras de UI.
Aqui fica tudo que depende de console — habilitação de UTF-8, detecção de
suporte a cores e a paleta ANSI usada pelo relatório.
"""

from __future__ import annotations

import os
import sys


def configurar_utf8() -> None:
    """
    Força o console Windows a usar UTF-8 (code page 65001).

    Sem isto, todo acento (é, ã, ç, Rússia) sai como '?' porque o console
    assume cp850/cp1252. Idempotente e inofensivo fora do Windows.
    """
    if os.name == "nt":  # pragma: no cover - depende do host
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleCP(65001)
            kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def habilitar_ansi() -> bool:
    """
    Habilita sequências de cor no Windows e devolve False se indisponível.

    Nada quebra sem ANSI: a simulação roda igualmente em `cmd.exe` antigo,
    pipes e logs gravados em arquivo.
    """
    if os.name == "nt":  # pragma: no cover - depende do host
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-10), 7)
        except Exception:
            return False
    return True


class Pintura:
    """Paleta de cores ANSI. Sem-op quando `ativar=False`."""

    def __init__(self, ativar: bool) -> None:
        self.ativar = ativar

    def _w(self, texto: str, codigo: str) -> str:
        return f"{codigo}{texto}\033[0m" if self.ativar else texto

    def eua(self, texto: str) -> str:
        return self._w(texto, "\033[94m")

    def russia(self, texto: str) -> str:
        return self._w(texto, "\033[91m")

    def alerta(self, texto: str) -> str:
        return self._w(texto, "\033[93m")

    def ok(self, texto: str) -> str:
        return self._w(texto, "\033[92m")

    def negrito(self, texto: str) -> str:
        return self._w(texto, "\033[1m")
