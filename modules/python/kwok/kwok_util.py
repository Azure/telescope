"""Helpers for pacing KWOK node creation and reporting progress."""
import time
from threading import Lock


NODE_CREATE_PROGRESS_INTERVAL_SECONDS = 10


class NodeCreatePacer:
    """Share evenly spaced attempt permits, without accumulating idle-time credit."""

    def __init__(self, qps, stopped):
        self.interval = 1.0 / qps
        self.stopped = stopped
        self.lock = Lock()
        self.next_attempt = 0.0

    def acquire(self):
        with self.lock:
            while not self.stopped.is_set():
                delay = self.next_attempt - time.monotonic()
                if delay <= 0:
                    self.next_attempt = time.monotonic() + self.interval
                    return True
                self.stopped.wait(delay)
            return False


class NodeCreationTracker:
    """Report successful node creation requests."""

    def __init__(self, total):
        self.total = total
        self.created = 0
        self.lock = Lock()
        self.started = time.monotonic()
        self.last_report = self.started

    def record_node(self):
        with self.lock:
            self.created += 1

    def report(self, in_flight, force=False):
        now = time.monotonic()
        if not force and now - self.last_report < NODE_CREATE_PROGRESS_INTERVAL_SECONDS:
            return
        self.last_report = now
        elapsed = now - self.started
        with self.lock:
            created = self.created
        rate = created / elapsed if elapsed > 0 else 0
        print(
            f"Created {created}/{self.total} virtual nodes; in-flight={in_flight}; "
            f"elapsed={elapsed:.1f}s; completed-rate={rate:.1f} nodes/s",
            flush=True,
        )
