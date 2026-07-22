import copy
import hashlib
import itertools
import os
import queue
import threading
import time

from assets.runtime import dms_reader_runtime as reader
from assets.runtime import dms_session_runtime as session
from assets.runtime import lector_core as core


QUEUE_CAPACITY = 64
FORM_REARM_SECONDS = 1.80
TARGET_STABLE_SECONDS = 0.70
TARGET_CHECK_SECONDS = 0.10
TARGET_STATUS_LOG_SECONDS = 5.0
RECENT_TARGET_SECONDS = 12.0
DUPLICATE_WINDOW_SECONDS = 0.85

_scan_queue = queue.Queue(maxsize=QUEUE_CAPACITY)
_sequence = itertools.count(1)
_worker_lock = threading.Lock()
_worker_started = False
_last_target_pid = 0
_last_completed_at = 0.0
_last_digest = b""
_last_digest_at = 0.0


def _target_is_valid(target):
    pid = int(target.get("pid") or 0)
    return pid > 0 and pid != os.getpid()


def _target_key(target):
    return (
        int(target.get("pid") or 0),
        str(target.get("title") or ""),
    )


def _wait_for_stable_target(expected_pid=0):
    """Espera una ventana estable antes de comenzar una escritura completa."""
    stable_key = None
    stable_since = 0.0
    stable_target = None
    last_status_log = 0.0

    while not session.STOP.is_set():
        now = time.monotonic()
        target = reader._capture_target_window()
        pid = int(target.get("pid") or 0)
        valid = _target_is_valid(target) and (
            not expected_pid or pid == expected_pid
        )

        if valid:
            key = _target_key(target)
            if key == stable_key:
                if now - stable_since >= TARGET_STABLE_SECONDS:
                    return stable_target or target
            else:
                stable_key = key
                stable_since = now
                stable_target = target
        else:
            stable_key = None
            stable_since = 0.0
            stable_target = None

        if now - last_status_log >= TARGET_STATUS_LOG_SECONDS:
            if expected_pid:
                session.log(
                    "⏳ Lectura en cola: esperando que el formulario anterior "
                    "vuelva a estar activo y estable."
                )
            else:
                session.log(
                    "⏳ Lectura en cola: esperando una ventana de formulario estable."
                )
            last_status_log = now

        if session.STOP.wait(TARGET_CHECK_SECONDS):
            return None

    return None


def _wait_form_rearm():
    if not _last_completed_at:
        return True
    remaining = FORM_REARM_SECONDS - (time.monotonic() - _last_completed_at)
    if remaining <= 0:
        return True
    session.log(
        f"⏳ Esperando {remaining:.2f}s para que el formulario termine de reiniciarse."
    )
    return not session.STOP.wait(remaining)


def _writer_loop():
    global _last_target_pid, _last_completed_at

    while not session.STOP.is_set():
        try:
            job = _scan_queue.get(timeout=0.25)
        except queue.Empty:
            continue

        sequence = job["sequence"]
        try:
            if not _wait_form_rearm():
                return

            hint = job.get("target_hint") or {}
            hint_pid = int(hint.get("pid") or 0)
            target_is_recent = (
                _last_target_pid
                and _last_completed_at
                and time.monotonic() - _last_completed_at <= RECENT_TARGET_SECONDS
            )
            expected_pid = _last_target_pid if target_is_recent else hint_pid

            target = _wait_for_stable_target(expected_pid)
            if target is None:
                return

            _last_target_pid = int(target.get("pid") or expected_pid or 0)
            session.log(
                f"▶️ Iniciando escritura de lectura #{sequence}. "
                f"Pendientes después de esta: {_scan_queue.qsize()}."
            )

            completed = reader.write_form(
                job["data"],
                job["configuration"],
            )
            _last_completed_at = time.monotonic()

            if completed:
                session.log(
                    f"✅ Lectura #{sequence} escrita completa. "
                    f"Rearme del formulario: {FORM_REARM_SECONDS:.2f}s."
                )
            else:
                session.log(
                    f"⚠️ Lectura #{sequence} no completó todos los campos. "
                    "La siguiente lectura permanecerá en cola hasta estabilizar el formulario."
                )
        except Exception as error:
            _last_completed_at = time.monotonic()
            session.log(
                f"⚠️ Error en escritor secuencial para lectura #{sequence}: {error}"
            )
        finally:
            _scan_queue.task_done()


