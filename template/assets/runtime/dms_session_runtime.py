import csv
import ctypes
import locale
import os
import subprocess
import sys
import threading
import time


MUTEX_NAME = r"Global\DMS_QRReader_SingleInstance_v33"
STOP_EVENT_NAME = r"Global\DMS_QRReader_StopEvent_v39"
ERROR_ALREADY_EXISTS = 183
CREATE_NO_WINDOW = 0x08000000
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
EVENT_MODIFY_STATE = 0x0002
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258

STOP = threading.Event()
_shutdown_lock = threading.Lock()
_serial_lock = threading.Lock()
_hotkey_lock = threading.Lock()
_shutdown_started = False
_active_serial = None
_tray_icon = None
_hotkey_thread_id = None
_mutex_handle = None
_stop_event_handle = None
_logger = None


def configure_logger(logger):
    global _logger
    _logger = logger


def log(message):
    try:
        if _logger:
            _logger(message)
    except Exception:
        pass


def set_tray_icon(icon):
    global _tray_icon
    _tray_icon = icon


def set_active_serial(serial_port):
    global _active_serial
    with _serial_lock:
        _active_serial = serial_port


def _close_active_serial():
    global _active_serial
    with _serial_lock:
        serial_port = _active_serial
        _active_serial = None
    if serial_port is not None:
        try:
            serial_port.cancel_read()
        except Exception:
            pass
        try:
            serial_port.close()
        except Exception:
            pass


def set_hotkey_thread_id(thread_id):
    global _hotkey_thread_id
    with _hotkey_lock:
        _hotkey_thread_id = thread_id


def stop_hotkey():
    with _hotkey_lock:
        thread_id = _hotkey_thread_id
    if os.name == "nt" and thread_id:
        try:
            ctypes.windll.user32.PostThreadMessageW(thread_id, 0x0012, 0, 0)
        except Exception:
            pass


def shutdown(reason, icon=None):
    """Detiene todos los componentes del lector y finaliza el proceso."""
    global _shutdown_started
    with _shutdown_lock:
        if _shutdown_started:
            return
        _shutdown_started = True

    log(f"ℹ️ Cerrando lector: {reason}")
    STOP.set()
    _close_active_serial()
    stop_hotkey()
    try:
        (icon or _tray_icon).stop()
    except Exception:
        pass
    time.sleep(0.15)
    os._exit(0)


def set_low_resource_mode():
    if os.name != "nt":
        return
    try:
        ctypes.windll.kernel32.SetPriorityClass(
            ctypes.windll.kernel32.GetCurrentProcess(),
            BELOW_NORMAL_PRIORITY_CLASS,
        )
        log("ℹ️ Lector iniciado con prioridad reducida.")
    except Exception as error:
        log(f"⚠️ No se pudo reducir la prioridad del lector: {error}")


def _same_executable_pids():
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return []

    executable_name = os.path.basename(sys.executable)
    try:
        result = subprocess.run(
            [
                "tasklist",
                "/FI",
                f"IMAGENAME eq {executable_name}",
                "/FO",
                "CSV",
                "/NH",
            ],
            capture_output=True,
            text=True,
            encoding=locale.getpreferredencoding(False) or "utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except Exception:
        return []

    pids = []
    for row in csv.reader(result.stdout.splitlines()):
        if len(row) < 2 or row[0].lower() != executable_name.lower():
            continue
        try:
            pid = int(row[1].replace(",", ""))
            if pid != os.getpid():
                pids.append(pid)
        except Exception:
            pass
    return pids


def _force_close_previous_instances():
    closed = False
    for pid in _same_executable_pids():
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
                check=False,
            )
            closed = result.returncode == 0 or closed
        except Exception:
            pass
    return closed


def _signal_previous_instance(kernel32):
    try:
        handle = kernel32.OpenEventW(
            EVENT_MODIFY_STATE,
            False,
            STOP_EVENT_NAME,
        )
        if not handle:
            return False
        try:
            return bool(kernel32.SetEvent(handle))
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


def _try_acquire_mutex(kernel32):
    global _mutex_handle
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return False
    if ctypes.get_last_error() != ERROR_ALREADY_EXISTS:
        _mutex_handle = handle
        return True
    kernel32.CloseHandle(handle)
    return False


