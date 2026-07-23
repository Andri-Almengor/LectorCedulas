from __future__ import annotations

import threading
from datetime import datetime, timezone

from assets.runtime.hardened.models import (
    FinalAction,
    ScanJob,
    TargetWindow,
    WriteResult,
)
from assets.runtime.hardened.single_scan_app import (
    SingleScanAdmission,
    _CooldownWriter,
    _SingleCycleQueue,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class SuccessfulWriter:
    def __init__(self) -> None:
        self.calls = 0

    def write(self, job, cancel_event):
        self.calls += 1
        return WriteResult(True, "completed", 0, 0, 0, 1)


def make_job(sequence_id: int = 1) -> ScanJob:
    return ScanJob(
        sequence_id=sequence_id,
        created_at_utc=datetime.now(timezone.utc),
        raw_sha256=f"{sequence_id:064x}",
        data={"Cedula": "119320121"},
        configuration_id="cfg",
        configuration_name="Config",
        configuration_version=2,
        configuration_generation=1,
        write_profile="rapida",
        target=TargetWindow(10, 20, 10),
        fields=(),
        final_action=FinalAction.NONE,
    )


def test_only_one_scan_can_hold_the_cycle() -> None:
    clock = FakeClock()
    admission = SingleScanAdmission(2.0, clock=clock)

    assert admission.try_reserve() == (True, "accepted", 0.0)
    accepted, reason, _remaining = admission.try_reserve()
    assert not accepted
    assert reason == "busy"

    assert admission.release_unhanded()
    assert admission.try_reserve() == (True, "accepted", 0.0)


def test_written_cycle_requires_two_second_rescan_window() -> None:
    clock = FakeClock()
    admission = SingleScanAdmission(2.0, clock=clock)
    assert admission.try_reserve()[0]
    admission.mark_handed_to_queue()

    writer = SuccessfulWriter()
    protected = _CooldownWriter(writer, admission, lambda _message: None)
    protected.write(make_job(), threading.Event())

    assert writer.calls == 1
    accepted, reason, remaining = admission.try_reserve()
    assert not accepted
    assert reason == "cooldown"
    assert remaining == 2.0

    clock.advance(1.99)
    assert admission.try_reserve()[1] == "cooldown"
    clock.advance(0.02)
    assert admission.try_reserve() == (True, "accepted", 0.0)


def test_scans_rejected_before_queue_do_not_start_cooldown() -> None:
    clock = FakeClock()
    admission = SingleScanAdmission(2.0, clock=clock)
    assert admission.try_reserve()[0]

    assert admission.release_unhanded()
    assert admission.status().cooldown_remaining == 0.0
    assert admission.try_reserve() == (True, "accepted", 0.0)


def test_clearing_pending_job_releases_cycle_without_replaying_it() -> None:
    clock = FakeClock()
    admission = SingleScanAdmission(2.0, clock=clock)
    assert admission.try_reserve()[0]
    admission.mark_handed_to_queue()

    scan_queue = _SingleCycleQueue(
        admission=admission,
        writer=SuccessfulWriter(),
        capacity=1,
    )
    scan_queue.submit(make_job())

    assert scan_queue.clear_pending("prueba") == 1
    status = admission.status()
    assert not status.reserved
    assert status.cooldown_remaining == 0.0
    assert scan_queue.status().queued == 0


def test_queue_capacity_is_one_pending_job() -> None:
    admission = SingleScanAdmission(2.0)
    scan_queue = _SingleCycleQueue(
        admission=admission,
        writer=SuccessfulWriter(),
        capacity=1,
    )

    scan_queue.submit(make_job(1))
    assert scan_queue.status().queued == 1