def _ensure_writer_started():
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
        threading.Thread(
            target=_writer_loop,
            name="DMSSequentialWriter",
            daemon=True,
        ).start()


def _is_duplicate_physical_read(raw):
    """Ignora solo la repetición exacta causada por una misma pasada física."""
    global _last_digest, _last_digest_at

    digest = hashlib.sha256(raw).digest()
    now = time.monotonic()
    duplicate = (
        digest == _last_digest
        and now - _last_digest_at <= DUPLICATE_WINDOW_SECONDS
    )
    _last_digest = digest
    _last_digest_at = now
    return duplicate


def _enqueue_read(data, configuration, target_hint):
    sequence = next(_sequence)
    job = {
        "sequence": sequence,
        "data": copy.deepcopy(data),
        "configuration": copy.deepcopy(configuration),
        "target_hint": dict(target_hint or {}),
    }

    while not session.STOP.is_set():
        try:
            _scan_queue.put(job, timeout=0.25)
            session.log(
                f"📥 Lectura #{sequence} agregada a la cola. "
                f"Total pendiente: {_scan_queue.qsize()}."
            )
            return True
        except queue.Full:
            session.log(
                "⏳ Cola de lecturas llena; conservando la lectura hasta que "
                "el formulario termine las anteriores."
            )
    return False


def serial_listener_queued(port, load_configuration):
    """Lee continuamente y entrega cada cédula a un único escritor secuencial."""
    _ensure_writer_started()

    try:
        with core.serial.Serial(port, 9600, timeout=0.25) as serial_port:
            session.set_active_serial(serial_port)
            serial_port.reset_input_buffer()
            reader.wait_serial_silent(serial_port)
            session.log(
                f"ℹ️ Lector activo en {port}; cola secuencial de precisión habilitada."
            )

            while not session.STOP.is_set():
                raw = reader.read_serial_buffer(serial_port)
                if session.STOP.is_set():
                    break
                if not raw:
                    continue

                invalid, reason = core._buffer_parece_mezclado_o_incompleto(raw)
                if invalid:
                    core.guardar_raw_no_reconocido(raw, reason)
                    session.log(f"⚠️ Lectura serial ignorada: {reason}.")
                    continue

                if _is_duplicate_physical_read(raw):
                    session.log(
                        "ℹ️ Repetición exacta de la misma pasada física ignorada."
                    )
                    continue

                try:
                    data = core.parse_cedula_unificada(raw)
                    session.log(data)
                    if not core._is_probably_valid_person(data):
                        core.guardar_raw_no_reconocido(
                            raw,
                            "datos_no_confiables_o_documento_no_soportado",
                        )
                        continue

                    configuration = load_configuration()
                    if not configuration:
                        session.log(
                            "⚠️ Lectura correcta sin configuración activa para escribir."
                        )
                        continue

                    target_hint = reader._capture_target_window()
                    if not _enqueue_read(data, configuration, target_hint):
                        break
                except Exception as error:
                    if not session.STOP.is_set():
                        session.log(f"⚠️ Error procesando lectura serial: {error}")
    except Exception as error:
        if not session.STOP.is_set():
            session.log(f"❌ Error del puerto serial {port}: {error}")
    finally:
        try:
            reader._release_modifier_keys()
        except Exception:
            pass
        session.set_active_serial(None)


# Parche aplicado al importar el paquete runtime. PyInstaller lo incluye mediante
# la importación estática de assets.runtime.__init__.
reader.serial_listener = serial_listener_queued
