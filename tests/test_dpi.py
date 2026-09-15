"""Talking to the game in its coordinate space.

These guard an invariant that is invisible in the code: *which thread DPI
awareness context is in force* while Windows is called. Get it wrong and
nothing raises — the captured frame is silently padded with black, and posted
clicks silently land somewhere else. That combination cost a real user a raid
that detected everything correctly and then clicked at nothing.

Reproduced and measured on a 125% display:

* capture with an aware thread -> the game's 898x507 rendering in the top-left
  of a 1122x633 bitmap; ``start.png`` scored 0.36 with the button plainly on
  screen, and ``section.png`` scored 0.91 against empty background.
* capture with an unaware thread, same screen -> 0.986 and 0.991.
* clicking the matched Attack button from an aware thread did nothing at all;
  from an unaware thread the battle started.
"""
from __future__ import annotations

import ctypes
import os

import pytest

import dpi
from game_control import GameControl

windows_only = pytest.mark.skipif(
    os.name != "nt", reason="thread DPI awareness is a Windows concept"
)

UNAWARE = ctypes.c_void_p(-1)
PER_MONITOR_V2 = ctypes.c_void_p(-4)


def current_context():
    return ctypes.windll.user32.GetThreadDpiAwarenessContext()


def is_unaware(context) -> bool:
    return bool(
        ctypes.windll.user32.AreDpiAwarenessContextsEqual(
            ctypes.c_void_p(context), UNAWARE
        )
    )


@pytest.fixture
def aware_thread():
    """Put this thread in the awareness the app's UI runs under."""
    previous = ctypes.windll.user32.SetThreadDpiAwarenessContext(PER_MONITOR_V2)
    yield
    if previous:
        ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(previous))


# ── the context manager ─────────────────────────────────────────────────────


@windows_only
def test_the_block_runs_unaware(aware_thread):
    with dpi.game_space():
        assert is_unaware(current_context())


@windows_only
def test_the_caller_is_put_back_afterwards(aware_thread):
    """It runs on the UI thread too — leaving that unaware would skew Qt."""
    before = current_context()

    with dpi.game_space():
        pass

    assert not is_unaware(current_context())
    assert is_unaware(before) == is_unaware(current_context())


@windows_only
def test_the_caller_is_put_back_even_when_the_block_raises(aware_thread):
    with pytest.raises(ValueError):
        with dpi.game_space():
            raise ValueError("boom")

    assert not is_unaware(current_context())


@windows_only
def test_scaling_is_read_off_the_monitor(aware_thread):
    """Not off the window: a DPI-unaware one answers 96 whatever the screen is,
    which is exactly the case worth detecting."""
    desktop = ctypes.windll.user32.GetDesktopWindow()

    percent = dpi.scaling_percent(desktop)

    assert percent is None or 50 <= percent <= 400


def test_an_unusable_handle_reports_nothing_rather_than_lying():
    assert dpi.scaling_percent(0) in (None, 100)


# ── the calls that must happen in that space ────────────────────────────────


def make_control(hwnd=0x1234):
    """A GameControl without a window behind it, for input plumbing only."""
    from conftest import bare_control

    return bare_control(hwnd)


@windows_only
def test_clicks_are_posted_from_an_unaware_thread(monkeypatch, aware_thread):
    """The bug: Windows rescales a posted mouse message by the *sender's*
    awareness, so an aware thread's correct coordinate arrives wrong."""
    seen = []
    monkeypatch.setattr(
        GameControl, "_target_hwnd", lambda self, point: self.hwnd
    )
    monkeypatch.setattr(
        "game_control.win32gui.PostMessage",
        lambda hwnd, msg, wparam, lparam: seen.append(is_unaware(current_context())),
    )
    monkeypatch.setattr("game_control.time.sleep", lambda _s: None)

    make_control().click((875, 429))

    assert seen, "no message was posted"
    assert all(seen), "a click was posted from a DPI-aware thread"


@windows_only
def test_the_window_lookup_agrees_about_units(monkeypatch, aware_thread):
    """Picking the target by point is itself a coordinate question."""
    seen = []
    monkeypatch.setattr(
        GameControl, "_target_hwnd",
        lambda self, point: seen.append(is_unaware(current_context())) or self.hwnd,
    )
    monkeypatch.setattr("game_control.win32gui.PostMessage", lambda *a: None)
    monkeypatch.setattr("game_control.time.sleep", lambda _s: None)

    make_control().click((10, 20))

    assert seen == [True]


@windows_only
def test_the_window_is_measured_in_the_games_space(monkeypatch, aware_thread):
    """The client size decides the capture bitmap size. Measured in screen
    pixels, a virtualised game fills only part of it and the rest stays black."""
    seen = []

    def rect(_hwnd):
        seen.append(is_unaware(current_context()))
        return (0, 0, 1138, 672)

    monkeypatch.setattr("game_control.win32gui.GetWindowRect", rect)
    monkeypatch.setattr(
        "game_control.win32gui.GetClientRect", lambda _h: (0, 0, 1122, 633)
    )

    control = make_control()
    control._measure_window()

    assert seen == [True]
    assert (control.client_width, control.client_height) == (1122, 633)


