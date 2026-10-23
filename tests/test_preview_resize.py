"""A screenshot is taken at the size the window has now.

Reported: after Alt+Enter to full screen, the screenshot button "still takes the
old size". The control behind a window's thumbnail is kept for as long as the
window is listed, and it was measured once, when it was made.
"""
from __future__ import annotations

from conftest import bare_control

OLD = (1136, 640, 1152, 679)
FULL = (1920, 1080, 1920, 1080)


def control_now(monkeypatch, metrics):
    control = bare_control(client=OLD[:2])
    control.window_width, control.window_height = OLD[2:]
    now = {"metrics": metrics}
    closed = []
    monkeypatch.setattr(control, "_read_metrics", lambda: now["metrics"])
    monkeypatch.setattr(control, "close", lambda: closed.append(True))
    monkeypatch.setattr(control, "full_shot",
                        lambda gray=False: (control.client_width, control.client_height))
    return control, closed


def test_a_window_gone_full_screen_is_captured_at_its_new_size(monkeypatch):
    control, closed = control_now(monkeypatch, FULL)

    assert control.preview() == FULL[:2]
    assert closed, "the bitmaps made at the old size were kept"


def test_a_window_that_has_not_changed_keeps_its_bitmaps(monkeypatch):
    """Two Win32 calls per thumbnail, and nothing torn down when nothing moved."""
    control, closed = control_now(monkeypatch, OLD)

    assert control.preview() == OLD[:2]
    assert closed == []


def test_the_borders_follow_the_new_size(monkeypatch):
    control, _ = control_now(monkeypatch, FULL)
    control.preview()

    assert (control.border_left, control.border_top) == (0, 0)
