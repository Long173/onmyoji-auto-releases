"""The coordinate picker.

The picker exists so nobody has to guess a number, which makes its arithmetic
the whole of its correctness: a click that resolves one pixel out is a click on
something else, and there is nothing on screen to reveal it. So the mapping is
pinned in both directions, at 1:1 and scaled down, and at the edges where the
loupe has to shift instead of shrink.

The warning is tested too. It is the only thing standing between a badly placed
point and a purchase button, and a warning that fails to appear is worse than
no warning at all, because the picker looks like it is checking.
"""
from __future__ import annotations

import math
from typing import Tuple

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from PyQt5 import QtCore, QtGui  # noqa: E402

import geometry  # noqa: E402
from ui import point_picker  # noqa: E402
from ui.point_picker import (LOUPE_SOURCE, LOUPE_ZOOM, PointPicker,  # noqa: E402
                            _Canvas, loupe_corner, loupe_origin)

REFERENCE = geometry.REFERENCE_CLIENT_SIZE


def canvas(qt_app, size: Tuple[int, int] = REFERENCE,
           point: Tuple[int, int] = (10, 10),
           max_size: Tuple[int, int] = REFERENCE) -> _Canvas:
    """A canvas with the cap pinned, so a test does not depend on the screen.

    Left to itself the cap comes from whatever monitor the suite happens to run
    on, which would make the scale — and every assertion about it — different
    on the build machine than on a laptop.
    """
    pixmap = QtGui.QPixmap(*size)
    pixmap.fill(QtGui.QColor("#402010"))
    return _Canvas(pixmap, point, max_size=max_size)


# ── mapping ─────────────────────────────────────────────────────────────────


def test_at_one_to_one_a_widget_position_is_the_game_pixel(qt_app):
    """The usual case: the frame fits, so nothing sits between click and pixel."""
    board = canvas(qt_app)
    assert board._scale == 1.0
    assert board._to_game(QtCore.QPoint(1030, 549)) == (1030, 549)


@pytest.mark.parametrize("point", [(0, 0), (1, 1), (500, 300),
                                   (1030, 549), (1121, 632)])
def test_a_point_survives_the_round_trip(qt_app, point):
    """Drawn where it was picked, and picked where it was drawn."""
    board = canvas(qt_app)
    widget = board._to_widget(point)
    assert board._to_game(QtCore.QPoint(int(widget.x()), int(widget.y()))) == point


@pytest.mark.parametrize("point", [(0, 0), (100, 60), (1121, 632)])
def test_scaled_down_the_round_trip_is_off_by_no_more_than_one_screen_pixel(
        qt_app, point):
    """On a small screen the picture shrinks, and precision shrinks with it.

    At half scale two game pixels share one screen pixel, so the mouse simply
    cannot name them both — the round trip is exact only at 1:1. What must hold
    is that the error stays within that one screen pixel and does not grow with
    distance from the origin, which is what a scale applied on one side only
    would do. The arrow keys are what reach the pixels the mouse cannot.
    """
    board = canvas(qt_app, max_size=(561, 316))
    assert board._scale < 1.0, "the picture was not scaled; the test proves nothing"
    tolerance = math.ceil(1 / board._scale)
    widget = board._to_widget(point)
    got = board._to_game(QtCore.QPoint(int(widget.x()), int(widget.y())))
    assert abs(got[0] - point[0]) <= tolerance
    assert abs(got[1] - point[1]) <= tolerance


def test_the_picture_is_sized_to_fit_the_screen_it_is_shown_on(qt_app):
    """A dialog taller than the screen puts its own buttons out of reach."""
    cap = point_picker.canvas_cap()
    assert cap[0] <= point_picker.MAX_CANVAS[0]
    assert cap[1] <= point_picker.MAX_CANVAS[1]

    board = canvas(qt_app, max_size=(561, 316))
    assert board.width() <= 561 and board.height() <= 316


