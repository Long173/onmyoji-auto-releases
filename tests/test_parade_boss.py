"""Following the picked boss through the parade, and counting its cards after."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

import parade_boss
import parade_results
from game_control import read_image

FIXTURES = Path(__file__).parent / "fixtures" / "demon_parade"


def _fixture(name):
    return read_image(str(FIXTURES / name))


def _emulator_sized(frame):
    return cv2.resize(frame, (1600, 900), interpolation=cv2.INTER_LINEAR)


# ── the "Picked" badge ──────────────────────────────────────────────────────


def test_the_picked_badge_is_found_where_it_circles_the_boss():
    x, y = parade_boss.badge_at(_fixture("round-picked-boss.jpg"))

    assert abs(x - 715) < 6 and abs(y - 311) < 6


def test_the_badge_is_found_on_an_emulator_sized_frame_in_reference_units():
    x, y = parade_boss.badge_at(_emulator_sized(_fixture("round-picked-boss.jpg")))

    assert abs(x - 715) < 6 and abs(y - 311) < 6


@pytest.mark.parametrize("name", ["round-counter-0.jpg", "round-counter-2.jpg",
                                  "pick.png", "result-two-boss-cards.jpg"])
def test_no_badge_is_seen_where_there_is_none(name):
    assert parade_boss.badge_at(_fixture(name)) is None


# ── bodies on the stage ─────────────────────────────────────────────────────


def test_a_figure_on_the_stage_is_a_body_and_the_sky_is_not():
    background = np.zeros((633, 1122, 3), dtype=np.uint8)
    frame = background.copy()
    frame[250:400, 500:580] = 255          # a figure on the stage
    frame[20:90, 100:300] = 255            # something in the sky: the counter

    found = parade_boss.bodies(frame, background)

    assert len(found) == 1
    assert abs(found[0][0] - 540) < 3 and abs(found[0][1] - 325) < 3


def test_specks_are_not_bodies():
    background = np.zeros((633, 1122, 3), dtype=np.uint8)
    frame = background.copy()
    frame[300:320, 500:520] = 255          # a bean in flight

    assert parade_boss.bodies(frame, background) == []


# ── the chase ───────────────────────────────────────────────────────────────


def test_nothing_is_aimed_at_before_the_boss_is_seen():
    chase = parade_boss.BossChase()
    chase.see(0.0, None, [(600, 330)])

    assert chase.aim(0.0) is None


def test_the_body_under_the_badge_is_aimed_at_ahead_of_where_it_walks():
    """Beans take time to land and the figure keeps walking left: a bean aimed
    at where it is lands behind it."""
    chase = parade_boss.BossChase(lead_seconds=0.8)
    chase.see(0.0, (715, 311), [(200, 330), (720, 340), (1000, 330)])

    x, y = chase.aim(0.0)

    assert x == pytest.approx(720 + parade_boss.DEFAULT_VELOCITY * 0.8, abs=1)
    assert y == 340


def test_the_speed_is_measured_from_the_boss_s_own_track():
    chase = parade_boss.BossChase(lead_seconds=1.0)
    chase.see(0.0, (800, 300), [(800, 330)])
    chase.see(1.0, (700, 300), [(700, 330)])

    x, _ = chase.aim(1.0)

    assert x == pytest.approx(700 - 100, abs=1)


def test_the_chase_carries_on_through_a_moment_without_the_badge():
    """The badge orbits the figure and is edge-on half the time."""
    chase = parade_boss.BossChase(lead_seconds=0.0)
    chase.see(0.0, (800, 300), [(800, 330)])
    chase.see(1.0, None, [(650, 330), (300, 330)])

    x, _ = chase.aim(1.0)

    assert x == pytest.approx(650, abs=1)


def test_the_chase_is_dropped_when_the_boss_has_been_lost_too_long():
    chase = parade_boss.BossChase()
    chase.see(0.0, (800, 300), [(800, 330)])
    chase.see(parade_boss.CHASE_SECONDS + 0.5, None, [])

    assert chase.aim(parade_boss.CHASE_SECONDS + 0.5) is None


def test_a_figure_far_from_the_badge_is_not_taken_for_the_boss():
    chase = parade_boss.BossChase()
    chase.see(0.0, (800, 300), [(800 - parade_boss.MATCH_RADIUS - 20, 330)])

    assert chase.aim(0.0) is None


def test_the_chase_does_not_jump_back_to_a_figure_walking_behind():
    """Everyone walks left, so the boss is never suddenly further right — that
    is the next figure in line coming up behind it."""
    chase = parade_boss.BossChase(lead_seconds=0.0)
    chase.see(0.0, (800, 300), [(800, 330)])
    # Close enough to where the boss should be to be mistaken for it, but
    # further right than the boss ever moves.
    chase.see(0.3, None, [(800 + parade_boss.MAX_STEP_BACK + 20, 330)])

    x, _ = chase.aim(0.3)

    assert x < 800, "followed the figure behind"


def test_a_boss_walking_off_screen_is_not_thrown_at():
    chase = parade_boss.BossChase(lead_seconds=0.8)
    chase.see(0.0, (40, 300), [(40, 330)])

    assert chase.aim(0.0) is None


def test_the_chase_says_when_it_has_just_found_the_boss():
    chase = parade_boss.BossChase()

    assert chase.see(0.0, (800, 300), [(800, 330)]) is True
    assert chase.see(0.3, (760, 300), [(760, 330)]) is False


# ── the boss's cards on the result scroll ───────────────────────────────────


def test_both_boss_cards_on_a_scroll_are_counted():
    assert parade_results.boss_cards(_fixture("result-two-boss-cards.jpg")) == 2


def test_a_scroll_without_the_boss_counts_none():
    assert parade_results.boss_cards(_fixture("result-no-boss-card.jpg")) == 0


def test_boss_cards_are_counted_on_an_emulator_sized_scroll():
    frame = _emulator_sized(_fixture("result-two-boss-cards.jpg"))

    assert parade_results.boss_cards(frame) == 2


def test_a_boss_found_again_is_timed_afresh_not_against_its_last_pass():
    """The boss can walk by twice. Measured across both passes, it would seem
    to have walked right — and beans would trail behind it."""
    chase = parade_boss.BossChase(lead_seconds=1.0)
    chase.see(0.0, (300, 300), [(300, 330)])
    chase.see(0.5, (225, 300), [(225, 330)])
    # Lost for longer than the chase allows, then back at the right.
    chase.see(2.1, (1000, 300), [(1000, 330)])

    x, _ = chase.aim(2.1)

    assert x == pytest.approx(1000 + parade_boss.DEFAULT_VELOCITY * 1.0, abs=1)


def test_one_stray_point_does_not_send_the_aim_far_ahead():
    """Live, the body blob merged with the figure walking ahead of the boss,
    the measured speed hit the old 300 px/s ceiling, and the beans landed on
    that figure instead: "Miss" over the wrong shikigami, round after round."""
    chase = parade_boss.BossChase(lead_seconds=1.0)
    for i in range(10):
        chase.see(i * 0.2, (800 - 30 * i, 300), [(800 - 30 * i, 330)])
    chase.see(2.0, None, [(800 - 30 * 9 - 110, 330)])     # merged with the one ahead

    assert -parade_boss.VELOCITY_RANGE[0] <= 200
    assert chase.velocity() > -200


def test_figures_are_never_taken_to_walk_faster_than_they_do():
    chase = parade_boss.BossChase()
    chase.see(0.0, (900, 300), [(900, 330)])
    chase.see(0.5, None, [(900 - parade_boss.MATCH_RADIUS + 5, 330)])

    assert chase.velocity() >= parade_boss.VELOCITY_RANGE[0]


# ── helpers worth one bean: Assist Up, Got Beans ────────────────────────────


def test_an_assist_up_flier_is_found_above_its_label():
    found = parade_boss.helpers(_fixture("round-assist-up.jpg"))

    kinds = {kind for kind, _ in found}
    assert "assist" in kinds
    x, y = next(p for kind, p in found if kind == "assist")
    # The label's centre is at about (452, 259); the flier hangs above it and
    # drifts left, so the aim is above and a little ahead.
    assert abs(x - (452 - parade_boss.HELPER_LEAD_X)) < 15
    assert y < 259 - 60, "aim at the flier, above its label"


def test_a_got_beans_flier_is_found():
    found = parade_boss.helpers(_fixture("round-got-beans.jpg"))

    assert "beans" in {kind for kind, _ in found}


def test_a_chance_up_flier_is_found_and_not_taken_for_assist_up():
    """Both labels are the same green; only the words tell them apart."""
    found = parade_boss.helpers(_fixture("round-chance-up.jpg"))

    assert [kind for kind, _ in found] == ["chance"]


def test_an_assist_up_flier_is_not_taken_for_chance_up():
    assert "chance" not in {kind for kind, _ in parade_boss.helpers(_fixture("round-assist-up.jpg"))}


@pytest.mark.parametrize("name", ["round-counter-2.jpg", "round-picked-boss.jpg",
                                  "pick.png", "result-two-boss-cards.jpg"])
def test_no_helper_is_seen_where_there_is_none(name):
    assert parade_boss.helpers(_fixture(name)) == []
