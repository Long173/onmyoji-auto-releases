"""A pass that will not be allowed to click is a pass that changes nothing.

Clicks are withheld while the player's own cursor sits over the game window,
which is the point of the setting. What was not thought through is what the
loops do meanwhile: they carried on running full passes, counting stuck frames
and writing "Clicking START at (579, 333)" once a second for a click that never
left. A user watching that log reported the raid as attacking one barrier over
and over — a bug that did not exist. The loop had not attacked anything at all.

Two things are asked for here. A held loop does no work, and says so once
rather than every pass; and nothing claims a click that was withheld.
"""
from __future__ import annotations

import inspect
import logging

import pytest

pytest.importorskip("win32con")

from game_control import GameControl  # noqa: E402


# ── the control's own answer ────────────────────────────────────────────────


@pytest.fixture
def cursor(monkeypatch):
    """Places the real cursor against a window at (100, 100)-(700, 500)."""
    monkeypatch.setattr("game_control.win32gui.GetWindowRect",
                        lambda hwnd: (100, 100, 700, 500))

    def place(x, y):
        monkeypatch.setattr("game_control.win32gui.GetCursorPos", lambda: (x, y))

    return place


def a_control():
    from conftest import bare_control

    return bare_control(0x1234)


def test_a_control_over_the_cursor_admits_it_is_withholding(cursor):
    """The same question click() asks itself, asked out loud.

    A loop cannot decide to stand down until it can find out, and it must find
    out *before* it starts a pass rather than by watching clicks fail.
    """
    cursor(400, 300)                      # inside the window

    assert a_control().withholding_clicks() is True


def test_a_control_the_cursor_has_left_is_not_withholding(cursor):
    cursor(50, 50)

    assert a_control().withholding_clicks() is False


def test_nothing_is_withheld_with_the_setting_switched_off(cursor, monkeypatch):
    cursor(400, 300)
    monkeypatch.setattr("game_control._pause_while_hovering", False)

    assert a_control().withholding_clicks() is False


# ── what a held loop does ───────────────────────────────────────────────────


@pytest.fixture
def held_raid(monkeypatch):
    """A raid worker whose control refuses every click, on a live board.

    Borrows test_realm_raid's stub rather than growing a second one: what a
    control does when it withholds is one behaviour, and two stubs of it would
    drift.
    """
    import realm_raid
    import task_worker
    from test_realm_raid import StubControl

    control = StubControl(1, matches={realm_raid.TPL_START: (579, 333)})
    control.clicking = False
    monkeypatch.setattr(task_worker, "GameControl", lambda hwnd: control)
    monkeypatch.setattr(realm_raid.ticket_counter, "is_zero", lambda *_a: False)

    worker = realm_raid.RealmRaidWorker(hwnd=1)
    yield worker
    worker.stop()


def test_a_held_raid_does_not_report_clicks_it_never_sent(held_raid, caplog):
    """The log line that caused the false report.

    "Clicking START at ..." was written before the click, so it printed just
    the same when the click was withheld — and it was the only evidence the
    user had. A log that narrates actions the program did not take is worse
    than no log: it sends whoever reads it after the wrong bug.
    """
    with caplog.at_level(logging.INFO):
        held_raid._step()

    assert held_raid._control.clicks == []
    claimed = [r.getMessage() for r in caplog.records if "START" in r.getMessage()]
    assert claimed == [], "claimed a click that was withheld: %r" % (claimed,)


def test_a_held_raid_says_so_once_rather_than_every_pass(held_raid, caplog):
    """Holding is a state, not an event. Ten passes are not ten pieces of news.

    The user leaving their mouse on the game for a minute should cost one line,
    so that whatever the loop was doing before it stopped is still on screen.
    """
    with caplog.at_level(logging.INFO):
        for _ in range(10):
            held_raid._step()

    said = [r.getMessage() for r in caplog.records if "cursor" in r.getMessage().lower()]
    assert len(said) == 1, "said it %d times over ten passes" % len(said)


def test_a_raid_says_when_it_picks_up_again(held_raid, caplog):
    """The other half: a log that only ever says "held" leaves a reader unable
    to tell a paused loop from one that stopped for good."""
    held_raid._step()

    with caplog.at_level(logging.INFO):
        held_raid._control.clicking = True
        held_raid._step()

    resumed = [r.getMessage() for r in caplog.records
               if "cursor" in r.getMessage().lower()]
    assert len(resumed) == 1, "said nothing when the cursor left"


def test_a_held_raid_does_not_count_the_pass_as_being_stuck(held_raid):
    """Being held is not being stuck.

    _stuck_count drives the escape hatches — giving up on a barrier, pressing
    an empty corner, re-rolling the list. Feeding it passes where the loop was
    never allowed to act makes it fire those on a game that is behaving
    perfectly, and the user comes back to a run that has thrown its board away.
    """
    # Five, not twenty. Past its limit _stuck_count resets itself as the
    # escape hatches fire, so a long enough run comes back to zero on its own
    # and the assertion stops meaning anything.
    for _ in range(5):
        held_raid._step()

    assert held_raid._stuck_count == 0
    assert held_raid._start_clicks == 0


# ── nothing gets forgotten ──────────────────────────────────────────────────


def test_every_task_loop_stands_down_while_the_cursor_is_over_the_game():
    """Each worker has its own loop, so each has to ask. A new task that does
    not is the same bug again, in a place nobody is looking."""
    import demon_parade
    import event_clicker
    import exploration
    import realm_raid
    import souls_dungeon

    workers = {
        "realm_raid": realm_raid.RealmRaidWorker,
        "souls": souls_dungeon.SoulsDungeonWorker,
        "beans": demon_parade.DemonParadeWorker,
        "event": event_clicker.EventClickerWorker,
        "exploration": exploration.ExplorationWorker,
    }

    forgot = [name for name, cls in workers.items()
              if "_holding_for_the_cursor" not in inspect.getsource(cls._step)]

    assert forgot == [], "these loops carry on regardless: %s" % ", ".join(forgot)
