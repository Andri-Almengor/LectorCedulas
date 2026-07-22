from assets.runtime import dms_reader_runtime as reader
from assets.runtime import dms_scan_queue_guard as queue_guard
from assets.runtime import dms_universal_form_guard as universal
from assets.runtime import lector_core as core


SPEED_RUNTIME = {
    "rapida": {
        "pyautogui_pause": 0.008,
        "queue_rearm": 0.30,
    },
    "equilibrada": {
        "pyautogui_pause": 0.014,
        "queue_rearm": 0.55,
    },
    "segura": {
        "pyautogui_pause": 0.025,
        "queue_rearm": 0.90,
    },
}

_original_write_form = reader.write_form


def write_form_with_runtime_speed(data, configuration):
    profile = universal._profile_from(configuration)
    settings = SPEED_RUNTIME.get(profile.get("name"), SPEED_RUNTIME["rapida"])

    # template/main.py conserva pausas antiguas para el escritor base. El perfil
    # de la configuración manda aquí para evitar sumar demoras invisibles.
    core.pyautogui.PAUSE = settings["pyautogui_pause"]
    queue_guard.FORM_REARM_SECONDS = settings["queue_rearm"]
    return _original_write_form(data, configuration)


# La cola ya espera una ventana válida; esta pausa corta elimina latencia sin
# volver a introducir anclas de campo ni estado específico de Lenel.
queue_guard.TARGET_STABLE_SECONDS = 0.08
queue_guard.TARGET_CHECK_SECONDS = 0.02
reader.write_form = write_form_with_runtime_speed
