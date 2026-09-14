"""Screen capture and background mouse input for a bound game window.

Two things make this work while the game window sits in the background:

* ``PrintWindow(PW_RENDERFULLCONTENT)`` asks the window to redraw itself into
  our device context. Plain ``BitBlt`` on a DirectX-backed surface returns a
  stale GDI snapshot, so the bot would match against a frozen frame.
* ``PostMessage(WM_LBUTTON*)`` delivers clicks straight to the window's message
  queue, so the cursor never moves and the window never needs focus.
"""
from __future__ import annotations

import ctypes
import logging
import random
import time
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import win32api
import win32con
import win32gui
import win32ui

import dpi
from geometry import REFERENCE_CLIENT_SIZE, Point, Region

logger = logging.getLogger(__name__)

PW_RENDERFULLCONTENT = 0x2
CLICK_HOLD_MS_RANGE = (40, 100)

# Whether a click is withheld while the player's own cursor is over the game.
# App-wide rather than per task, and read at click time rather than when a
# worker is built, so changing it takes effect without restarting anything.
_pause_while_hovering = True


def set_pause_while_hovering(on: bool) -> None:
    """Turn the courtesy pause on or off for every window at once."""
    global _pause_while_hovering
    _pause_while_hovering = bool(on)
    logger.info("Pause while the cursor is over the game: %s",
                "on" if _pause_while_hovering else "off")
MOUSE_MOVE_SETTLE_SECONDS = 0.01
# Paid before a *capture*, to let whatever was just clicked finish animating
# before it is photographed. Deliberately not paid per match: see
# ``_will_capture``.
DEFAULT_MATCH_DELAY_SECONDS = 0.1
# How far apart two matches have to be to count as separate copies, and the
# row height used to order them. Template matching lights up a cluster of
# pixels around each hit; a raid board's cards sit about 118px apart.
MATCH_SPACING = 40


class CaptureError(RuntimeError):
    """The window could not be captured this round."""


def read_image(file_path: str, flag: int = cv2.IMREAD_COLOR) -> np.ndarray:
    """Decode an image file.

    ``cv2.imread`` passes the path to the C runtime in the system ANSI code
    page and silently returns ``None`` for non-ASCII paths — and this project
    lives under a folder named 陰陽師Onmyoji. Reading the bytes in Python and
    handing them to ``imdecode`` sidesteps that entirely.

    Module level rather than a GameControl method so callers can load templates
    without holding a window handle.
    """
    with open(file_path, "rb") as handle:
        data = np.frombuffer(handle.read(), dtype=np.uint8)
    image = cv2.imdecode(data, flag)
    if image is None:
        raise ValueError("Not a decodable image: %s" % file_path)
    return image


