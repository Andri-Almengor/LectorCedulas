import time

from assets.runtime import dms_lenel_control_guard as guard
from assets.runtime import dms_reader_runtime as reader
from assets.runtime import dms_scan_queue_guard as queue_guard
from assets.runtime import dms_session_runtime as session
from assets.runtime import lector_core as core


# Validación rápida, pero con tiempo suficiente para que Lenel exponga
# el campo que realmente tiene el foco.
guard.CONTROL_STABLE_SECONDS = 0.03
guard.CONTROL_READY_TIMEOUT = 0.18
guard.CONTROL_CHECK_SECONDS = 0.01
guard.FIELD_VERIFY_ATTEMPTS = 2
guard.FIELD_RETRY_DELAY = 0.035
guard.VERIFY_READ_DELAY = 0.012
guard.WINDOW_MESSAGE_TIMEOUT_MS = 60

# Perfil rápido de escritura. Las pausas de Tab se gestionan de forma
# independiente porque Lenel tarda más en cambiar de campo que en pegar texto.
reader.INITIAL_FORM_SETTLE = 0.04
reader.FOCUS_RESTORE_TIMEOUT = 1.0
reader.TAB_STEP_DELAY = 0.06
reader.TAB_GROUP_DELAY = 0.08
reader.PRE_FIELD_DELAY = 0.025
reader.CLIPBOARD_SETTLE_DELAY = 0.02
reader.PASTE_KEY_DELAY = 0.01
reader.POST_PASTE_DELAY = 0.055
reader.EMPTY_FIELD_DELAY = 0.02
reader.POST_FIELD_TAB_DELAY = 0.045
reader.BETWEEN_FIELDS_DELAY = 0.04

# Cola rápida sin permitir que dos cédulas escriban simultáneamente.
queue_guard.FORM_REARM_SECONDS = 0.30
queue_guard.TARGET_STABLE_SECONDS = 0.05
queue_guard.TARGET_CHECK_SECONDS = 0.01

FIRST_FIELD_TAB_SETTLE = 0.18
NORMAL_FIELD_TAB_SETTLE = 0.10
CONFIG_TAB_SETTLE = 0.065
TAB_GROUP_EXTRA_SETTLE = 0.04


def _apply_fast_keyboard_profile():
    """Evita que patch_core() vuelva a activar el perfil conservador."""
    core.pyautogui.PAUSE = 0.008
    core.TAB_PAUSE = 0.04
    core.BETWEEN_FIELDS = 0.05


def _paste_clipboard(target, value, replace_existing=False):
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
    """Sondea el campo y termina inmediatamente cuando el valor coincide."""
    deadline = time.monotonic() + timeout

    while not session.STOP.is_set() and time.monotonic() < deadline:
        actual = guard._read_control_text(control)

        if actual is None:
            return None

        if guard._value_matches(actual, expected):
            return True

        if session.STOP.wait(0.01):
            return False

    return False


def _compatible_protected_write(value, target, position, label):
    """Modo rápido para controles privados que no permiten WM_GETTEXT."""
    if not _paste_clipboard(target, value, replace_existing=False):
        return False, False

    # Apellidos es el campo que Lenel puede ignorar mientras termina la búsqueda.
    if position == 1:
        if session.STOP.wait(0.10):
            return False, False

        if not _paste_clipboard(target, value, replace_existing=True):
            return False, False

        session.log(
            f"🛡️ Campo {position} '{label}' reforzado antes de cambiar de campo."
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
            f"modo compatible activado tras {elapsed_ms} ms."
        )
        return _compatible_protected_write(text, target, position, label)

    if not guard._keyboard_replace_and_paste(
        target,
        control,
        text,
        replace_existing=False,
    ):
        return False, True

    validation = _wait_until_value_matches(control, text, timeout=0.12)

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

    validation = _wait_until_value_matches(control, text, timeout=0.15)

    if validation is None:
        return True, False

    if validation:
        session.log(
            f"🔎 Campo {position} '{label}' verificado en el segundo intento."
        )
        return True, True

    if guard._set_control_text_fallback(target, control, text):
        session.log(
            f"🔎 Campo {position} '{label}' verificado mediante respaldo Win32."
        )
        return True, True

    session.log(
        f"⚠️ Campo {position} '{label}' no fue verificable; "
        "se aplicará pegado protegido."
    )
    return _compatible_protected_write(text, target, position, label)


def _press_tab_with_settle(target, settle_seconds):
    """Envía un Tab y deja que Lenel active el siguiente campo."""
    if not reader._ensure_target_focus(target):
        return False

    reader._release_modifier_keys()
    core.pyautogui.press("tab")
    return not session.STOP.wait(settle_seconds)


def _move_configured_tabs(count, target):
    try:
        total = max(0, min(250, int(count or 0)))
    except Exception:
        total = 0

    for index in range(total):
        settle = CONFIG_TAB_SETTLE
        if (index + 1) % 5 == 0:
            settle += TAB_GROUP_EXTRA_SETTLE

        if not _press_tab_with_settle(target, settle):
            return False

    return True


def _write_form_fast(data, configuration):
    """
    Escritura rápida y secuencial.

    Valida cada valor, cambia de campo una sola vez y espera que Lenel
    complete ese cambio antes de escribir el siguiente dato.
    """
    _apply_fast_keyboard_profile()

    fields = list(configuration.get("campos", []))
    if not fields:
        return False

    with reader._write_lock:
        target = reader._capture_target_window()
        session.log(
            "ℹ️ Escritura rápida verificada iniciada: "
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

            if not _move_configured_tabs(previous_tabs, target):
                session.log(
                    f"⚠️ No se pudo llegar al campo {position} '{label}'."
                )
                return False

            if session.STOP.wait(reader.PRE_FIELD_DELAY):
                return False

            completed, verified = _fast_write_verified_value(
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

            tab_settle = (
                FIRST_FIELD_TAB_SETTLE
                if position == 1
                else NORMAL_FIELD_TAB_SETTLE
            )

            if not _press_tab_with_settle(target, tab_settle):
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

        session.log("✅ Escritura rápida verificada completada correctamente.")
        return True


guard._write_verified_value = _fast_write_verified_value
guard.write_form_verified = _write_form_fast
reader.write_form = _write_form_fast
