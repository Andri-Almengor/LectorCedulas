from __future__ import annotations

import threading
from types import SimpleNamespace

from assets.runtime.hardened.reliable_app import ReliableDesktopApplication
from assets.runtime.hardened.reliable_writer import ReliableFormWriter
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


class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(message)


def _job():
    return SimpleNamespace(target=object())


def test_modern_control_uses_unicode_delivery():
    adapter = FakeInput()
    writer = ReliableFormWriter(
        windows=FakeWindows(),
        input_adapter=adapter,
        control_probe=lambda _job: ControlProbe(False, class_name="XamlTextControl"),
    )
    result = writer._paste(
        "ANDRICK",
        _job(),
        PROFILES["rapida"],
        threading.Event(),
        FakeClipboard(),
        replace=False,
    )
    assert result
    assert adapter.writes[0][0] == "ANDRICK"
    assert ("ctrl", "v") not in adapter.hotkeys


def test_classic_control_uses_clipboard():
    adapter = FakeInput()
    clipboard = FakeClipboard(succeeds=True)
    writer = ReliableFormWriter(
        windows=FakeWindows(),
        input_adapter=adapter,
        control_probe=lambda _job: ControlProbe(True, class_name="WindowsForms10.EDIT"),
    )
    result = writer._paste(
        "123456789",
        _job(),
        PROFILES["rapida"],
        threading.Event(),
        clipboard,
        replace=False,
    )
    assert result
    assert clipboard.values == ["123456789"]
    assert ("ctrl", "v") in adapter.hotkeys
    assert adapter.writes == []


def test_clipboard_failure_uses_unicode_delivery():
    adapter = FakeInput()
    writer = ReliableFormWriter(
        windows=FakeWindows(),
        input_adapter=adapter,
        control_probe=lambda _job: ControlProbe(True, class_name="Edit"),
    )
    result = writer._paste(
        "MARÍA JOSÉ",
        _job(),
        PROFILES["equilibrada"],
        threading.Event(),
        FakeClipboard(succeeds=False),
        replace=False,
    )
    assert result
    assert adapter.writes[0][0] == "MARÍA JOSÉ"


def test_replace_works_for_modern_control():
    adapter = FakeInput()
    writer = ReliableFormWriter(
        windows=FakeWindows(),
        input_adapter=adapter,
        control_probe=lambda _job: ControlProbe(False, class_name="XamlTextControl"),
    )
    result = writer._paste(
        "NUEVO",
        _job(),
        PROFILES["rapida"],
        threading.Event(),
        FakeClipboard(),
        replace=True,
    )
    assert result
    assert adapter.hotkeys[0] == ("ctrl", "a")
    assert adapter.presses == ["backspace"]
    assert adapter.writes[0][0] == "NUEVO"


def test_queue_failure_updates_last_error():
    app = ReliableDesktopApplication.__new__(ReliableDesktopApplication)
    app.last_error = "Sin errores"
    app.logger = FakeLogger()
    app._log("queue_failed:7:validation_failed")
    assert app.last_error == "Escritura fallida: validation_failed"
    assert app.logger.messages == ["queue_failed:7:validation_failed"]
