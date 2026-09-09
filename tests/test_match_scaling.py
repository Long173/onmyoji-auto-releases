"""Matching against a window that is not the reference size.

Templates were cut at 1122x633. Matching them against a window of any other
size is what breaks first when the app moves to another machine — a user's log
showed a client of 1117x623 and every template far under threshold.

So the search area is stretched to template scale before matching. Two things
have to hold, and the second is the one that silently misbehaves:

* the score comes back where it should — otherwise the stretch bought nothing;
* the returned coordinate is in the **window's own pixels**. A centre left in
  stretched space still looks plausible, is a few pixels off, and clicks next to
  the button rather than on it.
"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

import game_control
from game_control import GameControl
from geometry import REFERENCE_CLIENT_SIZE as REF


def make_control(monkeypatch, client, scene):
    """A control that hands back ``scene`` as the window's capture."""
    from conftest import bare_control

    monkeypatch.setattr(GameControl, "_measure_window", lambda self: None)
    made = bare_control(client=client)
    made.grabs = []

    def fake_grab(gray):
        made.grabs.append(gray)
        # No resize when the size already matches: a real capture does not
        # resize either, and a spurious one here was counted as the stretch
        # under test and failed the cost tests below.
        frame = (scene if client == (scene.shape[1], scene.shape[0])
                 else cv2.resize(scene, client, interpolation=cv2.INTER_AREA))
        if gray:
            return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        made._last_frame = frame
        return frame

    monkeypatch.setattr(made, "_grab", fake_grab)
    return made


@pytest.fixture
def scene():
    """A reference-sized picture with enough detail to match against."""
    rng = np.random.default_rng(7)
    picture = rng.integers(0, 255, (REF[1], REF[0], 3), dtype=np.uint8)
    # A hard-edged marker, so a template of it has one clear best position.
    cv2.rectangle(picture, (600, 300), (700, 380), (255, 255, 255), -1)
    cv2.rectangle(picture, (620, 320), (680, 360), (0, 0, 0), -1)
    return picture


def install_template(control, monkeypatch, scene, box):
    """Use a crop of the reference-scale scene as the template."""
    x1, y1, x2, y2 = box
    tpl = cv2.cvtColor(scene[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    monkeypatch.setattr(control, "_template", lambda path, gray: tpl)
    return tpl


# ── the score ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("client", [
    tuple(REF),          # the everyday case: nothing to do
    (1136, 640),         # the game's own natural size
    (1117, 623),         # from a real user's log
    (1063, 599),         # where Windows clamps the game at 175% scaling
    (898, 507),          # a DPI-virtualised client
])
def test_a_template_is_found_whatever_size_the_window_is(monkeypatch, scene, client):
    control = make_control(monkeypatch, client, scene)
    install_template(control, monkeypatch, scene, (600, 300, 700, 380))

    score, _centre = control.match("tpl", delay=0)

    assert score > 0.9, "scored %.3f on a %dx%d client" % ((score,) + client)


def test_the_stretch_is_what_makes_the_odd_sizes_work(monkeypatch, scene):
    """Same frame, same template — the only difference is the stretch."""
    control = make_control(monkeypatch, (898, 507), scene)
    install_template(control, monkeypatch, scene, (600, 300, 700, 380))

    stretched, _ = control.match("tpl", delay=0)
    monkeypatch.setattr(control, "_reference_scale", lambda: (1.0, 1.0))
    control.invalidate_frame()
    raw, _ = control.match("tpl", delay=0)

    assert stretched > raw + 0.1, (
        "stretch %.3f vs raw %.3f — it is not doing anything" % (stretched, raw)
    )


# ── the coordinate ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("client", [tuple(REF), (1136, 640), (1117, 623), (898, 507)])
def test_the_centre_comes_back_in_the_windows_own_pixels(monkeypatch, scene, client):
    """A centre left in stretched space clicks beside the button, not on it."""
    box = (600, 300, 700, 380)
    control = make_control(monkeypatch, client, scene)
    install_template(control, monkeypatch, scene, box)

    _score, (cx, cy) = control.match("tpl", delay=0)

    # Where that marker really is on a window of this size.
    scale_x = client[0] / REF[0]
    scale_y = client[1] / REF[1]
    want_x = (box[0] + box[2]) / 2 * scale_x
    want_y = (box[1] + box[3]) / 2 * scale_y
    assert abs(cx - want_x) <= 3, "x %d, expected about %.0f" % (cx, want_x)
    assert abs(cy - want_y) <= 3, "y %d, expected about %.0f" % (cy, want_y)
    assert 0 <= cx < client[0] and 0 <= cy < client[1], (
        "centre %s is outside a %dx%d window" % ((cx, cy),) + client
    )


def test_a_region_search_also_answers_in_window_pixels(monkeypatch, scene):
    """The region is given in window pixels, so the answer must match it."""
    box = (600, 300, 700, 380)
    client = (898, 507)
    control = make_control(monkeypatch, client, scene)
    install_template(control, monkeypatch, scene, box)
    scale_x, scale_y = client[0] / REF[0], client[1] / REF[1]
    region = ((round(560 * scale_x), round(260 * scale_y)),
              (round(760 * scale_x), round(430 * scale_y)))

    score, (cx, cy) = control.match("tpl", region=region, delay=0)

    assert score > 0.9
    assert region[0][0] <= cx <= region[1][0]
    assert region[0][1] <= cy <= region[1][1]


