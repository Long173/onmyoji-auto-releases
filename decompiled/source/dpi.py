"""Talking to the game in its own coordinate space.

The game is DPI-unaware. On a machine at 125% scaling Windows therefore runs it
virtualised: the game believes its client is 898x507 and draws exactly that,
while a DPI-aware process asking Windows about the same window is told
1122x633, because that is the size in real screen pixels.

Both numbers are true. Mixing them is not, and this app mixed them:

* ``PrintWindow`` handed back a 1122x633 bitmap with the game's 898x507
  rendering in the top-left corner and black everywhere else — so every
  template was matched against artwork 0.8x too small. On a real run
  ``start.png`` scored 0.36 while the Attack button was plainly on screen, and
  ``section.png`` scored 0.91 against *empty background*, which is worse: the
  bot clicked that empty spot, no enemy card opened, and the raid went nowhere.
* Clicks were posted in screen pixels to a window that reads them as its own.

Windows lets a single thread opt out of DPI awareness, and that is all this
needs. Inside :func:`game_space` every measurement, capture and click is in the
game's own units, exactly as on a 100% machine — while the app's Qt interface,
which lives on other threads, stays sharp.

Nothing here changes behaviour at 100% scaling: the two spaces are the same,
and the calls are absent on Windows older than 10 1607, where they no-op.
"""
from __future__ import annotations

import ctypes
import logging
from contextlib import contextmanager
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

# DPI_AWARENESS_CONTEXT_UNAWARE. A handle-like negative constant, not an index.
_UNAWARE = ctypes.c_void_p(-1)

_MDT_EFFECTIVE_DPI = 0
_MONITOR_DEFAULTTONEAREST = 2


def _user32():
    return ctypes.windll.user32


@contextmanager
def game_space() -> Iterator[None]:
    """Run a block in the game's coordinate space, then restore the caller's.

    Restoring matters: this runs on the UI thread too (the window scan, the
    resize before a task starts), and leaving that thread unaware would make
    Qt's own geometry wrong for the rest of the session.
    """
    try:
        previous = _user32().SetThreadDpiAwarenessContext(_UNAWARE)
    except (AttributeError, OSError):
        # Windows 8.1 or older: there is no per-thread awareness, and no
        # virtualisation of the kind this works around either.
        yield
        return
    try:
        yield
    finally:
        if previous:
            try:
                _user32().SetThreadDpiAwarenessContext(ctypes.c_void_p(previous))
            except (AttributeError, OSError):
                logger.debug("Could not restore thread DPI awareness", exc_info=True)


def scaling_percent(hwnd: int) -> Optional[int]:
    """Display scaling of the monitor ``hwnd`` sits on, e.g. 125. None if unknown.

    Read from the monitor rather than the window: ``GetDpiForWindow`` answers
    96 for a DPI-unaware window whatever the screen is set to, which is exactly
    the case this module exists for — so it cannot tell 100% from 125%.
    """
    try:
        monitor = _user32().MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
        x = ctypes.c_uint()
        y = ctypes.c_uint()
        ctypes.windll.shcore.GetDpiForMonitor(
            monitor, _MDT_EFFECTIVE_DPI, ctypes.byref(x), ctypes.byref(y)
        )
        return round(x.value / 96 * 100)
    except (AttributeError, OSError):
        return None


def screen_size() -> tuple:
    """Primary screen in real pixels, or ``(0, 0)`` if it cannot be read.

    Real pixels, not scaled ones: the point of asking is to compare against how
    much room the game window actually needs, and at 175% scaling a window
    described as 1138 wide occupies 1992.
    """
    try:
        user = _user32()
        return (user.GetSystemMetrics(0), user.GetSystemMetrics(1))
    except (AttributeError, OSError):
        return (0, 0)
