from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from typing import Callable

from .models import ScanJob, WriteProfile
from .writer import ClipboardManager, ControlProbe, FormWriter, InputAdapter, PyAutoGuiAdapter


class Win32UnicodeInputAdapter(PyAutoGuiAdapter):
    """Envía texto Unicode con una estructura INPUT válida en Windows x64/x86."""

    def write(self, text: str, interval: float) -> None:
        if os.name != "nt":
            super().write(text, interval)
            return

        input_keyboard = 1
        keyeventf_keyup = 0x0002
        keyeventf_unicode = 0x0004
        ulong_ptr = ctypes.c_size_t

        class MouseInput(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ulong_ptr),
            ]

        class KeyboardInput(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ulong_ptr),
            ]

        class HardwareInput(ctypes.Structure):
            _fields_ = [
                ("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD),
            ]

        class InputUnion(ctypes.Union):
            _fields_ = [
                ("mi", MouseInput),
                ("ki", KeyboardInput),
                ("hi", HardwareInput),
            ]

        class Input(ctypes.Structure):
            _anonymous_ = ("union",)
            _fields_ = [("type", wintypes.DWORD), ("union", InputUnion)]

        units = str(text).encode("utf-16-le")
        values: list[Input] = []
        for index in range(0, len(units), 2):
            scan = int.from_bytes(units[index : index + 2], "little")
            values.append(
                Input(
                    type=input_keyboard,
                    ki=KeyboardInput(0, scan, keyeventf_unicode, 0, 0),
                )
            )
            values.append(
                Input(
                    type=input_keyboard,
                    ki=KeyboardInput(
                        0,
                        scan,
                        keyeventf_unicode | keyeventf_keyup,
                        0,
                        0,
                    ),
                )
            )

        if not values:
            return

        user32 = ctypes.windll.user32
        user32.SendInput.argtypes = [
            wintypes.UINT,
            ctypes.POINTER(Input),
            ctypes.c_int,
        ]
        user32.SendInput.restype = wintypes.UINT
        events = (Input * len(values))(*values)
        sent = int(user32.SendInput(len(values), events, ctypes.sizeof(Input)))
        if sent != len(values):
            error = ctypes.get_last_error()
            raise OSError(error, f"SendInput Unicode incompleto: {sent}/{len(values)}")
        if interval:
            time.sleep(min(float(interval) * max(1, len(units) // 2), 0.08))


class Win32ClipboardManager(ClipboardManager):
    """Portapapeles Win32 con firmas de puntero correctas para procesos x64."""

    def __init__(self):
        super().__init__()
        if os.name == "nt":
            self._configure_api()

    @staticmethod
    def _configure_api() -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        handle = ctypes.c_void_p

        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.argtypes = []
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = handle
        user32.SetClipboardData.argtypes = [wintypes.UINT, handle]
        user32.SetClipboardData.restype = handle
        user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
        user32.EnumClipboardFormats.restype = wintypes.UINT

        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = handle
        kernel32.GlobalLock.argtypes = [handle]
        kernel32.GlobalLock.restype = handle
        kernel32.GlobalUnlock.argtypes = [handle]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalFree.argtypes = [handle]
        kernel32.GlobalFree.restype = handle


class ReliableFormWriter(FormWriter):
    """Escritor universal con entrega diferenciada por tipo de control."""

    def __init__(
        self,
        *,
        windows,
        input_adapter: InputAdapter | None = None,
        clipboard_factory: Callable[[], ClipboardManager] = Win32ClipboardManager,
        control_probe: Callable[[ScanJob], ControlProbe] | None = None,
        logger: Callable[[str], None] | None = None,
    ):
        super().__init__(
            windows=windows,
            input_adapter=input_adapter or Win32UnicodeInputAdapter(),
            clipboard_factory=clipboard_factory,
            control_probe=control_probe,
            logger=logger,
        )

    def _direct_unicode(
        self,
        value: str,
        profile: WriteProfile,
        cancel_event,
        class_name: str,
    ) -> bool:
        try:
            self.input.write(value, interval=max(0.001, profile.tab_delay / 4))
            self.logger(f"input_delivery:sendinput_unicode:class={class_name or 'unknown'}")
            return self._sleep(profile.post_paste_delay, cancel_event)
        except Exception as exc:
            self.logger(f"input_delivery_error:sendinput:{type(exc).__name__}")
            return False

    def _clipboard_paste(
        self,
        value: str,
        profile: WriteProfile,
        cancel_event,
        clipboard: ClipboardManager,
        class_name: str,
    ) -> bool:
        try:
            if not getattr(clipboard, "can_modify", True):
                return False
            if not clipboard.set_text(value):
                return False
            if not self._sleep(profile.clipboard_delay, cancel_event):
                return False
            self.input.hotkey("ctrl", "v")
            self.logger(f"input_delivery:clipboard:class={class_name or 'unknown'}")
            return self._sleep(profile.post_paste_delay, cancel_event)
        except Exception as exc:
            self.logger(f"input_delivery_error:clipboard:{type(exc).__name__}")
            return False

    def _paste(
        self,
        value: str,
        job: ScanJob,
        profile: WriteProfile,
        cancel_event,
        clipboard: ClipboardManager,
        *,
        replace: bool,
    ) -> bool:
        valid, reason = self._validate_target(job)
        if not valid:
            self.logger(f"input_target_invalid:{reason}")
            return False

        probe = self.control_probe(job)
        if replace:
            if not probe.readable:
                self.logger(
                    "input_replace_unverified:"
                    f"class={probe.class_name or 'unknown'}"
                )
            self.input.hotkey("ctrl", "a")
            if not self._sleep(0.01, cancel_event):
                return False
            self.input.press("backspace")

        if probe.readable:
            if self._clipboard_paste(
                value,
                profile,
                cancel_event,
                clipboard,
                probe.class_name,
            ):
                return True
            return self._direct_unicode(
                value,
                profile,
                cancel_event,
                probe.class_name,
            )

        if self._direct_unicode(
            value,
            profile,
            cancel_event,
            probe.class_name,
        ):
            return True
        return self._clipboard_paste(
            value,
            profile,
            cancel_event,
            clipboard,
            probe.class_name,
        )
