import ctypes
import os
import re
import threading
import time
import unicodedata
from ctypes import wintypes

from assets.runtime import dms_config_runtime as config
from assets.runtime import dms_reader_runtime as reader
from assets.runtime import dms_scan_queue_guard as queue_guard
from assets.runtime import dms_session_runtime as session
from assets.runtime import lector_core as core


# Perfiles pensados para cualquier formulario de Windows o web. El modo rápido
# usa pausas cortas, pero solo reintenta cuando el control permite comprobar el
# valor. Nunca conserva un HWND de campo entre lecturas o configuraciones.
WRITE_PROFILES = {
    "rapida": {
        "initial_delay": 0.10,
        "focus_stable": 0.06,
        "focus_timeout": 0.55,
        "configured_tab_delay": 0.045,
        "post_tab_delay": 0.060,
        "clipboard_delay": 0.018,
        "paste_key_delay": 0.010,
        "post_paste_delay": 0.055,
        "verify_delay": 0.035,
        "verify_timeout": 0.12,
        "between_fields": 0.035,
        "attempts": 2,
    },
    "equilibrada": {
        "initial_delay": 0.16,
        "focus_stable": 0.08,
        "focus_timeout": 0.80,
        "configured_tab_delay": 0.070,
        "post_tab_delay": 0.090,
        "clipboard_delay": 0.030,
        "paste_key_delay": 0.016,
        "post_paste_delay": 0.080,
        "verify_delay": 0.055,
        "verify_timeout": 0.20,
        "between_fields": 0.060,
        "attempts": 3,
    },
    "segura": {
        "initial_delay": 0.28,
        "focus_stable": 0.12,
        "focus_timeout": 1.20,
        "configured_tab_delay": 0.110,
        "post_tab_delay": 0.140,
        "clipboard_delay": 0.055,
        "paste_key_delay": 0.025,
        "post_paste_delay": 0.130,
        "verify_delay": 0.090,
        "verify_timeout": 0.34,
        "between_fields": 0.100,
        "attempts": 3,
    },
}

_PROFILE_ALIASES = {
    "rapida": "rapida",
    "rápida": "rapida",
    "rapido": "rapida",
    "rápido": "rapida",
    "rapida_y_precisa": "rapida",
    "rápida y precisa": "rapida",
    "equilibrada": "equilibrada",
    "equilibrado": "equilibrada",
    "normal": "equilibrada",
    "segura": "segura",
    "seguro": "segura",
    "maxima_compatibilidad": "segura",
    "máxima compatibilidad": "segura",
}

_runtime_lock = threading.RLock()
_configuration_generation = 0
_original_set_active = config.set_active


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
SMTO_ABORTIFHUNG = 0x0002
DWORD_PTR_T = ctypes.c_size_t
WPARAM_T = ctypes.c_size_t
LPARAM_T = ctypes.c_ssize_t


def _profile_from(configuration):
    raw = str(
        configuration.get("perfil_escritura")
        or configuration.get("velocidad_escritura")
        or "rapida"
    ).strip().casefold()
    key = _PROFILE_ALIASES.get(raw, raw)
    selected = dict(WRITE_PROFILES.get(key, WRITE_PROFILES["rapida"]))

    # Permite futuros ajustes avanzados en JSON sin romper configuraciones viejas.
    custom = configuration.get("ajustes_escritura")
    if isinstance(custom, dict):
        for name in selected:
            if name not in custom:
                continue
            try:
                value = float(custom[name])
            except (TypeError, ValueError):
                continue
            if value >= 0:
                selected[name] = value
    selected["name"] = key if key in WRITE_PROFILES else "rapida"
    return selected


def _validation_enabled(configuration):
    return bool(configuration.get("validar_escritura", True))


def _replace_existing_enabled(configuration):
    return bool(configuration.get("reemplazar_contenido", False))


def _user32():
    return ctypes.windll.user32


