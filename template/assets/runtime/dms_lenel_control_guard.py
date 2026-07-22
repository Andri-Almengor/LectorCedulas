import ctypes
import os
import re
import time
import unicodedata
from ctypes import wintypes

from assets.runtime import dms_reader_runtime as reader
from assets.runtime import dms_session_runtime as session
from assets.runtime import lector_core as core


CONTROL_STABLE_SECONDS = 0.30
CONTROL_READY_TIMEOUT = 3.50
CONTROL_CHECK_SECONDS = 0.05
FIELD_VERIFY_ATTEMPTS = 3
FIELD_RETRY_DELAY = 0.30
VERIFY_READ_DELAY = 0.12
WINDOW_MESSAGE_TIMEOUT_MS = 700

# Con la verificación real del control ya no hace falta una espera inicial larga.
reader.INITIAL_FORM_SETTLE = 0.15
reader.TAB_STEP_DELAY = 0.10
reader.TAB_GROUP_DELAY = 0.18
reader.PRE_FIELD_DELAY = 0.08
reader.CLIPBOARD_SETTLE_DELAY = 0.08
reader.PASTE_KEY_DELAY = 0.05
reader.POST_PASTE_DELAY = 0.22
reader.EMPTY_FIELD_DELAY = 0.08
reader.POST_FIELD_TAB_DELAY = 0.12
reader.BETWEEN_FIELDS_DELAY = 0.14


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_SETTEXT = 0x000C
WM_COMMAND = 0x0111
EN_CHANGE = 0x0300
SMTO_ABORTIFHUNG = 0x0002

WPARAM_T = ctypes.c_size_t
LPARAM_T = ctypes.c_ssize_t
DWORD_PTR_T = ctypes.c_size_t


def _user32():
    return ctypes.windll.user32


def _focused_control(target):
    if os.name != "nt":
        return 0

    try:
        foreground = reader._foreground_window()
        if not foreground or reader._window_process_id(foreground) != target.get("pid"):
            return 0

        thread_id = _user32().GetWindowThreadProcessId(
            ctypes.c_void_p(foreground),
            None,
        )
        if not thread_id:
            return 0

        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(GUITHREADINFO)
        if not _user32().GetGUIThreadInfo(thread_id, ctypes.byref(info)):
            return 0

        return int(info.hwndFocus or info.hwndCaret or 0)
    except Exception:
        return 0


def _control_class(hwnd):
    if os.name != "nt" or not hwnd:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(256)
        _user32().GetClassNameW(
            ctypes.c_void_p(hwnd),
            buffer,
            len(buffer),
        )
        return buffer.value or ""
    except Exception:
        return ""


def _looks_like_text_control(class_name):
    name = str(class_name or "").casefold()
    return any(
        token in name
        for token in (
            "edit",
            "textbox",
            "richedit",
            "windowsforms10",
            "masked",
            "tedit",
        )
    )


def _wait_for_stable_control(target):
    """Espera que el campo interno de Lenel deje de cambiar de foco."""
    if os.name != "nt":
        return 0

    deadline = time.monotonic() + CONTROL_READY_TIMEOUT
    stable_handle = 0
    stable_since = 0.0

    while not session.STOP.is_set() and time.monotonic() < deadline:
        if not reader._ensure_target_focus(target):
            return 0

        current = _focused_control(target)
        if current and reader._window_process_id(current) == target.get("pid"):
            if current == stable_handle:
                if time.monotonic() - stable_since >= CONTROL_STABLE_SECONDS:
                    return current
            else:
                stable_handle = current
                stable_since = time.monotonic()
        else:
            stable_handle = 0
            stable_since = 0.0

        if session.STOP.wait(CONTROL_CHECK_SECONDS):
            return 0

    return stable_handle


def _focus_child_control(target, control):
    if os.name != "nt" or not control:
        return reader._ensure_target_focus(target)

    if not reader._ensure_target_focus(target):
        return False

    user32 = _user32()
    current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
    target_thread = user32.GetWindowThreadProcessId(
        ctypes.c_void_p(control),
        None,
    )
    attached = False

    try:
        if target_thread and target_thread != current_thread:
            attached = bool(
                user32.AttachThreadInput(current_thread, target_thread, True)
            )
        user32.SetForegroundWindow(ctypes.c_void_p(target.get("hwnd") or 0))
        user32.SetFocus(ctypes.c_void_p(control))
    except Exception:
        pass
    finally:
        if attached:
            try:
                user32.AttachThreadInput(current_thread, target_thread, False)
            except Exception:
                pass

    return _focused_control(target) == control