class GameControl:
    """Captures frames from, and posts clicks to, a single window handle."""

    def __init__(self, hwnd: int) -> None:
        if not hwnd or not win32gui.IsWindow(hwnd):
            raise ValueError("Invalid window handle: %r" % (hwnd,))
        self.hwnd = hwnd
        self._templates: Dict[Tuple[str, bool], np.ndarray] = {}
        self._dc_ready = False
        self._printwindow_failed = False
        self._frame_cache: Dict[bool, np.ndarray] = {}
        # The same frame stretched to template scale. Kept beside the raw
        # one rather than replacing it: the thumbnail and every part_shot
        # want the window's real pixels, only matching wants the stretch.
        self._scaled_cache: Dict[bool, np.ndarray] = {}
        self._caching = False
        self._last_frame: Optional[np.ndarray] = None
        self._measure_window()

    # ---------- window metrics ----------

    def _measure_window(self) -> None:
        # Every number below is in the game's own coordinate space, not the
        # screen's. They differ whenever the game is DPI-virtualised; see dpi.py.
        with dpi.game_space():
            left, top, right, bottom = win32gui.GetWindowRect(self.hwnd)
            _, _, client_right, client_bottom = win32gui.GetClientRect(self.hwnd)
        self.client_width = client_right
        self.client_height = client_bottom
        self.window_width = max(1, right - left)
        self.window_height = max(1, bottom - top)
        # Windows reports no border offsets directly; derive them from the
        # difference between the outer and client rectangles.
        self.border_left = (self.window_width - client_right) // 2
        self.border_top = self.window_height - client_bottom - self.border_left

    @property
    def client_is_measurable(self) -> bool:
        """Whether the window has a client area to capture and click in.

        False for a minimised window: Windows parks one off-screen and reports
        a window rect of about 160x25 with a client rect of nothing at all.
        Every coordinate the app scales is then multiplied by 0/1122, so the
        whole board collapses onto (0, 0) — which is how an Event clicker came
        to be logged as "point=(0, 0)" before it died.
        """
        return self.client_width > 0 and self.client_height > 0

    def refresh_metrics(self) -> None:
        """Re-read the window geometry after it was moved or resized.

        Bitmaps are sized to the old client area, so they are torn down too;
        the next capture rebuilds them.
        """
        self.close()
        self._frame_cache.clear()
        self._scaled_cache.clear()
        self._last_frame = None
        self._measure_window()

    def window_dpi(self) -> int:
        """Display scaling of the monitor this window is on, as a percentage.

        Taken from the monitor, not the window: a DPI-unaware window reports 96
        whatever the screen is set to, so asking it cannot tell 100% from 125%
        — and 125% is precisely the case worth knowing about here.
        """
        return dpi.scaling_percent(self.hwnd) or 100

    def describe(self) -> str:
        return (
            "hwnd=0x%08x class=%r title=%r window=%dx%d client=%dx%d "
            "border=(%d,%d) dpi=%d%% children=%d"
            % (
                self.hwnd,
                win32gui.GetClassName(self.hwnd),
                win32gui.GetWindowText(self.hwnd),
                self.window_width,
                self.window_height,
                self.client_width,
                self.client_height,
                self.border_left,
                self.border_top,
                self.window_dpi(),
                # Clicks are posted to the deepest child under the point, but
                # with the *parent's* client coordinates. That is correct only
                # while the game has no child windows — it has none here, and
                # this says so if that ever stops being true.
                self._child_count(),
            )
        )

    def _child_count(self) -> int:
        found = []
        try:
            win32gui.EnumChildWindows(
                self.hwnd, lambda h, _: found.append(h) or True, None
            )
        except Exception:
            return -1
        return len(found)

    # ---------- device contexts ----------

    def _ensure_dc(self) -> None:
        if self._dc_ready:
            return
        self._window_dc = win32gui.GetWindowDC(self.hwnd)
        self._src_dc = win32ui.CreateDCFromHandle(self._window_dc)

        self._client_dc = self._src_dc.CreateCompatibleDC()
        self._client_bmp = win32ui.CreateBitmap()
        self._client_bmp.CreateCompatibleBitmap(
            self._src_dc, self.client_width, self.client_height
        )
        self._client_dc.SelectObject(self._client_bmp)

        self._window_mem_dc = self._src_dc.CreateCompatibleDC()
        self._window_bmp = win32ui.CreateBitmap()
        self._window_bmp.CreateCompatibleBitmap(
            self._src_dc, self.window_width, self.window_height
        )
        self._window_mem_dc.SelectObject(self._window_bmp)
        self._dc_ready = True

    def close(self) -> None:
        """Release GDI handles and the cached frames. Safe to call more than once."""
        # Dropped before the early return: a control closed twice, or closed
        # before it ever captured, should still not be sitting on ~2 MB of
        # pixels. Callers usually discard the object straight after, but this
        # must not depend on that.
        self._frame_cache.clear()
        self._scaled_cache.clear()
        self._last_frame = None
        if not self._dc_ready:
            return
        self._dc_ready = False
        for dc in ("_client_dc", "_window_mem_dc", "_src_dc"):
            try:
                getattr(self, dc).DeleteDC()
            except Exception:
                logger.debug("Failed to delete %s", dc, exc_info=True)
        for bmp in ("_client_bmp", "_window_bmp"):
            try:
                win32gui.DeleteObject(getattr(self, bmp).GetHandle())
            except Exception:
                logger.debug("Failed to delete %s", bmp, exc_info=True)
        try:
            win32gui.ReleaseDC(self.hwnd, self._window_dc)
        except Exception:
            logger.debug("Failed to release window DC", exc_info=True)

    # ---------- capture ----------

    def _render_window(self) -> bool:
        """Draw the full window into ``_window_mem_dc``; True if PrintWindow won.

        Guarded in its own right rather than relying on ``_grab`` to have done
        it. Nesting costs nothing — the context manager restores whatever it
        found — and a helper that is only correct when called from one place is
        a trap for whoever adds the second caller.
        """
        try:
            with dpi.game_space():
                rc = ctypes.windll.user32.PrintWindow(
                    self.hwnd, self._window_mem_dc.GetSafeHdc(), PW_RENDERFULLCONTENT
                )
        except Exception:
            if not self._printwindow_failed:
                logger.warning(
                    "PrintWindow raised; falling back to BitBlt", exc_info=True
                )
                self._printwindow_failed = True
            return False
        if rc != 1:
            if not self._printwindow_failed:
                logger.warning(
                    "PrintWindow returned %s; falling back to BitBlt (frames may be stale)",
                    rc,
                )
                self._printwindow_failed = True
            return False
        if self._printwindow_failed:
            logger.info("PrintWindow recovered")
            self._printwindow_failed = False
        return True

    # ── frame cache ─────────────────────────────────────────────────────────
    # A scan pass matches a dozen templates in a row, and each match used to
    # trigger its own PrintWindow. With several game windows running that cost
    # multiplies. While caching is on, every read in a pass shares one capture.
    #
    # The cache is dropped whenever the screen may have moved on — after a click
    # and after any sleep — so a match never runs against a pre-click frame.

    def begin_frame(self) -> None:
        self._caching = True
        self._frame_cache.clear()
        self._scaled_cache.clear()

    def end_frame(self) -> None:
        self._caching = False
        self._frame_cache.clear()
        self._scaled_cache.clear()

    def invalidate_frame(self) -> None:
        self._frame_cache.clear()
        self._scaled_cache.clear()

    def last_frame(self) -> Optional[np.ndarray]:
        """Most recent colour capture, or ``None`` if nothing has been grabbed.

        Outlives the per-pass cache on purpose: the UI thumbnail reads it
        between passes, when the cache has already been dropped.
        """
        return self._last_frame

    def full_shot(self, gray: bool = False) -> np.ndarray:
        """Capture the client area. Raises ``CaptureError`` if the grab fails."""
        if not self._caching:
            return self._grab(gray)

        cached = self._frame_cache.get(gray)
        if cached is not None:
            return cached

        # Always grab in colour, then derive greyscale from it. One GDI capture
        # serves both, and the UI thumbnail needs colour anyway.
        # BGRA2GRAY and BGR2GRAY apply the same luma weights, so the greyscale
        # a template sees is identical either way.
        colour = self._frame_cache.get(False)
        if colour is None:
            colour = self._grab(False)
            self._frame_cache[False] = colour
        if not gray:
            return colour
        grey = cv2.cvtColor(colour, cv2.COLOR_BGR2GRAY)
        self._frame_cache[True] = grey
        return grey

    def _grab(self, gray: bool) -> np.ndarray:
        try:
            # The bitmap has to be the size the game actually draws. Sized in
            # screen pixels instead, a virtualised game fills only the top-left
            # corner of it and leaves the rest black — which is how a raid came
            # to match templates against 0.8x artwork and click empty space.
            with dpi.game_space():
                self._ensure_dc()
                source = (
                    self._window_mem_dc if self._render_window() else self._src_dc
                )
                self._client_dc.BitBlt(
                    (0, 0),
                    (self.client_width, self.client_height),
                    source,
                    (self.border_left, self.border_top),
                    win32con.SRCCOPY,
                )
                raw = self._client_bmp.GetBitmapBits(True)
            # Inside the guard, not after it. This is the line most likely to
            # disagree with the window's own measurements — the buffer is
            # whatever the bitmap holds and the shape is whatever the client
            # rect last said — and it was the one line not covered.
            #
            # A minimised window measures no client area at all, so this became
            # "cannot reshape array of size 2 into shape (0,0,4)". Every loop
            # knows how to wait out a CaptureError and try again; none of them
            # knows what to do with a ValueError, so it ended the task instead.
            image = np.frombuffer(raw, dtype=np.uint8).reshape(
                self.client_height, self.client_width, 4
            )
        except Exception as exc:
            # Device contexts go stale when the window is resized or recreated.
            # Drop them so the next attempt rebuilds from scratch.
            logger.warning("Capture failed (%s); resetting device contexts", exc)
            self.close()
            raise CaptureError(str(exc)) from exc

        if gray:
            return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
        colour = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        self._last_frame = colour
        return colour

    def part_shot(self, region: Region, gray: bool = False) -> np.ndarray:
        """Capture a sub-rectangle of the client area, as ``((x1,y1),(x2,y2))``."""
        (x1, y1), (x2, y2) = region
        return self.full_shot(gray)[y1:y2, x1:x2]

    def save_shot(self, file_path: str) -> None:
        """Write a capture to disk. Uses imencode for the same reason as read_image."""
        ok, buffer = cv2.imencode(".png", self.full_shot())
        if not ok:
            raise CaptureError("Could not encode screenshot")
        with open(file_path, "wb") as handle:
            handle.write(buffer.tobytes())

    # ---------- template matching ----------

    def _template(self, template_path: str, gray: bool) -> np.ndarray:
        """Load and memoise a template image.

        The raid loop matches a dozen templates several times a second; reading
        them from disk every time was pure overhead.
        """
        key = (template_path, gray)
        template = self._templates.get(key)
        if template is None:
            flag = cv2.IMREAD_GRAYSCALE if gray else cv2.IMREAD_COLOR
            template = read_image(template_path, flag)
            self._templates[key] = template
        return template

    def _reference_scale(self) -> Tuple[float, float]:
        """How much this window's pixels must stretch to reach template scale.

        Templates were cut at the reference client size, and matching them
        against a window of any other size is what breaks first when the app
        moves to somebody else's machine. Measured on one frame, with templates
        cut from it so a perfect match is 1.000 by definition:

            window          raw match        after this scaling
            1122x633        1.000 / 1.000    1.000 / 1.000
            1117x623        0.976 / 0.969    0.997 / 0.996
            1063x599        0.840 / 0.701    0.998 / 0.997
            898x507         0.658 / 0.537    0.997 / 0.996

        The last two rows are real: 1063x599 is where Windows clamps the game
        at 175% display scaling, and 898x507 is what a DPI-virtualised client
        draws. Both used to put every template far under its threshold, which is
        the "works on my machine, not on my friend's laptop" failure.

        Resizing the *search area* rather than demanding the window be resized
        costs 0.7 ms once per pass — 0.3% of a pass that spends 213 ms matching
        — and makes ``resize_game_window`` a convenience instead of a
        precondition.
        """
        ref_w, ref_h = REFERENCE_CLIENT_SIZE
        if self.client_width <= 0 or self.client_height <= 0:
            return (1.0, 1.0)
        return (ref_w / self.client_width, ref_h / self.client_height)

    def _search_frame(self, gray: bool) -> np.ndarray:
        """The frame at template scale, cached for the pass like the raw one.

        Cached because the stretch is per *frame*, not per template. Done inside
        ``match`` it ran once for every template — ten times a pass — and cost
        25 ms of the 238 ms a Realm Raid pass spends matching. Exactly the shape
        of the mistake the settle delay used to make.
        """
        frame = self.full_shot(gray)
        if self._reference_scale() == (1.0, 1.0):
            return frame
        cached = self._scaled_cache.get(gray)
        if cached is not None:
            return cached
        scaled = cv2.resize(frame, tuple(REFERENCE_CLIENT_SIZE),
                            interpolation=cv2.INTER_CUBIC)
        if self._caching:
            self._scaled_cache[gray] = scaled
        return scaled

    def reference_shot(self, gray: bool = True) -> np.ndarray:
        """The frame stretched to template scale, as ``match`` sees it.

        Public because reading text needs the pixels rather than a score:
        :mod:`ticket_counter` segments the ticket counter into glyphs, and it
        has to do that in the same coordinate space the templates were cut in.
        Going through ``full_shot`` instead would leave it measuring glyph
        widths that shift with the window size.
        """
        return self._search_frame(gray)

    def _will_capture(self) -> bool:
        """Whether the next ``full_shot`` actually goes to the window.

        False once this pass has already grabbed: the cache then answers, and
        the colour frame is what everything derives from — a greyscale request
        converts that rather than grabbing again.
        """
        return not self._caching or self._frame_cache.get(False) is None

    def match(
        self,
        template_path: str,
        region: Optional[Region] = None,
        gray: bool = True,
        delay: float = DEFAULT_MATCH_DELAY_SECONDS,
    ) -> Tuple[float, Point]:
        """Return ``(score, centre)`` where centre is in client coordinates."""
        # Only when a capture is really coming. A loop pass matches a dozen
        # templates against **one** cached frame, and sleeping before each of
        # them cannot change what any of them sees — the picture is already
        # taken. Measured: matching costs 8.8 ms of real work against a 100 ms
        # wait, so a Realm Raid pass spent about a second asleep to do 88 ms of
        # looking, and the median pass in a real log took 1.60 s.
        #
        # The wait that matters is kept exactly: the first match of a pass still
        # pauses before the screen is photographed, which is the whole point of
        # it — a click needs time to finish animating. Anything that drops the
        # cache (every ``_sleep``) makes the next match pay it again.
        if delay and self._will_capture():
            time.sleep(delay)
        template = self._template(template_path, gray)
        # Everything below works at template scale, and is converted back to the
        # window's own pixels once, at the end.
        scale_x, scale_y = self._reference_scale()
        frame = self._search_frame(gray)
        if region is None:
            source = frame
            origin: Point = (0, 0)
        else:
            (x1, y1), (x2, y2) = region
            origin = (round(x1 * scale_x), round(y1 * scale_y))
            source = frame[origin[1]:round(y2 * scale_y),
                           origin[0]:round(x2 * scale_x)]

        t_height, t_width = template.shape[:2]
        if source.shape[0] < t_height or source.shape[1] < t_width:
            raise ValueError(
                "Search area %dx%d is smaller than template %s (%dx%d)"
                % (source.shape[1], source.shape[0], template_path, t_width, t_height)
            )

        result = cv2.matchTemplate(source, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, top_left = cv2.minMaxLoc(result)
        # Back into the window's own pixels — a click has to land where the
        # window really is, not where the stretched copy put it.
        centre_x = origin[0] + top_left[0] + t_width // 2
        centre_y = origin[1] + top_left[1] + t_height // 2
        if (scale_x, scale_y) != (1.0, 1.0):
            centre_x = round(centre_x / scale_x)
            centre_y = round(centre_y / scale_y)
        return score, (centre_x, centre_y)

    def find(
        self,
        template_path: str,
        threshold: float = 0.9,
        region: Optional[Region] = None,
        gray: bool = True,
        delay: float = DEFAULT_MATCH_DELAY_SECONDS,
    ) -> Optional[Point]:
        """Centre of the best match above ``threshold``, else ``None``."""
        score, centre = self.match(template_path, region, gray, delay)
        if score > threshold:
            logger.debug("Matched %s score=%.3f at %s", template_path, score, centre)
            return centre
        return None

    def find_all(
        self,
        template_path: str,
        threshold: float = 0.9,
        gray: bool = True,
        delay: float = DEFAULT_MATCH_DELAY_SECONDS,
        spacing: int = MATCH_SPACING,
    ) -> List[Point]:
        """Every copy of the template above ``threshold``, in reading order.

        ``match`` answers with the single global best, and that is the wrong
        shape for a screen carrying several equally good copies of one thing. A
        live raid board scored its nine opponent cards between 0.943 and 0.990,
        so the same card won every pass — and a card that could not be attacked
        was picked again on the pass after it was dismissed, indefinitely.

        Matching lights up a small cluster of pixels around each hit, so points
        within ``spacing`` of an already-accepted one are the same copy and are
        dropped. What comes back is ordered by row and then across, which is
        what lets a caller simply walk the list.
        """
        if delay and self._will_capture():
            time.sleep(delay)
        template = self._template(template_path, gray)
        scale_x, scale_y = self._reference_scale()
        frame = self._search_frame(gray)
        t_height, t_width = template.shape[:2]
        if frame.shape[0] < t_height or frame.shape[1] < t_width:
            raise ValueError(
                "Search area %dx%d is smaller than template %s (%dx%d)"
                % (frame.shape[1], frame.shape[0], template_path, t_width, t_height)
            )

        result = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
        hits = np.argwhere(result >= threshold)
        if hits.size == 0:
            return []
        # Strongest first, so the point kept for each cluster is its best pixel
        # rather than whichever the scan reached first.
        order = sorted(hits, key=lambda yx: -result[yx[0], yx[1]])
        kept: List[Point] = []
        for y, x in order:
            centre = (int(x) + t_width // 2, int(y) + t_height // 2)
            if any(abs(centre[0] - k[0]) < spacing and abs(centre[1] - k[1]) < spacing
                   for k in kept):
                continue
            kept.append(centre)

        if (scale_x, scale_y) != (1.0, 1.0):
            kept = [(round(x / scale_x), round(y / scale_y)) for x, y in kept]
        kept.sort(key=lambda p: (p[1] // spacing, p[0]))
        logger.debug("Matched %s %d times", template_path, len(kept))
        return kept

    # ---------- input ----------

    def _target_hwnd(self, point: Point) -> int:
        """Deepest child window under ``point``, or the bound window itself.

        ``point`` is in the game's units, so the lookup has to be too — see
        :func:`dpi.game_space`. Guarded here as well as in ``click`` so the
        method stands on its own.
        """
        try:
            with dpi.game_space():
                child = win32gui.ChildWindowFromPoint(self.hwnd, point)
        except Exception:
            return self.hwnd
        return child if child and child != self.hwnd else self.hwnd

    def drag(self, start: Point, end: Point, steps: int = 16,
             hold_seconds: float = 0.12, step_seconds: float = 0.035) -> bool:
        """Press at ``start``, travel to ``end``, release. For sliders.

        The intermediate moves are not decoration: a slider that only ever sees
        a press and a release at two places treats it as a click and does not
        follow. Same coordinate space as :meth:`click`.

        Returns False when nothing was sent because the player's cursor is over
        the window. A drag needs that guard more than a click does, not less: it
        holds the button for the whole journey — about 0.7 seconds at the
        defaults against 40-100ms for a click — and every genuine mouse move in
        that window is added to the one being performed.
        """
        if self.withholding_clicks():
            logger.debug("Cursor is over the window; not dragging %s -> %s",
                         start, end)
            return False
        self.invalidate_frame()
        with dpi.game_space():
            target = self._target_hwnd(start)
            down = win32api.MAKELONG(start[0], start[1])
            win32gui.PostMessage(target, win32con.WM_MOUSEMOVE, 0, down)
            time.sleep(MOUSE_MOVE_SETTLE_SECONDS)
            win32gui.PostMessage(
                target, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, down
            )
            time.sleep(hold_seconds)
            for index in range(1, steps + 1):
                x = start[0] + (end[0] - start[0]) * index // steps
                y = start[1] + (end[1] - start[1]) * index // steps
                win32gui.PostMessage(
                    target, win32con.WM_MOUSEMOVE, win32con.MK_LBUTTON,
                    win32api.MAKELONG(x, y),
                )
                time.sleep(step_seconds)
            win32gui.PostMessage(
                target, win32con.WM_LBUTTONUP, 0, win32api.MAKELONG(end[0], end[1])
            )
        return True

    def _player_is_hovering(self) -> bool:
        """Whether the real cursor is pointing at this window.

        A posted click does not move the cursor, so the player's own can sit
        inside the game while a loop works. That is harmless until a button is
        held: for as long as it is, every genuine mouse move Windows delivers
        reads to the game as a drag, and the view slides while the player is
        touching nothing. Reported on the Event clicker, which presses every two
        seconds for as long as it runs.

        Asked as "what is under the cursor" rather than "is the cursor inside
        the window rectangle", because those two are the same question only
        while nothing covers the game. This app's own window usually does.

        The rectangle test failed outright at 200% display scaling. The game is
        DPI-unaware, so it sees a 1920x1080 screen as a 960x540 desktop, and the
        window it is given cannot fit on that in either direction — its rect
        ends up spanning the whole desktop. Every pixel the cursor could be at
        was then "over the game", this app's own controls included, so clicks
        were withheld for the entire run. The Event clicker, which needs nothing
        from the screen and should have been the task least troubled by a small
        window, was the one that stopped working.

        ``WindowFromPoint`` answers with the deepest window at that point, which
        for a game hosting a render child is not the handle held here — hence
        the walk up to the top-level owner before comparing.
        """
        try:
            with dpi.game_space():
                position = win32gui.GetCursorPos()
                under = win32gui.WindowFromPoint(position)
        except Exception:          # noqa: BLE001 - a missing window is not fatal
            return False
        if not under:
            return False
        try:
            root = win32gui.GetAncestor(under, win32con.GA_ROOT) or under
        except Exception:          # noqa: BLE001 - pre-2000 Windows lacks it
            root = under
        return root == self.hwnd

    def withholding_clicks(self) -> bool:
        """Whether a click right now would be held back.

        The same question :meth:`click` asks itself, exposed so a loop can
        decide *before* a pass rather than by watching clicks come back False.
        A pass that will not be allowed to act changes nothing, and running it
        anyway fills the log with attacks that never happened — which is how a
        held raid came to be reported as attacking one barrier over and over.
        """
        return bool(_pause_while_hovering) and self._player_is_hovering()

    def click(self, point: Point) -> bool:
        """Post a left click at a client coordinate without moving the cursor.

        Returns False when nothing was sent because the player's own cursor is
        over the window — see :meth:`_player_is_hovering`. Callers that count
        presses should count only the ones that went out.

        The whole sequence runs in the game's coordinate space, and that is not
        merely tidiness: Windows rescales the coordinates packed into a posted
        mouse message according to the DPI awareness of the *posting thread*.
        Sent from an aware thread to this virtualised window, an otherwise
        correct point lands somewhere else entirely and the game ignores it.

        Measured on a 125% display, clicking a matched Attack button at the
        same (875, 429): from an aware thread, nothing happened at all; from an
        unaware one, the battle started.
        """
        if self.withholding_clicks():
            logger.debug("Cursor is over the window; not clicking at %s", point)
            return False
        lparam = win32api.MAKELONG(point[0], point[1])
        # Whatever is on screen after this is no longer what we matched against.
        self.invalidate_frame()
        with dpi.game_space():
            target = self._target_hwnd(point)
            logger.debug("Click at %s (hwnd=0x%08x)", point, target)
            win32gui.PostMessage(target, win32con.WM_MOUSEMOVE, 0, lparam)
            time.sleep(MOUSE_MOVE_SETTLE_SECONDS)
            win32gui.PostMessage(
                target, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam
            )
            time.sleep(random.randint(*CLICK_HOLD_MS_RANGE) / 1000)
            # Put the pointer back before letting go. A posted click does not
            # move the real cursor, so the player's own can be inside the window
            # while this runs — and for as long as the button is held, every
            # genuine mouse move Windows delivers reads to the game as a drag.
            # Reported on the Event clicker, which presses every two seconds for
            # as long as it runs: moving the mouse over the game, touching
            # nothing, scrolled the view.
            #
            # This does not stop the game seeing those moves. It makes them add
            # up to nothing: the last position it is given before the release is
            # the one the press started from.
            win32gui.PostMessage(target, win32con.WM_MOUSEMOVE, 0, lparam)
            win32gui.PostMessage(target, win32con.WM_LBUTTONUP, 0, lparam)
        return True
