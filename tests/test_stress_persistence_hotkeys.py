from __future__ import annotations

import threading
from types import SimpleNamespace

from assets.runtime.hardened.global_hotkeys import GlobalHotkeyService
from assets.runtime.hardened.models import ReaderState
from assets.runtime.hardened.production_app import ProductionDesktopApplication
from assets.runtime.hardened.stress_safe_writer import StressSafeFormWriter
from assets.runtime.hardened.writer import ControlProbe, PROFILES


class FakeWindows:
    def validate_exact(self, target, require_foreground=True):
        return True, "ok"


class FakeInput:
    def __init__(self):
        self.writes = []
        self.hotkeys = []
        self.presses = []
        self.released = []

    def press(self, key):
        self.presses.append(key)

    def hotkey(self, *keys):
        self.hotkeys.append(keys)

    def key_down(self, key):
        return None

    def key_up(self, key):
        self.released.append(key)

    def write(self, text, interval):
        self.writes.append((text, interval))


class FakeClipboard:
    def __init__(self, succeeds=True, can_modify=True):
        self.succeeds = succeeds
        self.can_modify = can_modify
        self.values = []

    def set_text(self, value):
        self.values.append(value)
        return self.succeeds


class FakeThread:
    def __init__(self, alive):
        self.alive = alive

    def is_alive(self):
        return self.alive


class FakeQueue:
    def __init__(self, alive=False):
        self._worker = FakeThread(alive)
        self._stop = threading.Event()
        self.starts = 0

    def start(self):
        self.starts += 1
        self._worker = FakeThread(True)


class FakeSerial:
    def __init__(self, alive=False):
        self._thread = FakeThread(alive)
        self.stop_calls = 0
        self.start_calls = 0
        self.reconnect_calls = 0

    def stop(self):
        self.stop_calls += 1

    def start(self):
        self.start_calls += 1
        self._thread = FakeThread(True)

    def reconnect_now(self):
        self.reconnect_calls += 1


def _job():
    return SimpleNamespace(target=object())


def _writer(probe, adapter):
    writer = StressSafeFormWriter(
        windows=FakeWindows(),
        input_adapter=adapter,
        control_probe=probe,
    )
    writer._sleep = lambda _seconds, _cancel: True
    return writer


def test_modern_control_prefers_atomic_clipboard_paste():
    adapter = FakeInput()
    clipboard = FakeClipboard(succeeds=True)
    writer = _writer(
        lambda _job: ControlProbe(False, class_name="XamlTextControl"),
        adapter,
    )

    result = writer._paste(
        "ALMENGOR QUIROS",
        _job(),
        PROFILES["rapida"],
        threading.Event(),
        clipboard,
        replace=False,
    )

    assert result
    assert clipboard.values == ["ALMENGOR QUIROS"]
    assert ("ctrl", "v") in adapter.hotkeys
    assert adapter.writes == []


def test_clipboard_failure_uses_paced_unicode_fallback():
    adapter = FakeInput()
    writer = _writer(
        lambda _job: ControlProbe(False, class_name="XamlTextControl"),
        adapter,
    )

    result = writer._paste(
        "ANDRICK IVAN",
        _job(),
        PROFILES["rapida"],
        threading.Event(),
        FakeClipboard(succeeds=False),
        replace=False,
    )

    assert result
    assert adapter.writes[0][0] == "ANDRICK IVAN"
    assert adapter.writes[0][1] >= 0.007


def test_global_hotkey_dispatches_favorites_and_emergency():
    actions = []
    service = GlobalHotkeyService(
        toggle_favorites=lambda: actions.append("favorites"),
        cancel_current=lambda: actions.append("emergency"),
    )

    service.dispatch(service.FAVORITES_ID)
    service.dispatch(service.EMERGENCY_ID)

    assert actions == ["favorites", "emergency"]


def test_supervisor_restarts_dead_queue_and_serial_manager():
    app = ProductionDesktopApplication.__new__(ProductionDesktopApplication)
    app.stop_event = threading.Event()
    app.queue = FakeQueue(alive=False)
    old_serial = FakeSerial(alive=False)
    new_serial = FakeSerial(alive=False)
    app.serial = old_serial
    app.reader_state = ReaderState.READY
    app.last_error = "Sin errores"
    app._last_reader_state_at = 0.0
    app._last_watchdog_reconnect_at = 0.0
    messages = []
    app._log = messages.append
    app._build_serial_manager = lambda: new_serial

    app._supervise_once(now=100.0)

    assert app.queue.starts == 1
    assert old_serial.stop_calls == 1
    assert app.serial is new_serial
    assert new_serial.start_calls == 1
    assert "watchdog_restart:queue" in messages
    assert "watchdog_restart:serial" in messages


def test_supervisor_reconnects_stuck_serial_reader():
    app = ProductionDesktopApplication.__new__(ProductionDesktopApplication)
    app.stop_event = threading.Event()
    app.queue = FakeQueue(alive=True)
    app.serial = FakeSerial(alive=True)
    app.reader_state = ReaderState.READING
    app.last_error = "Sin errores"
    app._last_reader_state_at = 0.0
    app._last_watchdog_reconnect_at = 0.0
    app._log = lambda _message: None

    app._supervise_once(now=20.0)

    assert app.serial.reconnect_calls == 1
    assert app._last_watchdog_reconnect_at == 20.0
