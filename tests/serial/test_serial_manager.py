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


class TimedSerial:
    def __init__(self, chunks):
        self.started = time.monotonic()
        self.chunks = list(chunks)
        self.closed = False

    @property
    def in_waiting(self):
        if self.closed:
            raise OSError("closed")
        if not self.chunks:
            return 0
        available_after, payload = self.chunks[0]
        if time.monotonic() - self.started >= available_after:
            return len(payload)
        return 0

    def read(self, size):
        _, payload = self.chunks.pop(0)
        return payload[:size]

    def close(self):
        self.closed = True


def make_manager(**overrides):
    options = {
        "list_ports": lambda: [],
        "open_port": lambda *args: FakeSerial([]),
        "submit_frame": lambda *args: True,
        "load_last_port": lambda: {},
        "save_last_port": lambda data: None,
    }
    options.update(overrides)
    return SerialManager(**options)


def test_fragmented_first_scan_is_submitted_not_lost():
    submitted = []
    saved = []
    serial = FakeSerial([b"1234", b"5678"])
    manager = SerialManager(
        list_ports=lambda: [
            SimpleNamespace(
                device="COM4",
                vid=1,
                pid=2,
                serial_number="S",
                manufacturer="M",
                description="Reader",
            )
        ],
        open_port=lambda *args: serial,
        submit_frame=lambda raw, context, identity: submitted.append(
            (raw, context, identity)
        )
        or True,
        capture_context=lambda: "TARGET",
        load_last_port=lambda: {},
        save_last_port=saved.append,
        idle_seconds=0.01,
        settle_seconds=0.01,
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


def test_late_fragment_inside_settle_window_is_merged():
    logs = []
    serial = TimedSerial([(0.0, b"1234"), (0.03, b"5678")])
    manager = make_manager(
        capture_context=lambda: "TARGET_AT_FIRST_BYTE",
        logger=logs.append,
        idle_seconds=0.01,
        settle_seconds=0.05,
        frame_timeout=0.2,
    )
    raw = manager._read_frame(serial)
    assert raw == b"12345678"
    assert manager.metrics.late_fragment_extensions == 1
    assert manager._pending_context == "TARGET_AT_FIRST_BYTE"
    assert any(item.startswith("serial_late_fragment:") for item in logs)


def test_device_selection_uses_usb_identity_not_only_com_name():
    ports = [
        SimpleNamespace(
            device="COM3",
            vid=9,
            pid=9,
            serial_number="OTHER",
            manufacturer="X",
            description="X",
        ),
        SimpleNamespace(
            device="COM8",
            vid=1,
            pid=2,
            serial_number="MATCH",
            manufacturer="DMS",
            description="QR",
        ),
    ]
    manager = make_manager(
        list_ports=lambda: ports,
        load_last_port=lambda: {
            "device": "COM4",
            "vid": 1,
            "pid": 2,
            "serial_number": "MATCH",
        },
    )
    assert manager._candidates()[0].device == "COM8"


def test_reconnect_state_after_disconnect():
    states = []
    attempts = {"count": 0}

    def open_port(*args):
        attempts["count"] += 1
        return FakeSerial([], disconnect=True)

    manager = make_manager(
        list_ports=lambda: [SimpleNamespace(device="COM4")],
        open_port=open_port,
        state_callback=lambda state, detail: states.append(state),
        frame_timeout=0.5,
    )
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
    manager = make_manager(logger=logs.append)
    manager._active_serial = serial
    manager.stop()
    assert any("serial_close_error:stop:OSError" in item for item in logs)
    manager.stop_event.clear()
    manager._active_serial = serial
    manager.reconnect_now()
    assert any("serial_close_error:reconnect:OSError" in item for item in logs)


def test_serial_manager_rejects_invalid_stabilization_configuration():
    try:
        make_manager(idle_seconds=0.2, settle_seconds=0.2, frame_timeout=0.3)
    except ValueError as exc:
        assert "frame_timeout" in str(exc)
    else:
        raise AssertionError("Debió rechazar una ventana mayor que frame_timeout")
