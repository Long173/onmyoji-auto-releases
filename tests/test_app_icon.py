"""The app icon, "Dấu Kết Giới".

Drawn vectorially at each size from the Claude Design spec. The geometry
constants are the design's own numbers in its own unit (1u = 1% of the side),
so these tests check the drawing holds together rather than re-deriving them.
"""
from __future__ import annotations

import pytest

QtGui = pytest.importorskip("PyQt5.QtGui")

from ui import app_icon  # noqa: E402


def colour_at(image, x, y):
    return QtGui.QColor(image.pixel(x, y))


def alpha_at(image, x, y):
    return QtGui.QColor.fromRgba(image.pixel(x, y)).alpha()


@pytest.fixture(scope="module")
def large(qt_app):
    return app_icon.render(256).toImage()


# ── shape ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("size", app_icon.ICON_SIZES)
def test_renders_at_every_packed_size(qt_app, size):
    pixmap = app_icon.render(size)
    assert not pixmap.isNull()
    assert pixmap.width() == size and pixmap.height() == size


def test_corners_are_rounded_away(large):
    """The design gives it a 12u corner radius, so the corner pixel is empty."""
    for x, y in ((0, 0), (255, 0), (0, 255), (255, 255)):
        assert alpha_at(large, x, y) == 0, "corner (%d,%d) is not transparent" % (x, y)


def test_the_middle_is_opaque(large):
    assert alpha_at(large, 128, 128) == 255


# ── the design's marks ──────────────────────────────────────────────────────


def test_the_centre_diamond_is_gold_with_a_hole(large):
    """A solid gold diamond with a small square punched out of its middle."""
    import theme

    hole = colour_at(large, 128, 128)
    assert hole.name().lower() == theme.WINDOW.lower(), (
        "the middle should be punched out, got %s" % hole.name()
    )

    # 6u out from the centre is inside the gold diamond but outside the hole.
    gold = colour_at(large, 128 + int(6.0 * 2.56), 128)
    assert gold.name().lower() == theme.ACCENT.lower(), (
        "expected the accent beside the hole, got %s" % gold.name()
    )


def test_the_accent_appears_across_the_icon(large):
    """Three separate gold marks: two outlines and the centre."""
    import theme

    accent = QtGui.QColor(theme.ACCENT)
    hits = 0
    for x in range(0, 256, 2):
        pixel = colour_at(large, x, 128)
        if abs(pixel.red() - accent.red()) < 12 and abs(pixel.green() - accent.green()) < 12:
            hits += 1
    assert hits > 6, "the gold marks are missing or too faint (%d hits)" % hits


def test_it_is_not_a_flat_block(large):
    shades = {large.pixel(x, y) for x in range(0, 256, 4) for y in range(0, 256, 4)}
    assert len(shades) > 20, "the icon has almost no detail"


def test_the_wash_is_lighter_towards_the_top_left(large):
    """radial-gradient(... at 30% 20%, #211e1a, #141311)."""
    near = colour_at(large, 77, 51)     # 30%, 20%
    far = colour_at(large, 230, 230)    # opposite corner, inside the rounding
    assert near.lightness() > far.lightness(), (
        "the gradient runs the wrong way: %s vs %s" % (near.name(), far.name())
    )


# ── packaging ───────────────────────────────────────────────────────────────


def test_the_icon_carries_every_size(qt_app):
    icon = app_icon.build_icon()
    assert not icon.isNull()

    available = {size.width() for size in icon.availableSizes()}
    assert available == set(app_icon.ICON_SIZES), (
        "packed sizes %s do not match %s" % (sorted(available), app_icon.ICON_SIZES)
    )


def test_small_sizes_keep_the_gold(qt_app):
    """At 16px the strokes are sub-pixel; the mark must still read."""
    import theme

    image = app_icon.render(16).toImage()
    accent = QtGui.QColor(theme.ACCENT)
    golden = [
        (x, y)
        for x in range(16)
        for y in range(16)
        if colour_at(image, x, y).red() > accent.red() * 0.6
        and colour_at(image, x, y).blue() < accent.blue() * 1.6
    ]
    assert golden, "the 16px icon has no visible gold left"
