"""Glowing nests go first, and they have to be found to go first at all.

Some nests on the exploration map wear a bright gold arc that sweeps around the
badge. Those are the ones the player wants fought ahead of anything else, and
the loop did not fight them at all.

Two reasons, both measured on a live map. The template is a plain badge and
only covers the 48px core, not the rim, so a glowing badge scores 0.77-0.90
against it while a plain one scores 0.98-1.00. `find` hands back the single best
match, so a plain nest always won; and with the cut-off at 0.9, a glowing nest
on its own was mostly under it and swept straight past.

Telling them apart took three tries, and the two that failed are worth keeping:

* Rim brightness separated the live map 77 vs 145 — then an older chapter's
  red-sword nest, not glowing at all, read 115-121.
* A template of the glowing badge scored its own kind 0.13-0.64. The arc is a
  comet sweeping round the rim, at a different angle every frame.

What survives rotation is how much of the rim the arc covers. Counting the
angular slices that hold a bright gold pixel: plain 1-8 of 24, glowing 14-19,
red-sword 12 — and the red-sword badge scores 0.65 as a nest, so requiring a
real nest match as well leaves a gap on both measures.

The fixtures are crops of a live map and an old recording, 80x80, badge centred.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("win32con")

import exploration  # noqa: E402
from game_control import read_image  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "exploration"
CENTRE = (40, 40)


def crop(name):
    image = read_image(str(FIXTURES / name))
    assert image is not None, name
    return image


@pytest.mark.parametrize("name", ["glowing_%d.png" % i for i in range(1, 7)])
def test_a_glowing_nest_is_recognised_at_every_angle_of_its_arc(name):
    assert exploration.is_glowing(crop(name), CENTRE), name


@pytest.mark.parametrize("name", ["plain_1.png", "plain_2.png", "plain_3.png"])
def test_a_plain_nest_is_not_taken_for_a_glowing_one(name):
    assert not exploration.is_glowing(crop(name), CENTRE), name


def test_the_red_sword_nest_is_not_taken_for_a_glowing_one():
    """The case that sank the brightness test: bright gold trim, no glow."""
    assert not exploration.is_glowing(crop("red_sword.png"), CENTRE)


def test_the_measure_has_room_on_both_sides():
    """Pinned to the numbers, so a tweak that narrows the gap shows up here."""
    glowing = [exploration.glow_sectors(crop("glowing_%d.png" % i), CENTRE)
               for i in range(1, 7)]
    plain = [exploration.glow_sectors(crop("plain_%d.png" % i), CENTRE)
             for i in range(1, 4)]
    red = exploration.glow_sectors(crop("red_sword.png"), CENTRE)

    assert min(glowing) >= exploration.GLOW_SECTORS
    assert max(plain + [red]) < exploration.GLOW_SECTORS


def test_a_badge_at_the_edge_of_the_frame_is_not_measured():
    """Half a rim cannot be counted honestly; better to say nothing."""
    assert exploration.glow_sectors(crop("glowing_1.png"), (5, 40)) is None


# ── the order on the map ────────────────────────────────────────────────────


@pytest.fixture
def worker(monkeypatch):
    from test_exploration import REFERENCE, StubControl
    from exploration import ExplorationWorker

    class Control(StubControl):
        nests = []

        def find_all(self, template_path, threshold=0.9, **kwargs):
            return list(self.nests) if template_path == exploration.TPL_ENEMY else []

        def full_shot(self, gray=False):
            return np.zeros((REFERENCE[1], REFERENCE[0], 3), np.uint8)

    def make(seen, nests, glowing):
        control = Control(REFERENCE, seen)
        control.nests = nests
        built = ExplorationWorker(hwnd=1, control=control)
        monkeypatch.setattr(built, "_sleep", lambda s: None)
        monkeypatch.setattr(exploration, "is_glowing",
                            lambda frame, centre, scale=1.0: tuple(centre) in glowing)
        monkeypatch.setattr(built, "_await_handover", lambda: True)
        built.control = control
        return built

    return make


def test_a_glowing_nest_is_fought_before_a_plain_one(worker):
    w = worker({exploration.TPL_ON_MAP: (10, 10), exploration.TPL_ENEMY: (204, 369)},
               nests=[(204, 369), (576, 330)], glowing={(576, 330)})

    w._work_the_map()

    assert w.control.clicks == [(576, 330)]


def test_a_glowing_nest_is_fought_before_the_boss(worker):
    """The point of the request: beating the boss ends the chapter, and a glowing
    nest still standing then is lost."""
    w = worker({exploration.TPL_ON_MAP: (10, 10), exploration.TPL_BOSS: (245, 248),
                exploration.TPL_ENEMY: (204, 369)},
               nests=[(204, 369), (576, 330)], glowing={(576, 330)})

    w._work_the_map()

    assert w.control.clicks == [(576, 330)]


def test_a_reward_still_comes_before_any_fight(worker):
    w = worker({exploration.TPL_ON_MAP: (10, 10), exploration.TPL_MAP_REWARD: (700, 300)},
               nests=[(576, 330)], glowing={(576, 330)})

    w._work_the_map()

    assert w.control.clicks == [(700, 300)]


def test_without_a_glowing_nest_the_old_order_holds(worker):
    w = worker({exploration.TPL_ON_MAP: (10, 10), exploration.TPL_BOSS: (245, 248),
                exploration.TPL_ENEMY: (204, 369)},
               nests=[(204, 369)], glowing=set())

    w._work_the_map()

    assert w.control.clicks == [(245, 248)]
