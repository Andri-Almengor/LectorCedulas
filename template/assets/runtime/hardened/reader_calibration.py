from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Protocol

from .serial_manager import PortIdentity


class SerialPortLike(Protocol):
    @property
    def in_waiting(self) -> int: ...
    def read(self, size: int) -> bytes: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class CalibrationProgress:
    device: str
    index: int
    total: int
    remaining_seconds: float
    detail: str


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    success: bool
    identity: PortIdentity | None
    message: str


class PortCalibrationService:
    """Busca el lector COM y confirma el puerto usando una lectura reconocida."""

    def __init__(
        self,
        *,
        list_ports: Callable[[], Iterable[Any]],
        open_port: Callable[[str, int, float], SerialPortLike],
        validate_frame: Callable[[bytes], bool],
        load_last_port: Callable[[], dict[str, Any]],
        save_last_port: Callable[[dict[str, Any]], None],
        logger: Callable[[str], None] | None = None,
        baudrates: tuple[int, ...] = (9600,),
        read_timeout: float = 0.2,
        idle_seconds: float = 0.18,
        max_bytes: int = 4096,
        min_bytes: int = 8,
        per_port_timeout: float = 10.0,
    ):
        self.list_ports = list_ports
        self.open_port = open_port
        self.validate_frame = validate_frame
        self.load_last_port = load_last_port
        self.save_last_port = save_last_port
        self.logger = logger or (lambda _message: None)
        self.baudrates = baudrates
        self.read_timeout = read_timeout
        self.idle_seconds = idle_seconds
        self.max_bytes = max_bytes
        self.min_bytes = min_bytes
        self.per_port_timeout = per_port_timeout

    @staticmethod
    def _identity(item: Any) -> PortIdentity:
        return PortIdentity(
            device=str(getattr(item, "device", "")),
            vid=getattr(item, "vid", None),
            pid=getattr(item, "pid", None),
            serial_number=getattr(item, "serial_number", None),
            manufacturer=getattr(item, "manufacturer", None),
            description=getattr(item, "description", None),
        )

    @staticmethod
    def _score(identity: PortIdentity, preferred: dict[str, Any]) -> int:
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

    def candidates(self, preferred_device: str | None = None) -> list[PortIdentity]:
        preferred = dict(self.load_last_port() or {})
        identities = [self._identity(item) for item in self.list_ports()]
        identities = [item for item in identities if item.device]
        identities.sort(key=lambda item: self._score(item, preferred), reverse=True)
        if preferred_device:
            identities.sort(key=lambda item: item.device != preferred_device)
        return identities

    def _frame_is_valid(self, raw: bytes) -> bool:
        if not self.min_bytes <= len(raw) <= self.max_bytes:
            return False
        try:
            return bool(self.validate_frame(raw))
        except Exception as exc:
            self.logger(f"calibration_validator_error:{type(exc).__name__}")
            return False

    def _try_port(
        self,
        identity: PortIdentity,
        baudrate: int,
        *,
        index: int,
        total: int,
        cancel_event: threading.Event,
        progress: Callable[[CalibrationProgress], None],
    ) -> bool:
        serial_port = self.open_port(identity.device, baudrate, self.read_timeout)
        deadline = time.monotonic() + self.per_port_timeout
        data = bytearray()
        last_data: float | None = None
        last_progress = 0.0
        try:
            while not cancel_event.is_set() and time.monotonic() < deadline:
                now = time.monotonic()
                if now - last_progress >= 0.1:
                    progress(
                        CalibrationProgress(
                            device=identity.device,
                            index=index,
                            total=total,
                            remaining_seconds=max(0.0, deadline - now),
                            detail=f"Esperando una lectura válida en {identity.device}",
                        )
                    )
                    last_progress = now

                waiting = int(serial_port.in_waiting or 0)
                if waiting:
                    remaining_capacity = self.max_bytes - len(data)
                    if remaining_capacity <= 0:
                        data.clear()
                        last_data = None
                        continue
                    chunk = serial_port.read(min(waiting, remaining_capacity))
                    if chunk:
                        data.extend(chunk)
                        last_data = now
                elif data and last_data is not None and now - last_data >= self.idle_seconds:
                    raw = bytes(data)
                    data.clear()
                    last_data = None
                    if self._frame_is_valid(raw):
                        return True
                else:
                    cancel_event.wait(0.01)

            return bool(data and self._frame_is_valid(bytes(data)))
        finally:
            try:
                serial_port.close()
            except Exception as exc:
                self.logger(f"calibration_close_error:{identity.device}:{type(exc).__name__}")

    def calibrate(
        self,
        *,
        preferred_device: str | None = None,
        cancel_event: threading.Event | None = None,
        progress: Callable[[CalibrationProgress], None] | None = None,
    ) -> CalibrationResult:
        cancel = cancel_event or threading.Event()
        notify = progress or (lambda _progress: None)
        try:
            candidates = self.candidates(preferred_device)
        except Exception as exc:
            self.logger(f"calibration_list_ports_error:{type(exc).__name__}")
            return CalibrationResult(False, None, "No se pudieron enumerar los puertos COM.")

        if not candidates:
            return CalibrationResult(False, None, "No se encontraron puertos COM disponibles.")

        total = len(candidates)
        for index, identity in enumerate(candidates, start=1):
            if cancel.is_set():
                return CalibrationResult(False, None, "Calibración cancelada.")
            for baudrate in self.baudrates:
                try:
                    if self._try_port(
                        identity,
                        baudrate,
                        index=index,
                        total=total,
                        cancel_event=cancel,
                        progress=notify,
                    ):
                        self.save_last_port(identity.as_dict())
                        self.logger(f"calibration_success:{identity.device}:{baudrate}")
                        return CalibrationResult(True, identity, f"Lector detectado en {identity.device}.")
                except Exception as exc:
                    self.logger(f"calibration_port_error:{identity.device}:{type(exc).__name__}")
            notify(
                CalibrationProgress(
                    device=identity.device,
                    index=index,
                    total=total,
                    remaining_seconds=0.0,
                    detail=f"Sin lectura en {identity.device}; probando el siguiente puerto.",
                )
            )

        return CalibrationResult(
            False,
            None,
            "No se detectó una lectura válida en ninguno de los puertos COM.",
        )
