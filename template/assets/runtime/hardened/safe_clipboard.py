from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes
from typing import Protocol


class ClipboardBackend(Protocol):
    def copy(self, text: str) -> None: ...
    def paste(self) -> str: ...


class _PyperclipBackend:
    def copy(self, text: str) -> None:
        import pyperclip

        pyperclip.copy(str(text))

    def paste(self) -> str:
        import pyperclip

        value = pyperclip.paste()
        return "" if value is None else str(value)


class _WindowsClipboardApi:
    def __init__(self) -> None:
        self.available = os.name == "nt"
        if not self.available:
            self.user32 = None
            return
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.OpenClipboard.argtypes = [wintypes.HWND]
        self.user32.OpenClipboard.restype = wintypes.BOOL
        self.user32.CloseClipboard.argtypes = []
        self.user32.CloseClipboard.restype = wintypes.BOOL
        self.user32.EmptyClipboard.argtypes = []
        self.user32.EmptyClipboard.restype = wintypes.BOOL
        self.user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
        self.user32.EnumClipboardFormats.restype = wintypes.UINT

    def _open(self) -> bool:
        if not self.available or self.user32 is None:
            return False
        for _ in range(20):
            if self.user32.OpenClipboard(None):
                return True
            time.sleep(0.01)
        return False

    def formats(self) -> set[int] | None:
        if not self.available:
            return set()
        if not self._open():
            return None
        formats: set[int] = set()
        try:
            current = 0
            while True:
                current = int(self.user32.EnumClipboardFormats(current) or 0)
                if not current:
                    break
                formats.add(current)
            return formats
        finally:
            self.user32.CloseClipboard()

    def clear(self) -> bool:
        if not self.available:
            return True
        if not self._open():
            return False
        try:
            return bool(self.user32.EmptyClipboard())
        finally:
            self.user32.CloseClipboard()


class SafeClipboardManager:
    """Portapapeles de texto sin administrar HGLOBAL manualmente.

    Pyperclip se encarga de la memoria nativa. Esta clase conserva el contenido
    de texto cuando es seguro hacerlo y evita sobrescribir imágenes u otros
    formatos que no se podrían restaurar fielmente.
    """

    TEXT_FORMATS = {1, 7, 13, 16}
    _process_lock = threading.RLock()

    def __init__(self, backend: ClipboardBackend | None = None, api=None) -> None:
        self.backend = backend or _PyperclipBackend()
        self.api = api or _WindowsClipboardApi()
        self._saved = ""
        self._saved_available = False
        self._original_empty = False
        self._entered = False
        self.can_modify = True

    def __enter__(self):
        self._process_lock.acquire()
        self._entered = True
        formats = self.api.formats()
        if formats is None:
            self.can_modify = False
            return self
        self._original_empty = not formats
        self.can_modify = self._original_empty or formats.issubset(self.TEXT_FORMATS)
        if self.can_modify and not self._original_empty:
            try:
                self._saved = self.backend.paste()
                self._saved_available = True
            except Exception:
                self.can_modify = False
        return self

    def set_text(self, text: str) -> bool:
        if not self.can_modify:
            return False
        value = str(text)
        for attempt in range(5):
            try:
                self.backend.copy(value)
                if self.backend.paste() == value:
                    return True
            except Exception:
                pass
            time.sleep(0.01 * (attempt + 1))
        return False

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.can_modify:
                if self._original_empty:
                    self.api.clear()
                elif self._saved_available:
                    for attempt in range(3):
                        try:
                            self.backend.copy(self._saved)
                            break
                        except Exception:
                            time.sleep(0.01 * (attempt + 1))
        finally:
            if self._entered:
                self._entered = False
                self._process_lock.release()
