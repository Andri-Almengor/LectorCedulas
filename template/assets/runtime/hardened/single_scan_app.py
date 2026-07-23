from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from .models import ScanJob
from .privacy import technical_event
from .production_app import ProductionDesktopApplication
from .scan_queue import ScanQueue


@dataclass(frozen=True, slots=True)
class AdmissionStatus:
    reserved: bool
    handed_to_queue: bool
    cooldown_remaining: float


class SingleScanAdmission:
    """Permite una sola lectura desde el parsing hasta el fin del enfriamiento."""

    def __init__(
        self,
        cooldown_seconds: float = 2.0,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if cooldown_seconds < 0.0 or cooldown_seconds > 60.0:
            raise ValueError("cooldown_seconds fuera de rango")
        self.cooldown_seconds = float(cooldown_seconds)
        self.clock = clock
        self._lock = threading.RLock()
        self._reserved = False
        self._handed_to_queue = False
        self._cooldown_until = 0.0

    def try_reserve(self) -> tuple[bool, str, float]:
        with self._lock:
            now = self.clock()
            remaining = max(0.0, self._cooldown_until - now)
            if self._reserved:
                return False, "busy", remaining
            if remaining > 0.0:
                return False, "cooldown", remaining
            self._reserved = True
            self._handed_to_queue = False
            return True, "accepted", 0.0

    def mark_handed_to_queue(self) -> None:
        with self._lock:
            if self._reserved:
                self._handed_to_queue = True

    def release_unhanded(self) -> bool:
        """Libera una lectura rechazada antes de llegar a la cola, sin cooldown."""
        with self._lock:
            if not self._reserved or self._handed_to_queue:
                return False
            self._reserved = False
            return True

    def cancel_pending(self) -> bool:
        """Libera un trabajo retirado de la cola antes de comenzar a escribir."""
        with self._lock:
            if not self._reserved:
                return False
            self._reserved = False
            self._handed_to_queue = False
            return True

    def finish_written_cycle(self) -> None:
        """Finaliza escritura/cancelación y abre el enfriamiento posterior."""
        with self._lock:
            now = self.clock()
            self._reserved = False
            self._handed_to_queue = False
            self._cooldown_until = max(
                self._cooldown_until,
                now + self.cooldown_seconds,
            )

    def status(self) -> AdmissionStatus:
        with self._lock:
            remaining = max(0.0, self._cooldown_until - self.clock())
            return AdmissionStatus(
                reserved=self._reserved,
                handed_to_queue=self._handed_to_queue,
                cooldown_remaining=remaining,
            )


class _CooldownWriter:
    def __init__(self, delegate, admission: SingleScanAdmission, logger) -> None:
        self.delegate = delegate
        self.admission = admission
        self.logger = logger

    def write(self, job, cancel_event):
        try:
            return self.delegate.write(job, cancel_event)
        finally:
            self.admission.finish_written_cycle()
            self.logger(
                technical_event(
                    "scan_cooldown_started",
                    sequence_id=job.sequence_id,
                    cooldown_seconds=self.admission.cooldown_seconds,
                )
            )


class _SingleCycleQueue(ScanQueue):
    def __init__(self, *, admission: SingleScanAdmission, **kwargs) -> None:
        super().__init__(**kwargs)
        self.admission = admission

    def clear_pending(self, reason: str = "cola_vaciada") -> int:
        removed = super().clear_pending(reason)
        if removed and self.status().current_sequence is None:
            self.admission.cancel_pending()
        return removed


class SingleScanProductionApplication(ProductionDesktopApplication):
    """Runtime que descarta cualquier pasada mientras otro ciclo está activo."""

    POST_WRITE_COOLDOWN_SECONDS = 2.0

    def __init__(self, root_dir=None, *, recovery_mode: bool = False):
        self._scan_admission = SingleScanAdmission(
            self.POST_WRITE_COOLDOWN_SECONDS
        )
        super().__init__(root_dir=root_dir, recovery_mode=recovery_mode)

        protected_writer = _CooldownWriter(
            self.writer,
            self._scan_admission,
            self._log,
        )
        self.writer = protected_writer
        self.queue = _SingleCycleQueue(
            admission=self._scan_admission,
            writer=protected_writer,
            capacity=1,
            logger=self._log,
            notify=self._notify,
        )

    def _submit_serial_frame(self, raw, target, identity) -> bool:
        if self.queue.status().paused:
            self._log(technical_event("scan_ignored", reason="queue_paused"))
            return False

        accepted, reason, remaining = self._scan_admission.try_reserve()
        if not accepted:
            self._log(
                technical_event(
                    "scan_ignored",
                    reason=reason,
                    cooldown_remaining_ms=round(remaining * 1000.0),
                )
            )
            return False

        submitted = super()._submit_serial_frame(raw, target, identity)
        if not submitted:
            self._scan_admission.release_unhanded()
        return submitted

    def _enqueue_validated_scan(self, raw, data, target, snapshot) -> bool:
        accepted = super()._enqueue_validated_scan(raw, data, target, snapshot)
        if accepted:
            self._scan_admission.mark_handed_to_queue()
        return accepted

    def _process_scan_async(self, raw, target, identity, captured_snapshot) -> None:
        try:
            super()._process_scan_async(raw, target, identity, captured_snapshot)
        finally:
            if self._scan_admission.release_unhanded():
                self._log(
                    technical_event(
                        "scan_cycle_released_without_write",
                        reason="validation_or_parser_rejection",
                    )
                )


__all__ = [
    "AdmissionStatus",
    "SingleScanAdmission",
    "SingleScanProductionApplication",
]
