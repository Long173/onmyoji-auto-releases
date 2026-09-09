"""Closing the dashboard must stop every running worker.

Workers are threads inside the app's own process, so they cannot outlive it —
but they can keep clicking into the game for as long as the process is winding
down, and a worker left un-joined would block a clean exit. These tests pin the
behaviour: shutting the window down tells every worker to stop, releases the
device contexts, and leaves nothing that would keep the process alive.

The dashboard fixture and its stubs live in conftest.py.
"""
from __future__ import annotations

import threading
import time

import pytest

from conftest import SpyWorker

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")

SETTLE = 0.3


def test_closing_stops_every_running_worker(dashboard):
    dashboard._on_start_all()
    time.sleep(SETTLE)
    assert len(SpyWorker.live) == 2
    assert dashboard._manager.running_count == 2

    dashboard.close()

    assert all(worker.stop_called for worker in SpyWorker.live), (
        "a worker was left running after the window closed"
    )
    time.sleep(SETTLE)
    assert not any(worker.is_alive() for worker in SpyWorker.live)
    assert dashboard._manager.sessions == []


def test_closing_does_not_hang_the_ui(dashboard):
    dashboard._on_start_all()
    time.sleep(SETTLE)

    started = time.time()
    dashboard.close()
    elapsed = time.time() - started

    assert elapsed < 5, "closing took %.1fs — the join timeout is blocking" % elapsed


def test_closing_leaves_no_thread_holding_the_process_open(dashboard):
    dashboard._on_start_all()
    time.sleep(SETTLE)
    dashboard.close()
    time.sleep(SETTLE)

    lingering = [
        thread
        for thread in threading.enumerate()
        if thread is not threading.main_thread()
        and thread.is_alive()
        and not thread.daemon
    ]
    assert not lingering, "non-daemon threads would keep the process alive: %s" % (
        lingering,
    )


def test_closing_with_nothing_running_is_harmless(dashboard):
    dashboard.close()
    assert dashboard._manager.sessions == []
    assert not SpyWorker.live


def test_stop_all_leaves_the_window_usable(dashboard):
    """Stopping is not closing — the cards stay so the user can start again."""
    dashboard._on_start_all()
    time.sleep(SETTLE)
    dashboard._on_stop_all()

    assert dashboard._manager.running_count == 0
    assert len(dashboard._manager.sessions) == 2, "cards vanished on stop"
    assert all(worker.stop_called for worker in SpyWorker.live)


# ── the "are you sure" prompt ───────────────────────────────────────────────


def test_closing_while_running_asks_first(dashboard):
    asked = []
    dashboard._confirm_exit = lambda running: asked.append(running) or True

    dashboard._on_start_all()
    time.sleep(SETTLE)
    dashboard.close()

    assert asked == [2], "the prompt did not report how many windows were running"


def test_answering_stay_keeps_everything_running(dashboard):
    dashboard._confirm_exit = lambda running: False

    dashboard._on_start_all()
    time.sleep(SETTLE)
    dashboard.close()

    assert dashboard.isVisible(), "the window closed despite answering 'stay'"
    assert dashboard._manager.running_count == 2, "workers were stopped anyway"
    assert not any(worker.stop_called for worker in SpyWorker.live)
    # The refresh timer must survive too, or the cards would freeze.
    dashboard._refresh()
    assert dashboard._manager.sessions


def test_answering_leave_stops_everything(dashboard):
    dashboard._confirm_exit = lambda running: True

    dashboard._on_start_all()
    time.sleep(SETTLE)
    dashboard.close()

    assert not dashboard.isVisible(), "the window stayed open after 'leave'"
    assert all(worker.stop_called for worker in SpyWorker.live)
    assert dashboard._manager.sessions == []


def test_no_prompt_when_nothing_is_running(dashboard):
    """A routine close must not cost a click."""
    asked = []
    dashboard._confirm_exit = lambda running: asked.append(running) or True

    dashboard.close()

    assert asked == [], "it asked even though no window was running"


def test_the_wiki_is_a_page_not_a_second_window(dashboard):
    """It used to open a window of its own, which could be left behind."""
    dashboard.open_wiki()
    wiki = dashboard._wiki

    assert wiki is not None
    assert not wiki.isWindow(), "the wiki is still a top-level window"
    assert dashboard._stack.currentWidget() is wiki
    assert dashboard._stack.indexOf(wiki) >= 0, "it is not in the main window's stack"


def test_closing_waits_for_a_wiki_sync(dashboard):
    """A sync thread must not outlive the window it was started from."""
    dashboard.open_wiki()
    waited = []
    dashboard._wiki.shutdown = lambda: waited.append(True)

    dashboard.close()

    assert waited == [True]
