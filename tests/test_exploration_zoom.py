"""Badges on a zoomed-out exploration map.

Reported from a player's machine (3.21): the map farm fought four nests and then
swept for an hour beside a nest and the boss. The video shows why. That
player's game draws the exploration map about 12% smaller than the captures the
templates were cut from — the UI on top is full size, so it is the map's own
zoom — and at that size the plain nest scored 0.835 and the boss 0.639 at full
size, both under their cut-offs.

The fixture is cut from that video at the client's own pixels: the boss and a
nest, at (170, 180) in a 1122x633 client. It is a lossy screen recording, so
these scores are lower than a live capture would give.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

import exploration
from conftest import bare_control

FIXTURE = Path(__file__).parent / "fixtures" / "exploration" / "zoomed_out.png"
ORIGIN = (170, 180)
NEST = (317, 265)       # badge centres in the client
BOSS = (240, 241)


def control_showing(crop: np.ndarray):
    made = bare_control(client=(1122, 633))
    frame = np.full((633, 1122, 3), 200, np.uint8)
    h, w = crop.shape[:2]
    frame[ORIGIN[1]:ORIGIN[1] + h, ORIGIN[0]:ORIGIN[0] + w] = crop
    made.full_shot = lambda gray=False: (
        cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if gray else frame)
    return made


@pytest.fixture(scope="module")
def crop():
    image = cv2.imdecode(np.fromfile(str(FIXTURE), np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return image


def near(point, target, within=8):
    return point is not None and abs(point[0] - target[0]) <= within \
        and abs(point[1] - target[1]) <= within


def test_at_full_size_neither_badge_is_found(crop):
    """The bug as it was: one size, and nothing clears its cut-off."""
    control = control_showing(crop)
    assert control.find(exploration.TPL_ENEMY, exploration.THRESHOLD, delay=0) is None
    assert control.find(exploration.TPL_BOSS, exploration.BOSS_THRESHOLD,
                        delay=0) is None


def test_a_zoomed_out_nest_is_found(crop):
    control = control_showing(crop)
    point = control.find(exploration.TPL_ENEMY, exploration.THRESHOLD, delay=0,
                         scales=exploration.MAP_SCALES)
    assert near(point, NEST), point


def test_a_zoomed_out_boss_is_found(crop):
    control = control_showing(crop)
    point = control.find(exploration.TPL_BOSS, exploration.BOSS_THRESHOLD,
                         delay=0, scales=exploration.MAP_SCALES)
    assert near(point, BOSS), point


def test_find_all_reports_each_nest_once_across_sizes(crop):
    control = control_showing(crop)
    points = control.find_all(exploration.TPL_ENEMY, threshold=exploration.THRESHOLD,
                              delay=0, scales=exploration.MAP_SCALES)
    assert len(points) == 1 and near(points[0], NEST), points


def test_one_size_is_the_old_behaviour(crop):
    control = control_showing(crop)
    assert control.match(exploration.TPL_ENEMY, delay=0) == control.match(
        exploration.TPL_ENEMY, delay=0, scales=(1.0,))


def test_the_loop_looks_at_every_size(monkeypatch):
    """The wiring: the map step passes MAP_SCALES for nests and the boss."""
    asked = []

    class Control:
        client_width, client_height = 1122, 633
        hwnd = 1

        def find(self, path, threshold=0.9, region=None, gray=True, delay=0.1,
                 scales=(1.0,)):
            asked.append((path, tuple(scales)))
            return (300, 300) if path == exploration.TPL_ON_MAP else None

        def find_all(self, path, threshold=0.9, scales=(1.0,), **kwargs):
            asked.append((path, tuple(scales)))
            return []

        def __getattr__(self, name):
            return lambda *a, **k: True

    worker = exploration.ExplorationWorker(hwnd=1, control=Control())
    monkeypatch.setattr(worker, "_sweep", lambda: None)
    worker._work_the_map()

    looked = dict(asked)
    assert looked[exploration.TPL_ENEMY] == exploration.MAP_SCALES
    assert looked[exploration.TPL_BOSS] == exploration.MAP_SCALES
    assert looked[exploration.TPL_MAP_REWARD] == exploration.MAP_SCALES


# ── the boss on any map ─────────────────────────────────────────────────────
#
# Reported on 3.27: six nests fought, then minutes of "Reached the edge of the
# map" beside a boss the loop could not see, on a bamboo-forest map. The
# template was then a 69 px square, four corners of it Chapter 28's map, and it
# found the badge in the right place at 0.735-0.751. Cut down to the inside of
# the disc it reads the boss wherever it stands. Each crop below is the badge on
# a different map; boss_bamboo is one frame of that player's recording.

FIXTURES = Path(__file__).parent / "fixtures" / "exploration"
ANY_ORIGIN = (90, 180)
# red_sword.png was cut for the glow tests, centred on where the nest template
# landed; the boss disc itself sits up and left of the crop's middle, at (35, 29).
BOSSES = (("boss_bamboo.png", (180, 258)), ("red_sword.png", (125, 209)))
NOT_A_BOSS = ("plain_1.png", "plain_2.png", "plain_3.png", "glowing_1.png",
              "glowing_4.png", "glowing_6.png")


def fixture(name: str) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(FIXTURES / name), np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, name
    return image


@pytest.mark.parametrize("name,centre", BOSSES)
def test_the_boss_is_found_whatever_map_it_stands_on(name, centre):
    control = control_showing_at(fixture(name), ANY_ORIGIN)
    point = control.find(exploration.TPL_BOSS, exploration.BOSS_THRESHOLD,
                         delay=0, scales=exploration.MAP_SCALES)
    assert near(point, centre), point


def test_the_boss_template_holds_no_map():
    """The bug as it was: a square round the disc carried the map's corners."""
    template = cv2.imdecode(np.fromfile(exploration.TPL_BOSS, np.uint8),
                            cv2.IMREAD_GRAYSCALE)
    disc_radius = 36   # reference px; see GLOW_RING
    half_diagonal = (template.shape[0] ** 2 + template.shape[1] ** 2) ** 0.5 / 2
    assert half_diagonal <= disc_radius, template.shape


