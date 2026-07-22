import time

from assets.runtime import dms_lenel_control_guard as guard
from assets.runtime import dms_reader_runtime as reader
from assets.runtime import dms_scan_queue_guard as queue_guard
from assets.runtime import dms_session_runtime as session
from assets.runtime import lector_core as core


# Validación rápida: conserva la comprobación del contenido sin introducir
# esperas largas cuando Lenel responde inmediatamente.
guard.CONTROL_STABLE_SECONDS = 0.02
guard.CONTROL_READY_TIMEOUT = 0.08
guard.CONTROL_CHECK_SECONDS = 0.005
guard.FIELD_VERIFY_ATTEMPTS = 2
guard.FIELD_RETRY_DELAY = 0.025
guard.VERIFY_READ_DELAY = 0.01
guard.WINDOW_MESSAGE_TIMEOUT_MS = 40

# Pausas cortas pero suficientes para Ctrl+V, Tab y validaciones de Lenel.
reader.INITIAL_FORM_SETTLE = 0.03
reader.FOCUS_RESTORE_TIMEOUT = 0.70
reader.TAB_STEP_DELAY = 0.025
reader.TAB_GROUP_DELAY = 0.035
reader.PRE_FIELD_DELAY = 0.015
reader.CLIPBOARD_SETTLE_DELAY = 0.015
reader.PASTE_KEY_DELAY = 0.008
reader.POST_PASTE_DELAY = 0.045
reader.EMPTY_FIELD_DELAY = 0.015
reader.POST_FIELD_TAB_DELAY = 0.025
reader.BETWEEN_FIELDS_DELAY = 0.025

# Reduce únicamente las esperas entre lecturas consecutivas. La cola y el orden
# de escritura se conservan.
queue_guard.FORM_REARM_SECONDS = 0.25
queue_guard.TARGET_STABLE_SECONDS = 0.04
queue_guard.TARGET_CHECK_SECONDS = 0.01


def _apply_fast_keyboard_profile():
    """Aplica el perfil después de patch_core(), que usa valores conservadores."""
    core.pyautogui.PAUSE = 0.005
    core.TAB_PAUSE = 0.025
    core.BETWEEN_FIELDS = 0.035


def _paste_clipboard(target, value, replace_existing=False):
    if not reader._ensure_target_focus(target):
        return False

    reader._release_modifier_keys()

    if replace_existing:
        core.pyautogui.hotkey("ctrl", "a")
        if session.STOP.wait(0.008):
            return False

        core.pyautogui.press("backspace")
        if session.STOP.wait(0.008):
            return False

    text = str(value)
    if not reader._prepare_verified_clipboard(text):
        core.safe_write(text)
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


def _wait_until_value_matches(control, expected, timeout):
    """Sondea el campo y sale apenas aparece el valor esperado."""
    deadline = time.monotonic() + timeout

    while not session.STOP.is_set() and time.monotonic() < deadline:
        actual = guard._read_control_text(control)

        if actual is None:
            return None

        if guard._value_matches(actual, expected):
            return True

        if session.STOP.wait(0.008):
            return False

    return False


def _compatible_protected_write(value, target, position, label):
    """Modo rápido para controles privados que no permiten WM_GETTEXT."""
    if not _paste_clipboard(target, value, replace_existing=False):
        return False, False

    # El primer campo puede ser ignorado mientras Lenel termina su búsqueda.
    # Se sustituye rápidamente una segunda vez sin duplicar el contenido.
    if position == 1:
        if session.STOP.wait(0.08):
            return False, False

        if not _paste_clipboard(target, value, replace_existing=True):
            return False, False

        session.log(
            f"🛡️ Campo {position} '{label}' reforzado rápidamente antes de avanzar."
        )

    return True, False


def _fast_write_verified_value(value, target, position, label):
    _apply_fast_keyboard_profile()

    if value in (None, ""):
        return not session.STOP.wait(reader.EMPTY_FIELD_DELAY), False

    text = str(value)
    started = time.monotonic()
    control = guard._wait_for_stable_control(target)
    control_class = guard._control_class(control) or "control-desconocido"

    if not control or not guard._looks_like_text_control(control_class):
        elapsed_ms = int((time.monotonic() - started) * 1000)
        session.log(
            f"ℹ️ Campo {position} '{label}': control privado de Lenel; "
            f"modo rápido activado tras {elapsed_ms} ms."
        )
        return _compatible_protected_write(text, target, position, label)

    # Primer intento.
    if not guard._keyboard_replace_and_paste(
        target,
        control,
        text,
        replace_existing=False,
    ):
        return False, True

    validation = _wait_until_value_matches(control, text, timeout=0.10)

    if validation is None:
        session.log(
            f"⚡ Campo {position} '{label}' enviado; "
            "el control no permite lectura directa."
        )
        return True, False

    if validation:
        session.log(
            f"🔎 Campo {position} '{label}' verificado rápidamente."
        )
        return True, True

    # Reintento inmediato: selecciona, reemplaza y vuelve a comprobar.
    session.log(
        f"🔁 Campo {position} '{label}' no quedó completo; "
        "reintento rápido."
    )

    if not guard._keyboard_replace_and_paste(
        target,
        control,
        text,
        replace_existing=True,
    ):
        return False, True

    validation = _wait_until_value_matches(control, text, timeout=0.12)

    if validation is None:
        return True, False

    if validation:
        session.log(
            f"🔎 Campo {position} '{label}' verificado en reintento rápido."
        )
        return True, True

    if guard._set_control_text_fallback(target, control, text):
        session.log(
            f"🔎 Campo {position} '{label}' verificado mediante respaldo Win32."
        )
        return True, True

    session.log(
        f"⚠️ Campo {position} '{label}' no fue verificable; "
        "se aplicará pegado protegido antes de avanzar."
    )
    return _compatible_protected_write(text, target, position, label)


_original_write_form_verified = guard.write_form_verified


def _write_form_fast(data, configuration):
    _apply_fast_keyboard_profile()
    return _original_write_form_verified(data, configuration)


# El escritor de la cola consulta reader.write_form, mientras que el módulo de
# verificación consulta el nombre global _write_verified_value.
guard._write_verified_value = _fast_write_verified_value
guard.write_form_verified = _write_form_fast
reader.write_form = _write_form_fast