# ── cost ────────────────────────────────────────────────────────────────────


def count_stretches(monkeypatch):
    """Record only the resizes *to reference size* — the stretch under test.

    Counting every ``cv2.resize`` counted the fake capture's own resize too,
    which made both tests below fail for a reason that had nothing to do with
    the code.
    """
    calls = []
    real = cv2.resize

    def spy(src, dsize, *args, **kwargs):
        if tuple(dsize) == tuple(REF):
            calls.append(tuple(dsize))
        return real(src, dsize, *args, **kwargs)

    monkeypatch.setattr(game_control.cv2, "resize", spy)
    return calls


def test_the_frame_is_stretched_once_a_pass_not_once_a_template(monkeypatch, scene):
    """Per template it cost 25 ms of a 238 ms pass — ten stretches instead of one."""
    control = make_control(monkeypatch, (898, 507), scene)
    install_template(control, monkeypatch, scene, (600, 300, 700, 380))
    calls = count_stretches(monkeypatch)

    control.begin_frame()
    for _ in range(10):
        control.match("tpl", delay=0)
    control.end_frame()

    assert len(calls) == 1, "stretched %d times for one frame" % len(calls)


def test_a_reference_sized_window_is_never_stretched(monkeypatch, scene):
    """The everyday path must pay nothing at all."""
    control = make_control(monkeypatch, tuple(REF), scene)
    install_template(control, monkeypatch, scene, (600, 300, 700, 380))
    calls = count_stretches(monkeypatch)

    control.begin_frame()
    control.match("tpl", delay=0)
    control.end_frame()

    assert calls == []


def test_dropping_the_frame_drops_the_stretched_copy_too(monkeypatch, scene):
    """Otherwise a stale stretch outlives the frame it was made from."""
    control = make_control(monkeypatch, (898, 507), scene)
    install_template(control, monkeypatch, scene, (600, 300, 700, 380))

    control.begin_frame()
    control.match("tpl", delay=0)
    assert control._scaled_cache
    control.invalidate_frame()

    assert not control._scaled_cache

# ── every copy, not just the best one ───────────────────────────────────────


@pytest.fixture
def three_markers():
    """A scene carrying three equally good copies of the same marker.

    Which is the shape of a raid board: nine opponent cards, all matching the
    same template, none of them a better match for any reason that matters.
    """
    rng = np.random.default_rng(11)
    picture = rng.integers(0, 255, (REF[1], REF[0], 3), dtype=np.uint8)
    for x, y in ((200, 150), (600, 150), (200, 400)):
        cv2.rectangle(picture, (x, y), (x + 100, y + 80), (255, 255, 255), -1)
        cv2.rectangle(picture, (x + 20, y + 20), (x + 80, y + 60), (0, 0, 0), -1)
    return picture


def test_find_all_answers_with_one_point_per_copy(monkeypatch, three_markers):
    """`match` returns the single global best, and that is the wrong shape here.

    On a live raid board every card scored between 0.943 and 0.990, so the same
    one won every pass — which is how a barrier somebody else had already broken
    got attacked nine times, dismissed, and picked again, for as long as the task
    was left running.
    """
    control = make_control(monkeypatch, tuple(REF), three_markers)
    install_template(control, monkeypatch, three_markers, (200, 150, 300, 230))

    found = control.find_all("x", threshold=0.9, delay=0)

    assert len(found) == 3, "matched %d copies of three: %s" % (len(found), found)


def test_find_all_comes_back_in_reading_order(monkeypatch, three_markers):
    """Deterministic order is the point: the caller walks the list.

    Left to right, then top to bottom — so the first two cards on a board get
    their turn instead of being permanently outscored by a third.
    """
    control = make_control(monkeypatch, tuple(REF), three_markers)
    install_template(control, monkeypatch, three_markers, (200, 150, 300, 230))

    found = control.find_all("x", threshold=0.9, delay=0)

    assert found == sorted(found, key=lambda p: (p[1] // 40, p[0]))
    assert found[0][1] < found[-1][1], "the lower row did not come last"


def test_find_all_answers_in_window_pixels(monkeypatch, three_markers):
    """Same rule as `match`: a point left in stretched space clicks beside it."""
    client = (1063, 599)
    control = make_control(monkeypatch, client, three_markers)
    install_template(control, monkeypatch, three_markers, (200, 150, 300, 230))

    found = control.find_all("x", threshold=0.9, delay=0)

    assert found, "nothing matched at all"
    for x, y in found:
        assert 0 <= x < client[0] and 0 <= y < client[1], (x, y)


def test_find_all_is_empty_when_nothing_matches(monkeypatch, three_markers):
    """A template of something not on screen finds nothing, rather than the
    closest patch of noise."""
    control = make_control(monkeypatch, tuple(REF), three_markers)
    absent = np.zeros((40, 40), dtype=np.uint8)
    absent[10:30, 10:30] = 128            # a flat grey square: nowhere in the scene
    monkeypatch.setattr(control, "_template", lambda path, gray: absent)

    assert control.find_all("x", threshold=0.9, delay=0) == []
