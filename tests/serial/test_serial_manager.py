from __future__ import annotations

import time
from types import SimpleNamespace

from assets.runtime.hardened.models import ReaderState
from assets.runtime.hardened.serial_manager import SerialManager


class FakeSerial:
    def __init__(self, chunks, disconnect=False):
        self.chunks = list(chunks)
        self.closed = False
        self.disconnect = disconnect

    @property
    def in_waiting(self):
        if self.closed:
            raise OSError("closed")
        if self.disconnect and not self.chunks:
            raise OSError("usb disconnected")
        return len(self.chunks[0]) if self.chunks else 0

    def read(self, size):
        return self.chunks.pop(0)

    def close(self):
        self.closed = True


def test_fragmented_first_scan_is_submitted_not_lost():
    submitted = []
    saved = []
    serial = FakeSerial([b"1234", b"5678"])
    manager = SerialManager(
        list_ports=lambda: [SimpleNamespace(device="COM4", vid=1, pid=2, serial_number="S", manufacturer="M", description="Reader")],
        open_port=lambda *args: serial,
        submit_frame=lambda raw, context, identity: submitted.append((raw, context, identity)) or True,
        capture_context=lambda: "TARGET",
        load_last_port=lambda: {},
        save_last_port=saved.append,
        idle_seconds=0.01,
        frame_timeout=0.1,
    )
    identity = manager._candidates()[0]
    raw = manager._read_frame(serial)
    assert raw == b"12345678"
    assert manager._process_frame(raw, identity)
    assert submitted[0][0] == raw
    assert submitted[0][1] == "TARGET"
    manager.confirm_accepted(identity)
    assert saved[0]["device"] == "COM4"


def test_device_selection_uses_usb_identity_not_only_com_name():
    ports = [
        SimpleNamespace(device="COM3", vid=9, pid=9, serial_number="OTHER", manufacturer="X", description="X"),
        SimpleNamespace(device="COM8", vid=1, pid=2, serial_number="MATCH", manufacturer="DMS", description="QR"),
    ]
    manager = SerialManager(list_ports=lambda: ports, open_port=lambda *args: FakeSerial([]), submit_frame=lambda *args: True, load_last_port=lambda: {"device": "COM4", "vid": 1, "pid": 2, "serial_number": "MATCH"}, save_last_port=lambda data: None)
    assert manager._candidates()[0].device == "COM8"


def test_reconnect_state_after_disconnect():
    states = []
    attempts = {"count": 0}

    def open_port(*args):
        attempts["count"] += 1
        return FakeSerial([], disconnect=True)

    manager = SerialManager(list_ports=lambda: [SimpleNamespace(device="COM4")], open_port=open_port, submit_frame=lambda *args: True, load_last_port=lambda: {}, save_last_port=lambda data: None, state_callback=lambda state, detail: states.append(state), frame_timeout=0.02)
    manager.start()
    time.sleep(0.15)
    manager.stop()
    assert ReaderState.RECONNECTING in states
    assert attempts["count"] >= 1


class CloseFailSerial(FakeSerial):
    def close(self):
        raise OSError("cannot close")


def test_close_failures_are_logged_not_silenced():
    logs = []
    serial = CloseFailSerial([])
    manager = SerialManager(list_ports=lambda: [], open_port=lambda *args: serial, submit_frame=lambda *args: True, load_last_port=lambda: {}, save_last_port=lambda data: None, logger=logs.append)
    manager._active_serial = serial
    manager.stop()
    assert any("serial_close_error:stop:OSError" in item for item in logs)
    manager.stop_event.clear()
    manager._active_serial = serial
    manager.reconnect_now()
    assert any("serial_close_error:reconnect:OSError" in item for item in logs)
