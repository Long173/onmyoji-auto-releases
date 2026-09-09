"""Event dungeon (Event): press the one button, over and over.

An event's start screen is deliberately *not* recognised here. The word on its
button changes with the event — "Challenge" on one, "Fight" on another,
something else next month — and so does the artwork behind it, so a template
cut from one event is a template that expires when the event does.

What does not change is that there is one button and it stays in one place. So
this loop never looks for it: it clicks the point it was given, waits, clicks
again.

One point turns out to be enough for the whole run, which is more than was
expected of it. Recorded off a live event — 150 seconds, eleven complete runs,
about thirteen seconds each — a run passes through six screens that all want a
press, and the same point serves every one:

    event screen   press Challenge (or Fight, or whatever it says)
    deploy board   press Ready
    confirm        press the Fight drum
    battle         lands on nothing that matters; auto plays it out
    victory        "Tap to continue"
    rewards        "Tap to continue", twice

The game stacks all of those in the bottom-right corner, so the loop needs no
idea which screen it is on. That is the whole reason this can be a clicker
rather than a recogniser.

**Nothing here reads the screen, so nothing here can tell that a run failed.**
Two consequences to know before leaving it unattended:

* Out of tickets — or sushi, since an event takes either — the game answers a
  press with a shop panel offering to sell more, priced in jade. Measured on a
  capture of that panel, it spans x 170-930, so the default point at
  (1030, 549) falls outside it and reads as a tap that closes it. A point moved
  towards the middle would land on a purchase button instead. That is why the
  picker magnifies what sits under the crosshair, and why the default is where
  it is.
* The figure this reports is **clicks, not battles**. A loop that cannot see
  the screen cannot know how many runs finished, and a count that drifts from
  reality is worse than no count at all.

The one thing it does read is a co-op Wanted Quest invite. That dialog is
somebody else's doing, it covers the screen and swallows every click underneath
— so a blind clicker would sit behind it pressing nothing until it timed out.
Every other task answers it; this one does too.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

import geometry
import wanted_invite
from game_control import CaptureError, GameControl
from task_worker import Callback, TaskWorker

logger = logging.getLogger(__name__)

# --- Tuning ----------------------------------------------------------------
# Seconds between clicks. Two, because a run needs six presses and two seconds
# delivered 6.4 clicks per run over the recorded 150 seconds — enough to hit
# every screen with almost nothing wasted, and slow enough that the game has
# settled in between. Faster is selectable and would shave the average wait per
# screen; it is not the default because two is the value that was measured
# working end to end.
DEFAULT_INTERVAL_SECONDS = 2.0
MIN_INTERVAL_SECONDS = 0.5
LOOP_LOG_EVERY = 30
POPUP_SETTLE_SECONDS = 1.0
CAPTURE_RETRY_SECONDS = 1.0


class EventClickerWorker(TaskWorker):
    """Clicks one point on a fixed cadence until stopped."""

    def __init__(
        self,
        hwnd: int,
        point: Optional[Tuple[int, int]] = None,
        interval: float = DEFAULT_INTERVAL_SECONDS,
        accept_wanted_quest: bool = False,
        on_finished: Callback = None,
        on_error: Callback = None,
        control: Optional[GameControl] = None,
    ) -> None:
        if interval < MIN_INTERVAL_SECONDS:
            raise ValueError(
                "Interval must be at least %.1fs" % MIN_INTERVAL_SECONDS
            )
        super().__init__("EventClickerWorker", hwnd, control, on_finished, on_error)
        self._interval = interval
        self._accept_wanted_quest = accept_wanted_quest

        # Stored in reference coordinates — the convention every other task's
        # points use — so one saved setting is still right on a window whose
        # client area is not the reference size.
        chosen = tuple(point) if point else geometry.EVENT_CLICK_POINT
        self._point = self._geometry.point(chosen)
        self._clicks = 0
        self._invites_handled = 0

    @property
    def progress(self) -> int:
        """Clicks made. See the module docstring: clicks, not battles."""
        return self._clicks

    def run(self) -> None:
        logger.info(
            "Event clicker starting — point=%s every %.1fs — %s",
            self._point, self._interval, self._control.describe(),
        )
        if not self._geometry.is_reference_size:
            logger.warning(
                "Client area is %dx%d but the point was saved against %dx%d "
                "— it has been scaled, which may not land where intended",
                self._geometry.client_width,
                self._geometry.client_height,
                *geometry.REFERENCE_CLIENT_SIZE,
            )
        self._begin_timing()
        try:
            self._loop()
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI below
            logger.exception("Event clicker crashed")
            self._notify(self._on_error, str(exc))
            return
        finally:
            self._end_timing()
            self._control.close()
        logger.info("Event clicker stopped after %d clicks", self._clicks)

    # ---------- main loop ----------

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self._wait_while_paused()
            if self._stop_event.is_set():
                break
            self._iteration += 1
            if self._iteration % LOOP_LOG_EVERY == 1:
                logger.info("loop iter=%d clicks=%d", self._iteration, self._clicks)
            try:
                self._control.begin_frame()
                self._step()
            except CaptureError:
                # Transient: window resized, minimised or being recreated. The
                # invite check needs a frame; the click does not, but waiting a
                # beat beats clicking into a window mid-rebuild.
                self._sleep(CAPTURE_RETRY_SECONDS)
            finally:
                self._control.end_frame()

    def _step(self) -> None:
        """One pass: answer a blocking dialog if there is one, else click."""
        if self._holding_for_the_cursor():
            return
        if self._handle_wanted_invite():
            return
        # Counted only if it went out. The control withholds clicks while the
        # player's cursor is over the game, and a figure that counts those is a
        # figure that drifts from what the game was actually told.
        if self._control.click(self._point):
            self._clicks += 1
        self._sleep(self._interval)

    def _handle_wanted_invite(self) -> bool:
        """Answer a co-op Wanted Quest invite. Shared with every other task."""
        target = wanted_invite.find_reply(
            self._control, self._geometry, self._accept_wanted_quest
        )
        if target is None:
            return False
        self._invites_handled += 1
        logger.info(
            "Wanted Quest invite: %s at %s (total %d)",
            "chap nhan" if self._accept_wanted_quest else "tu choi",
            target,
            self._invites_handled,
        )
        self._control.click(target)
        self._sleep(POPUP_SETTLE_SECONDS)
        return True
