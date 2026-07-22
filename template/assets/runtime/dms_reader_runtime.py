import ctypes
import os
import threading
import time

from assets.runtime import dms_session_runtime as session
from assets.runtime import lector_core as core


SERIAL_POLL_SECONDS = 0.025
INITIAL_FORM_SETTLE = 0.55
FOCUS_RESTORE_TIMEOUT = 2.5
TAB_STEP_DELAY = 0.14
TAB_GROUP_DELAY = 0.28
PRE_FIELD_DELAY = 0.16
CLIPBOARD_SETTLE_DELAY = 0.12
PASTE_KEY_DELAY = 0.08
POST_PASTE_DELAY = 0.38
EMPTY_FIELD_DELAY = 0.12
POST_FIELD_TAB_DELAY = 0.20
BETWEEN_FIELDS_DELAY = 0.24

_write_lock = threading.Lock()


def wait_serial_silent(serial_port, quiet_seconds=0.35, timeout=2.0):
    start = time.monotonic()
    quiet_start = time.monotonic()
    while not session.STOP.is_set() and time.monotonic() - start < timeout:
        try:
            waiting = serial_port.in_waiting
            if waiting:
                serial_port.read(waiting)
                quiet_start = time.monotonic()
            elif time.monotonic() - quiet_start >= quiet_seconds:
                return
        except Exception:
            return
        if session.STOP.wait(SERIAL_POLL_SECONDS):
            return


def read_serial_buffer(
    serial_port,
    timeout_total=3.0,
    max_bytes=None,
    idle_seconds=None,
):
    max_bytes = max_bytes or core.READ_MAX_BYTES
    idle_seconds = idle_seconds or core.READ_IDLE_SECONDS
    data = bytearray()
    start = time.monotonic()
    last_data = None

    while not session.STOP.is_set() and time.monotonic() - start < timeout_total:
        try:
            waiting = serial_port.in_waiting
            if waiting:
                chunk = serial_port.read(waiting)
                if chunk:
                    data.extend(chunk)
                    last_data = time.monotonic()
                    if len(data) > max_bytes:
                        break
            elif data and last_data and time.monotonic() - last_data >= idle_seconds:
                if session.STOP.wait(0.06):
                    break
                if not serial_port.in_waiting:
                    break
        except Exception:
            break

        if session.STOP.wait(SERIAL_POLL_SECONDS):
            break

    return bytes(data)


def port_responds(port, callback=None, seconds=3):
    if not port or session.STOP.is_set():
        return False
    try:
        if callback:
            callback(f"🔁 Probando último puerto guardado: {port}... pase la cédula")
        with core.serial.Serial(port, 9600, timeout=0.25) as serial_port:
            serial_port.reset_input_buffer()
            data = bytearray()
            start = time.monotonic()
            while not session.STOP.is_set() and time.monotonic() - start < seconds:
                waiting = serial_port.in_waiting
                if waiting:
                    data.extend(serial_port.read(waiting))
                    if len(data) >= 100 or data.endswith(b"\r\n"):
                        if callback:
                            callback(f"✅ {port} respondió correctamente")
                        return True
                if session.STOP.wait(SERIAL_POLL_SECONDS):
                    break
        return False
    except Exception as error:
        if callback and not session.STOP.is_set():
            callback(f"⚠️ {port} no disponible: {error}")
        return False


def find_reader(callback):
    for device in core.serial.tools.list_ports.comports():
        if session.STOP.is_set():
            return None
        port = device.device
        callback(f"🧪 {port} - Pase la cédula")
        try:
            with core.serial.Serial(port, 9600, timeout=0.25) as serial_port:
                serial_port.reset_input_buffer()
                data = bytearray()
                start = time.monotonic()
                while not session.STOP.is_set() and time.monotonic() - start < 6:
                    waiting = serial_port.in_waiting
                    if waiting:
                        data.extend(serial_port.read(waiting))
                        if len(data) >= 100:
                            callback(f"✅ {port} detectado")
                            return port
                    if session.STOP.wait(SERIAL_POLL_SECONDS):
                        return None
        except Exception as error:
            callback(f"❌ {port} falló: {error}")

    if not session.STOP.is_set():
        callback("🔴 No se detectó lector QR.")
    return None


