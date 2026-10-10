"""A :class:`GameControl` for an emulator: the same interface, driven over ADB.

Every task talks to its window through ``GameControl`` — ``full_shot``,
``find``, ``click``, ``drag`` and the per-pass frame cache — and none of them
needs to know what is behind it. This subclass keeps all of the matching and
caching and replaces the three things that touch Windows: how a frame is taken
(``screencap``), how a press is made (``input tap``) and how a drag is made
(``input swipe``).

Coordinates are the device's own pixels, exactly as a window's client pixels
are for the PC game: the frame is 1600x900 on a default BlueStacks, the base
class stretches it to the reference size before matching and maps every match
back, and :class:`geometry.Geometry` scales fixed points the same way. So the
device's resolution is this control's "client size", and nothing downstream
can tell the difference.

Two things a window has and a device does not:

* **No cursor to wait for.** The PC game shares the mouse with the player, so
  clicks are held while the cursor is over it. Taps sent through ADB never meet
  the player's mouse, so nothing is ever held.
* **A slower camera.** A raw screencap costs about 0.19 s against roughly 17 ms
  for PrintWindow. A task looks once a second or so and does not notice; the
  dashboard's thumbnails, taken on the UI thread every two seconds, would. So
  :meth:`preview` answers from the last frame and refreshes it on a thread of
  its own.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import cv2
import numpy as np

import adb as adb_module
from game_control import CaptureError, GameControl
from geometry import Point

logger = logging.getLogger(__name__)

# The drag the PC control performs — press, 16 moves 35 ms apart, release —
# takes about 0.7 s; a swipe of the same length reads to the game the same way.
DRAG_MILLISECONDS = 700
# A thumbnail older than this is refreshed in the background.
PREVIEW_MAX_AGE_SECONDS = 1.5
# Captures failing for this long mean the emulator is gone, not busy: the card
# is then dropped as a closed window's is. A loading screen never stops adb
# answering; a closed emulator does at once.
LOST_AFTER_SECONDS = 15.0
# Taps refused this many times in a row end the run with a message. One can be a
# glitch; BlueStacks with ADB switched off refuses every one ("error: closed")
# while still answering screencaps, so the run saw the board, pressed nothing,
# and said nothing — the failure was only in the log.
TAP_FAILURE_LIMIT = 3


class EmulatorRefusesInput(RuntimeError):
    """The emulator answers screencaps but not taps: ADB is off or blocked."""

    MESSAGE = ("Giả lập không nhận lệnh bấm qua ADB. Hãy bật ADB trong cài đặt "
               "giả lập (BlueStacks: Cài đặt → Nâng cao → Android Debug "
               "Bridge), rồi bấm Bắt đầu lại.")

    def __init__(self) -> None:
        super().__init__(self.MESSAGE)


def open_control(hwnd: int, window_control=GameControl) -> GameControl:
    """The control for a session's handle: ADB for an emulator, else the window.

    ``window_control`` is what to build for a real window. Callers pass their
    own module's ``GameControl`` name rather than relying on this one, so a test
    that replaces it there still decides what a window gets.
    """
    from auto import window_scanner

    serial = window_scanner.emulator_serial(hwnd)
    if serial:
        return AdbControl(serial, hwnd)
    return window_control(hwnd)


class AdbControl(GameControl):
    """Captures and taps one emulator over ADB. ``hwnd`` is the session's key."""

    def __init__(self, serial: str, hwnd: int,
                 adb: Optional["adb_module.Adb"] = None) -> None:
        # Deliberately not GameControl.__init__: that one checks and measures a
        # window handle, and there is none.
        self.hwnd = hwnd
        self.serial = serial
        self._adb = adb if adb is not None else adb_module.shared()
        if self._adb is None:
            raise ValueError("Không tìm thấy adb của giả lập")
        self._templates = {}
        self._dc_ready = False
        self._printwindow_failed = False
        self._frame_cache = {}
        self._scaled_cache = {}
        self._caching = False
        self._last_frame: Optional[np.ndarray] = None
        self._preview_at = 0.0
        self._preview_thread: Optional[threading.Thread] = None
        self._failing_since: Optional[float] = None
        self._tap_failures = 0
        self.client_width = self.client_height = 0
        self.window_width = self.window_height = 0
        self.border_left = self.border_top = 0
        self._measure_window()

    # ── measuring ───────────────────────────────────────────────────────────

    def _measure_window(self) -> None:
        """The device's screen size, from a frame. Zero if it cannot be had."""
        try:
            frame = self._screencap()
        except CaptureError:
            return
        self._set_size(frame)
        self._last_frame = frame
        self._preview_at = time.monotonic()

    def _set_size(self, frame: np.ndarray) -> None:
        height, width = frame.shape[:2]
        self.client_width = self.window_width = width
        self.client_height = self.window_height = height

    def window_dpi(self) -> int:
        return 100

    def describe(self) -> str:
        return "adb=%s screen=%dx%d" % (self.serial, self.client_width,
                                        self.client_height)

    def close(self) -> None:
        self._frame_cache.clear()
        self._scaled_cache.clear()

    # ── capture ─────────────────────────────────────────────────────────────

    def _screencap(self) -> np.ndarray:
        from auto import window_scanner

        try:
            frame = self._adb.screencap(self.serial)
        except adb_module.AdbError as exc:
            now = time.monotonic()
            if self._failing_since is None:
                self._failing_since = now
            elif now - self._failing_since >= LOST_AFTER_SECONDS:
                window_scanner.mark_emulator_lost(self.serial, True)
            raise CaptureError(str(exc)) from exc
        if self._failing_since is not None:
            self._failing_since = None
            window_scanner.mark_emulator_lost(self.serial, False)
        return frame

    def _grab(self, gray: bool) -> np.ndarray:
        frame = self._screencap()
        if frame.shape[1] != self.client_width or frame.shape[0] != self.client_height:
            # Rotated, or the emulator's resolution was changed under us:
            # whatever the frame is now is the size from now on. Matching
            # follows at once; a running task's fixed points were scaled at
            # start, so it should be restarted.
            logger.warning("%s changed resolution to %dx%d mid-run — restart the "
                           "task", self.serial, frame.shape[1], frame.shape[0])
            self._set_size(frame)
            self._scaled_cache.clear()
        self._last_frame = frame
        self._preview_at = time.monotonic()
        if gray:
            return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return frame

    def preview(self) -> Optional[np.ndarray]:
        """The latest frame at once; a fresh one is fetched in the background."""
        stale = time.monotonic() - self._preview_at > PREVIEW_MAX_AGE_SECONDS
        busy = self._preview_thread is not None and self._preview_thread.is_alive()
        if stale and not busy:
            self._preview_thread = threading.Thread(
                target=self._refresh_preview, name="AdbPreview", daemon=True)
            self._preview_thread.start()
        return self._last_frame

    def _refresh_preview(self) -> None:
        try:
            frame = self._screencap()
        except CaptureError:
            logger.debug("Preview capture failed for %s", self.serial, exc_info=True)
            return
        self._last_frame = frame
        self._preview_at = time.monotonic()

    # ── input ───────────────────────────────────────────────────────────────

    def withholding_clicks(self) -> bool:
        return False

    def click(self, point: Point) -> bool:
        self.invalidate_frame()
        x, y = int(point[0]), int(point[1])
        logger.debug("Tap at (%d, %d) on %s", x, y, self.serial)
        try:
            self._adb.tap(self.serial, x, y)
        except adb_module.AdbError as exc:
            self._input_failed(exc)
            return False
        self._tap_failures = 0
        return True

    def _input_failed(self, exc: Exception) -> None:
        """Count a refused tap or swipe; give up, loudly, after a few."""
        self._tap_failures += 1
        logger.warning("Input on %s failed (%d/%d): %s", self.serial,
                       self._tap_failures, TAP_FAILURE_LIMIT, exc)
        if self._tap_failures >= TAP_FAILURE_LIMIT:
            raise EmulatorRefusesInput() from exc

    def drag(self, start: Point, end: Point, steps: int = 16,
             hold_seconds: float = 0.12, step_seconds: float = 0.035) -> bool:
        self.invalidate_frame()
        milliseconds = max(DRAG_MILLISECONDS,
                           int(1000 * (hold_seconds + steps * step_seconds)))
        try:
            self._adb.swipe(self.serial, (int(start[0]), int(start[1])),
                            (int(end[0]), int(end[1])), milliseconds)
        except adb_module.AdbError as exc:
            self._input_failed(exc)
            return False
        self._tap_failures = 0
        return True