def _send_message_timeout(hwnd, message, wparam=0, lparam=0):
    if os.name != "nt" or not hwnd:
        return None

    result = DWORD_PTR_T()
    try:
        send = _user32().SendMessageTimeoutW
        send.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            WPARAM_T,
            LPARAM_T,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.POINTER(DWORD_PTR_T),
        ]
        send.restype = wintypes.LPARAM
        ok = send(
            ctypes.c_void_p(hwnd),
            message,
            WPARAM_T(wparam),
            LPARAM_T(lparam),
            SMTO_ABORTIFHUNG,
            WINDOW_MESSAGE_TIMEOUT_MS,
            ctypes.byref(result),
        )
        if not ok:
            return None
        return int(result.value)
    except Exception:
        return None


def _read_control_text(control):
    if os.name != "nt" or not control:
        return None

    length = _send_message_timeout(control, WM_GETTEXTLENGTH)
    if length is None or length < 0 or length > 8192:
        return None

    buffer = ctypes.create_unicode_buffer(length + 2)
    copied = _send_message_timeout(
        control,
        WM_GETTEXT,
        len(buffer),
        ctypes.cast(buffer, ctypes.c_void_p).value or 0,
    )
    if copied is None:
        return None
    return buffer.value


def _normalize(value):
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text)


def _value_matches(actual, expected):
    expected_normalized = _normalize(expected)
    actual_normalized = _normalize(actual)
    if not expected_normalized:
        return not actual_normalized
    return actual_normalized == expected_normalized


def _keyboard_replace_and_paste(target, control, value, replace_existing):
    if not _focus_child_control(target, control):
        return False

    reader._release_modifier_keys()
    if replace_existing:
        core.pyautogui.hotkey("ctrl", "a")
        if session.STOP.wait(0.08):
            return False
        core.pyautogui.press("backspace")
        if session.STOP.wait(0.08):
            return False

    if not reader._prepare_verified_clipboard(value):
        core.safe_write(str(value))
    else:
        try:
            core.pyautogui.keyDown("ctrl")
            if session.STOP.wait(reader.PASTE_KEY_DELAY):
                return False
            core.pyautogui.press("v")
            if session.STOP.wait(reader.PASTE_KEY_DELAY):
                return False
        finally:
            try:
                core.pyautogui.keyUp("ctrl")
            except Exception:
                pass

    return not session.STOP.wait(reader.POST_PASTE_DELAY)


def _set_control_text_fallback(target, control, value):
    """Último respaldo para controles Win32/WinForms que ignoran Ctrl+V."""
    if os.name != "nt" or not control:
        return False
    if not _focus_child_control(target, control):
        return False

    text = ctypes.create_unicode_buffer(str(value))
    changed = _send_message_timeout(
        control,
        WM_SETTEXT,
        0,
        ctypes.cast(text, ctypes.c_void_p).value or 0,
    )
    if changed is None:
        return False

    try:
        _user32().GetParent.restype = wintypes.HWND
        parent = _user32().GetParent(ctypes.c_void_p(control))
        control_id = _user32().GetDlgCtrlID(ctypes.c_void_p(control))
        if parent and control_id:
            command = (EN_CHANGE << 16) | (control_id & 0xFFFF)
            _send_message_timeout(
                int(parent),
                WM_COMMAND,
                command,
                control,
            )
    except Exception:
        pass

    if session.STOP.wait(VERIFY_READ_DELAY):
        return False
    return _value_matches(_read_control_text(control), value)