# ── the rule, enforced across the source ────────────────────────────────────
#
# Being right today is not the point; the raid, the souls dungeon and the
# Wanted Quest reply all happen to route through GameControl, so all three were
# fixed at once. The next task added could just as easily call win32gui itself
# and be silently wrong on exactly the machines nobody tests on. This checks
# the rule instead of the current state.

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "decompiled" / "source"

# Win32 calls whose answer, or whose argument, is a coordinate.
COORDINATE_CALLS = {
    "GetClientRect", "GetWindowRect", "MoveWindow", "SetWindowPos",
    "PostMessage", "SendMessage", "PrintWindow", "ClientToScreen",
    "ScreenToClient", "ChildWindowFromPoint", "WindowFromPoint",
}


def guarded_line_ranges(tree) -> list:
    """Line spans of every ``with dpi.game_space():`` block."""
    spans = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            call = item.context_expr
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr in ("game_space", "window_space")
            ):
                spans.append((node.lineno, node.end_lineno))
    return spans


def coordinate_calls(tree) -> list:
    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in COORDINATE_CALLS
        ):
            found.append((node.func.attr, node.lineno))
    return found


def python_sources():
    for path in sorted(SOURCE.rglob("*.py")):
        if "__pycache__" in path.parts or path.name == "dpi.py":
            continue
        yield path


def parse(path: Path):
    # utf-8-sig: several sources carry a BOM, and ast.parse rejects it.
    return ast.parse(path.read_text(encoding="utf-8-sig"))


def test_every_coordinate_call_runs_in_the_games_space():
    offenders = []
    for path in python_sources():
        tree = parse(path)
        spans = guarded_line_ranges(tree)
        for name, line in coordinate_calls(tree):
            if not any(start <= line <= end for start, end in spans):
                offenders.append(
                    "%s:%d %s" % (path.relative_to(SOURCE), line, name)
                )
    assert not offenders, (
        "these read or write a coordinate outside dpi.game_space(), so they use "
        "screen pixels where the rest of the app uses the game's units:\n  "
        + "\n  ".join(offenders)
    )


def test_the_check_would_notice_an_unguarded_call(tmp_path):
    """A rule nothing can fail is not a rule."""
    bad = tmp_path / "sloppy.py"
    bad.write_text("import win32gui\nwin32gui.GetClientRect(1)\n", encoding="utf-8")

    tree = parse(bad)

    assert coordinate_calls(tree) == [("GetClientRect", 2)]
    assert guarded_line_ranges(tree) == []


def test_the_task_modules_do_not_touch_win32_at_all():
    """Tasks should reach the game only through GameControl.

    That is what let one fix cover the raid, the souls dungeon and the Wanted
    Quest reply together.
    """
    for name in ("souls_dungeon.py", "wanted_invite.py"):
        text = (SOURCE / name).read_text(encoding="utf-8-sig")
        assert "win32" not in text, "%s reaches past GameControl" % name
        assert "ctypes" not in text, "%s reaches past GameControl" % name


# ── a game that draws in real pixels ────────────────────────────────────────
#
# `game_space` assumes the game is DPI-unaware, which it is out of the box.
# Windows lets anyone change that: Properties -> Compatibility -> "Override
# high DPI scaling behavior" -> **Application** tells Windows to stop scaling
# the game and let it draw at the monitor's real resolution. A user did exactly
# that, and reported the click-point picker showing the top-left quarter of the
# game blown up to fill the frame.
#
# That is what a mismatch looks like. The bitmap is sized from a client rect
# read on an unaware thread — 1122x633 of virtualised units — while PrintWindow
# draws the window at its real 2244x1266, so the copy takes the top-left
# quarter. Their friend set "the same thing" and saw nothing wrong, which fits:
# the other two choices in that dropdown leave Windows doing the scaling, and
# the game stays unaware.
#
# So the space to measure in is not a constant. It is whichever space the game
# itself draws in, and the game's own process says which that is.


@windows_only
def test_an_unaware_game_is_measured_unaware(monkeypatch):
    monkeypatch.setattr(dpi, "process_is_dpi_aware", lambda hwnd: False)
    seen = []

    with dpi.window_space(0x1234):
        seen.append(is_unaware(current_context()))

    assert seen == [True]


@windows_only
def test_a_game_that_draws_in_real_pixels_is_measured_that_way(monkeypatch,
                                                               aware_thread):
    """The override case. Measuring this one unaware is what crops the capture."""
    monkeypatch.setattr(dpi, "process_is_dpi_aware", lambda hwnd: True)
    seen = []

    with dpi.window_space(0x1234):
        seen.append(is_unaware(current_context()))

    assert seen == [False]


@windows_only
def test_the_caller_is_put_back_either_way(monkeypatch, aware_thread):
    for aware in (False, True):
        monkeypatch.setattr(dpi, "process_is_dpi_aware", lambda hwnd: aware)
        before = current_context()

        with dpi.window_space(0x1234):
            pass

        assert is_unaware(current_context()) == is_unaware(before)


@windows_only
def test_a_window_that_cannot_be_asked_is_treated_as_unaware(monkeypatch):
    """Unaware is the out-of-the-box state, so it is the safer guess."""
    def boom(hwnd):
        raise OSError("no such process")

    monkeypatch.setattr(dpi, "_query_process_awareness", boom)

    assert dpi.process_is_dpi_aware(0xDEAD) is False
