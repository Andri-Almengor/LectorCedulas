from __future__ import annotations

import threading
from datetime import datetime, timezone

from assets.runtime.hardened.models import EmptyPolicy, FieldAction, FinalAction, ScanJob, TargetWindow, ValidationType
from assets.runtime.hardened.writer import ControlProbe, FormWriter


class FakeWindows:
    def __init__(self):
        self.target = None
        self.valid = True
        self.wait_calls = []
        self.validation_calls = []

    def wait_until_exact_foreground(self, target, timeout, cancel, allow_activate=True):
        self.wait_calls.append(target)
        return (self.valid, "ok" if self.valid else "hwnd_no_existe")

    def validate_exact(self, target, require_foreground=False):
        self.validation_calls.append((target, require_foreground))
        return (self.valid, "ok" if self.valid else "hwnd_no_existe")


class FakeInput:
    def __init__(self):
        self.events = []

    def press(self, key): self.events.append(("press", key))
    def hotkey(self, *keys): self.events.append(("hotkey", keys))
    def key_down(self, key): self.events.append(("down", key))
    def key_up(self, key): self.events.append(("up", key))
    def write(self, text, interval): self.events.append(("write", text))


class ClipboardState:
    def __init__(self, value="ORIGINAL"):
        self.value = value


class FakeClipboard:
    def __init__(self, state):
        self.state = state
        self.saved = None

    def __enter__(self):
        self.saved = self.state.value
        return self

    def __exit__(self, *args):
        self.state.value = self.saved

    def set_text(self, text):
        self.state.value = text
        return True


def make_job(fields, data=None, final_action=FinalAction.NONE):
    return ScanJob(
        sequence_id=1,
        created_at_utc=datetime.now(timezone.utc),
        raw_sha256="a" * 64,
        data=data or {"Cedula": "123456789", "Nombre": "ANA"},
        configuration_id="cfg",
        configuration_name="Config",
        configuration_version=2,
        configuration_generation=1,
        write_profile="rapida",
        target=TargetWindow(hwnd=101, pid=202, root_hwnd=101, title="Form"),
        fields=tuple(fields),
        final_action=final_action,
    )


def build_writer(probes=None):
    windows = FakeWindows()
    inputs = FakeInput()
    clipboard = ClipboardState()
    sequence = iter(probes or [ControlProbe(False)])
    last = [ControlProbe(False)]

    def probe(job):
        try:
            last[0] = next(sequence)
        except StopIteration:
            pass
        return last[0]

    writer = FormWriter(windows=windows, input_adapter=inputs, clipboard_factory=lambda: FakeClipboard(clipboard), control_probe=probe)
    return writer, windows, inputs, clipboard


def test_writer_uses_exact_job_target_and_restores_clipboard():
    writer, windows, inputs, clipboard = build_writer()
    job = make_job([FieldAction("Cedula", action_after=FinalAction.NONE)])
    result = writer.write(job, threading.Event())
    assert result.success
    assert all(call[0] == job.target for call in windows.validation_calls)
    assert windows.wait_calls == [job.target]
    assert clipboard.value == "ORIGINAL"
    assert ("hotkey", ("ctrl", "v")) in inputs.events


def test_unreadable_control_never_uses_ctrl_a():
    writer, _, inputs, _ = build_writer([ControlProbe(False)])
    field = FieldAction("Cedula", replace_existing=True, action_after=FinalAction.NONE)
    result = writer.write(make_job([field]), threading.Event())
    assert not result.success
    assert ("hotkey", ("ctrl", "a")) not in inputs.events


def test_validation_failure_does_not_advance():
    probes = [ControlProbe(True, ""), ControlProbe(True, "incorrecto"), ControlProbe(True, "incorrecto"), ControlProbe(True, "incorrecto")]
    writer, _, inputs, _ = build_writer(probes)
    field = FieldAction("Nombre", validation=ValidationType.STRICT_TEXT, action_after=FinalAction.TAB)
    result = writer.write(make_job([field]), threading.Event())
    assert not result.success
    assert ("press", "tab") not in inputs.events


def test_accents_and_hyphens_are_not_collapsed_as_equal():
    writer, *_ = build_writer()
    action = FieldAction("Nombre", validation=ValidationType.NAME)
    assert writer._validate_value("MUÑOZ", "MUNOZ", action) is False
    assert writer._validate_value("ANA-MARÍA", "ANA MARIA", action) is False


def test_empty_policies():
    for policy, expected_success in [(EmptyPolicy.PRESERVE, True), (EmptyPolicy.DEFAULT, True), (EmptyPolicy.CANCEL, False)]:
        writer, _, _, _ = build_writer()
        field = FieldAction("Nombre", empty_policy=policy, default_value="DESCONOCIDO", action_after=FinalAction.NONE)
        result = writer.write(make_job([field], data={"Nombre": ""}), threading.Event())
        assert result.success is expected_success


def test_final_action_is_configurable():
    writer, _, inputs, _ = build_writer()
    result = writer.write(make_job([FieldAction("Cedula", action_after=FinalAction.TAB)], final_action=FinalAction.ENTER), threading.Event())
    assert result.success
    assert ("press", "enter") in inputs.events
    assert ("press", "tab") not in inputs.events
