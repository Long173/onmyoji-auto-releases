"""Choosing the Demon Parade boss by silhouette size, on real pick screens.

The two "rare" captures are pick screens whose SSR/SP candidate a player named
by eye, out of 205 captured. They are ones the rule gets right; it gets 9 of
the 13 such screens right, and the misses are a common figure drawn bigger than
the rare one beside it.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

import parade_pick

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "demon_parade"


def load(name: str) -> np.ndarray:
    path = FIXTURES / name
    if not path.is_file():
        pytest.skip("missing capture: %s" % path)
    return cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)


@pytest.mark.parametrize("capture, column", [
    ("pick-rare-left.png", 0),
    ("pick-rare-middle.png", 1),
])
def test_the_biggest_candidate_for_its_place_is_the_rare_one(capture, column):
    assert parade_pick.choose(load(capture)).column == column


def test_all_three_candidates_are_found():
    found = parade_pick.candidates(load("pick-rare-left.png"))

    assert [c.column for c in found] == [0, 1, 2]


def test_every_tap_lands_on_the_figure_it_is_for():
    """A tap on empty ground deselects, so a point outside the body is worse
    than no point."""
    for candidate in parade_pick.candidates(load("pick-rare-middle.png")):
        for x, y in candidate.taps:
            assert candidate.mask[y, x], (candidate.column, (x, y))


def test_a_chosen_candidate_is_seen_to_light_up():
    none = load("pick-rare-left.png")
    lit = load("pick-rare-left-lit.png")
    left = parade_pick.choose(none)

    assert not parade_pick.is_lit(none, left)
    assert parade_pick.is_lit(lit, left)


def test_the_others_stay_dark_while_one_is_lit():
    lit = load("pick-rare-left-lit.png")
    others = [c for c in parade_pick.candidates(load("pick-rare-left.png")) if c.column]

    assert not any(parade_pick.is_lit(lit, c) for c in others)


def test_a_screen_that_is_not_the_pick_screen_offers_no_choice():
    """The entry screen has a dark night sky, which must not pass for three
    silhouettes."""
    assert parade_pick.choose(load("entry.png")) is None


def test_a_black_frame_offers_no_choice():
    """A failed or blacked-out capture is dark from edge to edge, which is
    not three figures."""
    assert parade_pick.choose(np.zeros((633, 1122, 3), np.uint8)) is None


def test_the_window_size_does_not_change_the_choice():
    """Emulators run at 1600x900 and PCs at 1122x633; area is judged at the
    reference size either way."""
    frame = load("pick-rare-middle.png")
    bigger = cv2.resize(frame, (1600, 900), interpolation=cv2.INTER_CUBIC)

    assert parade_pick.choose(bigger).column == parade_pick.choose(frame).column
