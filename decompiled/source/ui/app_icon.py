"""The app icon — "Dấu Kết Giới", from the Claude Design spec.

The source draws it in CSS with ``font-size: size/100`` and every measurement in
``em``, so one em is one percent of the icon's side. That unit is kept here as
``u``: the geometry constants below are the design's numbers unchanged.

Six layers, outermost first:

1. a rounded square filled with the window colour
2. a radial wash, lighter towards the top-left
3. a hairline frame just inside the rounded edge
4. a faint gold diamond outline
5. a bright gold diamond outline
6. a solid gold diamond with a small square punched out of its middle

Drawn vectorially at each size rather than scaled from one bitmap: at 16px a
downscaled 256px render turns the hairlines to mud.
"""
from __future__ import annotations

from typing import Tuple

from PyQt5 import QtCore, QtGui

import theme

# Sizes packed into the icon, matching the design's .ico list.
ICON_SIZES: Tuple[int, ...] = (16, 32, 48, 64, 128, 256)
DEFAULT_SIZE = 256

# ── geometry, in u (1u = 1% of the icon's side) ─────────────────────────────
CORNER_RADIUS = 12.0
FRAME_WIDTH = 1.5
FAINT_INSET = 20.0
FAINT_WIDTH = 1.4
BRIGHT_INSET = 27.0
BRIGHT_WIDTH = 1.8
CENTRE_SIDE = 18.0
HOLE_SIDE = 6.4

# ── colour ──────────────────────────────────────────────────────────────────
BASE = theme.WINDOW              # #171614
FRAME = "#332d24"
GRADIENT_INNER = "#211e1a"
GRADIENT_OUTER = "#141311"
GRADIENT_CENTRE = (30.0, 20.0)   # u, from the top-left
GRADIENT_RADIUS = 120.0          # u
GRADIENT_OUTER_STOP = 0.70
FAINT_ALPHA = 77                 # rgba(201, 161, 92, .30)


def _rounded_path(size: int, unit: float) -> QtGui.QPainterPath:
    path = QtGui.QPainterPath()
    radius = CORNER_RADIUS * unit
    path.addRoundedRect(QtCore.QRectF(0, 0, size, size), radius, radius)
    return path


def _stroke_square(painter: QtGui.QPainter, inset_u: float, width_u: float,
                   colour: QtGui.QColor, unit: float) -> None:
    """A CSS-style outlined box, centred on the origin and already rotated.

    CSS draws a border inside the box, so the stroke's centre line sits half a
    stroke in from the edge — hence the ``- stroke`` below.
    """
    side = (100.0 - 2.0 * inset_u) * unit
    stroke = width_u * unit
    painter.setPen(QtGui.QPen(colour, stroke))
    painter.setBrush(QtCore.Qt.NoBrush)
    half = (side - stroke) / 2.0
    painter.drawRect(QtCore.QRectF(-half, -half, half * 2.0, half * 2.0))


def _fill_square(painter: QtGui.QPainter, side_u: float, colour: QtGui.QColor,
                 unit: float) -> None:
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(colour)
    half = side_u * unit / 2.0
    painter.drawRect(QtCore.QRectF(-half, -half, half * 2.0, half * 2.0))


def render(size: int = DEFAULT_SIZE) -> QtGui.QPixmap:
    """Draw the icon at ``size`` pixels."""
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.transparent)

    unit = size / 100.0
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)

    outline = _rounded_path(size, unit)
    painter.setClipPath(outline)

    painter.fillPath(outline, QtGui.QColor(BASE))
    wash = QtGui.QRadialGradient(
        QtCore.QPointF(GRADIENT_CENTRE[0] * unit, GRADIENT_CENTRE[1] * unit),
        GRADIENT_RADIUS * unit,
    )
    wash.setColorAt(0.0, QtGui.QColor(GRADIENT_INNER))
    wash.setColorAt(GRADIENT_OUTER_STOP, QtGui.QColor(GRADIENT_OUTER))
    wash.setColorAt(1.0, QtGui.QColor(GRADIENT_OUTER))
    painter.fillPath(outline, QtGui.QBrush(wash))

    # The frame follows the rounded edge, so it is drawn before the rotation.
    frame_inset = FRAME_WIDTH * unit / 2.0
    painter.setPen(QtGui.QPen(QtGui.QColor(FRAME), FRAME_WIDTH * unit))
    painter.setBrush(QtCore.Qt.NoBrush)
    radius = CORNER_RADIUS * unit - frame_inset
    painter.drawRoundedRect(
        QtCore.QRectF(
            frame_inset, frame_inset, size - 2 * frame_inset, size - 2 * frame_inset
        ),
        radius,
        radius,
    )

    painter.translate(size / 2.0, size / 2.0)
    painter.rotate(45)

    accent = QtGui.QColor(theme.ACCENT)
    faint = QtGui.QColor(accent)
    faint.setAlpha(FAINT_ALPHA)

    _stroke_square(painter, FAINT_INSET, FAINT_WIDTH, faint, unit)
    _stroke_square(painter, BRIGHT_INSET, BRIGHT_WIDTH, accent, unit)
    _fill_square(painter, CENTRE_SIDE, accent, unit)
    _fill_square(painter, HOLE_SIDE, QtGui.QColor(BASE), unit)

    painter.end()
    return pixmap


def build_icon() -> QtGui.QIcon:
    """A QIcon carrying a crisp pixmap for every size Windows asks for."""
    icon = QtGui.QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(render(size))
    return icon
