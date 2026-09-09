"""Find the game windows currently open.

The single-window build asked for an exact window title. Running several
accounts means the titles differ ("陰陽師Onmyoji", "Onmyoji — Acc phụ", an
emulator's caption), so matching is a case-insensitive substring test against a
list of patterns instead.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import List, Sequence, Tuple

import win32gui
import win32process

import dpi

logger = logging.getLogger(__name__)

DEFAULT_PATTERNS: Tuple[str, ...] = ("陰陽師", "Onmyoji")
# Anything smaller is a tooltip, a splash or a stray tool window.
MIN_CLIENT_SIZE = (320, 240)

# A title match alone is not enough: this app's own windows are called
# "Onmyoji Tool …", and an Explorer window browsing the project folder is
# titled "onmyoji_wiki - File Explorer". Both were showing up as game windows.
EXCLUDED_CLASSES = frozenset({
    "CabinetWClass",        # File Explorer
    "ExploreWClass",        # legacy Explorer
    "Progman", "WorkerW",   # desktop
    "Shell_TrayWnd",        # taskbar
    "ApplicationFrameWindow",  # UWP shells
})
EXCLUDED_CLASS_PREFIXES = (
    "Qt",                   # this app, and any other Qt tool
    "Chrome_WidgetWin",     # Chrome, Edge, Electron
    "MozillaWindowClass",
)
# "Onmyoji Auto" stays alongside the current name: an installed copy that has
# not been updated yet still carries the old title, and a build left running
# from before the rename must not be picked up as a game window either.
EXCLUDED_TITLE_PREFIXES = ("Onmyoji Tool", "Onmyoji Auto", "Onmyoji Wiki")


@dataclass(frozen=True)
class GameWindow:
    """An open window that looks like the game."""

    hwnd: int
    title: str
    client_width: int
    client_height: int

    @property
    def handle_text(self) -> str:
        """Just the handle, for places too narrow for the full descriptor."""
        return "HWND 0x%08X" % self.hwnd

    @property
    def descriptor(self) -> str:
        """The mono caption under a card title, e.g. ``HWND 0x0004A21C · 1122×633``."""
        return "%s · %d×%d" % (
            self.handle_text,
            self.client_width,
            self.client_height,
        )


def is_excluded_class(class_name: str) -> bool:
    """True for window classes that can never be the game."""
    return class_name in EXCLUDED_CLASSES or class_name.startswith(
        EXCLUDED_CLASS_PREFIXES
    )


def scan(patterns: Sequence[str] = DEFAULT_PATTERNS) -> List[GameWindow]:
    """Every visible top-level window whose title matches one of ``patterns``.

    Sorted by title then handle so the dashboard keeps a stable card order
    across rescans.
    """
    needles = [p.casefold() for p in patterns if p.strip()]
    own_pid = os.getpid()
    found: List[GameWindow] = []

    def visit(hwnd: int, _extra: object) -> bool:
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return True
        folded = title.casefold()
        if not any(needle in folded for needle in needles):
            return True
        if title.startswith(EXCLUDED_TITLE_PREFIXES):
            return True
        # Our own windows match every pattern; so does anything Qt-based when
        # this app is launched as a separate process.
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid == own_pid:
                return True
        except Exception:
            logger.debug("Could not read owner pid of 0x%08x", hwnd, exc_info=True)
        if is_excluded_class(win32gui.GetClassName(hwnd)):
            return True
        try:
            # In the game's own units, like every other client size in the app.
            # Measured as screen pixels instead, a card would advertise
            # "1402×791" for a window the worker is driving as 1122×633, and the
            # minimum-size test below would quietly change meaning with the
            # user's display scaling.
            with dpi.game_space():
                _, _, width, height = win32gui.GetClientRect(hwnd)
        except Exception:
            logger.debug("Could not measure hwnd 0x%08x", hwnd, exc_info=True)
            return True
        if width < MIN_CLIENT_SIZE[0] or height < MIN_CLIENT_SIZE[1]:
            return True
        found.append(GameWindow(hwnd, title, width, height))
        return True

    win32gui.EnumWindows(visit, None)
    found.sort(key=lambda w: (w.title, w.hwnd))
    logger.info("Window scan matched %d window(s)", len(found))
    return found


def is_gone(hwnd: int) -> bool:
    """True once the handle refers to no window at all.

    Deliberately weaker than ``not is_alive``: that is also true of a window
    which is merely hidden — minimised, or on another virtual desktop — and
    such a window comes back. This one cannot. Windows never reissues a
    destroyed handle to the same window, so there is nothing to wait for and
    the session can be closed out rather than left failing.
    """
    try:
        return not bool(win32gui.IsWindow(hwnd))
    except Exception:      # noqa: BLE001 - treat an unanswerable handle as live
        return False


def is_alive(hwnd: int) -> bool:
    """True while the handle still refers to a visible window."""
    try:
        return bool(win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd))
    except Exception:
        return False
