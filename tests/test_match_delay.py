"""When the matcher pays its settle delay, and when it does not.

The delay exists so a click has time to finish animating before the screen is
photographed. It used to be paid on *every* match, which meant a loop pass
matching a dozen templates slept a dozen times — against one cached frame that
could not change between them. Measured: 8.8 ms of real matching work against a
100 ms wait, and a median pass of 1.60 s in a real run log.

So the rule is now "pay it before a capture, not before a comparison". These
tests pin both halves of that, because the half that is easy to lose by
accident is the one that still has to happen: drop it entirely and the loop
photographs buttons mid-animation, which is the failure this app has already
shipped twice.
"""
from __future__ import annotations

import numpy as np
import pytest

import game_control
from game_control import GameControl

CLIENT = (1136, 640)
TEMPLATE = "tpl"


@pytest.fixture
def control(monkeypatch):
    """A GameControl that records its sleeps and never touches GDI."""
    monkeypatch.setattr(GameControl, "_measure_window", lambda self: None)
    from conftest import bare_control

    made = bare_control(client=CLIENT)

    grabs = []

    def fake_grab(gray):
        frame = np.zeros(
            (made.client_height, made.client_width)
            if gray
            else (made.client_height, made.client_width, 3),
            dtype=np.uint8,
        )
        grabs.append(gray)
        if not gray:
            made._last_frame = frame
        return frame

    monkeypatch.setattr(made, "_grab", fake_grab)
    # A template small enough to match anywhere; the score is irrelevant here.
    # It has to carry the same channel count as the frame it is matched against,
    # or OpenCV refuses before any of this is exercised.
    monkeypatch.setattr(
        made, "_template",
        lambda path, gray: np.zeros((4, 4) if gray else (4, 4, 3), dtype=np.uint8),
    )

    sleeps = []
    monkeypatch.setattr(game_control.time, "sleep", lambda s: sleeps.append(s))
    made.grabs = grabs
    made.sleeps = sleeps
    return made


# ── the delay that still has to happen ──────────────────────────────────────


def test_the_first_match_of_a_pass_waits_before_photographing(control):
    """Its whole purpose: a click needs time to finish animating."""
    control.begin_frame()
    control.match(TEMPLATE)

    assert control.sleeps == [game_control.DEFAULT_MATCH_DELAY_SECONDS]


def test_a_match_outside_a_pass_always_waits(control):
    """Uncached, every call goes to the window, so every call earns the wait."""
    for _ in range(3):
        control.match(TEMPLATE)

    assert control.sleeps == [game_control.DEFAULT_MATCH_DELAY_SECONDS] * 3
    # Three real captures. Counted in total rather than by channel: with no
    # pass open there is no colour frame to derive greyscale from, so a
    # greyscale request grabs greyscale straight from the window.
    assert len(control.grabs) == 3


def test_dropping_the_cache_makes_the_next_match_wait_again(control):
    """Every _sleep in a loop invalidates the frame; the next look is fresh."""
    control.begin_frame()
    control.match(TEMPLATE)
    control.invalidate_frame()
    control.match(TEMPLATE)

    assert len(control.sleeps) == 2
    assert control.grabs.count(False) == 2


# ── the delay that was pure waste ───────────────────────────────────────────


def test_later_matches_in_one_pass_do_not_wait(control):
    """They read the cached frame, so waiting cannot change what they see."""
    control.begin_frame()
    for _ in range(12):
        control.match(TEMPLATE)

    assert control.grabs.count(False) == 1, "the cache is not doing its job"
    assert control.sleeps == [game_control.DEFAULT_MATCH_DELAY_SECONDS], (
        "slept %d times for one photograph" % len(control.sleeps)
    )


def test_a_greyscale_match_after_a_colour_one_does_not_wait(control):
    """Greyscale is derived from the colour frame, not grabbed again."""
    control.begin_frame()
    control.match(TEMPLATE, gray=False)
    control.match(TEMPLATE, gray=True)

    assert control.grabs.count(True) == 0
    assert len(control.sleeps) == 1


def test_a_whole_pass_costs_one_delay_not_one_each(control):
    """The saving, stated as the loop actually experiences it."""
    control.begin_frame()
    for _ in range(10):
        control.match(TEMPLATE)
    control.end_frame()

    paid = sum(control.sleeps)
    assert paid == pytest.approx(game_control.DEFAULT_MATCH_DELAY_SECONDS)
    # What it would have been before, for whoever reads this later.
    assert paid < 10 * game_control.DEFAULT_MATCH_DELAY_SECONDS


# ── the explicit override still works ───────────────────────────────────────


def test_a_caller_can_still_ask_for_no_delay_at_all(control):
    control.match(TEMPLATE, delay=0)

    assert control.sleeps == []
