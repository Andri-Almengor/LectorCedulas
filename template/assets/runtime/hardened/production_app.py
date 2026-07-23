from __future__ import annotations

import ctypes
import threading
import time

from .desktop_app import DesktopApplication
from .global_hotkeys import GlobalHotkeyService
from .models import ReaderState
from .privacy import technical_event
from .reliable_app import ReliableDesktopApplication
from .runtime_state import mark_manual_exit
from .stress_safe_writer import StressSafeFormWriter
from .version import PRODUCT_NAME, VERSION
from .windows_control import WindowsControlProbe


class ProductionDesktopApplication(ReliableDesktopApplication):
    """Runtime final con escritura de estrés, atajos y auto-recuperación."""

    _STUCK_STATE_SECONDS = 15.0
    _RECONNECT_COOLDOWN_SECONDS = 12.0

    def __init__(self, root_dir=None, *, recovery_mode: bool = False):
        self._last_reader_state_at = time.monotonic()
        self._last_watchdog_reconnect_at = 0.0
        self._recovery_mode = bool(recovery_mode)
        super().__init__(root_dir=root_dir)
        self.writer = StressSafeFormWriter(
            windows=self.windows,
            control_probe=WindowsControlProbe(self.windows),
            logger=self._log,
        )
        self.queue.writer = self.writer

    def _log(self, message: str) -> None:
        text = str(message or "")
        if text.startswith("hotkey_register_failed:") and hasattr(self, "last_error"):
            shortcut = text.split(":", 1)[1]
            self.last_error = f"No se pudo registrar el atajo {shortcut}"
        elif text.startswith("watchdog_restart:") and hasattr(self, "last_error"):
            component = text.split(":", 1)[1]
            self.last_error = f"Componente reiniciado automáticamente: {component}"
        super()._log(text)

    def _request_exit(self) -> None:
        try:
            mark_manual_exit()
            self._log(technical_event("manual_exit_requested"))
        finally:
            self.shutdown()

    def _state_changed(self, state: ReaderState, detail: str) -> None:
        self._last_reader_state_at = time.monotonic()
        super()._state_changed(state, detail)

    def _emergency_hotkey_loop(self) -> None:
        def cancel_current() -> None:
            if self.queue.cancel_current("tecla_emergencia"):
                self._notify(
                    "Escritura cancelada",
                    "Cancelación de emergencia aplicada",
                )

        service = GlobalHotkeyService(
            toggle_favorites=lambda: self._toggle_favorites(),
            cancel_current=cancel_current,
            logger=self._log,
        )
        service.run(self.stop_event)

    def _restart_serial_manager(self) -> None:
        try:
            old_serial = self.serial
            try:
                old_serial.stop()
            except Exception as exc:
                self._log(
                    technical_event(
                        "watchdog_serial_stop_failed",
                        error_type=type(exc).__name__,
                    )
                )
            self.serial = self._build_serial_manager()
            self.serial.start()
            self._last_reader_state_at = time.monotonic()
            self._log("watchdog_restart:serial")
        except Exception as exc:
            self.last_error = f"No se pudo reiniciar el lector: {type(exc).__name__}"
            self._log(
                technical_event(
                    "watchdog_serial_restart_failed",
                    error_type=type(exc).__name__,
                )
            )

    def _supervise_once(self, now: float | None = None) -> None:
        if self.stop_event.is_set():
            return
        current_time = time.monotonic() if now is None else now

        queue_worker = getattr(self.queue, "_worker", None)
        queue_stopped = bool(getattr(self.queue, "_stop", threading.Event()).is_set())
        if not queue_stopped and (queue_worker is None or not queue_worker.is_alive()):
            self.queue.start()
            self._log("watchdog_restart:queue")

        serial_thread = getattr(self.serial, "_thread", None)
        if serial_thread is None or not serial_thread.is_alive():
            self._restart_serial_manager()
            return

        stuck_states = {
            ReaderState.CONNECTING,
            ReaderState.READING,
            ReaderState.PROCESSING,
        }
        state_age = current_time - self._last_reader_state_at
        reconnect_age = current_time - self._last_watchdog_reconnect_at
        if (
            self.reader_state in stuck_states
            and state_age >= self._STUCK_STATE_SECONDS
            and reconnect_age >= self._RECONNECT_COOLDOWN_SECONDS
        ):
            self._last_watchdog_reconnect_at = current_time
            self._last_reader_state_at = current_time
            self.serial.reconnect_now()
            self._log(
                technical_event(
                    "watchdog_serial_reconnect",
                    state=self.reader_state.value,
                    state_age_seconds=round(state_age, 1),
                )
            )

    def _runtime_supervisor_loop(self) -> None:
        while not self.stop_event.wait(2.0):
            try:
                self._supervise_once()
            except Exception as exc:
                self.last_error = f"Supervisor: {type(exc).__name__}"
                self._log(
                    technical_event(
                        "watchdog_iteration_failed",
                        error_type=type(exc).__name__,
                    )
                )

    def _startup(self) -> int:
        try:
            self.instance.acquire()
            self.config.initialize()
            self._validate_license()
        except Exception as exc:
            try:
                ctypes.windll.user32.MessageBoxW(
                    0,
                    str(exc),
                    f"{PRODUCT_NAME} - Inicio bloqueado",
                    0x10 | 0x00040000,
                )
            except Exception:
                print(f"Inicio bloqueado: {exc}")
            self._log(
                technical_event(
                    "startup_blocked",
                    error_type=type(exc).__name__,
                )
            )
            return 2

        if self._recovery_mode:
            preferred = str((self.config.load_last_port() or {}).get("device") or "")
            self.last_error = "Proceso recuperado automáticamente"
            self._log(
                technical_event(
                    "startup_recovery_mode",
                    preferred_port=preferred or "unknown",
                )
            )
            return 0

        if not self._run_calibration_dialog():
            self._log(technical_event("startup_calibration_cancelled"))
            self.instance.close()
            return 3
        return 0

    def run(self) -> int:
        startup_code = self._startup()
        if startup_code:
            return startup_code

        self.queue.start()
        self.serial.start()
        threading.Thread(
            target=self._emergency_hotkey_loop,
            name="DMSGlobalHotkeys",
            daemon=True,
        ).start()
        threading.Thread(
            target=self._runtime_supervisor_loop,
            name="DMSRuntimeSupervisor",
            daemon=True,
        ).start()

        self._notify(
            "Lector iniciado",
            "Lector recuperado y listo" if self._recovery_mode else "Lector calibrado y listo",
        )
        try:
            while not self.stop_event.is_set():
                try:
                    from pystray import Icon

                    self.tray_icon = Icon(
                        "DMS_LectorCedulas",
                        self._load_icon(),
                        f"{PRODUCT_NAME} {VERSION}",
                        self._menu(),
                    )
                    self.tray_icon.run()
                    if not self.stop_event.is_set():
                        self.last_error = "La bandeja se reinició automáticamente"
                        self._log("watchdog_restart:tray")
                        self.stop_event.wait(1.0)
                except Exception as exc:
                    if self.stop_event.is_set():
                        break
                    self.last_error = f"Bandeja reiniciada: {type(exc).__name__}"
                    self._log(
                        technical_event(
                            "tray_loop_failed",
                            error_type=type(exc).__name__,
                        )
                    )
                    self.stop_event.wait(1.0)
        finally:
            self.shutdown()
        return 0


__all__ = ["ProductionDesktopApplication", "DesktopApplication"]
