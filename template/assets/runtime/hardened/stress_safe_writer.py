from __future__ import annotations

import threading
import time
from typing import Callable

from .models import ScanJob, WriteProfile, WriteResult
from .reliable_writer import ReliableFormWriter, Win32UnicodeInputAdapter
from .safe_clipboard import SafeClipboardManager
from .writer import ClipboardManager, ControlProbe, InputAdapter


class PacedUnicodeInputAdapter(Win32UnicodeInputAdapter):
    """Fallback Unicode deliberadamente pausado para no saturar Windows."""

    def write(self, text: str, interval: float) -> None:
        delay = max(0.007, min(float(interval or 0.007), 0.025))
        for character in str(text):
            super().write(character, 0.0)
            time.sleep(delay)


class StressSafeFormWriter(ReliableFormWriter):
    """Escritor serializado que prioriza pegados atómicos y precisión."""

    _PASTE_SETTLE_SECONDS = {
        "rapida": 0.10,
        "equilibrada": 0.14,
        "maxima_compatibilidad": 0.20,
    }
    _JOB_GAP_SECONDS = {
        "rapida": 0.16,
        "equilibrada": 0.22,
        "maxima_compatibilidad": 0.30,
    }

    def __init__(
        self,
        *,
        windows,
        input_adapter: InputAdapter | None = None,
        clipboard_factory: Callable[[], ClipboardManager] = SafeClipboardManager,
        control_probe: Callable[[ScanJob], ControlProbe] | None = None,
        logger: Callable[[str], None] | None = None,
    ):
        super().__init__(
            windows=windows,
            input_adapter=input_adapter or PacedUnicodeInputAdapter(),
            clipboard_factory=clipboard_factory,
            control_probe=control_probe,
            logger=logger,
        )
        self._transaction_lock = threading.Lock()
        self._next_job_at = 0.0

    @staticmethod
    def _profile_name(profile: WriteProfile) -> str:
        return str(getattr(profile, "name", "equilibrada") or "equilibrada")

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
            if not self._sleep(max(profile.clipboard_delay, 0.035), cancel_event):
                return False
            self.input.hotkey("ctrl", "v")
            settle = self._PASTE_SETTLE_SECONDS.get(
                self._profile_name(profile),
                self._PASTE_SETTLE_SECONDS["equilibrada"],
            )
            self.logger(
                f"input_delivery:clipboard_atomic:class={class_name or 'unknown'}:"
                f"settle_ms={settle * 1000:.0f}"
            )
            return self._sleep(settle, cancel_event)
        except Exception as exc:
            self.logger(f"input_delivery_error:clipboard_atomic:{type(exc).__name__}")
            return False

    def _direct_unicode(
        self,
        value: str,
        profile: WriteProfile,
        cancel_event,
        class_name: str,
    ) -> bool:
        try:
            interval = max(0.007, profile.tab_delay / 2)
            self.input.write(value, interval=interval)
            self.logger(
                f"input_delivery:sendinput_paced:class={class_name or 'unknown'}:"
                f"interval_ms={interval * 1000:.1f}"
            )
            return self._sleep(max(profile.post_paste_delay, 0.06), cancel_event)
        except Exception as exc:
            self.logger(f"input_delivery_error:sendinput_paced:{type(exc).__name__}")
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
            if not self._sleep(0.035, cancel_event):
                return False
            self.input.press("backspace")
            if not self._sleep(0.035, cancel_event):
                return False

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

    def write(self, job: ScanJob, cancel_event) -> WriteResult:
        with self._transaction_lock:
            wait_seconds = max(0.0, self._next_job_at - time.monotonic())
            if wait_seconds and cancel_event.wait(wait_seconds):
                return WriteResult(
                    False,
                    "cancelled",
                    len(job.fields),
                    0,
                    0,
                    0.0,
                    "cancelado_antes_de_escribir",
                )
            try:
                return super().write(job, cancel_event)
            finally:
                profile_name = str(job.write_profile or "equilibrada")
                gap = self._JOB_GAP_SECONDS.get(
                    profile_name,
                    self._JOB_GAP_SECONDS["equilibrada"],
                )
                self._next_job_at = time.monotonic() + gap
