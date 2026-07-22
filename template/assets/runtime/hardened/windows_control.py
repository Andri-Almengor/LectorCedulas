from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from .models import ScanJob
from .writer import ControlProbe
from .windows_target import WindowService

WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
SMTO_ABORTIFHUNG = 0x0002


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


class WindowsControlProbe:
    """Lee únicamente el control enfocado de la ventana exacta del trabajo.

    Los controles de navegadores y superficies sin WM_GETTEXT se consideran no
    verificables; en esos casos el escritor conserva el fallback universal, pero
    no usa Ctrl+A ni afirma que validó el contenido.
    """

    READABLE_CLASS_TOKENS = (
        "edit",
        "richedit",
        "textbox",
        "windowsforms10",
        "masked",
        "tedit",
    )
    EXCLUDED_CLASS_TOKENS = (
        "chrome",
        "mozilla",
        "renderwidget",
        "internet explorer",
    )

    def __init__(self, windows: WindowService):
        self.windows = windows

    def _class_name(self, hwnd: int) -> str:
        if os.name != "nt" or not hwnd:
            return ""
        buffer = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(wintypes.HWND(hwnd), buffer, len(buffer))
        return buffer.value or ""

    def _focused_control(self, job: ScanJob) -> int:
        if os.name != "nt":
            return 0
        valid, _ = self.windows.validate_exact(job.target, require_foreground=True)
        if not valid:
            return 0
        thread_id = ctypes.windll.user32.GetWindowThreadProcessId(
            wintypes.HWND(job.target.hwnd), None
        )
        if not thread_id:
            return 0
        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
            return 0
        return int(info.hwndFocus or info.hwndCaret or 0)

    def _readable(self, class_name: str) -> bool:
        lowered = class_name.casefold()
        if any(token in lowered for token in self.EXCLUDED_CLASS_TOKENS):
            return False
        return any(token in lowered for token in self.READABLE_CLASS_TOKENS)

    def _send_timeout(self, hwnd: int, message: int, wparam=0, lparam=0, timeout_ms=150):
        result = ctypes.c_size_t()
        ok = ctypes.windll.user32.SendMessageTimeoutW(
            wintypes.HWND(hwnd),
            message,
            ctypes.c_size_t(wparam),
            ctypes.c_ssize_t(lparam),
            SMTO_ABORTIFHUNG,
            int(timeout_ms),
            ctypes.byref(result),
        )
        return int(result.value) if ok else None

    def __call__(self, job: ScanJob) -> ControlProbe:
        control = self._focused_control(job)
        if not control:
            return ControlProbe(False)
        class_name = self._class_name(control)
        if not self._readable(class_name):
            return ControlProbe(False, class_name=class_name)
        length = self._send_timeout(control, WM_GETTEXTLENGTH)
        if length is None or length < 0 or length > 8192:
            return ControlProbe(False, class_name=class_name)
        buffer = ctypes.create_unicode_buffer(length + 2)
        copied = self._send_timeout(
            control,
            WM_GETTEXT,
            len(buffer),
            ctypes.cast(buffer, ctypes.c_void_p).value or 0,
        )
        if copied is None:
            return ControlProbe(False, class_name=class_name)
        return ControlProbe(True, text=buffer.value, class_name=class_name)
