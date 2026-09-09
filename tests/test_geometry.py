"""Coordinate scaling between the reference client size and the real window."""
from __future__ import annotations

import pytest

import geometry
import realm_raid
from geometry import Geometry

# Every hard-coded point the raid presses blind, named so a failure says which
# one. Listed here rather than derived from the module so that adding a point
# without measuring it is a visible change to this file.
FIXED_POINTS = (
    ("Ready button", geometry.TAP_READY_BUTTON),
    ("popup dismiss", geometry.POPUP_DISMISS_POINT),
)


def test_reference_size_is_an_identity_transform():
    # Arrange
    geo = Geometry(*geometry.REFERENCE_CLIENT_SIZE)

    # Act / Assert
    assert geo.is_reference_size
    assert geo.scale == (1.0, 1.0)
    for name, point in FIXED_POINTS:
        assert geo.point(point) == point, "%s moved at reference size" % name


def test_points_scale_with_a_larger_client_area():
    # Arrange - twice the reference width and height
    ref_w, ref_h = geometry.REFERENCE_CLIENT_SIZE
    geo = Geometry(ref_w * 2, ref_h * 2)

    # Act
    scaled = geo.point((100, 50))

    # Assert
    assert not geo.is_reference_size
    assert scaled == (200, 100)


def test_region_scales_both_corners():
    ref_w, ref_h = geometry.REFERENCE_CLIENT_SIZE
    geo = Geometry(ref_w * 2, ref_h * 2)

    assert geo.region(((10, 20), (30, 40))) == ((20, 40), (60, 80))


def test_every_fixed_point_sits_inside_the_client_area():
    width, height = geometry.REFERENCE_CLIENT_SIZE

    for name, (x, y) in FIXED_POINTS:
        assert 0 <= x < width, "%s: x=%d is outside the client area" % (name, x)
        assert 0 <= y < height, "%s: y=%d is outside the client area" % (name, y)


def test_ticket_region_is_a_valid_rectangle():
    (x1, y1), (x2, y2) = geometry.TICKET_TEXT_REGION
    width, height = geometry.REFERENCE_CLIENT_SIZE

    assert x1 < x2 and y1 < y2
    assert x2 <= width and y2 <= height


def test_no_fixed_outer_window_size_is_declared():
    """The outer size is the client size plus whatever frame the machine has.

    A constant here was the bug: it baked one machine's 16x39 frame in, and on
    a 125% laptop, whose frame is 21x50, it left the client 10px short and the
    raid clicking at nothing.
    """
    assert not hasattr(geometry, "TARGET_WINDOW_SIZE")


# ── resizing the game window ────────────────────────────────────────────────
#
# The frame around a window is not a constant, and assuming it was is what
# broke the raid on a 125%-scaling laptop. These drive the real function
# against fake windows whose frames match machines actually measured.


class FakeWindow:
    """A window that resizes the way Windows does: outer set, client follows."""

    def __init__(self, frame, client, position=(100, 50), aspect_snap=0):
        self.frame_w, self.frame_h = frame
        self.client_w, self.client_h = client
        self.left, self.top = position
        # Some games nudge their own window afterwards to hold a ratio; this
        # shaves a pixel off the height the first time, like that behaviour.
        self.aspect_snap = aspect_snap
        self.moves = []

    def GetWindowRect(self, _hwnd):
        return (
            self.left, self.top,
            self.left + self.client_w + self.frame_w,
            self.top + self.client_h + self.frame_h,
        )

    def GetClientRect(self, _hwnd):
        return (0, 0, self.client_w, self.client_h)

    def MoveWindow(self, _hwnd, left, top, width, height, _repaint):
        self.moves.append((left, top, width, height))
        self.left, self.top = left, top
        self.client_w = width - self.frame_w
        self.client_h = height - self.frame_h
        if self.aspect_snap:
            self.client_h -= self.aspect_snap
            self.aspect_snap = 0


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(realm_raid.time, "sleep", lambda _s: None)


def resize_with(window, monkeypatch):
    monkeypatch.setattr(realm_raid.win32gui, "GetWindowRect", window.GetWindowRect)
    monkeypatch.setattr(realm_raid.win32gui, "GetClientRect", window.GetClientRect)
    monkeypatch.setattr(realm_raid.win32gui, "MoveWindow", window.MoveWindow)
    realm_raid.resize_game_window(0xABC)
    return (window.client_w, window.client_h)


def test_resize_lands_the_client_on_the_reference_size(monkeypatch, no_sleep):
    """The machine the templates were cut on: a 16x39 frame."""
    window = FakeWindow(frame=(16, 39), client=(1420, 800))

    assert resize_with(window, monkeypatch) == geometry.REFERENCE_CLIENT_SIZE


