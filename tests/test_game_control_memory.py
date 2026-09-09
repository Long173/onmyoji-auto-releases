"""What a capture holds on to.

A frame of the game client is ~2 MB, and the loop takes one every pass on every
window. Nothing here talks to Windows: the GDI half is stubbed and only the
book-keeping around the buffers is exercised — which is where a leak would be.
"""
from __future__ import annotations

import numpy as np
import pytest

import game_control
from game_control import GameControl

CLIENT = (1136, 640)


@pytest.fixture
def control(monkeypatch):
    """A GameControl whose capture returns a fresh array without touching GDI."""
    monkeypatch.setattr(GameControl, "_measure_window", lambda self: None)
    from conftest import bare_control

    made = bare_control(client=CLIENT)

    grabs = []

    def fake_grab(gray):
        frame = (
            np.zeros((made.client_height, made.client_width), dtype=np.uint8)
            if gray
            else np.zeros((made.client_height, made.client_width, 3), dtype=np.uint8)
        )
        grabs.append(gray)
        if not gray:
            made._last_frame = frame
        return frame

    monkeypatch.setattr(made, "_grab", fake_grab)
    made.grabs = grabs
    return made


# ── one pass ────────────────────────────────────────────────────────────────


def test_a_pass_captures_once_however_many_reads_it_does(control):
    """The whole point of the cache: a dozen template reads, one screen grab."""
    control.begin_frame()
    for _ in range(6):
        control.full_shot(gray=True)
        control.full_shot(gray=False)
    control.end_frame()

    assert control.grabs.count(False) == 1
    assert control.grabs.count(True) == 0, "greyscale is derived, not grabbed again"


def test_the_colour_frame_and_last_frame_are_one_buffer(control):
    """Not a copy — otherwise every pass would hold two frames instead of one."""
    control.begin_frame()
    colour = control.full_shot(gray=False)

    assert control.last_frame() is colour


def test_ending_a_pass_drops_the_cache(control):
    control.begin_frame()
    control.full_shot(gray=False)
    control.full_shot(gray=True)
    assert len(control._frame_cache) == 2

    control.end_frame()

    assert control._frame_cache == {}


def test_the_last_frame_outlives_the_pass(control):
    """The thumbnail reads it between passes, when the cache is already gone."""
    control.begin_frame()
    control.full_shot(gray=False)
    control.end_frame()

    assert control.last_frame() is not None


# ── nothing accumulates ─────────────────────────────────────────────────────


def test_repeated_passes_hold_exactly_one_frame(control):
    """A pass that kept its frame would add ~2 MB per second, per window."""
    for _ in range(50):
        control.begin_frame()
        control.full_shot(gray=False)
        control.full_shot(gray=True)
        control.end_frame()

    assert control._frame_cache == {}
    held = [control.last_frame()]
    assert sum(f.nbytes for f in held if f is not None) < 3 * 1024 * 1024


def test_closing_releases_the_frames(control):
    """~2 MB per window would otherwise sit there until the object is dropped."""
    control.begin_frame()
    control.full_shot(gray=False)
    control.full_shot(gray=True)

    control.close()

    assert control.last_frame() is None
    assert control._frame_cache == {}


def test_closing_twice_is_harmless(control):
    control.begin_frame()
    control.full_shot(gray=False)
    control.close()
    control.close()

    assert control.last_frame() is None


def test_closing_before_any_capture_is_harmless(control):
    control.close()
    assert control.last_frame() is None


# ── nothing reaches disk ────────────────────────────────────────────────────


def test_the_raid_loop_never_writes_a_capture_to_disk():
    """save_shot exists for debugging; no code path calls it during a run."""
    import inspect
    from pathlib import Path

    source_root = Path(game_control.__file__).parent
    callers = []
    for path in source_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "save_shot" in line and "def save_shot" not in line:
                callers.append("%s: %s" % (path.name, line.strip()))

    assert not callers, "something writes captures to disk: %s" % callers
    assert inspect.isfunction(GameControl.save_shot), "the helper itself is gone"
