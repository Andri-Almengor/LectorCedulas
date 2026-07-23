from __future__ import annotations

from assets.runtime.hardened.instance_control import MUTEX_NAME
from assets.runtime.hardened.runtime_state import SUPERVISOR_MUTEX_NAME
from tools import updater


def test_application_exit_waits_for_worker_then_supervisor(monkeypatch):
    calls: list[tuple[str, float]] = []

    def fake_wait(name: str, timeout: float) -> bool:
        calls.append((name, timeout))
        return True

    monkeypatch.setattr(updater, "_wait_for_named_mutex_release", fake_wait)

    assert updater._wait_for_application_exit(timeout=10.0)
    assert [name for name, _timeout in calls] == [
        MUTEX_NAME,
        SUPERVISOR_MUTEX_NAME,
    ]
    assert all(0.0 < timeout <= 10.0 for _name, timeout in calls)


def test_application_exit_fails_without_touching_second_mutex(monkeypatch):
    calls: list[str] = []

    def fake_wait(name: str, timeout: float) -> bool:
        calls.append(name)
        return False

    monkeypatch.setattr(updater, "_wait_for_named_mutex_release", fake_wait)

    assert not updater._wait_for_application_exit(timeout=1.0)
    assert calls == [MUTEX_NAME]


def test_runtime_activity_checks_both_process_mutexes(monkeypatch):
    seen: list[str] = []

    def fake_exists(name: str) -> bool:
        seen.append(name)
        return name == SUPERVISOR_MUTEX_NAME

    monkeypatch.setattr(updater, "_named_mutex_exists", fake_exists)

    active = updater._named_mutex_exists(MUTEX_NAME) or updater._named_mutex_exists(
        SUPERVISOR_MUTEX_NAME
    )
    assert active
    assert seen == [MUTEX_NAME, SUPERVISOR_MUTEX_NAME]


def test_named_mutex_wait_polls_until_object_disappears(monkeypatch):
    states = iter([True, True, False])
    sleeps: list[float] = []
    clock = {"value": 0.0}

    monkeypatch.setattr(updater.os, "name", "nt")
    monkeypatch.setattr(updater, "_named_mutex_exists", lambda _name: next(states))
    monkeypatch.setattr(updater.time, "monotonic", lambda: clock["value"])

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["value"] += seconds

    monkeypatch.setattr(updater.time, "sleep", fake_sleep)

    assert updater._wait_for_named_mutex_release("MUTEX", timeout=1.0)
    assert sleeps == [0.05, 0.05]


def test_named_mutex_wait_times_out_while_object_still_exists(monkeypatch):
    clock = {"value": 0.0}

    monkeypatch.setattr(updater.os, "name", "nt")
    monkeypatch.setattr(updater, "_named_mutex_exists", lambda _name: True)
    monkeypatch.setattr(updater.time, "monotonic", lambda: clock["value"])
    monkeypatch.setattr(
        updater.time,
        "sleep",
        lambda seconds: clock.__setitem__("value", clock["value"] + seconds),
    )

    assert not updater._wait_for_named_mutex_release("MUTEX", timeout=0.11)
