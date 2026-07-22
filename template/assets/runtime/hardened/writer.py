from __future__ import annotations

import ctypes
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Protocol

from .models import EmptyPolicy, FieldAction, FinalAction, ScanJob, ValidationType, WriteProfile, WriteResult
from .windows_target import WindowService


PROFILES = {
    "rapida": WriteProfile("rapida", 0.04, 1.0, 0.025, 0.012, 0.035, 0.15, 0.02, 2),
    "equilibrada": WriteProfile("equilibrada", 0.09, 1.8, 0.055, 0.025, 0.07, 0.28, 0.045, 3),
    "maxima_compatibilidad": WriteProfile("maxima_compatibilidad", 0.18, 3.0, 0.10, 0.05, 0.13, 0.50, 0.09, 3),
}


class InputAdapter(Protocol):
    def press(self, key: str) -> None: ...
    def hotkey(self, *keys: str) -> None: ...
    def key_down(self, key: str) -> None: ...
    def key_up(self, key: str) -> None: ...
    def write(self, text: str, interval: float) -> None: ...


class PyAutoGuiAdapter:
    def __init__(self):
        import pyautogui
        self._p = pyautogui

    def press(self, key: str) -> None:
        self._p.press(key)

    def hotkey(self, *keys: str) -> None:
        self._p.hotkey(*keys)

    def key_down(self, key: str) -> None:
        self._p.keyDown(key)

    def key_up(self, key: str) -> None:
        self._p.keyUp(key)

    def write(self, text: str, interval: float) -> None:
        if os.name != "nt":
            self._p.write(text, interval=interval)
            return
        from ctypes import wintypes
        INPUT_KEYBOARD = 1
        KEYEVENTF_KEYUP = 0x0002
        KEYEVENTF_UNICODE = 0x0004

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

        class INPUT_UNION(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]

        class INPUT(ctypes.Structure):
            _anonymous_ = ("union",)
            _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]

        units = str(text).encode("utf-16-le")
        for index in range(0, len(units), 2):
            scan = int.from_bytes(units[index:index + 2], "little")
            events = (INPUT * 2)(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, scan, KEYEVENTF_UNICODE, 0, None)), INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, scan, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None)))
            if ctypes.windll.user32.SendInput(2, ctypes.byref(events), ctypes.sizeof(INPUT)) != 2:
                raise OSError("SendInput Unicode incompleto")
            if interval:
                time.sleep(interval)


class ClipboardManager:
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    TEXT_FORMATS = {1, 7, 13, 16}

    def __init__(self):
        self._saved: str | None = None
        self._saved_available = False
        self._original_empty = False
        self.can_modify = True

    def _open(self) -> bool:
        if os.name != "nt":
            return False
        for _ in range(20):
            if ctypes.windll.user32.OpenClipboard(None):
                return True
            time.sleep(0.01)
        return False

    def read_text(self) -> tuple[bool, str | None]:
        if not self._open():
            return False, None
        try:
            handle = ctypes.windll.user32.GetClipboardData(self.CF_UNICODETEXT)
            if not handle:
                return True, None
            pointer = ctypes.windll.kernel32.GlobalLock(handle)
            if not pointer:
                return False, None
            try:
                return True, ctypes.wstring_at(pointer)
            finally:
                ctypes.windll.kernel32.GlobalUnlock(handle)
        finally:
            ctypes.windll.user32.CloseClipboard()

    def set_text(self, text: str) -> bool:
        if os.name != "nt" or not self._open():
            return False
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            user32.EmptyClipboard()
            data = (str(text) + "\0").encode("utf-16-le")
            handle = kernel32.GlobalAlloc(self.GMEM_MOVEABLE, len(data))
            if not handle:
                return False
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                kernel32.GlobalFree(handle)
                return False
            ctypes.memmove(pointer, data, len(data))
            kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(self.CF_UNICODETEXT, handle):
                kernel32.GlobalFree(handle)
                return False
            return True
        finally:
            ctypes.windll.user32.CloseClipboard()

    def __enter__(self):
        if os.name != "nt":
            self.can_modify = False
            return self
        formats: set[int] = set()
        if self._open():
            try:
                current = 0
                while True:
                    current = int(ctypes.windll.user32.EnumClipboardFormats(current) or 0)
                    if not current:
                        break
                    formats.add(current)
            finally:
                ctypes.windll.user32.CloseClipboard()
        self._original_empty = not formats
        self.can_modify = not formats or formats.issubset(self.TEXT_FORMATS)
        if self.can_modify and not self._original_empty:
            self._saved_available, self._saved = self.read_text()
            self.can_modify = self._saved_available
        return self

    def __exit__(self, exc_type, exc, tb):
        if not self.can_modify:
            return
        if self._original_empty:
            if self._open():
                try:
                    ctypes.windll.user32.EmptyClipboard()
                finally:
                    ctypes.windll.user32.CloseClipboard()
        elif self._saved_available:
            self.set_text(self._saved or "")