def _foreground_window():
    if os.name != "nt":
        return 0
    try:
        return int(ctypes.windll.user32.GetForegroundWindow())
    except Exception:
        return 0


def _window_process_id(hwnd):
    if os.name != "nt" or not hwnd:
        return 0
    try:
        process_id = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(
            ctypes.c_void_p(hwnd),
            ctypes.byref(process_id),
        )
        return int(process_id.value)
    except Exception:
        return 0


def _window_title(hwnd):
    if os.name != "nt" or not hwnd:
        return ""
    try:
        length = ctypes.windll.user32.GetWindowTextLengthW(ctypes.c_void_p(hwnd))
        buffer = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(
            ctypes.c_void_p(hwnd),
            buffer,
            length + 1,
        )
        return buffer.value or ""
    except Exception:
        return ""


def _capture_target_window():
    hwnd = _foreground_window()
    return {
        "hwnd": hwnd,
        "pid": _window_process_id(hwnd),
        "title": _window_title(hwnd),
    }


def _ensure_target_focus(target):
    """Mantiene los eventos dentro de la aplicación que estaba activa al leer."""
    if os.name != "nt" or not target.get("pid"):
        return True

    current = _foreground_window()
    if _window_process_id(current) == target["pid"]:
        target["hwnd"] = current
        return True

    deadline = time.monotonic() + FOCUS_RESTORE_TIMEOUT
    while not session.STOP.is_set() and time.monotonic() < deadline:
        hwnd = target.get("hwnd")
        if hwnd:
            try:
                ctypes.windll.user32.ShowWindow(ctypes.c_void_p(hwnd), 5)
                ctypes.windll.user32.BringWindowToTop(ctypes.c_void_p(hwnd))
                ctypes.windll.user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
            except Exception:
                pass

        if session.STOP.wait(0.10):
            return False

        current = _foreground_window()
        if _window_process_id(current) == target["pid"]:
            target["hwnd"] = current
            return True

    return False


def _release_modifier_keys():
    for key in ("ctrl", "shift", "alt", "win"):
        try:
            core.pyautogui.keyUp(key)
        except Exception:
            pass


def _read_windows_clipboard():
    if os.name != "nt":
        return None

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    CF_UNICODETEXT = 13

    try:
        user32.GetClipboardData.restype = ctypes.c_void_p
        kernel32.GlobalLock.restype = ctypes.c_void_p
        if not user32.OpenClipboard(None):
            return None
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return None
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                return None
            try:
                return ctypes.wstring_at(pointer)
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
    except Exception:
        return None


def _prepare_verified_clipboard(value):
    text = str(value)
    for _ in range(4):
        if session.STOP.is_set():
            return False
        try:
            written = core._set_clipboard_text_windows(text)
        except Exception:
            written = False

        if written:
            session.STOP.wait(CLIPBOARD_SETTLE_DELAY)
            current = _read_windows_clipboard()
            if current == text:
                return True
        session.STOP.wait(0.10)
    return False


def _paste_value_precisely(value, target):
    if value in (None, ""):
        return not session.STOP.wait(EMPTY_FIELD_DELAY)

    text = str(value)
    if not _ensure_target_focus(target):
        session.log("⚠️ Se perdió el foco del formulario antes de escribir un campo.")
        return False

    _release_modifier_keys()
    if _prepare_verified_clipboard(text):
        if not _ensure_target_focus(target):
            return False
        try:
            core.pyautogui.keyDown("ctrl")
            if session.STOP.wait(PASTE_KEY_DELAY):
                return False
            core.pyautogui.press("v")
            if session.STOP.wait(PASTE_KEY_DELAY):
                return False
        finally:
            try:
                core.pyautogui.keyUp("ctrl")
            except Exception:
                pass
    else:
        # Respaldo conservador cuando Windows no permite verificar el portapapeles.
        core.safe_write(text)

    return not session.STOP.wait(POST_PASTE_DELAY)


def _press_tab_precisely(target, extra_delay=0.0):
    if not _ensure_target_focus(target):
        return False
    _release_modifier_keys()
    core.pyautogui.press("tab")
    return not session.STOP.wait(TAB_STEP_DELAY + extra_delay)


