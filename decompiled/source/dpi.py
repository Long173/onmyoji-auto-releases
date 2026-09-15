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


# Per-monitor v2, for a game that draws in real screen pixels. The value it
# restores is whatever the caller had, so this only ever applies inside the
# block below.
_PER_MONITOR_V2 = ctypes.c_void_p(-4)

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _query_process_awareness(hwnd: int) -> int:
    """The DPI awareness of the process owning ``hwnd``, as shcore reports it.

    0 unaware, 1 system aware, 2 per-monitor aware.
    """
    user = _user32()
    pid = ctypes.c_ulong()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = ctypes.windll.kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value
    )
    if not handle:
        raise OSError("could not open process %d" % pid.value)
    try:
        value = ctypes.c_int()
        if ctypes.windll.shcore.GetProcessDpiAwareness(
                handle, ctypes.byref(value)):
            raise OSError("GetProcessDpiAwareness failed")
        return value.value
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def process_is_dpi_aware(hwnd: int) -> bool:
    """Whether that window's process draws in real screen pixels.

    False for the game as it ships, and for anything Windows is scaling on its
    behalf. True once somebody sets Properties -> Compatibility -> "Override
    high DPI scaling behavior" -> **Application**, which is Windows being told
    to stop scaling and let the program draw at the monitor's own resolution.

    Unaware is the answer when the question cannot be asked: it is the
    out-of-the-box state, and it is what every measurement in this app assumed
    before this existed.
    """
    try:
        return _query_process_awareness(hwnd) != 0
    except Exception:      # noqa: BLE001 - an unanswerable handle is not aware
        logger.debug("Could not read DPI awareness of 0x%08x", hwnd,
                     exc_info=True)
        return False


@contextmanager
def window_space(hwnd: int) -> Iterator[None]:
    """Run a block in the space *that window* is drawn in.

    :func:`game_space` assumes the game is DPI-unaware, which it is until
    somebody overrides it. When they do, the game draws at the monitor's real
    resolution while an unaware thread is told the window is the smaller
    virtualised size — and a capture sized from that measurement takes the
    top-left corner of what was drawn and calls it the whole frame. Reported at
    200% scaling as the picker showing a quarter of the game blown up.

    So the awareness is asked of the game rather than assumed, and the block
    runs in whichever space matches.
    """
    if not process_is_dpi_aware(hwnd):
        with game_space():
            yield
        return
    try:
        previous = _user32().SetThreadDpiAwarenessContext(_PER_MONITOR_V2)
    except (AttributeError, OSError):
        yield
        return
    try:
        yield
    finally:
        if previous:
            try:
                _user32().SetThreadDpiAwarenessContext(ctypes.c_void_p(previous))
            except (AttributeError, OSError):
                logger.debug("Could not restore thread DPI awareness",
                             exc_info=True)


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
