import time

from assets.runtime import dms_lenel_control_guard as guard
from assets.runtime import dms_reader_runtime as reader
from assets.runtime import dms_session_runtime as session
from assets.runtime import lector_core as core


# Lenel suele usar controles internos que no exponen texto por Win32. No se debe
# consumir varios segundos por campo intentando verificar algo que la aplicación
# no permite leer.
guard.CONTROL_STABLE_SECONDS = 0.08
guard.CONTROL_READY_TIMEOUT = 0.35
guard.CONTROL_CHECK_SECONDS = 0.02
guard.FIELD_VERIFY_ATTEMPTS = 2
guard.FIELD_RETRY_DELAY = 0.08
guard.VERIFY_READ_DELAY = 0.04
guard.WINDOW_MESSAGE_TIMEOUT_MS = 120

# Ritmo objetivo: aproximadamente 4-6 segundos para Apellidos, Nombre y Cédula,
# incluyendo cinco tabuladores antes de la cédula.
reader.INITIAL_FORM_SETTLE = 0.08
reader.TAB_STEP_DELAY = 0.055
reader.TAB_GROUP_DELAY = 0.08
reader.PRE_FIELD_DELAY = 0.04
reader.CLIPBOARD_SETTLE_DELAY = 0.04
reader.PASTE_KEY_DELAY = 0.025
reader.POST_PASTE_DELAY = 0.13
reader.EMPTY_FIELD_DELAY = 0.04
reader.POST_FIELD_TAB_DELAY = 0.07
reader.BETWEEN_FIELDS_DELAY = 0.07


def _paste_clipboard(target, value, replace_existing=False):
    if not reader._ensure_target_focus(target):
        return False

    reader._release_modifier_keys()
    if replace_existing:
        core.pyautogui.hotkey("ctrl", "a")
        if session.STOP.wait(0.04):
            return False
        core.pyautogui.press("backspace")
        if session.STOP.wait(0.04):
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


def _compatible_protected_write(value, target, position, label):
    """Modo rápido para controles privados que no permiten WM_GETTEXT."""
    if not _paste_clipboard(target, value, replace_existing=False):
        return False, False

    # El fallo observado ocurre en el primer campo mientras Lenel termina la
    # búsqueda interna. Se sustituye una segunda vez en el mismo campo antes de
    # enviar Tab: si el primer pegado fue ignorado, este lo escribe; si funcionó,
    # Ctrl+A lo reemplaza por el mismo valor sin duplicarlo.
    if position == 1:
        if session.STOP.wait(0.18):
            return False, False
        if not _paste_clipboard(target, value, replace_existing=True):
            return False, False
        session.log(
            f"🛡️ Campo {position} '{label}' reforzado antes de avanzar en Lenel."
        )

    return True, False


def _fast_write_verified_value(value, target, position, label):
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

    for attempt in range(1, guard.FIELD_VERIFY_ATTEMPTS + 1):
        if session.STOP.is_set():
            return False, True

        if not guard._keyboard_replace_and_paste(
            target,
            control,
            text,
            replace_existing=attempt > 1,
        ):
            return False, True

        if session.STOP.wait(guard.VERIFY_READ_DELAY):
            return False, True

        actual = guard._read_control_text(control)
        if actual is None:
            session.log(
                f"ℹ️ Campo {position} '{label}' no permite lectura; "
                "se acepta el pegado sin espera adicional."
            )
            return True, False

        if guard._value_matches(actual, text):
            session.log(
                f"🔎 Campo {position} '{label}' verificado en "
                f"'{control_class}' (intento {attempt})."
            )
            return True, True

        if session.STOP.wait(guard.FIELD_RETRY_DELAY):
            return False, True

        current_control = guard._wait_for_stable_control(target)
        if current_control:
            control = current_control
            control_class = guard._control_class(control) or control_class

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


# write_form_verified consulta este nombre global en cada campo.
guard._write_verified_value = _fast_write_verified_value