def _write_verified_value(value, target, position, label):
    if value in (None, ""):
        return not session.STOP.wait(reader.EMPTY_FIELD_DELAY), False

    text = str(value)
    control = _wait_for_stable_control(target)
    control_class = _control_class(control) or "control-desconocido"

    if not control:
        session.log(
            f"⚠️ Campo {position} '{label}': no se detectó un control interno; "
            "se usará pegado compatible sin verificación."
        )
        return reader._paste_value_precisely(text, target), False

    if not _looks_like_text_control(control_class):
        session.log(
            f"ℹ️ Campo {position} '{label}': control '{control_class}' no "
            "identificado como cuadro de texto; se usará modo compatible."
        )
        return reader._paste_value_precisely(text, target), False

    for attempt in range(1, FIELD_VERIFY_ATTEMPTS + 1):
        if session.STOP.is_set():
            return False, True

        replace_existing = attempt > 1
        if not _keyboard_replace_and_paste(
            target,
            control,
            text,
            replace_existing=replace_existing,
        ):
            return False, True

        if session.STOP.wait(VERIFY_READ_DELAY):
            return False, True

        actual = _read_control_text(control)
        if actual is None:
            session.log(
                f"ℹ️ Campo {position} '{label}' enviado al control "
                f"'{control_class}', pero el control no permite leer su contenido."
            )
            return True, False

        if _value_matches(actual, text):
            session.log(
                f"🔎 Campo {position} '{label}' verificado en "
                f"'{control_class}' (intento {attempt})."
            )
            return True, True

        session.log(
            f"🔁 Campo {position} '{label}' no quedó completo en Lenel "
            f"(intento {attempt}/{FIELD_VERIFY_ATTEMPTS}); se repetirá sin avanzar."
        )
        if session.STOP.wait(FIELD_RETRY_DELAY):
            return False, True

        # Lenel puede recrear el cuadro de texto durante una búsqueda interna.
        current_control = _wait_for_stable_control(target)
        if current_control:
            control = current_control
            control_class = _control_class(control) or control_class

    if _set_control_text_fallback(target, control, text):
        session.log(
            f"🔎 Campo {position} '{label}' verificado mediante respaldo Win32."
        )
        return True, True

    session.log(
        f"❌ Campo {position} '{label}' no pudo verificarse después de "
        f"{FIELD_VERIFY_ATTEMPTS} intentos; no se enviará Tab."
    )
    return False, True


def write_form_verified(data, configuration):
    """No avanza de campo hasta comprobar el valor en el control real."""
    fields = list(configuration.get("campos", []))
    if not fields:
        return False

    with reader._write_lock:
        target = reader._capture_target_window()
        session.log(
            "ℹ️ Escritura verificada iniciada: "
            f"{len(fields)} campos; ventana='{target.get('title') or 'sin título'}'."
        )

        if session.STOP.wait(reader.INITIAL_FORM_SETTLE):
            return False
        if not reader._ensure_target_focus(target):
            session.log("⚠️ No se pudo conservar la ventana del formulario al iniciar.")
            return False

        reader._release_modifier_keys()

        for position, field in enumerate(fields, start=1):
            if session.STOP.is_set():
                return False

            label = (field.get("dato") or "").strip()
            previous_tabs = field.get("tabuladores", 0)

            if not reader._move_tabs_precisely(previous_tabs, target):
                session.log(
                    f"⚠️ Escritura detenida antes del campo {position} '{label}': "
                    "no se pudo conservar el foco."
                )
                return False

            if session.STOP.wait(reader.PRE_FIELD_DELAY):
                return False

            completed, verified = _write_verified_value(
                data.get(label, ""),
                target,
                position,
                label,
            )
            if not completed:
                session.log(
                    f"⚠️ No se pudo completar el campo {position} '{label}'."
                )
                return False

            if session.STOP.wait(reader.POST_FIELD_TAB_DELAY):
                return False

            if not reader._press_tab_precisely(target):
                session.log(
                    f"⚠️ No se pudo avanzar después del campo {position} '{label}'."
                )
                return False

            if session.STOP.wait(reader.BETWEEN_FIELDS_DELAY):
                return False

            status = "verificado" if verified else "enviado"
            session.log(
                f"✅ Campo {position}/{len(fields)} {status}: '{label}' "
                f"(tabs previos: {previous_tabs})."
            )

        session.log("✅ Escritura verificada completada correctamente.")
        return True


reader.write_form = write_form_verified