def test_a_click_outside_the_picture_is_pulled_back_inside(qt_app):
    """Rounding at the far edge must not name a pixel that does not exist."""
    board = canvas(qt_app)
    assert board._to_game(QtCore.QPoint(99999, 99999)) == (REFERENCE[0] - 1,
                                                           REFERENCE[1] - 1)
    assert board._to_game(QtCore.QPoint(-40, -40)) == (0, 0)


# ── nudging ─────────────────────────────────────────────────────────────────


def test_an_arrow_key_moves_exactly_one_pixel(qt_app):
    board = canvas(qt_app, point=(500, 300))
    board.nudge(1, 0)
    assert board.point == (501, 300)
    board.nudge(0, -1)
    assert board.point == (501, 299)


def test_nudging_stops_at_the_edge(qt_app):
    board = canvas(qt_app, point=(0, 0))
    board.nudge(-10, -10)
    assert board.point == (0, 0)


# ── the loupe ───────────────────────────────────────────────────────────────


def test_the_loupe_is_centred_when_there_is_room(qt_app):
    origin = loupe_origin((500, 300), REFERENCE)
    assert origin == (500 - LOUPE_SOURCE // 2, 300 - LOUPE_SOURCE // 2)


@pytest.mark.parametrize("point", [(0, 0), (3, 2), (1121, 632), (1118, 630)])
def test_the_loupe_stays_inside_the_frame_at_every_corner(point):
    """Shifted, never shrunk — so the magnified box is always the same size."""
    x, y = loupe_origin(point, REFERENCE)
    assert 0 <= x <= REFERENCE[0] - LOUPE_SOURCE
    assert 0 <= y <= REFERENCE[1] - LOUPE_SOURCE


@pytest.mark.parametrize("point", [(0, 0), (3, 2), (500, 300), (1121, 632)])
def test_the_pixel_being_pointed_at_is_inside_the_loupe(point):
    """The highlight is drawn from this offset, so it has to land in the box.

    At an edge the offset is not the middle, which is the case that would go
    wrong if the highlight assumed a centred box — and an edge is exactly where
    a start button in the corner of the screen gets picked.
    """
    x0, y0 = loupe_origin(point, REFERENCE)
    assert 0 <= point[0] - x0 < LOUPE_SOURCE
    assert 0 <= point[1] - y0 < LOUPE_SOURCE


SIZE = LOUPE_SOURCE * LOUPE_ZOOM
CANVAS = tuple(REFERENCE)


@pytest.mark.parametrize("anchor,corner", [
    # cursor bottom right -> loupe top left, and so on round the picture
    ((1030, 549), (0, 0)),
    ((100, 60), (CANVAS[0] - SIZE, CANVAS[1] - SIZE)),
    ((1030, 60), (0, CANVAS[1] - SIZE)),
    ((100, 549), (CANVAS[0] - SIZE, 0)),
])
def test_the_loupe_parks_in_the_corner_furthest_from_the_cursor(anchor, corner):
    assert loupe_corner(anchor, CANVAS, SIZE) == corner


def test_the_loupe_never_covers_what_is_being_aimed_at(qt_app):
    """The target is a button in the bottom right, so this is the case that counts.

    A loupe that trailed the cursor sat on top of the start button every time,
    which is what this replaced.
    """
    board = canvas(qt_app, point=(1030, 549))
    left, top = loupe_corner((1030.0, 549.0), (board.width(), board.height()), SIZE)
    box = QtCore.QRect(left, top, SIZE, SIZE)
    assert not box.contains(1030, 549)


def test_the_loupe_stays_within_the_picture_wherever_it_parks(qt_app):
    board = canvas(qt_app)
    for anchor in ((0.0, 0.0), (1121.0, 632.0), (560.0, 316.0)):
        left, top = loupe_corner(anchor, (board.width(), board.height()), SIZE)
        assert 0 <= left <= board.width() - SIZE
        assert 0 <= top <= board.height() - SIZE


# ── the warning ─────────────────────────────────────────────────────────────


def blank_frame(size=REFERENCE):
    import numpy as np

    return np.zeros((size[1], size[0], 3), dtype=np.uint8)


def picker(qt_app, point, frame=None, danger=geometry.EVENT_SHOP_PANEL):
    """The picker as the event field configures it — danger zone included.

    The zone is a property of the field asking for the point, not of the dialog,
    so it has to be passed in the same way the app passes it. A picker built
    without one warns about nothing, which is what a chapter row wants.
    """
    return PointPicker(point, lambda: frame, geometry.EVENT_CLICK_POINT,
                       danger=danger,
                       danger_note="... nút mua bằng ngọc ...")


def test_the_default_point_raises_no_warning(qt_app):
    """It was chosen to sit outside the shop panel; say so in a test."""
    dialog = picker(qt_app, geometry.EVENT_CLICK_POINT, blank_frame())
    assert not dialog._warning.isVisible()
    dialog.deleteLater()


def test_a_point_inside_the_shop_panel_warns(qt_app):
    """Where the buy buttons appear once the tickets run out."""
    (x1, y1), (x2, y2) = geometry.EVENT_SHOP_PANEL
    middle = ((x1 + x2) // 2, (y1 + y2) // 2)
    dialog = picker(qt_app, middle, blank_frame())
    dialog.show()
    try:
        assert dialog._warning.isVisible(), (
            "no warning for %s, which is inside the shop panel %s"
            % (middle, geometry.EVENT_SHOP_PANEL)
        )
        assert "ngọc" in dialog._warning.text()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_a_picker_with_no_danger_zone_never_warns(qt_app):
    """A chapter row is not near anything that spends money."""
    (x1, y1), (x2, y2) = geometry.EVENT_SHOP_PANEL
    dialog = picker(qt_app, ((x1 + x2) // 2, (y1 + y2) // 2), blank_frame(),
                    danger=None)
    dialog.show()
    try:
        assert not dialog._warning.isVisible()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_the_warning_follows_the_point_as_it_moves(qt_app):
    (x1, y1), (x2, y2) = geometry.EVENT_SHOP_PANEL
    dialog = picker(qt_app, geometry.EVENT_CLICK_POINT, blank_frame())
    dialog.show()
    try:
        dialog._set_point(((x1 + x2) // 2, (y1 + y2) // 2))
        assert dialog._warning.isVisible()
        dialog._set_point(geometry.EVENT_CLICK_POINT)
        assert not dialog._warning.isVisible()
    finally:
        dialog.close()
        dialog.deleteLater()


# ── frames ──────────────────────────────────────────────────────────────────


def test_a_frame_of_another_size_is_normalised_to_the_reference(qt_app):
    """One saved number has to mean one place, whatever window it was picked on."""
    dialog = picker(qt_app, (10, 10), blank_frame((561, 316)))
    assert dialog._canvas is not None
    assert (dialog._canvas._pixmap.width(),
            dialog._canvas._pixmap.height()) == tuple(REFERENCE)
    dialog.deleteLater()


def test_with_no_game_window_it_says_so_and_keeps_the_point(qt_app):
    """Better than a dead button: the point survives and can still be cancelled."""
    dialog = picker(qt_app, (321, 123), None)
    assert dialog._canvas is None
    assert dialog.point() == (321, 123)
    dialog.deleteLater()


def test_a_capture_that_raises_is_treated_as_no_window(qt_app):
    """The preview grab talks to Windows; it is allowed to fail."""
    def explode():
        raise RuntimeError("window vanished")

    dialog = PointPicker((321, 123), explode, geometry.EVENT_CLICK_POINT)
    assert dialog._canvas is None
    assert dialog.point() == (321, 123)
    dialog.deleteLater()
