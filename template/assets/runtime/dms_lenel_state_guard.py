import ctypes
import os
import threading
import time

from assets.runtime import dms_config_runtime as config
from assets.runtime import dms_lenel_control_guard as guard
from assets.runtime import dms_lenel_fast_guard as fast
from assets.runtime import dms_reader_runtime as reader
from assets.runtime import dms_scan_queue_guard as queue_guard
from assets.runtime import dms_session_runtime as session


# La primera escritura y la primera escritura después de cambiar configuración
# necesitan una preparación breve. Las siguientes conservan el perfil rápido.
STARTUP_WARMUP_SECONDS = 0.30
CONFIG_WARMUP_SECONDS = 0.35
FOCUS_STABLE_SECONDS = 0.10
FOCUS_STABLE_TIMEOUT = 0.60
FOCUS_POLL_SECONDS = 0.01

# El Tab se mantiene físicamente presionado unos milisegundos y después se
# confirma el cambio del control interno cuando Windows permite observarlo.
TAB_KEY_HOLD_SECONDS = 0.020
TAB_TRANSITION_TIMEOUT = 0.35
TAB_TRANSITION_POLL_SECONDS = 0.010
TAB_FINAL_SETTLE_SECONDS = 0.055
TAB_PRIVATE_SETTLE_SECONDS = 0.16

_state_lock = threading.RLock()
_configuration_epoch = 0
_last_successful_epoch = -1
_warmup_required = True
_first_field_anchors = {}

_original_set_active = config.set_active
_original_write_form = fast._write_form_fast


def _target_key(target):
    return (
        int(target.get("pid") or 0),
        str(target.get("title") or "").strip().casefold(),
    )


def _window_is_valid(hwnd):
    if os.name != "nt" or not hwnd:
        return False
    try:
        return bool(ctypes.windll.user32.IsWindow(ctypes.c_void_p(hwnd)))
    except Exception:
        return False


def _focus_signature(target):
    """Obtiene control, caret y posición para detectar un cambio real de campo."""
    if os.name != "nt":
        return None

    try:
        foreground = reader._foreground_window()
        if not foreground:
            return None
        if reader._window_process_id(foreground) != int(target.get("pid") or 0):
            return None

        user32 = ctypes.windll.user32
        thread_id = user32.GetWindowThreadProcessId(
            ctypes.c_void_p(foreground),
            None,
        )
        if not thread_id:
            return None

        info = guard.GUITHREADINFO()
        info.cbSize = ctypes.sizeof(guard.GUITHREADINFO)
        if not user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
            return None

        focus = int(info.hwndFocus or 0)
        caret = int(info.hwndCaret or 0)
        rect = info.rcCaret
        signature = (
            focus,
            caret,
            int(rect.left),
            int(rect.top),
            int(rect.right),
            int(rect.bottom),
        )
        return signature if focus or caret else None
    except Exception:
        return None


def _wait_for_stable_focus(target):
    deadline = time.monotonic() + FOCUS_STABLE_TIMEOUT
    stable_signature = None
    stable_since = 0.0

    while not session.STOP.is_set() and time.monotonic() < deadline:
        if not reader._ensure_target_focus(target):
            return False

        current = _focus_signature(target)
        if current is None:
            # Lenel también puede usar controles privados. En ese caso basta con
            # conservar la ventana y realizar un asentamiento corto.
            return not session.STOP.wait(FOCUS_STABLE_SECONDS)

        if current == stable_signature:
            if time.monotonic() - stable_since >= FOCUS_STABLE_SECONDS:
                return True
        else:
            stable_signature = current
            stable_since = time.monotonic()

        if session.STOP.wait(FOCUS_POLL_SECONDS):
            return False

    return stable_signature is not None


def _remember_first_field_anchor(target):
    control = guard._focused_control(target)
    if not control:
        return False
    if reader._window_process_id(control) != int(target.get("pid") or 0):
        return False

    with _state_lock:
        _first_field_anchors[_target_key(target)] = int(control)
    return True


def _restore_first_field_anchor(target):
    key = _target_key(target)
    with _state_lock:
        control = int(_first_field_anchors.get(key) or 0)

    if not control or not _window_is_valid(control):
        return False
    if reader._window_process_id(control) != int(target.get("pid") or 0):
        return False

    if not guard._focus_child_control(target, control):
        return False

    session.log("🎯 Foco restaurado al primer campo guardado de Lenel.")
    return not session.STOP.wait(0.07)


