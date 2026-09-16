"""Minimising the game stops the task, so it has to be said out loud.

A minimised window has no client area, so nothing can be captured from it —
measured on the live game: 1122x633 open, 0x0 minimised, and every capture
raising CaptureError. All five loops catch that, sleep and try again, so the
task does not die; it simply stops doing anything until the window comes back.

What that looked like was worse than what it was. The card went on reading
"đang chạy", and the only sign was `Capture failed (cannot reshape array of
size 2 into shape (0,0,4))` in the log, once a second, saying nothing a user
could act on.

Nothing here restores the window. Minimising mid-run is usually deliberate —
the player wants the screen for something else — and the app taking it back
would be fighting them. Pressing Bắt đầu is a different matter and does open it.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from ui.auto_window import minimised_to_announce  # noqa: E402


def test_a_running_window_that_was_minimised_is_announced():
    fresh, told = minimised_to_announce(running={101}, minimised={101}, already=set())

    assert fresh == [101]
    assert told == {101}


def test_it_is_only_said_once():
    """The tick runs every second; a state is not news every second."""
    fresh, told = minimised_to_announce(running={101}, minimised={101}, already={101})

    assert fresh == []
    assert told == {101}


def test_restoring_the_window_arms_it_again():
    """Down, up, down deserves two notices — the second one is news again."""
    _, told = minimised_to_announce(running={101}, minimised=set(), already={101})
    assert told == set()

    fresh, told = minimised_to_announce(running={101}, minimised={101}, already=told)
    assert fresh == [101]


def test_a_window_with_no_task_running_is_left_alone():
    """Minimising a game nobody is driving is not worth a word."""
    fresh, told = minimised_to_announce(running=set(), minimised={101}, already=set())

    assert fresh == []
    assert told == set()


def test_stopping_the_task_clears_the_mark():
    """Otherwise a task started again on a still-minimised window says nothing."""
    _, told = minimised_to_announce(running=set(), minimised={101}, already={101})

    assert told == set()


def test_each_window_is_tracked_on_its_own():
    fresh, told = minimised_to_announce(running={101, 102}, minimised={101, 102},
                                        already={101})

    assert fresh == [102]
    assert told == {101, 102}


# ── the wiring ──────────────────────────────────────────────────────────────


def test_the_dashboard_says_it_once(dashboard, monkeypatch):
    said = []
    monkeypatch.setattr(dashboard._notifier, "notify",
                        lambda title, body, *a, **k: said.append(body))
    monkeypatch.setattr("ui.auto_window.window_scanner.is_minimised",
                        lambda hwnd: hwnd == 101)
    dashboard._manager.start(101, None, None)

    for _ in range(3):
        dashboard._warn_about_minimised_games()

    assert len(said) == 1, "said it %d times" % len(said)
    assert "thu nhỏ" in said[0]
