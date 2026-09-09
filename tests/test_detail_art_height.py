"""The portrait frame in the detail page should be as tall as the picture.

PORTRAIT_HEIGHT is 300 and was set for the artwork that used to be there. The
avatars captured from the game are about 1.40 wide to tall, so in the detail
column — 272px of usable width, measured — they draw 272x192 inside a 300-tall
frame and leave 107px of empty inset below. Reported as "dư ra 1 khúc ở height".

A fixed number cannot fix it: the column is allowed to shrink to
PORTRAIT_COLUMN_MIN, so any height computed for the wide case is wrong for the
narrow one. The frame has to follow its own width.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from PyQt5 import QtGui, QtWidgets  # noqa: E402

from ui.primitives import HatchFrame  # noqa: E402


def pixmap(width, height):
    made = QtGui.QPixmap(width, height)
    made.fill(QtGui.QColor("#804020"))
    return made


def asked(frame, width):
    """What the frame tells its layout it needs at that width.

    heightForWidth rather than the realised geometry: a widget that has not
    been shown gets no resize event — Qt holds it until the first show — so
    reading .height() here would only ever report the height it was built
    with. That is what broke the first version of this feature, which
    recomputed in resizeEvent and therefore did nothing until a window was up.
    """
    return frame.heightForWidth(width)


def test_the_frame_takes_the_height_the_picture_needs(qt_app):
    frame = HatchFrame("art", hug=True, hug_min=300)
    frame.set_pixmap(pixmap(143, 102))

    want = round(272 * 102 / 143)
    assert abs(asked(frame, 272) - want) <= 2, (
        "272 wide at 143:102 wants %d tall, got %d" % (want, asked(frame, 272))
    )


def test_a_narrower_column_gets_a_shorter_frame(qt_app):
    """The reason a constant cannot do this: the column may shrink to
    PORTRAIT_COLUMN_MIN."""
    frame = HatchFrame("art", hug=True, hug_min=300)
    frame.set_pixmap(pixmap(143, 102))

    assert asked(frame, 190) < asked(frame, 272)


def test_without_a_picture_the_placeholder_keeps_its_height(qt_app):
    """The hatched placeholder is all there is to see when an image is
    missing, and it needs room to be seen."""
    frame = HatchFrame("art", hug=True, hug_min=300)

    assert asked(frame, 272) == 300


def test_a_tall_picture_cannot_take_over_the_page(qt_app):
    """Hugging a portrait-shaped image would push the stats below the fold."""
    frame = HatchFrame("art", hug=True, hug_min=300)
    frame.set_pixmap(pixmap(100, 900))

    assert asked(frame, 272) <= HatchFrame.HUG_MAX_HEIGHT


def test_the_layout_is_told_to_use_it(qt_app):
    """A height nobody asks for changes nothing: the size policy has to
    declare it or QBoxLayout never calls heightForWidth."""
    frame = HatchFrame("art", hug=True, hug_min=300)

    assert frame.hasHeightForWidth()
    assert frame.sizePolicy().hasHeightForWidth()


def test_hugging_is_off_unless_asked(qt_app):
    """Every other HatchFrame in the app sizes itself from its layout, and the
    card grids in particular set an exact height on purpose."""
    frame = HatchFrame("art")
    frame.set_pixmap(pixmap(143, 102))

    assert not frame.hasHeightForWidth()
    assert frame.heightForWidth(272) == -1