def _mark_configuration_change(name):
    global _configuration_epoch, _warmup_required

    with _state_lock:
        _configuration_epoch += 1
        _warmup_required = True
        epoch = _configuration_epoch

    # La cola no debe seguir usando la referencia de ventana de una pasada
    # anterior después de cambiar de configuración.
    try:
        queue_guard._last_target_pid = 0
        queue_guard._last_completed_at = 0.0
    except Exception:
        pass

    try:
        reader._release_modifier_keys()
    except Exception:
        pass

    session.log(
        f"🔄 Estado de escritura reiniciado por cambio de configuración: "
        f"{name} (generación {epoch})."
    )


def _set_active_with_runtime_reset(name):
    result = _original_set_active(name)
    _mark_configuration_change(name)
    return result


_set_active_with_runtime_reset._dms_lenel_state_wrapper = True
if not getattr(config.set_active, "_dms_lenel_state_wrapper", False):
    config.set_active = _set_active_with_runtime_reset


def _send_tab_key():
    try:
        fast.core.pyautogui.keyDown("tab")
        if session.STOP.wait(TAB_KEY_HOLD_SECONDS):
            return False
    finally:
        try:
            fast.core.pyautogui.keyUp("tab")
        except Exception:
            pass
    return True


def _press_tab_confirmed(target, settle_seconds):
    """Avanza un campo y espera la transición antes de permitir otra escritura."""
    if not reader._ensure_target_focus(target):
        return False

    reader._release_modifier_keys()
    before = _focus_signature(target)
    before_control = guard._focused_control(target)
    before_class = guard._control_class(before_control)
    observable_text_control = bool(
        before_control and guard._looks_like_text_control(before_class)
    )

    if not _send_tab_key():
        return False

    if before is None:
        return not session.STOP.wait(
            max(TAB_PRIVATE_SETTLE_SECONDS, float(settle_seconds or 0.0))
        )

    deadline = time.monotonic() + TAB_TRANSITION_TIMEOUT
    while not session.STOP.is_set() and time.monotonic() < deadline:
        current = _focus_signature(target)
        if current is not None and current != before:
            return not session.STOP.wait(
                max(TAB_FINAL_SETTLE_SECONDS, float(settle_seconds or 0.0))
            )
        if session.STOP.wait(TAB_TRANSITION_POLL_SECONDS):
            return False

    # Si Windows identifica claramente un cuadro de texto y el foco no cambió,
    # Lenel ignoró el primer Tab. Se permite un único segundo envío controlado.
    if observable_text_control:
        session.log("🔁 Lenel no procesó el primer Tab; reintentando una vez.")
        if not _send_tab_key():
            return False

        retry_deadline = time.monotonic() + TAB_TRANSITION_TIMEOUT
        while not session.STOP.is_set() and time.monotonic() < retry_deadline:
            current = _focus_signature(target)
            if current is not None and current != before:
                return not session.STOP.wait(
                    max(TAB_FINAL_SETTLE_SECONDS, float(settle_seconds or 0.0))
                )
            if session.STOP.wait(TAB_TRANSITION_POLL_SECONDS):
                return False

        session.log(
            "⚠️ No fue posible confirmar el cambio de campo después del Tab."
        )
        return False

    # En controles privados no se reenvía Tab para evitar saltar dos campos.
    return not session.STOP.wait(
        max(TAB_PRIVATE_SETTLE_SECONDS, float(settle_seconds or 0.0))
    )


def _state_snapshot():
    with _state_lock:
        return _configuration_epoch, _warmup_required


def _mark_write_result(epoch, completed):
    global _last_successful_epoch, _warmup_required

    with _state_lock:
        if completed and epoch == _configuration_epoch:
            _last_successful_epoch = epoch
            _warmup_required = False
        else:
            _warmup_required = True


def _write_form_with_state_reset(data, configuration):
    epoch, needs_warmup = _state_snapshot()
    target = reader._capture_target_window()

    anchor_restored = _restore_first_field_anchor(target)

    if needs_warmup:
        wait_seconds = (
            STARTUP_WARMUP_SECONDS
            if epoch == 0
            else CONFIG_WARMUP_SECONDS
        )
        session.log(
            f"⏳ Preparando Lenel durante {wait_seconds:.2f}s antes de escribir."
        )
        if session.STOP.wait(wait_seconds):
            return False

    if not anchor_restored:
        if not _wait_for_stable_focus(target):
            session.log("⚠️ El primer campo de Lenel no llegó a estabilizarse.")
            _mark_write_result(epoch, False)
            return False
        _remember_first_field_anchor(target)

    completed = _original_write_form(data, configuration)
    _mark_write_result(epoch, completed)
    return completed


# El escritor rápido resuelve estas funciones globales en tiempo de ejecución.
fast._press_tab_with_settle = _press_tab_confirmed
fast._write_form_fast = _write_form_with_state_reset
guard.write_form_verified = _write_form_with_state_reset
reader.write_form = _write_form_with_state_reset