@dataclass(slots=True)
class ControlProbe:
    readable: bool
    text: str | None = None
    class_name: str = ""


class FormWriter:
    def __init__(self, *, windows: WindowService, input_adapter: InputAdapter | None = None, clipboard_factory: Callable[[], ClipboardManager] = ClipboardManager, control_probe: Callable[[ScanJob], ControlProbe] | None = None, logger: Callable[[str], None] | None = None):
        self.windows = windows
        self.input = input_adapter or PyAutoGuiAdapter()
        self.clipboard_factory = clipboard_factory
        self.control_probe = control_probe or (lambda job: ControlProbe(False))
        self.logger = logger or (lambda message: None)

    def _cancelled(self, cancel_event) -> bool:
        return bool(cancel_event.is_set())

    def _sleep(self, seconds: float, cancel_event) -> bool:
        return not cancel_event.wait(max(0.0, seconds))

    def _release_modifiers(self) -> None:
        for key in ("ctrl", "shift", "alt", "win"):
            try:
                self.input.key_up(key)
            except Exception:
                self.logger(f"modifier_release_failed:{key}")

    def _validate_target(self, job: ScanJob, *, foreground: bool = True) -> tuple[bool, str]:
        return self.windows.validate_exact(job.target, require_foreground=foreground)

    def _normalize(self, value: str) -> str:
        return unicodedata.normalize("NFC", str(value or "")).strip()

    def _validate_value(self, actual: str, expected: str, action: FieldAction) -> bool:
        a = self._normalize(actual)
        e = self._normalize(expected)
        if action.validation == ValidationType.NONE:
            return a == e
        if action.validation == ValidationType.CEDULA:
            return re.sub(r"\D", "", a) == re.sub(r"\D", "", e)
        if action.validation == ValidationType.DATE:
            try:
                return datetime.strptime(a, "%d/%m/%Y") == datetime.strptime(e, "%d/%m/%Y")
            except ValueError:
                return False
        if action.validation == ValidationType.SEX:
            aliases = {"M": "MASCULINO", "F": "FEMENINO"}
            return aliases.get(a.upper(), a.upper()) == aliases.get(e.upper(), e.upper())
        if action.validation == ValidationType.NAME:
            return a.casefold() == e.casefold()
        if action.normalized_compare:
            return unicodedata.normalize("NFC", a).casefold() == unicodedata.normalize("NFC", e).casefold()
        return a == e

    def _resolve_value(self, job: ScanJob, action: FieldAction) -> tuple[bool, str | None, str]:
        raw = job.data.get(action.label, "")
        value = "" if raw is None else str(raw)
        if value:
            return True, value, "value"
        if action.empty_policy == EmptyPolicy.PRESERVE:
            return True, None, "preserve"
        if action.empty_policy == EmptyPolicy.CLEAR:
            return True, "", "clear"
        if action.empty_policy == EmptyPolicy.DEFAULT:
            return True, action.default_value, "default"
        return False, None, "empty_cancel"

    def _replace_allowed(self, job: ScanJob) -> bool:
        return self.control_probe(job).readable

    def _paste(self, value: str, job: ScanJob, profile: WriteProfile, cancel_event, clipboard: ClipboardManager, *, replace: bool) -> bool:
        valid, _ = self._validate_target(job)
        if not valid:
            return False
        if replace:
            if not self._replace_allowed(job):
                return False
            self.input.hotkey("ctrl", "a")
            if not self._sleep(0.01, cancel_event):
                return False
            self.input.press("backspace")
        if getattr(clipboard, "can_modify", True) and clipboard.set_text(value):
            if not self._sleep(profile.clipboard_delay, cancel_event):
                return False
            self.input.hotkey("ctrl", "v")
        else:
            self.input.write(value, interval=max(0.001, profile.tab_delay / 3))
        return self._sleep(profile.post_paste_delay, cancel_event)

    def _navigate(self, action: FinalAction, custom: tuple[str, ...], job: ScanJob, profile: WriteProfile, cancel_event) -> bool:
        valid, _ = self._validate_target(job)
        if not valid:
            return False
        if action == FinalAction.NONE:
            return True
        if action == FinalAction.TAB:
            self.input.press("tab")
        elif action == FinalAction.ENTER:
            self.input.press("enter")
        elif action == FinalAction.SHIFT_TAB:
            self.input.hotkey("shift", "tab")
        elif action == FinalAction.CUSTOM:
            if not custom:
                return False
            self.input.hotkey(*custom)
        return self._sleep(profile.tab_delay, cancel_event)

    def write(self, job: ScanJob, cancel_event) -> WriteResult:
        started = time.monotonic()
        profile = PROFILES.get(job.write_profile, PROFILES["equilibrada"])
        written = 0
        verified = 0
        field_times: list[float] = []
        try:
            ok, reason = self.windows.wait_until_exact_foreground(job.target, timeout=profile.focus_timeout, cancel=lambda: self._cancelled(cancel_event))
            if not ok:
                return WriteResult(False, "target_unavailable", len(job.fields), 0, 0, (time.monotonic()-started)*1000, reason)
            if not self._sleep(profile.initial_delay, cancel_event):
                return WriteResult(False, "cancelled", len(job.fields), 0, 0, (time.monotonic()-started)*1000, "cancelado")
            self._release_modifiers()
            with self.clipboard_factory() as clipboard:
                for index, action in enumerate(job.fields, start=1):
                    field_started = time.monotonic()
                    if self._cancelled(cancel_event):
                        return WriteResult(False, "cancelled", len(job.fields), written, verified, (time.monotonic()-started)*1000, "cancelado", field_times)
                    for _ in range(action.tabs_before):
                        if not self._navigate(FinalAction.TAB, (), job, profile, cancel_event):
                            return WriteResult(False, "navigation_failed", len(job.fields), written, verified, (time.monotonic()-started)*1000, f"tabs_before:{index}", field_times)
                    proceed, value, mode = self._resolve_value(job, action)
                    if not proceed:
                        return WriteResult(False, "empty_policy_cancelled", len(job.fields), written, verified, (time.monotonic()-started)*1000, action.label, field_times)
                    if mode != "preserve":
                        probe = self.control_probe(job)
                        attempts = profile.attempts if probe.readable and action.validation != ValidationType.NONE else 1
                        success = False
                        for attempt in range(attempts):
                            replace = action.replace_existing or mode == "clear" or attempt > 0
                            if not self._paste(value or "", job, profile, cancel_event, clipboard, replace=replace):
                                break
                            written += 1 if attempt == 0 else 0
                            if action.validation == ValidationType.NONE or not probe.readable:
                                success = True
                                break
                            deadline = time.monotonic() + profile.verify_timeout
                            while time.monotonic() < deadline and not self._cancelled(cancel_event):
                                current = self.control_probe(job)
                                if current.readable and current.text is not None and self._validate_value(current.text, value or "", action):
                                    verified += 1
                                    success = True
                                    break
                                time.sleep(0.01)
                            if success:
                                break
                        if not success:
                            return WriteResult(False, "validation_failed", len(job.fields), written, verified, (time.monotonic()-started)*1000, action.label, field_times)
                    is_last = index == len(job.fields)
                    action_after = job.final_action if is_last else action.action_after
                    custom = action.custom_action if action_after == FinalAction.CUSTOM else ()
                    if not self._navigate(action_after, custom, job, profile, cancel_event):
                        return WriteResult(False, "navigation_failed", len(job.fields), written, verified, (time.monotonic()-started)*1000, action.label, field_times)
                    if action.extra_wait and not self._sleep(action.extra_wait, cancel_event):
                        return WriteResult(False, "cancelled", len(job.fields), written, verified, (time.monotonic()-started)*1000, "cancelado", field_times)
                    if not self._sleep(profile.between_fields, cancel_event):
                        return WriteResult(False, "cancelled", len(job.fields), written, verified, (time.monotonic()-started)*1000, "cancelado", field_times)
                    field_times.append((time.monotonic() - field_started) * 1000)
            return WriteResult(True, "completed", len(job.fields), written, verified, (time.monotonic()-started)*1000, per_field_ms=field_times)
        finally:
            self._release_modifiers()
