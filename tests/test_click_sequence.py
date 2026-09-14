"""The exact run of mouse messages a click posts.

A posted click does not move the real cursor, so the player's own cursor can be
sitting inside the game window while the loop works. Between the posted button
down and the posted button up the game believes the pointer is held — and every
genuine mouse move Windows delivers in that window reads to it as a drag.

Reported on the Event clicker, which presses once every two seconds for as long
as it runs: moving the mouse over the game, touching nothing, scrolled the view.
"""
from __future__ import annotations

import pytest

win32con = pytest.importorskip("win32con")

from game_control import GameControl  # noqa: E402


def make_control(hwnd=0x1234):
    from conftest import bare_control

    return bare_control(hwnd)


@pytest.fixture
def posted(monkeypatch):
    """Records the mouse messages a click posts, in order."""
    seen = []
    monkeypatch.setattr(GameControl, "_target_hwnd", lambda self, point: self.hwnd)
    monkeypatch.setattr(
        "game_control.win32gui.PostMessage",
        lambda hwnd, msg, wparam, lparam: seen.append((msg, wparam, lparam)),
    )
    monkeypatch.setattr("game_control.time.sleep", lambda _s: None)
    return seen


def test_the_pointer_is_put_back_before_the_button_is_released(posted):
    """The move before the release is what cancels an accidental drag.

    Whatever the player's own cursor dragged the view to while the button was
    held, the last thing the game is told before the release is that the pointer
    is back where the press began — so the drag nets out instead of leaving the
    view somewhere else.
    """
    make_control().click((875, 429))

    kinds = [msg for msg, _w, _l in posted]
    assert kinds == [win32con.WM_MOUSEMOVE, win32con.WM_LBUTTONDOWN,
                     win32con.WM_MOUSEMOVE, win32con.WM_LBUTTONUP]


def test_every_message_names_the_same_point(posted):
    """A click that presses in one place and releases in another is a drag."""
    make_control().click((875, 429))

    assert len({lparam for _m, _w, lparam in posted}) == 1, (
        "the messages disagree about where the click was"
    )


def test_the_button_is_only_held_down_for_the_press(posted):
    """Only the press carries the button flag; the moves and the release do not.

    A move that claims the button is down is a drag event in its own right.
    """
    holding = [msg for msg, wparam, _l in posted if wparam == win32con.MK_LBUTTON]

    make_control().click((875, 429))

    holding = [msg for msg, wparam, _l in posted if wparam == win32con.MK_LBUTTON]
    assert holding == [win32con.WM_LBUTTONDOWN]


# ── the player's own cursor ─────────────────────────────────────────────────


@pytest.fixture
def cursor(monkeypatch):
    """Places the real cursor on a desktop where the game is the only window.

    The game occupies (100, 100)-(700, 500) and nothing is drawn over it, so
    what the cursor is pointing at follows from where the cursor is. Which
    window is really on top is what decides the answer, and
    test_cursor_hold.py is where that is pinned down.
    """
    def place(x, y):
        monkeypatch.setattr("game_control.win32gui.GetCursorPos", lambda: (x, y))
        inside = 100 <= x < 700 and 100 <= y < 500
        monkeypatch.setattr("game_control.win32gui.WindowFromPoint",
                            lambda pos: 0x1234 if inside else 0x9999)
        monkeypatch.setattr("game_control.win32gui.GetAncestor",
                            lambda hwnd, flag: hwnd)

    return place


def test_no_click_is_sent_while_the_cursor_is_over_the_game(posted, cursor):
    """Returning the pointer made the drag net out; this removes it.

    Nothing can stop the game seeing the player's genuine mouse moves — the
    cursor is physically over the window. What can be stopped is the loop
    holding a button down underneath them, which is the half that turns a move
    into a drag.
    """
    cursor(400, 300)                      # inside (100, 100)-(700, 500)

    assert make_control().click((875, 429)) is False
    assert posted == [], "posted a click with the player's cursor over the game"


def test_a_click_is_sent_when_the_cursor_is_elsewhere(posted, cursor):
    cursor(50, 50)                        # outside the window

    assert make_control().click((875, 429)) is True
    assert posted, "skipped a click with the cursor nowhere near the game"


def test_the_pause_can_be_switched_off(posted, cursor, monkeypatch):
    """It is a setting, not a rule: somebody who wants the loop to keep going
    while they watch can have that."""
    cursor(400, 300)                      # inside the window
    monkeypatch.setattr("game_control._pause_while_hovering", False)

    assert make_control().click((875, 429)) is True
    assert posted, "held the click back with the pause switched off"


def test_no_drag_is_sent_while_the_cursor_is_over_the_game(posted, cursor):
    """A drag needs this more than a click does.

    It holds the button for the whole journey — about 0.7 seconds at the
    defaults, against 40-100ms for a click — and every genuine mouse move in
    that window is added to the one being performed.
    """
    cursor(400, 300)

    assert make_control().drag((100, 100), (400, 100)) is False
    assert posted == []


# ── a capture that cannot be shaped ─────────────────────────────────────────


def test_a_zero_sized_client_raises_a_capture_error(monkeypatch):
    """Every loop already knows how to wait out a CaptureError and retry.

    None of them knows what to do with a ValueError, so one escaping here ends
    the task outright — which is what a user saw twice in a row on a minimised
    window: "Event clicker crashed ... cannot reshape array of size 2 into
    shape (0,0,4)".

    The reshape sat outside the try that turns capture trouble into
    CaptureError, so the one line most likely to disagree with the window's
    measurements was the one line not covered by it.
    """
    from game_control import CaptureError

    control = make_control()
    control.client_width = 0
    control.client_height = 0
    # Set, because bare_control leaves them off and the AttributeError that
    # caused was itself being turned into CaptureError — the first version of
    # this test passed without ever reaching the line it is about.
    control.border_left = 0
    control.border_top = 0
    monkeypatch.setattr(GameControl, "_ensure_dc", lambda self: None)
    monkeypatch.setattr(GameControl, "_render_window", lambda self: False)
    control._src_dc = object()
    control._client_dc = type("DC", (), {"BitBlt": lambda *a, **k: None})()
    control._client_bmp = type("BMP", (), {"GetBitmapBits": lambda *a, **k: bytes(2)})()

    with pytest.raises(CaptureError):
        control.full_shot()