@pytest.mark.parametrize("name", NOT_A_BOSS)
def test_a_nest_is_not_taken_for_the_boss(name):
    """A nest read as the boss would be fought first, ahead of the real one."""
    control = control_showing_at(fixture(name), ANY_ORIGIN)
    score, _ = control.match(exploration.TPL_BOSS, delay=0,
                             scales=exploration.MAP_SCALES)
    assert score < exploration.BOSS_THRESHOLD - 0.1, score


# ── the reward the boss leaves behind ───────────────────────────────────────
#
# Reported from the same zoomed-out game on 3.22: the boss fell, two chests were
# left on the map, and the loop swept past them for two minutes ("4 sweeps in a
# row moved nothing…") until the player picked one up by hand. Nests and the
# boss had been taught every size in 3.22; the chest had not. Cut from the
# player's screenshot, which is the client at about 98% of its own pixels —
# the chest there is 88-92% of the template.

REWARD_FIXTURE = Path(__file__).parent / "fixtures" / "exploration" / "reward_zoomed.png"
REWARD_ORIGIN = (380, 326)
CHEST = (444, 429)


@pytest.fixture(scope="module")
def reward_crop():
    image = cv2.imdecode(np.fromfile(str(REWARD_FIXTURE), np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return image


def control_showing_at(crop: np.ndarray, origin):
    made = bare_control(client=(1122, 633))
    frame = np.full((633, 1122, 3), 200, np.uint8)
    h, w = crop.shape[:2]
    frame[origin[1]:origin[1] + h, origin[0]:origin[0] + w] = crop
    made.full_shot = lambda gray=False: (
        cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if gray else frame)
    return made


def test_a_zoomed_out_chest_is_found(reward_crop):
    control = control_showing_at(reward_crop, REWARD_ORIGIN)
    point = control.find(exploration.TPL_MAP_REWARD, exploration.REWARD_THRESHOLD,
                         delay=0, scales=exploration.MAP_SCALES)
    assert near(point, CHEST, within=40), point


def test_at_full_size_the_chest_barely_scores(reward_crop):
    """Why it went unseen: at one size it sits on the cut-off, not above it."""
    control = control_showing_at(reward_crop, REWARD_ORIGIN)
    full, _ = control.match(exploration.TPL_MAP_REWARD, delay=0)
    sized, _ = control.match(exploration.TPL_MAP_REWARD, delay=0,
                             scales=exploration.MAP_SCALES)
    assert sized > 0.95 and full < 0.9 and sized - full > 0.08


def test_no_chest_is_seen_on_a_map_without_one(crop):
    control = control_showing(crop)
    assert control.find(exploration.TPL_MAP_REWARD, exploration.REWARD_THRESHOLD,
                        delay=0, scales=exploration.MAP_SCALES) is None
