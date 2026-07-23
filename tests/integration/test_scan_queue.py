from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

import pytest

from assets.runtime.hardened.models import FinalAction, ScanJob, TargetWindow, WriteResult
from assets.runtime.hardened.scan_queue import QueueFullError, ScanQueue


class Writer:
    def __init__(self, block=False):
        self.jobs = []
        self.block = block
        self.started = threading.Event()
        self.release = threading.Event()

    def write(self, job, cancel):
        self.jobs.append(job)
        self.started.set()
        while self.block and not self.release.is_set() and not cancel.wait(0.01):
            pass
        if cancel.is_set():
            return WriteResult(False, "cancelled", 0, 0, 0, 1, "cancelled")
        return WriteResult(True, "completed", 0, 0, 0, 1)


def job(seq, generation=1):
    return ScanJob(
        sequence_id=seq,
        created_at_utc=datetime.now(timezone.utc),
        raw_sha256=f"{seq:064x}",
        data={},
        configuration_id="cfg",
        configuration_name="Config",
        configuration_version=2,
        configuration_generation=generation,
        write_profile="rapida",
        target=TargetWindow(10, 20, 10),
        fields=(),
        final_action=FinalAction.NONE,
    )


def wait_until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_queue_processes_100_jobs_without_reordering():
    writer = Writer()
    scan_queue = ScanQueue(writer=writer, capacity=128)
    scan_queue.start()
    for i in range(1, 101):
        scan_queue.submit(job(i))
    assert wait_until(lambda: scan_queue.status().completed == 100)
    assert [item.sequence_id for item in writer.jobs] == list(range(1, 101))
    scan_queue.stop()


def test_queue_full_is_nonblocking_backpressure():
    scan_queue = ScanQueue(writer=Writer(), capacity=1)
    scan_queue.submit(job(1))
    with pytest.raises(QueueFullError):
        scan_queue.submit(job(2))


def test_configuration_change_keeps_current_transaction_and_clears_pending():
    writer = Writer(block=True)
    scan_queue = ScanQueue(writer=writer, capacity=8)
    scan_queue.start()
    scan_queue.submit(job(1))
    scan_queue.submit(job(2))
    assert writer.started.wait(1)

    assert scan_queue.cancel_for_configuration_change(2) == 1
    time.sleep(0.05)
    assert scan_queue.status().current_sequence == 1
    assert scan_queue.status().cancelled == 1

    writer.release.set()
    assert wait_until(lambda: scan_queue.status().completed == 1)
    assert scan_queue.status().cancelled == 1
    scan_queue.stop()


def test_emergency_cancel_still_interrupts_current_write():
    writer = Writer(block=True)
    scan_queue = ScanQueue(writer=writer, capacity=8)
    scan_queue.start()
    scan_queue.submit(job(1))
    assert writer.started.wait(1)
    assert scan_queue.cancel_current("tecla_emergencia")
    assert wait_until(lambda: scan_queue.status().cancelled == 1)
    scan_queue.stop()


def test_pause_resume_and_clear():
    writer = Writer()
    scan_queue = ScanQueue(writer=writer, capacity=8)
    scan_queue.pause()
    scan_queue.start()
    scan_queue.submit(job(1))
    time.sleep(0.05)
    assert not writer.jobs
    assert scan_queue.clear_pending() == 1
    scan_queue.resume()
    scan_queue.stop()