def _focused_control(target):
    if os.name != "nt":
        return 0
    try:
        foreground = reader._foreground_window()
        if not foreground:
            return 0
        if reader._window_process_id(foreground) != int(target.get("pid") or 0):
            return 0
        thread_id = _user32().GetWindowThreadProcessId(
            ctypes.c_void_p(foreground), None
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


def _control_class(control):
    if os.name != "nt" or not control:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(256)
        _user32().GetClassNameW(ctypes.c_void_p(control), buffer, len(buffer))
        return buffer.value or ""
    except Exception:
        return ""


def _looks_readable_text_control(class_name):
    name = str(class_name or "").casefold()
    if any(token in name for token in ("chrome", "mozilla", "renderwidget", "internet explorer")):
        return False
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


def _send_message_timeout(hwnd, message, wparam=0, lparam=0, timeout_ms=90):
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
            int(timeout_ms),
            ctypes.byref(result),
        )
        return int(result.value) if ok else None
    except Exception:
        return None


def _read_control_text(control):
    class_name = _control_class(control)
    if not _looks_readable_text_control(class_name):
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
    return buffer.value if copied is not None else None


def _normalize(value):
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text)


def _matches(actual, expected):
    return _normalize(actual) == _normalize(expected)


def _focus_signature(target):
    if not reader._ensure_target_focus(target):
        return None
    foreground = reader._foreground_window()
    if not foreground:
        return None
    return (int(foreground), int(_focused_control(target) or 0))


def _wait_for_stable_focus(target, profile):
    deadline = time.monotonic() + float(profile["focus_timeout"])
    stable_signature = None
    stable_since = 0.0

    while not session.STOP.is_set() and time.monotonic() < deadline:
        current = _focus_signature(target)
        if current is None:
            return False
        if current == stable_signature:
            if time.monotonic() - stable_since >= float(profile["focus_stable"]):
                return True
        else:
            stable_signature = current
            stable_since = time.monotonic()
        if session.STOP.wait(0.01):
            return False
    return stable_signature is not None


def _press_tab(target, delay, require_change=False):
    if not reader._ensure_target_focus(target):
        return False
    before = _focused_control(target)
    reader._release_modifier_keys()
    core.pyautogui.press("tab")

    if not require_change or not before:
        return not session.STOP.wait(delay)

    deadline = time.monotonic() + max(delay, 0.20)
    while not session.STOP.is_set() and time.monotonic() < deadline:
        current = _focused_control(target)
        if current and current != before:
            return not session.STOP.wait(min(delay, 0.04))
        if session.STOP.wait(0.01):
            return False

    # Por seguridad no se envía un segundo Tab: un Tab tardío más un reintento
    # puede saltarse un campo completo en Lenel, web o sesiones remotas.
    session.log("⚠️ El formulario no confirmó el cambio de campo después de Tab.")
    return False


def _move_configured_tabs(count, target, profile):
    try:
        total = max(0, min(250, int(count or 0)))
    except (TypeError, ValueError):
        total = 0
    for _ in range(total):
        if not _press_tab(
            target,
            float(profile["configured_tab_delay"]),
            require_change=False,
        ):
            return False
    return True


def _paste_once(value, target, profile, replace_existing=False):
    if not reader._ensure_target_focus(target):
        return False
    reader._release_modifier_keys()

    if replace_existing:
        core.pyautogui.hotkey("ctrl", "a")
        if session.STOP.wait(0.012):
            return False
        core.pyautogui.press("backspace")
        if session.STOP.wait(0.012):
            return False

    text = str(value)
    prepared = reader._prepare_verified_clipboard(text)
    if prepared:
        if session.STOP.wait(float(profile["clipboard_delay"])):
            return False
        try:
            core.pyautogui.keyDown("ctrl")
            if session.STOP.wait(float(profile["paste_key_delay"])):
                return False
            core.pyautogui.press("v")
            if session.STOP.wait(float(profile["paste_key_delay"])):
                return False
        finally:
            try:
                core.pyautogui.keyUp("ctrl")
            except Exception:
                pass
    else:
        core.safe_write(text)

    return not session.STOP.wait(float(profile["post_paste_delay"]))


