"""Click sequence: press several chosen points in order, then go round again.

The event clicker's idea taken one step further. Some screens need more than
one press in a fixed order — open a panel, pick a tab, confirm — and the
positions never move, so the loop again needs no idea which screen it is on.
Each point carries its own wait, because a press that opens a new screen needs
longer before the next one than a press that only toggles something.

**Nothing here reads the screen, so nothing here can tell that a step missed.**
If a press opens something unexpected — a ticket shop priced in jade is the
case that matters — the next points in the list land on whatever that is. The
task page says so, and the danger is the same one the event clicker documents.

What it does read is a co-op Wanted Quest invite, like every other task: that
dialog covers the screen and swallows every click underneath, so a blind loop
would press into it for the rest of the run.

The count is **rounds**, one per pass through the whole list. A step is never
skipped to keep the count moving: a press the control withheld (the player's
cursor was over the game) is retried, so a round always means every point in
it went out once.
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence, Tuple

import geometry
import wanted_invite
from game_control import CaptureError, GameControl
from task_worker import Callback, TaskWorker

logger = logging.getLogger(__name__)

MIN_WAIT_SECONDS = 0.5
POPUP_SETTLE_SECONDS = 1.0
CAPTURE_RETRY_SECONDS = 1.0
WITHHELD_RETRY_SECONDS = 0.5
LOOP_LOG_EVERY = 10

Step = Tuple[int, int, float]


class SequenceClickerWorker(TaskWorker):
    """Clicks each step's point in turn, waiting each step's time after it."""

    def __init__(
        self,
        hwnd: int,
        steps: Sequence[Step],
        rounds: int = 0,
        accept_wanted_quest: bool = False,
        on_finished: Callback = None,
        on_error: Callback = None,
        control: Optional[GameControl] = None,
    ) -> None:
        if not steps:
            raise ValueError("A click sequence needs at least one point")
        if rounds < 0:
            raise ValueError("Rounds cannot be negative")
        for step in steps:
            if float(step[2]) < MIN_WAIT_SECONDS:
                raise ValueError("Each wait must be at least %.1fs" % MIN_WAIT_SECONDS)
        super().__init__("SequenceClickerWorker", hwnd, control, on_finished, on_error)
        self._rounds = int(rounds)            # 0 means keep going until stopped
        self._accept_wanted_quest = accept_wanted_quest
        # Saved in reference coordinates, like every other point the app keeps,
        # and scaled here to the window actually being driven.
        self._steps = [
            (self._geometry.point((int(x), int(y))), float(wait))
            for x, y, wait in steps
        ]
        self._completed = 0
        self._clicks = 0
        self._invites_handled = 0

    @property
    def progress(self) -> int:
        """Rounds completed: passes through the whole list."""
        return self._completed

    @property
    def clicks(self) -> int:
        return self._clicks

    def run(self) -> None:
        logger.info(
            "Sequence clicker starting — %d points, rounds=%s — %s",
            len(self._steps), self._rounds or "không giới hạn",
            self._control.describe(),
        )
        if not self._geometry.is_reference_size:
            logger.warning(
                "Client area is %dx%d but the points were saved against %dx%d "
                "— they have been scaled, which may not land where intended",
                self._geometry.client_width,
                self._geometry.client_height,
                *geometry.REFERENCE_CLIENT_SIZE,
            )
        self._begin_timing()
        try:
            finished = self._loop()
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI below
            logger.exception("Sequence clicker crashed")
            self._notify(self._on_error, str(exc))
            return
        finally:
            self._end_timing()
            self._control.close()

        if finished:
            logger.info("Sequence clicker finished after %d rounds", self._completed)
            self._notify(self._on_finished,
                         "Xong %d vòng nhấn theo chuỗi." % self._completed)
        else:
            logger.info("Sequence clicker stopped after %d rounds (%d clicks)",
                        self._completed, self._clicks)

    # ---------- main loop ----------

    def _loop(self) -> bool:
        """Returns True when the requested number of rounds was reached."""
        while not self._stop_event.is_set():
            self._iteration += 1
            if self._iteration % LOOP_LOG_EVERY == 1:
                logger.info("round %d starting, %d done", self._iteration, self._completed)
            for index, (point, wait) in enumerate(self._steps):
                if not self._press(index, point):
                    return False       # stopped part-way through a round
                self._sleep(wait)
                if self._stop_event.is_set():
                    return False
            self._completed += 1
            if self._rounds and self._completed >= self._rounds:
                return True
        return False

    def _press(self, index: int, point) -> bool:
        """Click this step's point once. False only if the run was stopped.

        Loops until the click actually goes out: a paused run, a cursor resting
        on the game, a capture that failed or an invite in the way all hold the
        step rather than skip it.
        """
        while not self._stop_event.is_set():
            self._wait_while_paused()
            if self._stop_event.is_set():
                return False
            if self._holding_for_the_cursor():
                continue
            try:
                self._control.begin_frame()
                if self._handle_wanted_invite():
                    continue
                if self._control.click(point):
                    self._clicks += 1
                    logger.debug("step %d clicked at %s", index + 1, point)
                    return True
                # Withheld between the cursor check and the click. Wait a beat
                # instead of asking again straight away.
                self._sleep(WITHHELD_RETRY_SECONDS)
            except CaptureError:
                # The invite check needs a frame. A window being resized or
                # rebuilt is waited out rather than clicked into.
                self._sleep(CAPTURE_RETRY_SECONDS)
            finally:
                self._control.end_frame()
        return False

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
            target, self._invites_handled,
        )
        self._control.click(target)
        self._sleep(POPUP_SETTLE_SECONDS)
        return True
