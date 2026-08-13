"""Atalho global no Windows via ``RegisterHotKey``, sem dependências externas.

A API nativa é usada de propósito: ela não exige privilégio de administrador e não
instala um hook de teclado global, portanto o daemon não observa o que é digitado.
Só a combinação registrada chega até aqui.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from devmate.errors import HotkeyUnavailableError

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

MODIFIERS = {
    "alt": MOD_ALT,
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
}

# Teclas nomeadas cujo código não deriva de ``ord``.
NAMED_KEYS = {
    "space": 0x20,
    "enter": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    **{f"f{index}": 0x6F + index for index in range(1, 13)},
}


def parse_hotkey(combination: str) -> tuple[int, int]:
    """Converte ``"ctrl+alt+d"`` no par ``(modificadores, virtual key)``."""
    parts = [part.strip().casefold() for part in combination.split("+") if part.strip()]
    if not parts:
        raise HotkeyUnavailableError("O atalho está vazio.")
    *modifier_names, key_name = parts
    modifiers = 0
    for name in modifier_names:
        if name not in MODIFIERS:
            raise HotkeyUnavailableError(f"Modificador desconhecido no atalho: {name}.")
        modifiers |= MODIFIERS[name]
    if not modifiers:
        raise HotkeyUnavailableError(
            "Use ao menos um modificador (ctrl, alt, shift ou win) para não capturar "
            "uma tecla comum do sistema."
        )
    if key_name in NAMED_KEYS:
        virtual_key = NAMED_KEYS[key_name]
    elif len(key_name) == 1 and key_name.isalnum():
        virtual_key = ord(key_name.upper())
    else:
        raise HotkeyUnavailableError(f"Tecla desconhecida no atalho: {key_name}.")
    return modifiers | MOD_NOREPEAT, virtual_key


class WindowsHotkey:
    """Registra a combinação e bloqueia na fila de mensagens até ela ocorrer."""

    name = "windows"

    def __init__(self, combination: str, identifier: int = 1) -> None:
        self.combination = combination
        self.identifier = identifier
        self._registered = False

    def available(self) -> tuple[bool, str | None]:
        if not hasattr(ctypes, "windll"):
            return False, "Atalho global só está disponível no Windows."
        try:
            parse_hotkey(self.combination)
        except HotkeyUnavailableError as exc:
            return False, str(exc)
        return True, None

    def __enter__(self) -> WindowsHotkey:
        self.register()
        return self

    def __exit__(self, *_exception: object) -> None:
        self.unregister()

    def register(self) -> None:
        available, reason = self.available()
        if not available:
            raise HotkeyUnavailableError(reason or "Atalho global indisponível.")
        modifiers, virtual_key = parse_hotkey(self.combination)
        user32 = ctypes.windll.user32
        if not user32.RegisterHotKey(None, self.identifier, modifiers, virtual_key):
            raise HotkeyUnavailableError(
                f"Não foi possível registrar {self.combination}; "
                "outro programa provavelmente já usa essa combinação."
            )
        self._registered = True

    def unregister(self) -> None:
        if not self._registered:
            return
        ctypes.windll.user32.UnregisterHotKey(None, self.identifier)
        self._registered = False

    def wait(self) -> bool:
        if not self._registered:
            raise HotkeyUnavailableError("O atalho não foi registrado.")
        user32 = ctypes.windll.user32
        message = wintypes.MSG()
        while True:
            result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
            if result in {0, -1}:
                # 0 = WM_QUIT, -1 = erro na fila; ambos encerram o daemon.
                return False
            if message.message == WM_HOTKEY and message.wParam == self.identifier:
                return True