def _write_value(value, target, profile, validate, replace_existing, position, label):
    if value in (None, ""):
        return True, False

    expected = str(value)
    control = _focused_control(target)
    readable = bool(control and _looks_readable_text_control(_control_class(control)))
    attempts = max(1, int(profile["attempts"])) if validate and readable else 1

    for attempt in range(1, attempts + 1):
        replace = replace_existing or attempt > 1
        if not _paste_once(expected, target, profile, replace_existing=replace):
            return False, readable

        if not validate or not readable:
            return True, False

        if session.STOP.wait(float(profile["verify_delay"])):
            return False, True

        deadline = time.monotonic() + float(profile["verify_timeout"])
        while not session.STOP.is_set() and time.monotonic() < deadline:
            current_control = _focused_control(target)
            if current_control and current_control != control:
                control = current_control
                readable = _looks_readable_text_control(_control_class(control))
                if not readable:
                    return True, False
            actual = _read_control_text(control)
            if actual is None:
                return True, False
            if _matches(actual, expected):
                return True, True
            if session.STOP.wait(0.012):
                return False, True

        session.log(
            f"🔁 Campo {position} '{label}' no coincidió; "
            f"reintento {attempt}/{attempts}."
        )

    session.log(
        f"❌ Campo {position} '{label}' no pudo verificarse; no se avanzará."
    )
    return False, True


def write_form_universal(data, configuration):
    """Escritura rápida, precisa y sin estado persistente entre formularios."""
    fields = list(configuration.get("campos", []))
    if not fields:
        return False

    profile = _profile_from(configuration)
    validate = _validation_enabled(configuration)
    replace_existing = _replace_existing_enabled(configuration)

    with reader._write_lock:
        target = reader._capture_target_window()
        if not int(target.get("pid") or 0) or int(target.get("pid") or 0) == os.getpid():
            session.log("⚠️ No hay un formulario externo activo para escribir.")
            return False

        session.log(
            "ℹ️ Escritura universal iniciada: "
            f"perfil={profile['name']}; campos={len(fields)}; "
            f"validación={'sí' if validate else 'no'}; "
            f"ventana='{target.get('title') or 'sin título'}'."
        )

        if session.STOP.wait(float(profile["initial_delay"])):
            return False
        if not _wait_for_stable_focus(target, profile):
            session.log("⚠️ El foco del formulario no se estabilizó antes de escribir.")
            return False

        reader._release_modifier_keys()

        for position, field in enumerate(fields, start=1):
            if session.STOP.is_set():
                return False

            label = str(field.get("dato") or "").strip()
            tabs = field.get("tabuladores", 0)
            if not _move_configured_tabs(tabs, target, profile):
                session.log(f"⚠️ No se pudo llegar al campo {position} '{label}'.")
                return False

            value = data.get(label, "")
            completed, verified = _write_value(
                value,
                target,
                profile,
                validate,
                replace_existing,
                position,
                label,
            )
            if not completed:
                return False

            # Conserva el comportamiento histórico: después de cada campo se
            # avanza una posición. En configuraciones de un solo campo no se
            # restaura ni se fuerza el primer campo de otra configuración.
            is_last = position == len(fields)
            if not _press_tab(
                target,
                float(profile["post_tab_delay"]),
                require_change=verified and not is_last,
            ):
                return False

            if session.STOP.wait(float(profile["between_fields"])):
                return False

            session.log(
                f"✅ Campo {position}/{len(fields)} "
                f"{'verificado' if verified else 'enviado'}: '{label}' "
                f"(tabs previos: {tabs})."
            )

        session.log("✅ Escritura universal completada correctamente.")
        return True


def reset_runtime_state(reason="reinicio manual"):
    global _configuration_generation
    with _runtime_lock:
        _configuration_generation += 1
        generation = _configuration_generation

    # Solo se limpia el sesgo de destino de la cola. No se conserva ni restaura
    # ningún control de formulario, evitando que una configuración rápida escriba
    # en el primer campo de la configuración anterior.
    try:
        queue_guard._last_target_pid = 0
        queue_guard._last_completed_at = 0.0
    except Exception:
        pass
    try:
        reader._release_modifier_keys()
    except Exception:
        pass
    session.log(f"🔄 Estado de escritura reiniciado: {reason} (generación {generation}).")


def _set_active_with_universal_reset(name):
    result = _original_set_active(name)
    reset_runtime_state(f"configuración activa {name}")
    return result


_set_active_with_universal_reset._dms_universal_writer_wrapper = True
if not getattr(config.set_active, "_dms_universal_writer_wrapper", False):
    config.set_active = _set_active_with_universal_reset


# Instala el escritor después de la cola. El lector serial mantiene la cola
# secuencial, pero cada trabajo usa el foco real y su propia copia de configuración.
reader.write_form = write_form_universal
