"""What every task loop shares: a thread that can be stopped, paused and timed.

Four loops — Realm Raid, the souls dungeon, the parade and the event clicker —
each need the same handful of things, and each had its own copy of them.
Compared structurally, **14 of 27 of those method bodies were byte-identical**
and the rest differed only in a log line. This is that shared half, written once.

Not an abstraction over what the loops *do*. Each one still owns its own `run`
and its own decisions; what lives here is the part the app outside them depends
on — the protocol declared in :mod:`tasks`: start/stop, pause/resume, a running
time that excludes pauses, and a frame for the window thumbnail.

The copies had already drifted, which is the real argument for this file.
``realm_raid.resume()`` was missing the ``if not is_set()`` guard the other
three had, so resuming a worker that was already running would reset the clock
reference and lose the time since it last started. Nothing reached it —
``GameSession.toggle_pause`` only resumes something it has checked is paused —
but the divergence was there, unnoticed, waiting for a second caller. One copy
cannot drift from itself.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

from game_control import GameControl
from geometry import Geometry

logger = logging.getLogger(__name__)

# How often a paused worker looks to see whether it should carry on or exit.
PAUSE_POLL_SECONDS = 0.2

# How long to wait between checks while clicks are being withheld. Long enough
# that a mouse resting on the game costs almost nothing, short enough that the
# loop picks up again the moment it moves away.
CURSOR_HOLD_POLL_SECONDS = 0.5

Callback = Optional[Callable[[str], None]]


class TaskWorker(threading.Thread):
    """Base for the task loops: lifecycle, timing and the frame for the UI.

    Subclasses implement ``run`` and call :meth:`_begin_timing` when they start
    working.
    """

    def __init__(
        self,
        name: str,
        hwnd: int,
        control: Optional[GameControl] = None,
        on_finished: Callback = None,
        on_error: Callback = None,
    ) -> None:
        super().__init__(name=name, daemon=True)
        self._control = control if control is not None else GameControl(hwnd)
        self._geometry = Geometry(
            self._control.client_width, self._control.client_height
        )

        self._stop_event = threading.Event()
        # Set means "running"; cleared means "paused".
        self._resume_event = threading.Event()
        self._resume_event.set()

        self._on_finished = on_finished
        self._on_error = on_error
        self._iteration = 0
        # Whether the last pass found clicks being withheld, so the change can
        # be announced once instead of every pass.
        self._cursor_holding = False
        self._started_at: Optional[float] = None
        self._elapsed_at_pause = 0.0

    # ---------- lifecycle ----------

    def stop(self) -> None:
        self._stop_event.set()
        # A paused worker is parked in _wait_while_paused; wake it so it can exit.
        self._resume_event.set()

    def pause(self) -> None:
        self._elapsed_at_pause = self.elapsed_seconds
        self._started_at = None
        self._resume_event.clear()

    def resume(self) -> None:
        # Guarded: without the check, resuming something already running would
        # move the clock reference to now and throw away the time it had been
        # running for. See the module docstring.
        if not self._resume_event.is_set():
            self._started_at = time.monotonic()
            self._resume_event.set()

    @property
    def is_paused(self) -> bool:
        return not self._resume_event.is_set()

    @property
    def is_stopping(self) -> bool:
        return self._stop_event.is_set()

    def share_pause_with(self, other: "TaskWorker") -> None:
        """Lend this worker's pause signal to another worker.

        For a task that runs a second task's loop on its own thread — the map
        farm breaking off to raid — rather than handing the window over. The
        borrower is never started as a thread, so it has signals nobody sets,
        and Pause would not reach it at all.

        Deliberately not a copy: both workers must watch the *same* event, so
        one press of Pause holds whichever of them is running.

        Stop is **not** shared here, and that is on purpose. The borrower needs
        an event the lender can set without setting its own — otherwise the only
        way to cut short a borrowed loop that has stopped making progress is to
        end the whole task. See ``exploration._run_raid_loop``.
        """
        other._resume_event = self._resume_event

    # ---------- timing ----------

    def _begin_timing(self) -> None:
        """Start the clock. Called by ``run`` once it is really working."""
        self._started_at = time.monotonic()

    def _end_timing(self) -> None:
        """Freeze the clock, so a finished worker still reports its total."""
        self._elapsed_at_pause = self.elapsed_seconds
        self._started_at = None

    @property
    def elapsed_seconds(self) -> float:
        """Running time, excluding stretches spent paused."""
        if self._started_at is None:
            return self._elapsed_at_pause
        return self._elapsed_at_pause + (time.monotonic() - self._started_at)

    # ---------- waiting ----------

    def _sleep(self, seconds: float) -> None:
        """Interruptible sleep — returns immediately once stop() is called.

        Also drops the frame cache: anything matched after a wait must be
        matched against a fresh capture, not the one from before it.
        """
        self._stop_event.wait(seconds)
        self._control.invalidate_frame()

    def _holding_for_the_cursor(self) -> bool:
        """True while clicks are being withheld; waits a beat when they are.

        Every loop asks this before it does anything else. Without it a held
        worker ran full passes that could not act on what they found: it kept
        matching templates, counting itself stuck, and logging clicks it was
        about to be refused. One user read that log and reported the raid as
        attacking the same barrier again and again — it had not attacked
        anything, and the board had not changed because nothing had touched it.

        Being held is not being stuck, and it is not being paused either: the
        task is still running, and picks up by itself the moment the cursor
        moves away. Nothing else about the worker changes meanwhile.

        The transition is logged, both ways and once each. A line per pass
        would bury whatever the loop was doing before it stood down, and that
        is exactly what a reader needs to still be able to see.
        """
        holding = self._control.withholding_clicks()
        if holding != self._cursor_holding:
            self._cursor_holding = holding
            logger.info(
                "Cursor is over the game window — holding off" if holding
                else "Cursor has left the game window — carrying on"
            )
        if holding:
            self._sleep(CURSOR_HOLD_POLL_SECONDS)
        return holding

    def _wait_while_paused(self) -> None:
        while not self._resume_event.is_set() and not self._stop_event.is_set():
            self._resume_event.wait(PAUSE_POLL_SECONDS)

    # ---------- talking to the UI ----------

    def latest_frame(self) -> Optional[Any]:
        """Most recent colour capture, for the window thumbnail.

        The UI only reads it, so no copy is made; treat the array as immutable.
        """
        return self._control.last_frame()

    @staticmethod
    def _notify(callback: Callback, message: str) -> None:
        if callback is None:
            return
        try:
            callback(message)
        except Exception:
            logger.exception("Callback failed")
