from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Protocol

from .models import ReaderState


class SerialPortLike(Protocol):
    @property
    def in_waiting(self) -> int: ...
    def read(self, size: int) -> bytes: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class PortIdentity:
    device: str
    vid: int | None = None
    pid: int | None = None
    serial_number: str | None = None
    manufacturer: str | None = None
    description: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "vid": self.vid,
            "pid": self.pid,
            "serial_number": self.serial_number,
            "manufacturer": self.manufacturer,
            "description": self.description,
        }


@dataclass(slots=True)
class SerialMetrics:
    bytes_received: int = 0
    frames_received: int = 0
    frames_accepted: int = 0
    frames_rejected: int = 0
    reconnects: int = 0
    late_fragment_extensions: int = 0
    last_frame_ms: float = 0.0


class SerialManager:
    def __init__(
        self,
        *,
        list_ports: Callable[[], Iterable[Any]],
        open_port: Callable[[str, int, float], SerialPortLike],
        submit_frame: Callable[[bytes, Any, PortIdentity], bool],
        capture_context: Callable[[], Any] | None = None,
        load_last_port: Callable[[], dict[str, Any]],
        save_last_port: Callable[[dict[str, Any]], None],
        logger: Callable[[str], None] | None = None,
        state_callback: Callable[[ReaderState, str], None] | None = None,
        baudrates: tuple[int, ...] = (9600,),
        read_timeout: float = 0.2,
        idle_seconds: float = 0.20,
        settle_seconds: float = 0.20,
        frame_timeout: float = 4.0,
        max_bytes: int = 4096,
        min_bytes: int = 8,
    ):
        if idle_seconds < 0.01 or settle_seconds < 0.0:
            raise ValueError("Los tiempos de estabilización serial son inválidos")
        if frame_timeout <= idle_seconds + settle_seconds:
            raise ValueError("frame_timeout debe superar la ventana de estabilización")
        self.list_ports = list_ports
        self.open_port = open_port
        self.submit_frame = submit_frame
        self.capture_context = capture_context or (lambda: None)
        self.load_last_port = load_last_port
        self.save_last_port = save_last_port
        self.logger = logger or (lambda message: None)
        self.state_callback = state_callback or (lambda state, detail: None)
        self.baudrates = baudrates
        self.read_timeout = read_timeout
        self.idle_seconds = idle_seconds
        self.settle_seconds = settle_seconds
        self.frame_timeout = frame_timeout
        self.max_bytes = max_bytes
        self.min_bytes = min_bytes
        self.stop_event = threading.Event()
        self.reconnect_event = threading.Event()
        self.state = ReaderState.DISCONNECTED
        self.current_port: PortIdentity | None = None
        self.metrics = SerialMetrics()
        self._thread: threading.Thread | None = None
        self._active_serial: SerialPortLike | None = None
        self._lock = threading.RLock()
        self._confirmed_identities: set[tuple] = set()
        self._pending_context: Any = None

    def _set_state(self, state: ReaderState, detail: str = "") -> None:
        self.state = state
        self.state_callback(state, detail)
        self.logger(f"serial_state:{state.value}:{detail}")

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            if self.stop_event.is_set():
                raise RuntimeError("No se puede reiniciar una instancia serial detenida")
            self._thread = threading.Thread(target=self._run, name="DMSSerialManager", daemon=True)
            self._thread.start()

    def stop(self, *, wait: bool = True, timeout: float = 2.0) -> None:
        self._set_state(ReaderState.STOPPING)
        self.stop_event.set()
        self.reconnect_event.set()
        with self._lock:
            serial_port = self._active_serial
            worker = self._thread
        if serial_port:
            try:
                serial_port.close()
            except Exception as exc:
                self.logger(f"serial_close_error:stop:{type(exc).__name__}")
        if wait and worker and worker is not threading.current_thread():
            worker.join(max(0.0, timeout))
            if worker.is_alive():
                self.logger("serial_stop_timeout")

    def reconnect_now(self) -> None:
        self.reconnect_event.set()
        with self._lock:
            serial_port = self._active_serial
        if serial_port:
            try:
                serial_port.close()
            except Exception as exc:
                self.logger(f"serial_close_error:reconnect:{type(exc).__name__}")

    def _port_identity(self, item: Any) -> PortIdentity:
        return PortIdentity(
            device=str(getattr(item, "device", "")),
            vid=getattr(item, "vid", None),
            pid=getattr(item, "pid", None),
            serial_number=getattr(item, "serial_number", None),
            manufacturer=getattr(item, "manufacturer", None),
            description=getattr(item, "description", None),
        )

    def _score(self, identity: PortIdentity, preferred: dict[str, Any]) -> int:
        score = 0
        if identity.device and identity.device == preferred.get("device"):
            score += 100
        if identity.serial_number and identity.serial_number == preferred.get("serial_number"):
            score += 80
        if identity.vid is not None and identity.vid == preferred.get("vid"):
            score += 20
        if identity.pid is not None and identity.pid == preferred.get("pid"):
            score += 20
        if identity.manufacturer and identity.manufacturer == preferred.get("manufacturer"):
            score += 5
        if identity.description and identity.description == preferred.get("description"):
            score += 5
        return score

    def _candidates(self) -> list[PortIdentity]:
        preferred = self.load_last_port() or {}
        identities = [self._port_identity(item) for item in self.list_ports()]
        identities = [item for item in identities if item.device]
        return sorted(identities, key=lambda item: self._score(item, preferred), reverse=True)

    def _read_frame(self, serial_port: SerialPortLike) -> bytes:
        started = time.monotonic()
        last_data: float | None = None
        quiet_started: float | None = None
        data = bytearray()
        self._pending_context = None

        while not self.stop_event.is_set() and time.monotonic() - started < self.frame_timeout:
            if self.reconnect_event.is_set():
                raise ConnectionError("reconexion_solicitada")
            waiting = int(serial_port.in_waiting or 0)
            if waiting:
                remaining = self.max_bytes - len(data)
                if remaining <= 0:
                    break
                chunk = serial_port.read(min(waiting, remaining))
                if chunk:
                    if not data:
                        try:
                            self._pending_context = self.capture_context()
                        except Exception as exc:
                            self._pending_context = None
                            self.logger(f"serial_context_capture_error:{type(exc).__name__}")
                    elif quiet_started is not None:
                        self.metrics.late_fragment_extensions += 1
                        self.logger(
                            f"serial_late_fragment:existing={len(data)}:added={len(chunk)}"
                        )
                    data.extend(chunk)
                    self.metrics.bytes_received += len(chunk)
                    last_data = time.monotonic()
                    quiet_started = None
                    if len(data) >= self.max_bytes:
                        break
            elif data and last_data is not None:
                now = time.monotonic()
                if now - last_data >= self.idle_seconds:
                    if quiet_started is None:
                        quiet_started = now
                    elif now - quiet_started >= self.settle_seconds:
                        break
                self.stop_event.wait(0.01)
            else:
                self.stop_event.wait(0.01)
        return bytes(data)

    def confirm_accepted(self, identity: PortIdentity) -> None:
        self.metrics.frames_accepted += 1
        key = (identity.device, identity.vid, identity.pid, identity.serial_number)
        with self._lock:
            first_confirmation = key not in self._confirmed_identities
            if first_confirmation:
                self._confirmed_identities.add(key)
        if first_confirmation:
            self.save_last_port(identity.as_dict())

    def confirm_rejected(self, raw: bytes, reason: str) -> None:
        self.metrics.frames_rejected += 1
        self.logger(
            f"serial_rejected:sha={hashlib.sha256(raw).hexdigest()[:12]}:"
            f"len={len(raw)}:reason={reason}"
        )

    def _process_frame(self, raw: bytes, identity: PortIdentity) -> bool:
        self.metrics.frames_received += 1
        context = self._pending_context
        self._pending_context = None
        if len(raw) < self.min_bytes or len(raw) > self.max_bytes:
            self.confirm_rejected(raw, "length")
            return False
        if context is None:
            try:
                context = self.capture_context()
            except Exception as exc:
                self.logger(f"serial_context_capture_error:late:{type(exc).__name__}")
                context = None
        started = time.monotonic()
        submitted = bool(self.submit_frame(raw, context, identity))
        self.metrics.last_frame_ms = (time.monotonic() - started) * 1000
        if not submitted:
            self.confirm_rejected(raw, "processing_backpressure")
        return submitted

    def _connected_loop(self, identity: PortIdentity, baudrate: int) -> None:
        self._set_state(ReaderState.CONNECTING, identity.device)
        serial_port = self.open_port(identity.device, baudrate, self.read_timeout)
        with self._lock:
            self._active_serial = serial_port
        self.current_port = identity
        self._set_state(ReaderState.READY, identity.device)
        try:
            while not self.stop_event.is_set() and not self.reconnect_event.is_set():
                self._set_state(ReaderState.READING, identity.device)
                raw = self._read_frame(serial_port)
                if not raw:
                    self._pending_context = None
                    self._set_state(ReaderState.READY, identity.device)
                    continue
                self._set_state(ReaderState.PROCESSING, identity.device)
                self._process_frame(raw, identity)
                self._set_state(ReaderState.READY, identity.device)
        finally:
            try:
                serial_port.close()
            finally:
                with self._lock:
                    self._active_serial = None
                self.current_port = None
                self._pending_context = None

    def _run(self) -> None:
        backoff = 0.5
        while not self.stop_event.is_set():
            self.reconnect_event.clear()
            self._set_state(ReaderState.DISCOVERING)
            candidates = self._candidates()
            connected = False
            for identity in candidates:
                for baudrate in self.baudrates:
                    if self.stop_event.is_set():
                        return
                    try:
                        self._connected_loop(identity, baudrate)
                        connected = True
                    except Exception as exc:
                        self.logger(f"serial_port_error:{identity.device}:{type(exc).__name__}")
                    if self.reconnect_event.is_set() or connected:
                        break
                if self.reconnect_event.is_set() or connected:
                    break
            if self.stop_event.is_set():
                break
            self.metrics.reconnects += 1
            self._set_state(ReaderState.RECONNECTING, f"backoff={backoff:.1f}")
            self.stop_event.wait(backoff)
            backoff = min(8.0, backoff * 2)
            if candidates:
                backoff = min(backoff, 2.0)
        self._set_state(ReaderState.STOPPING)