def ensure_single_instance():
    """Permite detener la sesión anterior y continuar con la nueva."""
    global _stop_event_handle
    if os.name != "nt":
        return True

    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateEventW.restype = wintypes.HANDLE
    kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenEventW.restype = wintypes.HANDLE
    kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    kernel32.SetEvent.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    if _try_acquire_mutex(kernel32):
        _stop_event_handle = kernel32.CreateEventW(None, False, False, STOP_EVENT_NAME)
        return True

    answer = ctypes.windll.user32.MessageBoxW(
        0,
        "Ya existe una sesión del lector abierta.\n\n"
        "¿Desea detenerla e iniciar esta nueva sesión?",
        "Lector de Cédulas DMS",
        0x00000004 | 0x00000020 | 0x00040000,
    )
    if answer != 6:
        return False

    cooperative = _signal_previous_instance(kernel32)
    first_deadline = time.monotonic() + (4 if cooperative else 1)
    while time.monotonic() < first_deadline:
        if _try_acquire_mutex(kernel32):
            _stop_event_handle = kernel32.CreateEventW(None, False, False, STOP_EVENT_NAME)
            return True
        time.sleep(0.2)

    _force_close_previous_instances()
    final_deadline = time.monotonic() + 6
    while time.monotonic() < final_deadline:
        if _try_acquire_mutex(kernel32):
            _stop_event_handle = kernel32.CreateEventW(None, False, False, STOP_EVENT_NAME)
            return True
        time.sleep(0.2)

    ctypes.windll.user32.MessageBoxW(
        0,
        "No fue posible detener la sesión anterior.\n"
        "Cierre el proceso desde el Administrador de tareas e intente nuevamente.",
        "No se pudo iniciar",
        0x10 | 0x00040000,
    )
    return False


def _stop_request_watch():
    if os.name != "nt" or not _stop_event_handle:
        return
    kernel32 = ctypes.windll.kernel32
    while not STOP.is_set():
        result = kernel32.WaitForSingleObject(_stop_event_handle, 500)
        if result == WAIT_OBJECT_0:
            shutdown("Otra instancia solicitó reemplazar esta sesión")
            return
        if result not in (WAIT_TIMEOUT,):
            return


def _windows_session_watch():
    """Cierra la instancia cuando Windows activa otro usuario o sesión."""
    if os.name != "nt":
        return
    try:
        process_id = ctypes.windll.kernel32.GetCurrentProcessId()
        own_session = ctypes.c_ulong()
        ctypes.windll.kernel32.ProcessIdToSessionId(
            process_id,
            ctypes.byref(own_session),
        )
        mismatches = 0
        while not STOP.wait(1.0):
            active_session = int(ctypes.windll.kernel32.WTSGetActiveConsoleSessionId())
            if active_session != 0xFFFFFFFF and active_session != own_session.value:
                mismatches += 1
            else:
                mismatches = 0
            if mismatches >= 2:
                shutdown("Windows cambió de usuario o de sesión")
                return
    except Exception as error:
        log(f"⚠️ No se pudo supervisar la sesión de Windows: {error}")


def start_watchers():
    threading.Thread(
        target=_stop_request_watch,
        name="DMSStopRequestWatch",
        daemon=True,
    ).start()
    threading.Thread(
        target=_windows_session_watch,
        name="DMSSessionWatch",
        daemon=True,
    ).start()


def hotkey_loop(callback, icon, hotkey_id=0xD35):
    if os.name != "nt":
        return
    import ctypes.wintypes

    user32 = ctypes.windll.user32
    thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
    set_hotkey_thread_id(thread_id)
    if not user32.RegisterHotKey(
        None,
        hotkey_id,
        0x0001 | 0x0002 | 0x4000,
        ord("C"),
    ):
        log("⚠️ No se pudo registrar Ctrl+Alt+C")
        return

    try:
        message = ctypes.wintypes.MSG()
        while not STOP.is_set() and user32.GetMessageW(
            ctypes.byref(message),
            None,
            0,
            0,
        ) > 0:
            if message.message == 0x0312 and message.wParam == hotkey_id:
                callback(icon)
    finally:
        user32.UnregisterHotKey(None, hotkey_id)
