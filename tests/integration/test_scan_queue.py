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

    def write(self, job, cancel):
        self.jobs.append(job)
        self.started.set()
        while self.block and not cancel.wait(0.01):
            pass
        if cancel.is_set():
            return WriteResult(False, "cancelled", 0, 0, 0, 1, "cancelled")
        return WriteResult(True, "completed", 0, 0, 0, 1)


def job(seq, generation=1):
    return ScanJob(sequence_id=seq, created_at_utc=datetime.now(timezone.utc), raw_sha256=f"{seq:064x}", data={}, configuration_id="cfg", configuration_name="Config", configuration_version=2, configuration_generation=generation, write_profile="rapida", target=TargetWindow(10, 20, 10), fields=(), final_action=FinalAction.NONE)


def wait_until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_queue_processes_100_jobs_without_reordering():
    writer = Writer()
    queue = ScanQueue(writer=writer, capacity=128)
    queue.start()
    for i in range(1, 101):
        queue.submit(job(i))
    assert wait_until(lambda: queue.status().completed == 100)
    assert [item.sequence_id for item in writer.jobs] == list(range(1, 101))
    queue.stop()


def test_queue_full_is_nonblocking_backpressure():
    queue = ScanQueue(writer=Writer(), capacity=1)
    queue.submit(job(1))
    with pytest.raises(QueueFullError):
        queue.submit(job(2))


def test_cancel_current_and_configuration_change():
    writer = Writer(block=True)
    queue = ScanQueue(writer=writer, capacity=8)
    queue.start()
    queue.submit(job(1))
    queue.submit(job(2))
    assert writer.started.wait(1)
    assert queue.cancel_for_configuration_change(2) == 1
    assert wait_until(lambda: queue.status().cancelled >= 2)
    queue.stop()


def test_pause_resume_and_clear():
    writer = Writer()
    queue = ScanQueue(writer=writer, capacity=8)
    queue.pause()
    queue.start()
    queue.submit(job(1))
    time.sleep(0.05)
    assert not writer.jobs
    assert queue.clear_pending() == 1
    queue.resume()
    queue.stop()