def _move_tabs_precisely(count, target):
    try:
        total = max(0, min(250, int(count or 0)))
    except Exception:
        total = 0

    for index in range(total):
        if session.STOP.is_set():
            return False
        extra = TAB_GROUP_DELAY if (index + 1) % 5 == 0 else 0.0
        if not _press_tab_precisely(target, extra_delay=extra):
            return False
    return True


def write_form(data, configuration):
    """Escritura secuencial de ultra precisión para formularios lentos."""
    fields = list(configuration.get("campos", []))
    if not fields:
        return False

    with _write_lock:
        target = _capture_target_window()
        session.log(
            "ℹ️ Escritura precisa iniciada: "
            f"{len(fields)} campos; ventana='{target.get('title') or 'sin título'}'."
        )

        if session.STOP.wait(INITIAL_FORM_SETTLE):
            return False
        if not _ensure_target_focus(target):
            session.log("⚠️ No se pudo conservar la ventana del formulario al iniciar.")
            return False

        _release_modifier_keys()

        for position, field in enumerate(fields, start=1):
            if session.STOP.is_set():
                return False

            label = (field.get("dato") or "").strip()
            previous_tabs = field.get("tabuladores", 0)

            if not _move_tabs_precisely(previous_tabs, target):
                session.log(
                    f"⚠️ Escritura detenida antes del campo {position} '{label}': "
                    "no se pudo conservar el foco."
                )
                return False

            if session.STOP.wait(PRE_FIELD_DELAY):
                return False

            if not _paste_value_precisely(data.get(label, ""), target):
                session.log(
                    f"⚠️ No se pudo completar el campo {position} '{label}'."
                )
                return False

            # Tiempo adicional para que validaciones JavaScript, .NET o formularios
            # remotos terminen de procesar el valor antes de abandonar el campo.
            if session.STOP.wait(POST_FIELD_TAB_DELAY):
                return False

            if not _press_tab_precisely(target):
                session.log(
                    f"⚠️ No se pudo avanzar después del campo {position} '{label}'."
                )
                return False

            if session.STOP.wait(BETWEEN_FIELDS_DELAY):
                return False

            session.log(
                f"✅ Campo {position}/{len(fields)} escrito: '{label}' "
                f"(tabs previos: {previous_tabs})."
            )

        session.log("✅ Escritura precisa completada correctamente.")
        return True


def serial_listener(port, load_configuration):
    try:
        with core.serial.Serial(port, 9600, timeout=0.25) as serial_port:
            session.set_active_serial(serial_port)
            serial_port.reset_input_buffer()
            wait_serial_silent(serial_port)
            session.log(f"ℹ️ Lector activo en {port} con modo de bajo consumo.")

            while not session.STOP.is_set():
                raw = read_serial_buffer(serial_port)
                if session.STOP.is_set():
                    break
                if not raw:
                    continue

                invalid, reason = core._buffer_parece_mezclado_o_incompleto(raw)
                if invalid:
                    core.guardar_raw_no_reconocido(raw, reason)
                    wait_serial_silent(serial_port)
                    continue

                now = time.monotonic()
                with core._processing_lock:
                    if now - core._last_read_ts < core.COOLDOWN_SECONDS:
                        wait_serial_silent(serial_port)
                        continue
                    core._last_read_ts = now

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
                    if configuration:
                        serial_port.reset_input_buffer()
                        if session.STOP.wait(0.25):
                            break
                        completed = write_form(data, configuration)
                        if not completed and not session.STOP.is_set():
                            session.log(
                                "⚠️ La lectura fue correcta, pero la escritura del "
                                "formulario no logró completarse."
                            )
                        if session.STOP.wait(0.30):
                            break
                        serial_port.reset_input_buffer()
                        wait_serial_silent(serial_port)
                except Exception as error:
                    if not session.STOP.is_set():
                        session.log(f"⚠️ Error procesando lectura: {error}")
    except Exception as error:
        if not session.STOP.is_set():
            session.log(f"❌ Error del puerto serial {port}: {error}")
    finally:
        _release_modifier_keys()
        session.set_active_serial(None)
