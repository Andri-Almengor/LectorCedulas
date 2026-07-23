from __future__ import annotations

import ctypes
import threading
import time
from pathlib import Path

from .app_runtime import Application
from .config_service import ConfigurationError
from .desktop_ui import (
    ControlPanelActions,
    ControlPanelSnapshot,
    run_calibration_dialog,
    run_configuration_selector,
    run_control_panel,
)
from .privacy import technical_event
from .reader_calibration import PortCalibrationService
from .version import PRODUCT_NAME, VERSION


class DesktopApplication(Application):
    """Aplicación de escritorio con calibración guiada y panel visual DMS."""

    def __init__(self, root_dir=None):
        super().__init__(root_dir=root_dir)
        self._calibration_lock = threading.Lock()
        self._control_panel_lock = threading.Lock()

    def _icon_path(self) -> Path:
        primary = self.root_dir / "assets" / "DMS_icono_circulo_i.ico"
        return primary if primary.is_file() else self.root_dir / "assets" / "icono.ico"

    def _validate_calibration_frame(self, raw: bytes) -> bool:
        try:
            return bool(self.parsers.parse(raw).recognized)
        except Exception as exc:
            self._log(technical_event("calibration_parse_error", error_type=type(exc).__name__))
            return False

    def _calibration_service(self) -> PortCalibrationService:
        return PortCalibrationService(
            list_ports=self.serial.list_ports,
            open_port=self.serial.open_port,
            validate_frame=self._validate_calibration_frame,
            load_last_port=self.config.load_last_port,
            save_last_port=self.config.save_last_port,
            logger=self._log,
            baudrates=self.serial.baudrates,
            read_timeout=self.serial.read_timeout,
            idle_seconds=self.serial.idle_seconds,
            max_bytes=self.serial.max_bytes,
            min_bytes=self.serial.min_bytes,
            per_port_timeout=10.0,
        )

    def _run_calibration_dialog(self) -> bool:
        service = self._calibration_service()
        preferred = str((self.config.load_last_port() or {}).get("device") or "")

        def ports_provider() -> list[str]:
            return [identity.device for identity in service.candidates(preferred)]

        return run_calibration_dialog(
            product_name=PRODUCT_NAME,
            icon_path=self._icon_path(),
            ports_provider=ports_provider,
            preferred_device=preferred,
            calibrate=lambda selected, cancel, progress: service.calibrate(
                preferred_device=selected,
                cancel_event=cancel,
                progress=progress,
            ),
        )

    def _manual_calibration_worker(self) -> None:
        if not self._calibration_lock.acquire(blocking=False):
            self._notify("Calibración", "Ya hay una calibración en curso")
            return
        try:
            self.queue.pause()
            self.serial.stop()
            time.sleep(0.25)
            success = False
            try:
                success = self._run_calibration_dialog()
            finally:
                self.serial = self._build_serial_manager()
                self.serial.start()
            if success:
                self.last_error = "Sin errores"
                self._notify(
                    "Lector calibrado",
                    "El puerto quedó guardado para el próximo inicio",
                )
            else:
                self._notify(
                    "Calibración cancelada",
                    "Se reanudará la búsqueda automática",
                )
        finally:
            self.queue.resume()
            self._calibration_lock.release()

    def _open_calibration(self, _icon=None, _item=None) -> None:
        threading.Thread(
            target=self._manual_calibration_worker,
            name="DMSManualCalibration",
            daemon=True,
        ).start()

    def _open_selector(self, _icon=None, _item=None) -> None:
        if not self._selector_lock.acquire(blocking=False):
            return

        def worker() -> None:
            try:
                def active_provider() -> str:
                    try:
                        return Path(self.config.load_active().source_path).name
                    except ConfigurationError:
                        return ""

                run_configuration_selector(
                    icon_path=self._icon_path(),
                    forms_provider=self.config.list_forms,
                    active_provider=active_provider,
                    activate=self._change_configuration,
                )
            finally:
                self._selector_lock.release()

        threading.Thread(target=worker, name="DMSConfigSelector", daemon=True).start()

    def _panel_snapshot(self) -> ControlPanelSnapshot:
        try:
            configuration = self.config.load_active()
            config_name = configuration.name
            profile = configuration.profile
        except Exception:
            config_name = "Inválida"
            profile = "sin perfil"
        queue_status = self.queue.status()
        port = self.serial.current_port.device if self.serial.current_port else "sin COM"
        return ControlPanelSnapshot(
            reader_state=self.reader_state.value,
            port=port,
            configuration=config_name,
            profile=profile,
            queue_count=queue_status.queued,
            queue_paused=queue_status.paused,
            last_success=self.last_success_utc,
            last_error=str(self.last_error or "Sin errores").replace("\n", " ")[:180],
        )

    def _open_control_panel(self, _icon=None, _item=None) -> None:
        if not self._control_panel_lock.acquire(blocking=False):
            return

        def worker() -> None:
            try:
                run_control_panel(
                    product_name=PRODUCT_NAME,
                    version=VERSION,
                    icon_path=self._icon_path(),
                    snapshot_provider=self._panel_snapshot,
                    actions=ControlPanelActions(
                        calibrate=self._open_calibration,
                        reconnect=lambda: self.serial.reconnect_now(),
                        change_configuration=self._open_selector,
                        toggle_favorites=self._toggle_favorites,
                        pause=self.queue.pause,
                        resume=self.queue.resume,
                        cancel_current=lambda: self.queue.cancel_current("panel_dms"),
                        clear_queue=lambda: self.queue.clear_pending("panel_dms"),
                        open_logs=lambda: self._open_folder(self.root_dir / "logs"),
                        open_diagnostics=lambda: self._open_folder(self.root_dir / "diagnosticos"),
                        clear_diagnostics=self._clear_diagnostics,
                        shutdown=self.shutdown,
                    ),
                )
            finally:
                self._control_panel_lock.release()

        threading.Thread(target=worker, name="DMSControlPanel", daemon=True).start()

    def _menu(self):
        from pystray import Menu, MenuItem

        def status_text(_item):
            port = self.serial.current_port.device if self.serial.current_port else "sin COM"
            return f"Lector: {self.reader_state.value} | {port}"

        def config_text(_item):
            try:
                snapshot = self.config.load_active()
                return f"Config: {snapshot.name} | {snapshot.profile}"
            except Exception:
                return "Config: inválida"

        def queue_text(_item):
            status = self.queue.status()
            return f"Cola: {status.queued} | {'pausada' if status.paused else 'activa'}"

        def last_text(_item):
            return f"Última lectura aceptada: {self.last_success_utc}"

        def error_text(_item):
            summary = str(self.last_error or "Sin errores").replace("\n", " ")[:80]
            return f"Último error: {summary}"

        return Menu(
            MenuItem("Abrir panel DMS", self._open_control_panel, default=True),
            MenuItem(status_text, None, enabled=False),
            MenuItem(config_text, None, enabled=False),
            MenuItem(queue_text, None, enabled=False),
            MenuItem(last_text, None, enabled=False),
            MenuItem(error_text, None, enabled=False),
            Menu.SEPARATOR,
            MenuItem("Calibrar lector", self._open_calibration),
            MenuItem("Reconectar lector", lambda _icon, _item: self.serial.reconnect_now()),
            MenuItem("Cambiar configuración", self._open_selector),
            MenuItem("Alternar favoritas (Ctrl+Alt+C)", self._toggle_favorites),
            MenuItem("Pausar escrituras", lambda _icon, _item: self.queue.pause()),
            MenuItem("Reanudar escrituras", lambda _icon, _item: self.queue.resume()),
            MenuItem(
                "Cancelar escritura actual (Ctrl+Alt+Esc)",
                lambda _icon, _item: self.queue.cancel_current(),
            ),
            MenuItem(
                "Vaciar cola",
                lambda _icon, _item: self.queue.clear_pending("vaciada_desde_bandeja"),
            ),
            Menu.SEPARATOR,
            MenuItem(
                "Abrir logs redactados",
                lambda _icon, _item: self._open_folder(self.root_dir / "logs"),
            ),
            MenuItem(
                "Abrir diagnóstico",
                lambda _icon, _item: self._open_folder(self.root_dir / "diagnosticos"),
            ),
            MenuItem("Borrar diagnósticos", lambda _icon, _item: self._clear_diagnostics()),
            Menu.SEPARATOR,
            MenuItem("Salir", lambda _icon, _item: self.shutdown()),
        )

    def run(self) -> int:
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
            self._log(technical_event("startup_blocked", error_type=type(exc).__name__))
            return 2

        if not self._run_calibration_dialog():
            self._log(technical_event("startup_calibration_cancelled"))
            self.instance.close()
            return 3

        self.queue.start()
        self.serial.start()
        threading.Thread(
            target=self._emergency_hotkey_loop,
            name="DMSEmergencyHotkey",
            daemon=True,
        ).start()

        from pystray import Icon

        self.tray_icon = Icon(
            "DMS_LectorCedulas",
            self._load_icon(),
            f"{PRODUCT_NAME} {VERSION}",
            self._menu(),
        )
        self._notify("Lector iniciado", "Lector calibrado y listo")
        try:
            self.tray_icon.run()
        finally:
            self.shutdown()
        return 0
