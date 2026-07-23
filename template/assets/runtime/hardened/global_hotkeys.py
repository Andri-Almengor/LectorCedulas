from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes
from typing import Callable


class GlobalHotkeyService:
    """Registra los atajos globales en un único message loop de Windows."""

    WM_HOTKEY = 0x0312
    PM_REMOVE = 0x0001
    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_NOREPEAT = 0x4000
    VK_C = 0x43
    VK_ESCAPE = 0x1B
    FAVORITES_ID = 0xD35
    EMERGENCY_ID = 0xD36

    def __init__(
        self,
        *,
        toggle_favorites: Callable[[], None],
        cancel_current: Callable[[], None],
        logger: Callable[[str], None] | None = None,
        user32=None,
    ):
        self.toggle_favorites = toggle_favorites
        self.cancel_current = cancel_current
        self.logger = logger or (lambda message: None)
        self.user32 = user32
        self.registered_ids: set[int] = set()

    def _api(self):
        if self.user32 is not None:
            return self.user32
        if os.name != "nt":
            return None
        return ctypes.windll.user32

    def _register(self, api, hotkey_id: int, virtual_key: int, label: str) -> bool:
        modifiers = self.MOD_ALT | self.MOD_CONTROL | self.MOD_NOREPEAT
        ok = bool(api.RegisterHotKey(None, hotkey_id, modifiers, virtual_key))
        if ok:
            self.registered_ids.add(hotkey_id)
            self.logger(f"hotkey_registered:{label}")
        else:
            self.logger(f"hotkey_register_failed:{label}")
        return ok

    def dispatch(self, hotkey_id: int) -> None:
        try:
            if hotkey_id == self.FAVORITES_ID:
                self.toggle_favorites()
                self.logger("hotkey_triggered:favorites")
            elif hotkey_id == self.EMERGENCY_ID:
                self.cancel_current()
                self.logger("hotkey_triggered:emergency")
        except Exception as exc:
            self.logger(f"hotkey_callback_error:{hotkey_id}:{type(exc).__name__}")

    def run(self, stop_event: threading.Event) -> None:
        api = self._api()
        if api is None:
            return

        self._register(api, self.FAVORITES_ID, self.VK_C, "ctrl_alt_c")
        self._register(api, self.EMERGENCY_ID, self.VK_ESCAPE, "ctrl_alt_escape")
        if not self.registered_ids:
            return

        message = wintypes.MSG()
        try:
            while not stop_event.wait(0.03):
                while api.PeekMessageW(
                    ctypes.byref(message),
                    None,
                    0,
                    0,
                    self.PM_REMOVE,
                ):
                    if message.message == self.WM_HOTKEY:
                        self.dispatch(int(message.wParam))
        finally:
            for hotkey_id in tuple(self.registered_ids):
                try:
                    api.UnregisterHotKey(None, hotkey_id)
                except Exception as exc:
                    self.logger(
                        f"hotkey_unregister_error:{hotkey_id}:"
                        f"{type(exc).__name__}"
                    )
            self.registered_ids.clear()
