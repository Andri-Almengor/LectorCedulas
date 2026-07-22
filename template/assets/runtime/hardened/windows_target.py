from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from typing import Callable

from .models import TargetWindow

GA_ROOT = 2
SW_RESTORE = 9


class WindowError(RuntimeError):
    pass


class WindowService:
    def __init__(self, *, own_pid: int | None = None):
        self.own_pid = own_pid if own_pid is not None else os.getpid()

    def _user32(self):
        if os.name != "nt":
            raise WindowError("La automatización de ventanas requiere Windows")
        return ctypes.windll.user32

    def is_window(self, hwnd: int) -> bool:
        if os.name != "nt" or not hwnd:
            return False
        return bool(self._user32().IsWindow(wintypes.HWND(hwnd)))

    def pid_for(self, hwnd: int) -> int:
        if os.name != "nt" or not hwnd:
            return 0
        pid = wintypes.DWORD()
        self._user32().GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        return int(pid.value)

    def root_for(self, hwnd: int) -> int:
        if os.name != "nt" or not hwnd:
            return 0
        return int(self._user32().GetAncestor(wintypes.HWND(hwnd), GA_ROOT) or 0)

    def title_for(self, hwnd: int) -> str:
        if os.name != "nt" or not hwnd:
            return ""
        length = int(self._user32().GetWindowTextLengthW(wintypes.HWND(hwnd)))
        buffer = ctypes.create_unicode_buffer(length + 1)
        self._user32().GetWindowTextW(wintypes.HWND(hwnd), buffer, len(buffer))
        return buffer.value or ""

    def class_for(self, hwnd: int) -> str:
        if os.name != "nt" or not hwnd:
            return ""
        buffer = ctypes.create_unicode_buffer(256)
        self._user32().GetClassNameW(wintypes.HWND(hwnd), buffer, len(buffer))
        return buffer.value or ""

    def foreground_hwnd(self) -> int:
        if os.name != "nt":
            return 0
        return int(self._user32().GetForegroundWindow() or 0)

    def capture_foreground(self) -> TargetWindow:
        hwnd = self.foreground_hwnd()
        pid = self.pid_for(hwnd)
        root = self.root_for(hwnd)
        target = TargetWindow(
            hwnd=hwnd,
            pid=pid,
            root_hwnd=root,
            title=self.title_for(hwnd),
            class_name=self.class_for(hwnd),
        )
        if not target.valid_identity or pid == self.own_pid:
            raise WindowError("No hay una ventana externa válida en primer plano")
        return target

    def validate_exact(self, target: TargetWindow, *, require_foreground: bool = False) -> tuple[bool, str]:
        if not target.valid_identity:
            return False, "identidad_incompleta"
        if not self.is_window(target.hwnd):
            return False, "hwnd_no_existe"
        if self.pid_for(target.hwnd) != target.pid:
            return False, "pid_cambio"
        if self.root_for(target.hwnd) != target.root_hwnd:
            return False, "ventana_superior_cambio"
        if require_foreground and self.foreground_hwnd() != target.hwnd:
            return False, "objetivo_no_esta_en_primer_plano"
        return True, "ok"

    def activate_exact(self, target: TargetWindow) -> bool:
        valid, _ = self.validate_exact(target)
        if not valid or os.name != "nt":
            return False
        user32 = self._user32()
        user32.ShowWindow(wintypes.HWND(target.hwnd), SW_RESTORE)
        user32.BringWindowToTop(wintypes.HWND(target.hwnd))
        return bool(user32.SetForegroundWindow(wintypes.HWND(target.hwnd)))

    def wait_until_exact_foreground(
        self,
        target: TargetWindow,
        *,
        timeout: float,
        cancel: Callable[[], bool],
        allow_activate: bool = True,
    ) -> tuple[bool, str]:
        deadline = time.monotonic() + max(0.0, timeout)
        attempted_activation = False
        while not cancel() and time.monotonic() < deadline:
            valid, reason = self.validate_exact(target)
            if not valid:
                return False, reason
            if self.foreground_hwnd() == target.hwnd:
                return True, "ok"
            if allow_activate and not attempted_activation:
                self.activate_exact(target)
                attempted_activation = True
            time.sleep(0.05)
        return False, "cancelado" if cancel() else "timeout_objetivo"
