"""Edge resizing on the frameless window.

The window draws its own chrome, so with `FramelessWindowHint` there are no
system resize grips. Two earlier attempts stand behind these tests:

* The first handled the right and bottom edges from Qt mouse events. Hovering
  the top or left edge did nothing at all.
* The second added the other two, but every edge still only worked in the
  *outer* half of its band — the half lying in the transparent margin. Inside
  the frame the cursor is over a child widget, and a child without mouse
  tracking swallows the move rather than passing it up. Once the drop shadow
  went, that margin was 8px of invisible nothing and the grip was unfindable.

What is here now answers `WM_NCHITTEST` instead, so Windows resizes the window
itself. Qt draws every child into the one top-level HWND, so a hit test on that
window covers the whole surface — children included — and the cursor shapes,
edge dragging and snapping come from the system rather than being reimplemented.
"""
from __future__ import annotations

import pytest

QtCore = pytest.importorskip("PyQt5.QtCore")
win32con = pytest.importorskip("win32con")

from ui import chrome  # noqa: E402

LEFT = QtCore.Qt.LeftEdge
RIGHT = QtCore.Qt.RightEdge
TOP = QtCore.Qt.TopEdge
BOTTOM = QtCore.Qt.BottomEdge


@pytest.fixture
def window(qt_app):
    made = chrome.FramelessWindow("thu")
    made.resize(600, 400)
    yield made
    made.deleteLater()


def on_edge(made, which):
    """A point on `which` edge of the window, in its own coordinates.

    Taken just *inside* the window now, which is the point of the change: the
    grip is on the visible edge rather than in a margin outside it.
    """
    rect = made.rect()
    x, y = rect.center().x(), rect.center().y()
    if which & LEFT:
        x = rect.left() + 1
    if which & RIGHT:
        x = rect.right() - 1
    if which & TOP:
        y = rect.top() + 1
    if which & BOTTOM:
        y = rect.bottom() - 1
    return QtCore.QPoint(x, y)


@pytest.mark.parametrize(
    "which",
    [LEFT, RIGHT, TOP, BOTTOM,
     LEFT | TOP, RIGHT | TOP, LEFT | BOTTOM, RIGHT | BOTTOM],
)
def test_every_edge_and_corner_is_recognised(window, which):
    assert window._edge_at(on_edge(window, which)) == which


def test_the_middle_is_not_an_edge(window):
    """Anything but an edge has to fall through to the interface underneath."""
    assert window._edge_at(window.rect().center()) == 0
    assert window._hit_code(0) is None


@pytest.mark.parametrize(
    "which, code",
    [(LEFT, win32con.HTLEFT),
     (RIGHT, win32con.HTRIGHT),
     (TOP, win32con.HTTOP),
     (BOTTOM, win32con.HTBOTTOM),
     (LEFT | TOP, win32con.HTTOPLEFT),
     (RIGHT | TOP, win32con.HTTOPRIGHT),
     (LEFT | BOTTOM, win32con.HTBOTTOMLEFT),
     (RIGHT | BOTTOM, win32con.HTBOTTOMRIGHT)],
)
def test_each_edge_answers_with_its_own_hit_code(window, which, code):
    """Windows takes the cursor and the drag from this answer, so the corners
    have to be right: a swapped pair resizes the opposite side."""
    assert window._hit_code(which) == code


def test_the_grip_reaches_over_the_title_bar(window):
    """The top band lies across the caption, which is a child widget.

    Under the old mouse-event scheme that made the top edge unreachable — the
    title bar received the move and kept it. A hit test does not care which
    child is painted there.
    """
    top_of_bar = QtCore.QPoint(window.rect().center().x(), 1)

    assert window._edge_at(top_of_bar) == TOP


def test_the_window_has_no_drop_shadow_and_no_margin(window):
    """Removed on request, and with it the margin it used to live in.

    The margin only ever existed to catch mouse events the children swallowed;
    the hit test needs none of it.
    """
    assert window._frame.graphicsEffect() is None
    assert window.layout().contentsMargins().top() == 0
