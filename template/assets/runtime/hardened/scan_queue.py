from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Callable

from .models import JobState, ScanJob, WriteResult


class QueueFullError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class QueueStatus:
    queued: int
    paused: bool
    current_sequence: int | None
    completed: int
    failed: int
    cancelled: int


class ScanQueue:
    def __init__(
        self,
        *,
        writer,
        capacity: int = 64,
        logger: Callable[[str], None] | None = None,
        notify: Callable[[str, str], None] | None = None,
    ):
        if capacity < 1 or capacity > 1000:
            raise ValueError("capacity fuera de rango")
        self.writer = writer
        self.capacity = capacity
        self.logger = logger or (lambda message: None)
        self.notify = notify or (lambda title, message: None)
        self._queue: queue.Queue[ScanJob] = queue.Queue(maxsize=capacity)
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._pause.set()
        self._current_cancel = threading.Event()
        self._current: ScanJob | None = None
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._completed = 0
        self._failed = 0
        self._cancelled = 0

    def start(self) -> None:
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            if self._stop.is_set():
                raise RuntimeError("No se puede reiniciar una cola detenida")
            self._worker = threading.Thread(target=self._run, name="DMSScanQueue", daemon=True)
            self._worker.start()

    def stop(self, *, wait: bool = True, timeout: float = 3.0) -> None:
        self._stop.set()
        self._pause.set()
        self._current_cancel.set()
        with self._lock:
            worker = self._worker
        if wait and worker and worker is not threading.current_thread():
            worker.join(max(0.0, timeout))
            if worker.is_alive():
                self.logger("queue_stop_timeout")

    def submit(self, job: ScanJob) -> None:
        if self._stop.is_set():
            raise RuntimeError("La cola está detenida")
        try:
            self._queue.put_nowait(job)
        except queue.Full as exc:
            raise QueueFullError("La cola alcanzó su capacidad; la lectura no fue aceptada") from exc
        self.logger(f"queue_enqueued:{job.sequence_id}:size={self._queue.qsize()}")

    def pause(self) -> None:
        self._pause.clear()
        self.logger("queue_paused")

    def resume(self) -> None:
        self._pause.set()
        self.logger("queue_resumed")

    def cancel_current(self, reason: str = "cancelado_por_usuario") -> bool:
        with self._lock:
            if self._current is None:
                return False
            self._current.cancellation_reason = reason
            self._current_cancel.set()
            return True

    def clear_pending(self, reason: str = "cola_vaciada") -> int:
        removed = 0
        while True:
            try:
                job = self._queue.get_nowait()
            except queue.Empty:
                break
            job.state = JobState.CANCELLED
            job.cancellation_reason = reason
            removed += 1
            with self._lock:
                self._cancelled += 1
            self._queue.task_done()
        if removed:
            self.logger(f"queue_cleared:{removed}:{reason}")
        return removed

    def cancel_for_configuration_change(self, new_generation: int) -> int:
        """Aplica una barrera de configuración sin cortar una escritura a mitad.

        El trabajo que ya está escribiendo conserva su snapshot y finaliza completo.
        Solo se descartan trabajos pendientes de la generación anterior. La cancelación
        inmediata del trabajo actual queda reservada para la tecla de emergencia o una
        salida explícita del usuario.
        """
        reason = f"configuracion_cambio_a_generacion_{new_generation}"
        with self._lock:
            current = self._current.sequence_id if self._current else None
        if current is not None:
            self.logger(f"queue_configuration_barrier:current={current}:generation={new_generation}")
        return self.clear_pending(reason)

    def status(self) -> QueueStatus:
        with self._lock:
            current = self._current.sequence_id if self._current else None
            return QueueStatus(
                self._queue.qsize(),
                not self._pause.is_set(),
                current,
                self._completed,
                self._failed,
                self._cancelled,
            )

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self._pause.wait(0.25):
                continue
            try:
                job = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            with self._lock:
                self._current = job
                self._current_cancel = threading.Event()
            try:
                if self._stop.is_set():
                    job.state = JobState.CANCELLED
                    job.cancellation_reason = "aplicacion_detenida"
                    with self._lock:
                        self._cancelled += 1
                    continue
                job.state = JobState.WAITING_TARGET
                job.attempts += 1
                job.state = JobState.WRITING
                result: WriteResult = self.writer.write(job, self._current_cancel)
                if result.success:
                    job.state = JobState.COMPLETED
                    with self._lock:
                        self._completed += 1
                    self.logger(
                        f"queue_completed:{job.sequence_id}:elapsed_ms={result.elapsed_ms:.1f}"
                    )
                elif self._current_cancel.is_set():
                    job.state = JobState.CANCELLED
                    job.cancellation_reason = (
                        job.cancellation_reason or result.reason or "cancelado"
                    )
                    with self._lock:
                        self._cancelled += 1
                    self.notify("Escritura cancelada", f"Trabajo #{job.sequence_id} cancelado")
                    self.logger(
                        f"queue_cancelled:{job.sequence_id}:{job.cancellation_reason}:"
                        f"fields_written={result.fields_written}"
                    )
                else:
                    job.state = JobState.FAILED
                    job.failure_reason = result.reason or result.state
                    with self._lock:
                        self._failed += 1
                    self.notify(
                        "No se escribió el documento",
                        "El formulario objetivo cambió o no pudo validarse",
                    )
                    self.logger(
                        f"queue_failed:{job.sequence_id}:{job.failure_reason}:"
                        f"fields_written={result.fields_written}:fields_verified={result.fields_verified}"
                    )
            except Exception as exc:
                job.state = JobState.FAILED
                job.failure_reason = type(exc).__name__
                with self._lock:
                    self._failed += 1
                self.logger(f"queue_exception:{job.sequence_id}:{type(exc).__name__}")
            finally:
                with self._lock:
                    self._current = None
                self._queue.task_done()
