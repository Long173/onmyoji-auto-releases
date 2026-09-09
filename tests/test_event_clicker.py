"""The event clicker.

Nothing here touches Windows: the capture and the clicks are stubbed, so these
run headless and never post input anywhere.

This loop is almost too simple to test, and the parts that are not are the
parts that cost something when wrong:

* **It clicks where it was told, and nowhere else.** The whole feature is one
  coordinate, and a coordinate that quietly drifts — scaled twice, defaulted
  over, rounded away — clicks a purchase button instead of a start button.
* **A blocking dialog wins over the click.** A Wanted Quest invite covers the
  screen and swallows every click underneath, so a loop that pressed on
  regardless would sit behind it doing nothing until it timed out.
* **The count is clicks.** Said out loud in a test because it is tempting to
  read the number on the card as battles, and this loop cannot know that.
"""
from __future__ import annotations

import time

import pytest

import event_clicker
import geometry
from event_clicker import EventClickerWorker

REFERENCE = geometry.REFERENCE_CLIENT_SIZE
SETTLE = 0.3


class StubControl:
    """Records clicks; reports whichever invite the test set up."""

    def __init__(self, hwnd, size=REFERENCE, invite=None):
        self.client_width, self.client_height = size
        self.clicks: list = []
        self.clicking = True
        self.closed = False
        self.invite = invite
        self.frames_begun = 0
        self.frames_ended = 0

    def describe(self):
        return "stub control"

    def find(self, template_path, threshold=0.9, region=None, gray=True, delay=0.1):
        time.sleep(0.001)  # keep the loop from spinning the CPU flat out
        return self.invite.get(template_path) if self.invite else None

    def withholding_clicks(self):
        """Whether the real control would refuse to click right now.

        `clicking = False` stands for the player's own cursor resting over the
        game window. The loops ask this before a pass, so a stub that cannot
        answer it makes every loop run passes the real one would skip.
        """
        return not self.clicking

    def click(self, point):
        # True stands for "it went out". The real control returns False while
        # the player's cursor is over the game, and the count follows that.
        if not self.clicking:
            return False
        self.clicks.append(tuple(point))
        return True

    def close(self):
        self.closed = True

    def begin_frame(self):
        self.frames_begun += 1

    def end_frame(self):
        self.frames_ended += 1

    def invalidate_frame(self):
        pass

    def last_frame(self):
        return None


@pytest.fixture
def worker(monkeypatch):
    """Builds workers backed by StubControl and tears them down afterwards."""
    created: list = []
    # The real floor is half a second, which would make every test below a
    # multi-second wait. Lifted here only — the test that the floor exists
    # builds its worker directly, without this fixture, so it sees the real
    # value.
    monkeypatch.setattr(event_clicker, "MIN_INTERVAL_SECONDS", 0.0)

    def build(size=REFERENCE, invite=None, interval=0.01, **kwargs):
        control = StubControl(1, size, invite)
        made = EventClickerWorker(hwnd=1, control=control, interval=interval, **kwargs)
        made.control = control
        created.append(made)
        return made

    yield build

    for made in created:
        made.stop()
        if made.ident is not None:
            made.join(3)


def run_briefly(made, seconds=SETTLE):
    made.start()
    time.sleep(seconds)
    made.stop()
    made.join(3)


# ── configuration ───────────────────────────────────────────────────────────


def test_rejects_an_interval_too_short_to_be_meant():
    """Zero would be a click storm, not a faster farm."""
    with pytest.raises(ValueError):
        EventClickerWorker(hwnd=1, control=StubControl(1), interval=0.0)


def test_falls_back_to_the_measured_default_point(worker):
    made = worker()
    assert made._point == geometry.EVENT_CLICK_POINT


def test_uses_the_point_it_was_given(worker):
    made = worker(point=(400, 300))
    assert made._point == (400, 300)


def test_scales_the_point_to_a_window_of_another_size(worker):
    """The saved number is in reference coordinates, like every other point.

    Half-size window, so the point should land at half the coordinates —
    otherwise one setting would mean two different places.
    """
    half = (REFERENCE[0] // 2, REFERENCE[1] // 2)
    made = worker(size=half, point=(1000, 500))
    assert made._point == (500, 250), (
        "point %s was not scaled onto a %dx%d client" % ((made._point,) + half)
    )


# ── clicking ────────────────────────────────────────────────────────────────


def test_clicks_the_configured_point_and_only_that_point(worker):
    made = worker(point=(777, 321))
    run_briefly(made)

    assert made.control.clicks, "the loop never clicked; the test proves nothing"
    assert set(made.control.clicks) == {(777, 321)}


def test_keeps_clicking_rather_than_stopping_after_one(worker):
    """The whole feature is repetition — one click is a manual press."""
    made = worker(point=(777, 321))
    run_briefly(made)

    assert len(made.control.clicks) > 2, (
        "only %d clicks in %.1fs" % (len(made.control.clicks), SETTLE)
    )


def test_the_count_is_clicks(worker):
    made = worker()
    run_briefly(made)

    assert made.progress == len(made.control.clicks)


def test_closes_the_control_when_it_stops(worker):
    made = worker()
    run_briefly(made)

    assert made.control.closed


# ── a dialog that blocks everything ─────────────────────────────────────────


def test_answers_a_wanted_invite_instead_of_clicking_behind_it(worker, monkeypatch):
    """The invite covers the screen; clicking underneath does nothing at all."""
    monkeypatch.setattr(event_clicker, "POPUP_SETTLE_SECONDS", 0.01)
    monkeypatch.setattr(
        event_clicker.wanted_invite, "find_reply",
        lambda control, geo, accept: (500, 400),
    )
    made = worker(point=(777, 321))
    run_briefly(made)

    assert made.control.clicks, "the loop never clicked"
    assert set(made.control.clicks) == {(500, 400)}, (
        "clicked the event point while a blocking dialog was up: %s"
        % sorted(set(made.control.clicks))
    )
    assert made.progress == 0, "a dismissed dialog was counted as a click"


# ── lifecycle ───────────────────────────────────────────────────────────────


def test_pausing_stops_the_clicks_and_resuming_starts_them_again(worker):
    made = worker()
    made.start()
    time.sleep(SETTLE)
    made.pause()
    time.sleep(0.05)
    while_paused = len(made.control.clicks)
    time.sleep(SETTLE)

    assert len(made.control.clicks) == while_paused, "clicked while paused"
    assert made.is_paused

    made.resume()
    time.sleep(SETTLE)
    made.stop()
    made.join(3)

    assert len(made.control.clicks) > while_paused, "never restarted after resume"


def test_a_paused_worker_still_stops(worker):
    """It is parked waiting to be resumed; stop has to wake it."""
    made = worker()
    made.start()
    time.sleep(0.05)
    made.pause()
    made.stop()
    made.join(3)

    assert not made.is_alive()


def test_elapsed_time_excludes_the_pause(worker):
    made = worker()
    made.start()
    time.sleep(0.2)
    made.pause()
    stopped_at = made.elapsed_seconds
    time.sleep(0.3)

    assert made.elapsed_seconds == pytest.approx(stopped_at, abs=0.01)
    made.stop()
    made.join(3)


def test_a_withheld_click_is_not_counted(worker):
    """The figure is what the game was told, not what the loop attempted.

    Clicks are withheld while the player's cursor is over the game window; a
    count that included those would drift from reality, which the module
    docstring is explicit about not wanting.
    """
    made = worker()
    made._control.clicking = False

    made._step()
    made._step()

    assert made.progress == 0, "counted presses that were never sent"
