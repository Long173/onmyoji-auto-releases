"""The lifecycle every task loop inherits.

Worth its own file because this code is now shared four ways: a mistake here is
a mistake in every automation at once, which is the trade for having one copy
instead of four.

The guard on :meth:`resume` is the reason the file exists. Three of the four
loops had it and Realm Raid did not, so resuming something already running
would have moved its clock reference to now and thrown away the time it had
been running for. Nothing reached that path — ``GameSession.toggle_pause`` only
resumes what it has checked is paused — so no test caught it and no user saw it.
Pinned here so the fix cannot quietly come undone.
"""
from __future__ import annotations

import time

import pytest

from task_worker import TaskWorker


class StubControl:
    def __init__(self, hwnd=1):
        self.client_width, self.client_height = 1122, 633
        self.closed = False
        self.invalidated = 0
        self.frame = "khung"

    def invalidate_frame(self):
        self.invalidated += 1

    def last_frame(self):
        return self.frame

    def close(self):
        self.closed = True


class Spin(TaskWorker):
    """A worker that does nothing but count passes, so timing can be watched."""

    def __init__(self, **kwargs):
        super().__init__("Spin", 1, StubControl(), **kwargs)
        self.passes = 0

    def run(self):
        self._begin_timing()
        try:
            while not self.is_stopping:
                self._wait_while_paused()
                if self.is_stopping:
                    break
                self.passes += 1
                self._sleep(0.01)
        finally:
            self._end_timing()
            self._control.close()


@pytest.fixture
def spin():
    made = []

    def build(**kwargs):
        worker = Spin(**kwargs)
        made.append(worker)
        return worker

    yield build
    for worker in made:
        worker.stop()
        if worker.ident is not None:
            worker.join(3)


# ── the guard that had drifted ──────────────────────────────────────────────


def test_resuming_something_already_running_does_not_reset_the_clock(spin):
    """The divergence this base class exists to end.

    Without the guard, resume() moves the clock reference to now, so the time
    already run is discarded and elapsed jumps backwards.
    """
    worker = spin()
    worker.start()
    time.sleep(0.25)
    before = worker.elapsed_seconds
    worker.resume()                     # already running
    after = worker.elapsed_seconds

    assert after >= before, (
        "elapsed went backwards, %.3f -> %.3f: resume() reset the clock"
        % (before, after)
    )
    assert after == pytest.approx(before, abs=0.05)


def test_resuming_a_paused_worker_does_start_it_again(spin):
    worker = spin()
    worker.start()
    time.sleep(0.1)
    worker.pause()
    paused_at = worker.passes
    time.sleep(0.15)

    assert worker.passes == paused_at, "kept working while paused"
    worker.resume()
    time.sleep(0.15)

    assert worker.passes > paused_at, "never restarted"


# ── timing ──────────────────────────────────────────────────────────────────


def test_elapsed_excludes_the_pause(spin):
    worker = spin()
    worker.start()
    time.sleep(0.2)
    worker.pause()
    frozen = worker.elapsed_seconds
    time.sleep(0.25)

    assert worker.elapsed_seconds == pytest.approx(frozen, abs=0.01)


def test_elapsed_survives_the_worker_finishing(spin):
    """A card still shows how long a finished run took."""
    worker = spin()
    worker.start()
    time.sleep(0.2)
    worker.stop()
    worker.join(3)
    final = worker.elapsed_seconds

    assert final >= 0.15
    time.sleep(0.1)
    assert worker.elapsed_seconds == final, "the clock kept running after the end"


def test_elapsed_is_zero_before_it_starts(spin):
    assert spin().elapsed_seconds == 0.0


# ── stopping ────────────────────────────────────────────────────────────────


def test_stop_wakes_a_paused_worker(spin):
    """Parked in _wait_while_paused, it still has to be able to exit."""
    worker = spin()
    worker.start()
    time.sleep(0.05)
    worker.pause()
    worker.stop()
    worker.join(3)

    assert not worker.is_alive()


def test_sleeping_returns_early_once_stopped(spin):
    worker = spin()
    worker.start()
    time.sleep(0.05)
    started = time.monotonic()
    worker.stop()
    worker.join(3)

    assert time.monotonic() - started < 1.0, "stop did not interrupt the wait"


def test_the_control_is_closed_when_it_ends(spin):
    worker = spin()
    worker.start()
    time.sleep(0.05)
    worker.stop()
    worker.join(3)

    assert worker._control.closed


# ── the frame cache ─────────────────────────────────────────────────────────


def test_every_wait_drops_the_frame_cache(spin):
    """Anything matched after a wait must be matched against a fresh capture."""
    worker = spin()
    worker.start()
    time.sleep(0.15)
    worker.stop()
    worker.join(3)

    assert worker._control.invalidated >= worker.passes


def test_the_thumbnail_reads_the_latest_frame(spin):
    worker = spin()
    assert worker.latest_frame() == "khung"


# ── callbacks ───────────────────────────────────────────────────────────────


def test_a_callback_that_raises_does_not_take_the_worker_down(spin):
    """The callback belongs to the UI; a worker must not die of its bugs."""
    def explode(_message):
        raise RuntimeError("giao dien loi")

    TaskWorker._notify(explode, "xong")   # must not raise


def test_no_callback_is_not_an_error(spin):
    TaskWorker._notify(None, "xong")
