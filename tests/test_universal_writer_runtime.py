import importlib.util
import os
import sys
import threading
import time
import types
from pathlib import Path


class FakeStop:
    def is_set(self):
        return False

    def wait(self, seconds):
        time.sleep(min(float(seconds), 0.002))
        return False


class FakePyAutoGui:
    def __init__(self):
        self.events = []
        self.PAUSE = 0.0

    def press(self, key):
        self.events.append(("press", key))

    def hotkey(self, *keys):
        self.events.append(("hotkey", keys))

    def keyDown(self, key):
        self.events.append(("down", key))

    def keyUp(self, key):
        self.events.append(("up", key))


def load_guard():
    logs = []
    pyautogui = FakePyAutoGui()

    config = types.ModuleType("assets.runtime.dms_config_runtime")
    config.set_active = lambda name: name

    reader = types.ModuleType("assets.runtime.dms_reader_runtime")
    reader._write_lock = threading.Lock()
    reader._capture_target_window = lambda: {
        "pid": os.getpid() + 1000,
        "hwnd": 10,
        "title": "Formulario de prueba",
    }
    reader._foreground_window = lambda: 10
    reader._window_process_id = lambda hwnd: os.getpid() + 1000
    reader._ensure_target_focus = lambda target: True
    reader._release_modifier_keys = lambda: None
    reader._prepare_verified_clipboard = lambda text: True

    queue_guard = types.ModuleType("assets.runtime.dms_scan_queue_guard")
    queue_guard._last_target_pid = 123
    queue_guard._last_completed_at = 456

    session = types.ModuleType("assets.runtime.dms_session_runtime")
    session.STOP = FakeStop()
    session.log = logs.append

    core = types.ModuleType("assets.runtime.lector_core")
    core.pyautogui = pyautogui
    core.safe_write = lambda value: pyautogui.events.append(("write", value))

    assets = types.ModuleType("assets")
    assets.__path__ = []
    runtime = types.ModuleType("assets.runtime")
    runtime.__path__ = []

    modules = {
        "assets": assets,
        "assets.runtime": runtime,
        "assets.runtime.dms_config_runtime": config,
        "assets.runtime.dms_reader_runtime": reader,
        "assets.runtime.dms_scan_queue_guard": queue_guard,
        "assets.runtime.dms_session_runtime": session,
        "assets.runtime.lector_core": core,
    }
    previous = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)

    module_path = (
        Path(__file__).resolve().parents[1]
        / "template"
        / "assets"
        / "runtime"
        / "dms_universal_form_guard.py"
    )
    spec = importlib.util.spec_from_file_location(
        "assets.runtime.dms_universal_form_guard",
        module_path,
    )
    guard = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = guard
    spec.loader.exec_module(guard)

    return guard, reader, queue_guard, pyautogui, logs, previous


def test_profile_aliases_and_defaults():
    guard, _, _, _, _, _ = load_guard()
    assert guard._profile_from({})["name"] == "rapida"
    assert guard._profile_from({"perfil_escritura": "Equilibrada"})["name"] == "equilibrada"
    assert (
        guard._profile_from({"velocidad_escritura": "Máxima compatibilidad"})["name"]
        == "segura"
    )


def test_multi_field_navigation_is_deterministic():
    guard, _, _, pyautogui, _, _ = load_guard()
    completed = guard.write_form_universal(
        {"Nombre": "ANA", "Cedula": "123"},
        {
            "perfil_escritura": "rapida",
            "validar_escritura": False,
            "campos": [
                {"dato": "Nombre", "tabuladores": 0},
                {"dato": "Cedula", "tabuladores": 1},
            ],
        },
    )
    assert completed is True
    assert pyautogui.events.count(("press", "v")) == 2
    # Tab final de Nombre + Tab configurado de Cédula + Tab final de Cédula.
    assert pyautogui.events.count(("press", "tab")) == 3


def test_single_field_quick_configuration_does_not_restore_an_old_anchor():
    guard, _, _, pyautogui, _, _ = load_guard()
    completed = guard.write_form_universal(
        {"Cedula": "123"},
        {
            "perfil_escritura": "rapida",
            "validar_escritura": False,
            "campos": [{"dato": "Cedula", "tabuladores": 4}],
        },
    )
    assert completed is True
    # Se respetan exactamente 4 tabs previos y 1 tab final. No hay salto al
    # primer campo guardado por otra configuración.
    assert pyautogui.events.count(("press", "tab")) == 5


def test_configuration_change_resets_only_queue_target_state():
    guard, _, queue_guard, _, _, _ = load_guard()
    guard.reset_runtime_state("prueba")
    assert queue_guard._last_target_pid == 0
    assert queue_guard._last_completed_at == 0.0
