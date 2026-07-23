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
