from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import itertools
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import Tk, messagebox, ttk

from .atomic_io import read_json, write_json_atomic
from .config_service import ConfigurationError, ConfigurationService
from .instance_control import InstanceControl
from .license_service import LicenseVerifier
from .models import JobState, ScanJob, TargetWindow, utc_now
from .parser_service import ParserService, TseEnrichmentService
from .privacy import build_logger, technical_event
from .scan_queue import QueueFullError, ScanQueue
from .serial_manager import PortIdentity, ReaderState, SerialManager
from .version import PRODUCT_NAME, VERSION
from .windows_control import WindowsControlProbe
from .windows_target import WindowError, WindowService
from .writer import FormWriter


class Application:
    def __init__(self, root_dir: str | os.PathLike[str] | None = None):
        self.root_dir = Path(root_dir or self._application_dir())
        self.stop_event = threading.Event()
        self.logger = build_logger(self.root_dir / "logs")
        self.config = ConfigurationService(self.root_dir / "configs")
        self.windows = WindowService()
        self.writer = FormWriter(windows=self.windows, control_probe=WindowsControlProbe(self.windows), logger=self._log)
        self.queue = ScanQueue(writer=self.writer, logger=self._log, notify=self._notify)
        self.sequence = itertools.count(1)
        self.reader_state = ReaderState.DISCONNECTED
        self.reader_detail = ""
        self.last_success_utc = "Nunca"
        self.last_error = "Sin errores"
        self.tray_icon = None
        self._selector_lock = threading.Lock()
        self._parser_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="DMSParser")
        self._processing_slots = threading.BoundedSemaphore(128)
        self.parsers = ParserService(self._load_core, self._log, formats_path=self.root_dir / "configs" / "formatos" / "formatos_cedulas.json")
        self.tse = TseEnrichmentService(self._load_core, self._log)
        self._last_raw_digest = ""
        self._last_raw_at = 0.0
        self._duplicate_lock = threading.Lock()
        self.serial = self._build_serial_manager()
        self.instance = InstanceControl(self.shutdown)

    @staticmethod
    def _application_dir() -> str:
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(sys.argv[0]))

    def _log(self, message: str) -> None:
        self.logger.info(message)

    def _notify(self, title: str, message: str) -> None:
        try:
            if self.tray_icon:
                self.tray_icon.notify(message, title)
        except Exception:
            self._log(technical_event("notification_failed", reason=title))

    def _state_changed(self, state: ReaderState, detail: str) -> None:
        previous = self.reader_state
        self.reader_state = state
        self.reader_detail = detail
        if state == ReaderState.ERROR:
            self.last_error = detail or "Error serial"
        if previous in {ReaderState.RECONNECTING, ReaderState.DISCONNECTED, ReaderState.ERROR} and state == ReaderState.READY:
            self._notify("Lector conectado", f"Puerto activo: {detail}")
        if state == ReaderState.RECONNECTING and previous != ReaderState.RECONNECTING:
            self._notify("Lector desconectado", "Se intentará reconectar automáticamente")

    def _load_core(self):
        from assets.runtime import lector_core as core
        return core

    def _process_scan_async(self, raw: bytes, target: TargetWindow | None, identity: PortIdentity) -> None:
        try:
            try:
                result = self.parsers.parse(raw)
            except Exception as exc:
                self.last_error = type(exc).__name__
                self.serial.confirm_rejected(raw, "parser_error")
                self._log(technical_event("parser_error", error_type=type(exc).__name__))
                return
            if not result.recognized:
                self.serial.confirm_rejected(raw, "format_not_recognized")
                return
            data = self.tse.enrich(result.data)
            self.serial.confirm_accepted(identity)
            self._on_scan(raw, data, target)
        finally:
            self._processing_slots.release()

    def _submit_serial_frame(self, raw: bytes, target: TargetWindow | None, identity: PortIdentity) -> bool:
        if not self._processing_slots.acquire(blocking=False):
            self.last_error = "Procesamiento saturado"
            self._notify("Procesamiento saturado", "Espere y vuelva a escanear")
            return False
        try:
            self._parser_pool.submit(self._process_scan_async, raw, target, identity)
            return True
        except Exception:
            self._processing_slots.release()
            return False

    def _capture_target_context(self) -> TargetWindow | None:
        try:
            return self.windows.capture_foreground()
        except WindowError:
            return None

    def _is_duplicate(self, raw: bytes) -> bool:
        digest = hashlib.sha256(raw).hexdigest()
        now = time.monotonic()
        with self._duplicate_lock:
            duplicate = digest == self._last_raw_digest and now - self._last_raw_at <= 0.85
            self._last_raw_digest = digest
            self._last_raw_at = now
        return duplicate

    def _on_scan(self, raw: bytes, data, target: TargetWindow | None) -> None:
        if self._is_duplicate(raw):
            self._log(technical_event("scan_duplicate_ignored"))
            return
        if target is None:
            self.last_error = "No había formulario externo activo al finalizar la lectura"
            self._notify("Formulario no detectado", "Active el formulario y vuelva a escanear")
            return
        valid, reason = self.windows.validate_exact(target)
        if not valid:
            self.last_error = reason
            self._notify("Formulario incorrecto", "La ventana objetivo se cerró o cambió")
            return
        try:
            snapshot = self.config.load_active()
        except ConfigurationError as exc:
            self.last_error = str(exc)
            self._notify("Configuración inválida", "Corrija la configuración antes de escanear")
            self._log(technical_event("configuration_invalid", reason=type(exc).__name__))
            return
        job = ScanJob(
            sequence_id=next(self.sequence),
            created_at_utc=utc_now(),
            raw_sha256=hashlib.sha256(raw).hexdigest(),
            data=dict(data),
            configuration_id=snapshot.configuration_id,
            configuration_name=snapshot.name,
            configuration_version=snapshot.schema_version,
            configuration_generation=snapshot.generation,
            write_profile=snapshot.profile,
            target=target,
            fields=snapshot.fields,
            final_action=snapshot.final_action,
            state=JobState.QUEUED,
        )
        try:
            self.queue.submit(job)
            self.last_success_utc = utc_now().strftime("%Y-%m-%d %H:%M:%SZ")
            self._log(technical_event("scan_accepted", sequence_id=job.sequence_id, configuration_id=job.configuration_id, configuration_generation=job.configuration_generation, target_hwnd=target.hwnd, target_pid=target.pid, queue_size=self.queue.status().queued))
        except QueueFullError:
            self.last_error = "Cola llena"
            self._notify("Cola llena", "La lectura no fue aceptada; espere y vuelva a escanear")

    def _build_serial_manager(self) -> SerialManager:
        def list_ports():
            import serial.tools.list_ports
            return serial.tools.list_ports.comports()

        def open_port(device: str, baudrate: int, timeout: float):
            import serial
            return serial.Serial(device, baudrate=baudrate, timeout=timeout)

        return SerialManager(
            list_ports=list_ports,
            open_port=open_port,
            submit_frame=self._submit_serial_frame,
            capture_context=self._capture_target_context,
            load_last_port=self.config.load_last_port,
            save_last_port=self.config.save_last_port,
            logger=self._log,
            state_callback=self._state_changed,
        )

    def _installation_id(self) -> str:
        path = self.root_dir / "configs" / "sistema" / "instalacion.json"
        data = read_json(path, default={}) or {}
        value = str(data.get("installation_id") or "").strip() if isinstance(data, dict) else ""
        if not value:
            value = str(uuid.uuid4())
            write_json_atomic(path, {"installation_id": value}, backup=False)
        return value

    def _validate_license(self) -> None:
        verifier = LicenseVerifier(
            public_key_path=self.root_dir / "assets" / "license_public_key.pem",
            license_path=self.root_dir / "licencia.key",
            state_path=self.root_dir / "configs" / "sistema" / "licencia_estado.json",
        )
        claims = verifier.verify(installation_id=self._installation_id())
        self._log(technical_event("license_valid", license_id=claims.license_id, client_id=claims.client_id))

    def _change_configuration(self, name: str) -> None:
        generation = self.config.set_active(name)
        self.queue.cancel_for_configuration_change(generation)
        self._notify("Configuración cambiada", Path(name).stem)
        self._log(technical_event("configuration_changed", configuration_generation=generation))

    def _toggle_favorites(self, icon=None, item=None) -> None:
        try:
            target, generation = self.config.toggle_favorite()
            self.queue.cancel_for_configuration_change(generation)
            self._notify("Configuración cambiada", Path(target).stem)
        except ConfigurationError as exc:
            self._notify("Favoritas no configuradas", str(exc))

    def _open_selector(self, icon=None, item=None) -> None:
        if not self._selector_lock.acquire(blocking=False):
            return

        def worker():
            try:
                root = Tk()
                root.title("Seleccionar configuración")
                root.geometry("500x210")
                root.resizable(False, False)
                frame = ttk.Frame(root, padding=20)
                frame.pack(fill="both", expand=True)
                ttk.Label(frame, text="Configuración activa:").pack(anchor="w")
                values = self.config.list_forms()
                combo = ttk.Combobox(frame, values=values, state="readonly", width=55)
                combo.pack(fill="x", pady=10)
                try:
                    active = Path(self.config.load_active().source_path).name
                except ConfigurationError:
                    active = ""
                    messagebox.showerror("Configuración activa inválida", "La configuración activa no se seleccionará automáticamente. Corríjala o elija explícitamente otra.", parent=root)
                combo.set(active)

                def activate():
                    try:
                        self._change_configuration(combo.get())
                        root.destroy()
                    except ConfigurationError as exc:
                        messagebox.showerror("Configuración inválida", str(exc), parent=root)

                ttk.Button(frame, text="Activar", command=activate).pack(pady=8)
                root.mainloop()
            finally:
                self._selector_lock.release()

        threading.Thread(target=worker, name="DMSConfigSelector", daemon=True).start()

    def _emergency_hotkey_loop(self) -> None:
        if os.name != "nt":
            return
        user32 = ctypes.windll.user32
        hotkey_id = 0xD36
        if not user32.RegisterHotKey(None, hotkey_id, 0x0001 | 0x0002 | 0x4000, 0x1B):
            self._log(technical_event("emergency_hotkey_failed"))
            return
        try:
            message = wintypes.MSG()
            while not self.stop_event.is_set() and user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == 0x0312 and message.wParam == hotkey_id:
                    if self.queue.cancel_current("tecla_emergencia"):
                        self._notify("Escritura cancelada", "Cancelación de emergencia aplicada")
        finally:
            user32.UnregisterHotKey(None, hotkey_id)

    def _open_folder(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except (AttributeError, OSError) as exc:
            self._log(technical_event("open_folder_failed", reason=path.name, error_type=type(exc).__name__))

    def _clear_diagnostics(self) -> None:
        diagnostics = self.root_dir / "diagnosticos"
        removed = 0
        if diagnostics.exists():
            for entry in diagnostics.iterdir():
                if entry.is_file() and not entry.is_symlink():
                    try:
                        entry.unlink()
                        removed += 1
                    except OSError as exc:
                        self._log(technical_event("diagnostic_delete_failed", reason=entry.suffix, error_type=type(exc).__name__))
        self._notify("Diagnósticos", f"Archivos eliminados: {removed}")

    def _menu(self):
        from pystray import Menu, MenuItem

        def status_text(item):
            port = self.serial.current_port.device if self.serial.current_port else "sin COM"
            return f"Lector: {self.reader_state.value} | {port}"

        def config_text(item):
            try:
                snapshot = self.config.load_active()
                return f"Config: {snapshot.name} | {snapshot.profile}"
            except Exception:
                return "Config: inválida"

        def queue_text(item):
            status = self.queue.status()
            return f"Cola: {status.queued} | {'pausada' if status.paused else 'activa'}"

        def last_text(item):
            return f"Última lectura aceptada: {self.last_success_utc}"

        def error_text(item):
            summary = str(self.last_error or "Sin errores").replace("\n", " ")[:80]
            return f"Último error: {summary}"

        return Menu(
            MenuItem(status_text, None, enabled=False),
            MenuItem(config_text, None, enabled=False),
            MenuItem(queue_text, None, enabled=False),
            MenuItem(last_text, None, enabled=False),
            MenuItem(error_text, None, enabled=False),
            Menu.SEPARATOR,
            MenuItem("Reconectar lector", lambda icon, item: self.serial.reconnect_now()),
            MenuItem("Cambiar configuración", self._open_selector),
            MenuItem("Alternar favoritas (Ctrl+Alt+C)", self._toggle_favorites),
            MenuItem("Pausar escrituras", lambda icon, item: self.queue.pause()),
            MenuItem("Reanudar escrituras", lambda icon, item: self.queue.resume()),
            MenuItem("Cancelar escritura actual (Ctrl+Alt+Esc)", lambda icon, item: self.queue.cancel_current()),
            MenuItem("Vaciar cola", lambda icon, item: self.queue.clear_pending("vaciada_desde_bandeja")),
            Menu.SEPARATOR,
            MenuItem("Abrir logs redactados", lambda icon, item: self._open_folder(self.root_dir / "logs")),
            MenuItem("Abrir diagnóstico", lambda icon, item: self._open_folder(self.root_dir / "diagnosticos")),
            MenuItem("Borrar diagnósticos", lambda icon, item: self._clear_diagnostics()),
            Menu.SEPARATOR,
            MenuItem("Salir", lambda icon, item: self.shutdown()),
        )

    def _load_icon(self):
        from PIL import Image
        for candidate in (self.root_dir / "assets" / "DMS_icono_circulo_i.ico", self.root_dir / "assets" / "icono.ico"):
            if candidate.exists():
                try:
                    return Image.open(candidate)
                except Exception:
                    continue
        return Image.new("RGB", (64, 64), "white")

    def shutdown(self) -> None:
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        self.queue.stop()
        self.serial.stop()
        self._parser_pool.shutdown(wait=False, cancel_futures=True)
        self.instance.close()
        try:
            if self.tray_icon:
                self.tray_icon.stop()
        except Exception as exc:
            self._log(technical_event("tray_stop_failed", error_type=type(exc).__name__))

    def run(self) -> int:
        try:
            self.instance.acquire()
            self.config.initialize()
            self._validate_license()
        except Exception as exc:
            try:
                ctypes.windll.user32.MessageBoxW(0, str(exc), f"{PRODUCT_NAME} - Inicio bloqueado", 0x10 | 0x00040000)
            except Exception:
                print(f"Inicio bloqueado: {exc}")
            self._log(technical_event("startup_blocked", error_type=type(exc).__name__))
            return 2

        self.queue.start()
        self.serial.start()
        threading.Thread(target=self._emergency_hotkey_loop, name="DMSEmergencyHotkey", daemon=True).start()

        from pystray import Icon
        self.tray_icon = Icon("DMS_LectorCedulas", self._load_icon(), f"{PRODUCT_NAME} {VERSION}", self._menu())
        self._notify("Lector iniciado", "Buscando lector serial")
        try:
            self.tray_icon.run()
        finally:
            self.shutdown()
        return 0