def test_resize_lands_the_client_on_the_reference_size_at_125_percent(
    monkeypatch, no_sleep
):
    """The laptop the raid failed on: the same frame at 125% is 21x50.

    The old code asked for a fixed 1138x672 outer size here and got a client of
    1117x623 — the actual failure, reproduced.
    """
    window = FakeWindow(frame=(21, 50), client=(1420, 800))

    assert resize_with(window, monkeypatch) == geometry.REFERENCE_CLIENT_SIZE


def test_the_outer_size_asked_for_includes_the_measured_frame(monkeypatch, no_sleep):
    window = FakeWindow(frame=(21, 50), client=(1420, 800))

    resize_with(window, monkeypatch)

    _left, _top, width, height = window.moves[0]
    assert (width, height) == (1122 + 21, 633 + 50)


def test_a_window_already_the_right_size_is_left_alone(monkeypatch, no_sleep):
    window = FakeWindow(frame=(16, 39), client=geometry.REFERENCE_CLIENT_SIZE)

    resize_with(window, monkeypatch)

    assert window.moves == [], "the window was moved for no reason"


def test_a_game_that_snaps_its_own_height_is_corrected(monkeypatch, no_sleep):
    """The game adjusts its window after ours; one pass is not always enough."""
    window = FakeWindow(frame=(16, 39), client=(1420, 800), aspect_snap=4)

    assert resize_with(window, monkeypatch) == geometry.REFERENCE_CLIENT_SIZE
    assert len(window.moves) == 2


def test_a_minimised_window_is_left_alone(monkeypatch, no_sleep):
    """GetClientRect reports 0x0 while minimised; resizing off that is nonsense."""
    window = FakeWindow(frame=(16, 39), client=(0, 0))

    resize_with(window, monkeypatch)

    assert window.moves == []


def test_a_game_that_refuses_the_size_is_reported(monkeypatch, no_sleep, caplog):
    """Silence here would leave every later template failure unexplained."""

    class Stubborn(FakeWindow):
        def MoveWindow(self, *args):
            self.moves.append(args[1:5])   # never actually changes size

    window = Stubborn(frame=(16, 39), client=(1420, 800))

    with caplog.at_level("WARNING"):
        resize_with(window, monkeypatch)

    assert "1420x800" in caplog.text and "1122x633" in caplog.text


def test_a_screen_too_small_for_the_scaling_says_so(monkeypatch, no_sleep, caplog):
    """At 175% the window needs 1992x1176 of real screen. On a 1080p display
    Windows clamps it, and 'the game is holding its aspect ratio' would send
    the user looking in entirely the wrong place."""

    class Clamped(FakeWindow):
        def MoveWindow(self, *args):
            self.moves.append(args[1:5])   # Windows refuses the size

    window = Clamped(frame=(16, 39), client=(1063, 599))
    monkeypatch.setattr(realm_raid.dpi, "scaling_percent", lambda _h: 175)
    monkeypatch.setattr(realm_raid.dpi, "screen_size", lambda: (1920, 1080))

    with caplog.at_level("WARNING"):
        resize_with(window, monkeypatch)

    assert "175%" in caplog.text
    assert "1920x1080" in caplog.text
    assert "scaling" in caplog.text.lower()
    assert "aspect ratio" not in caplog.text, "blamed the wrong thing"


def test_a_game_holding_its_aspect_ratio_is_still_reported_as_that(
    monkeypatch, no_sleep, caplog
):
    """Same symptom, different cause: here the window would fit fine."""

    class Stubborn(FakeWindow):
        def MoveWindow(self, *args):
            self.moves.append(args[1:5])

    window = Stubborn(frame=(16, 39), client=(1420, 800))
    monkeypatch.setattr(realm_raid.dpi, "scaling_percent", lambda _h: 100)
    monkeypatch.setattr(realm_raid.dpi, "screen_size", lambda: (1920, 1080))

    with caplog.at_level("WARNING"):
        resize_with(window, monkeypatch)

    assert "aspect ratio" in caplog.text
    assert "scaling" not in caplog.text.lower()


def test_an_unreadable_screen_size_does_not_break_the_warning(
    monkeypatch, no_sleep, caplog
):
    class Stubborn(FakeWindow):
        def MoveWindow(self, *args):
            self.moves.append(args[1:5])

    window = Stubborn(frame=(16, 39), client=(1420, 800))
    monkeypatch.setattr(realm_raid.dpi, "screen_size", lambda: (0, 0))

    with caplog.at_level("WARNING"):
        resize_with(window, monkeypatch)

    assert "1420x800" in caplog.text
