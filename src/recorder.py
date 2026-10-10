"""Recording one game window to an .mp4 while everything else carries on.

A thread with its own :class:`GameControl` and its own writer, which is the part
that had to be measured rather than assumed. The session deliberately does *not*
capture while a worker is running — it hands back the worker's latest frame
instead, because "capturing here too would use the same GDI handles from a second
thread". Following that rule here would have made a recording of a running task
a slideshow at the worker's own pace, roughly one frame a second.

So it was measured. Two separate ``GameControl`` instances on one window, both
capturing flat out from their own threads: **zero failed frames**, and 33.3 ms a
frame each against 16.7 ms for one alone. They serialise, they do not fail. At
ten frames a second the budget is 100 ms and a frame costs 33, so a recorder can
run beside a working task and still produce real video.

The cost is real and worth stating: while recording, the task's own captures take
about twice as long. Nothing in the loops is capture-bound at these rates, but a
machine already struggling will struggle more.

What the numbers mean for the files, at 1122x633 and the default ten frames a
second: about **26 MB a minute**, and 36.4 dB against the raw capture — the loss
sits in smooth gradients, not in the small text, which is what matters for a
recording somebody made to show what went wrong. One quirk: the codec rounds the
height down to an even number, so a 633-pixel capture comes back 632. Harmless to
watch, but a video is not a source of pixel-exact coordinates the way a
screenshot is.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2

import paths
from game_control import CaptureError, GameControl

logger = logging.getLogger(__name__)

DEFAULT_FPS = 10
# mp4v in an .mp4. Measured 36.4 dB and 26 MB/minute; MJPG scores 2 dB better
# and costs ten times the space, which is the wrong trade for something left
# running. Both go through OpenCV's FFMPEG backend, so the packaged build has to
# ship `opencv_videoio_ffmpeg*.dll` — see the .spec.
FOURCC = "mp4v"
SUFFIX = ".mp4"

# Consecutive failed captures before giving up. A minimised or resizing window
# fails for a moment and comes back, so a single miss must not end a recording;
# fifty at ten frames a second is five seconds of nothing, which is not a blip.
MAX_MISSES = 50


def recording_dir() -> Path:
    folder = paths.DATA_ROOT / "recordings"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def default_name(title: str = "", now: Optional[datetime] = None) -> str:
    """A filename that sorts by time and says which window it was."""
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    safe = "".join(ch for ch in title if ch.isalnum() or ch in " -_")[:24].strip()
    return "%s%s%s" % (stamp, ("-" + safe.replace(" ", "_")) if safe else "", SUFFIX)


class WindowRecorder(threading.Thread):
    """Captures one window to a file until asked to stop."""

    def __init__(self, hwnd: int, target: Optional[Path] = None,
                 fps: int = DEFAULT_FPS, title: str = "",
                 control: Optional[GameControl] = None) -> None:
        super().__init__(name="WindowRecorder", daemon=True)
        self._hwnd = hwnd
        self._fps = max(1, int(fps))
        self._path = Path(target) if target else recording_dir() / default_name(title)
        self._control = control
        # Named ``_stop_event`` and not ``_stop``: ``threading.Thread`` has a
        # private ``_stop`` of its own that ``join()`` calls, and shadowing it
        # with an Event breaks joining with "'Event' object is not callable" —
        # from inside the standard library, nowhere near the mistake.
        self._stop_event = threading.Event()
        self._writer = None
        self._frames = 0
        self._started_at: Optional[float] = None
        self._error = ""

    # ── what the UI asks ────────────────────────────────────────────────────

    @property
    def path(self) -> Path:
        return self._path

    @property
    def frames(self) -> int:
        return self._frames

    @property
    def error(self) -> str:
        """Why it stopped, or empty. Set before the thread ends."""
        return self._error

    @property
    def elapsed_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        return time.monotonic() - self._started_at

    def size_bytes(self) -> int:
        """How big the file is so far.

        Read from disk rather than counted, because the writer buffers and a
        guess would drift from what the user will actually find.
        """
        try:
            return self._path.stat().st_size
        except OSError:
            return 0

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def is_stopping(self) -> bool:
        return self._stop_event.is_set()

    # ── the loop ────────────────────────────────────────────────────────────

    def run(self) -> None:
        control = self._control
        try:
            if control is None:
                control = GameControl(self._hwnd)
            first = control.full_shot()
            if first is None or getattr(first, "size", 0) == 0:
                self._fail("Không chụp được cửa sổ để bắt đầu quay.")
                return
            height, width = first.shape[:2]
            self._writer = cv2.VideoWriter(
                str(self._path), cv2.VideoWriter_fourcc(*FOURCC),
                float(self._fps), (width, height),
            )
            if not self._writer.isOpened():
                # The usual cause is the FFMPEG backend's DLL missing from a
                # packaged build, which is a build problem rather than anything
                # the user did — so say something they can act on.
                self._fail("Bản này không ghi được video (thiếu bộ mã hoá).")
                return
            logger.info("Recording 0x%08x to %s at %d fps (%dx%d)",
                        self._hwnd, self._path, self._fps, width, height)
            self._started_at = time.monotonic()
            self._writer.write(first)
            self._frames = 1
            self._pump(control, width, height)
        except Exception as exc:  # noqa: BLE001 - surfaced through .error
            logger.exception("Recording 0x%08x crashed", self._hwnd)
            self._error = str(exc)
        finally:
            if self._writer is not None:
                # Released whatever happened: an unreleased writer leaves a file
                # that will not play, which is the worst way to lose a recording.
                self._writer.release()
                self._writer = None
            if control is not None and self._control is None:
                control.close()
            logger.info("Recording 0x%08x stopped after %d frames, %.1f KB",
                        self._hwnd, self._frames, self.size_bytes() / 1024)

    def _pump(self, control: GameControl, width: int, height: int) -> None:
        interval = 1.0 / self._fps
        misses = 0
        # Paced against a fixed clock rather than by sleeping a fixed amount, so
        # the time spent capturing does not stretch the interval and leave the
        # playback slower than real time.
        next_at = time.monotonic() + interval
        while not self._stop_event.is_set():
            wait = next_at - time.monotonic()
            if wait > 0:
                self._stop_event.wait(wait)
                if self._stop_event.is_set():
                    break
            next_at += interval
            frame = None
            try:
                frame = control.full_shot()
            except CaptureError:
                frame = None
            except Exception:  # noqa: BLE001 - one bad frame is not fatal
                logger.debug("Frame capture failed", exc_info=True)
                frame = None
            if frame is None or frame.shape[:2] != (height, width):
                misses += 1
                if misses >= MAX_MISSES:
                    self._error = "Mất hình quá lâu — đã dừng quay."
                    logger.warning("Recording 0x%08x lost the window", self._hwnd)
                    return
                continue
            misses = 0
            self._writer.write(frame)
            self._frames += 1

    def _fail(self, message: str) -> None:
        self._error = message
        logger.warning("Recording 0x%08x: %s", self._hwnd, message)
