"""Souls dungeon (Phụ bản ngự hồn) automation loop.

Two roles share one loop, because the member's job is a subset of the leader's:

* **Leader** — press Fight when the room is ready, then tap through the result.
  The game recreates the room and re-invites on its own, so there is nothing
  else to drive.
* **Member** — there is no Fight button; only the result screens are tapped.

Deciding whether Fight can be pressed is deliberately *not* a template match.
The lit and dead buttons carry the same lettering, so a greyscale template
matches both at 0.94, and matching in colour separates them by only 0.04 —
TM_CCOEFF_NORMED subtracts the mean, which cancels a uniform colour shift. The
colour is measured directly instead: mean saturation over a patch inside the
button was 149 lit against 4.5 dead, a 33x gap. See :mod:`geometry`.

That check earns its place: three seconds after a battle the room is back on
screen but the teammate has not rejoined, so the button is dead. A bot matching
only the button's shape would click there every single round.
"""
from __future__ import annotations

import logging
from typing import Optional

import cv2

import geometry
import wanted_invite
from game_control import CaptureError, GameControl
from paths import template
from task_worker import Callback, TaskWorker

logger = logging.getLogger(__name__)

# --- Template images -------------------------------------------------------
# Cut from a live co-op room at 1124x633. Measured separation on that recording:
# fight 1.000 against 0.32 elsewhere; tapContinue 0.951 against 0.43.
TPL_FIGHT = template("SoulsDungeon", "fight.png")
TPL_TAP_CONTINUE = template("SoulsDungeon", "tapContinue.png")
# The share and stats icons on the result screen, not the "Victory" lettering:
# the word has shikigami artwork behind it that changes every battle, and an
# animated shine over it. Realm Raid's own result templates were tried first and
# do not match this screen at all (0.48 and 0.63 against a 0.9 threshold).
TPL_VICTORY = template("SoulsDungeon", "victory.png")

# --- Tuning ----------------------------------------------------------------
DEFAULT_ACCURACY = 0.9
LOOP_LOG_EVERY = 30

ROLE_LEADER = "leader"
ROLE_MEMBER = "member"

BATTLE_POLL_SECONDS = 3.0
AFTER_FIGHT_SECONDS = 3.0
AFTER_TAP_SECONDS = 1.5
POPUP_SETTLE_SECONDS = 1.0
# How many passes with no result screen before the loop believes the battle is
# really over. One battle shows two result screens — the Victory banner and the
# reward screen — with a gap between them; a single-pass gap must not read as
# "back in the room, ready to count again".
RESULT_CLEAR_PASSES = 4
CAPTURE_RETRY_SECONDS = 1.0


class SoulsDungeonWorker(TaskWorker):
    """Runs the souls loop until stopped, or until the round count is reached."""

    def __init__(
        self,
        hwnd: int,
        role: str = ROLE_LEADER,
        rounds: int = 0,
        accept_wanted_quest: bool = False,
        accuracy: float = DEFAULT_ACCURACY,
        on_finished: Callback = None,
        on_error: Callback = None,
        control: Optional[GameControl] = None,
    ) -> None:
        if role not in (ROLE_LEADER, ROLE_MEMBER):
            raise ValueError("Role must be %r or %r" % (ROLE_LEADER, ROLE_MEMBER))
        if rounds < 0:
            raise ValueError("Rounds cannot be negative")
        super().__init__("SoulsDungeonWorker", hwnd, control, on_finished, on_error)
        self._role = role
        self._rounds = rounds            # 0 means keep going until stopped
        self._accuracy = accuracy
        self._accept_wanted_quest = accept_wanted_quest

        self._fight_button = self._geometry.point(geometry.SOULS_FIGHT_BUTTON)
        self._fight_patch = self._geometry.region(geometry.SOULS_FIGHT_PATCH)
        self._result_tap = self._geometry.point(geometry.SOULS_RESULT_TAP)

        self._completed = 0
        # Counting happens on the rising edge. The result screen sits there for
        # several seconds and the loop looks every second, so counting per pass
        # would score one battle as four or five.
        #
        # It starts *inside* the result state rather than outside it, and that
        # is the difference between a count that holds and one that drifts. A
        # run is usually started moments after the last was stopped, with the
        # previous battle's screen still on display; treating that as a rising
        # edge scores a battle this run never fought. Measured on a live log:
        # both windows wrote "Battle 1/9 finished" in the very second their
        # workers started, before a single Fight press, and the run then
        # reported three battles for the two it actually ran.
        self._in_result = True
        self._quiet_passes = 0
        self._invites_handled = 0

    @property
    def progress(self) -> int:
        """Battles finished. Counted from what this loop itself did."""
        return self._completed

    def run(self) -> None:
        logger.info(
            "Souls worker starting — role=%s rounds=%s — %s",
            self._role,
            self._rounds or "không giới hạn",
            self._control.describe(),
        )
        if not self._geometry.is_reference_size:
            logger.warning(
                "Client area is %dx%d but templates were captured near %dx%d "
                "— detection accuracy will suffer",
                self._geometry.client_width,
                self._geometry.client_height,
                *geometry.REFERENCE_CLIENT_SIZE,
            )
        self._begin_timing()
        try:
            finished = self._loop()
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI below
            logger.exception("Souls loop crashed")
            self._notify(self._on_error, str(exc))
            return
        finally:
            self._end_timing()
            self._control.close()

        if finished:
            logger.info("Souls run finished after %d battles", self._completed)
            self._notify(
                self._on_finished,
                "Xong %d trận phụ bản ngự hồn." % self._completed,
            )
        else:
            logger.info("Souls worker stopped after %d battles", self._completed)

    # ---------- main loop ----------

    def _loop(self) -> bool:
        """Returns True when the requested number of battles was reached."""
        while not self._stop_event.is_set():
            self._wait_while_paused()
            if self._stop_event.is_set():
                break
            self._iteration += 1
            if self._iteration % LOOP_LOG_EVERY == 1:
                logger.info(
                    "loop iter=%d done=%d/%s in_result=%s",
                    self._iteration,
                    self._completed,
                    self._rounds or "∞",
                    self._in_result,
                )
            try:
                self._control.begin_frame()
                if self._step():
                    return True
            except CaptureError:
                # Transient: window resized, minimised or being recreated.
                self._sleep(CAPTURE_RETRY_SECONDS)
            finally:
                self._control.end_frame()
        return False

    def _step(self) -> bool:
        """One decision pass. Returns True when the run is over."""
        if self._holding_for_the_cursor():
            return False
        # First: an invite modal covers the screen and swallows every click
        # underneath, so nothing else can make progress until it is answered.
        if self._handle_wanted_invite():
            return False

        if self._handle_result_screen():
            self._quiet_passes = 0
            return self._rounds > 0 and self._completed >= self._rounds

        # Leaving the result state is debounced. One battle shows *two* result
        # screens — the Victory banner, then the reward screen — and between
        # them is a moment where neither template matches. Clearing on the first
        # such pass made the reward screen count as a second battle: a real run
        # logged three battles in 44 seconds, two of them 6 and 16 seconds
        # apart, which no real fight takes.
        self._quiet_passes += 1
        if self._quiet_passes >= RESULT_CLEAR_PASSES:
            self._in_result = False

        if self._role == ROLE_LEADER and self._handle_fight_button():
            return False

        self._sleep(BATTLE_POLL_SECONDS)
        return False

    # ---------- handlers ----------

    def _find(self, template_path: str, accuracy: Optional[float] = None, **kwargs):
        return self._control.find(
            template_path,
            threshold=self._accuracy if accuracy is None else accuracy,
            **kwargs,
        )

    def _handle_wanted_invite(self) -> bool:
        """Answer a co-op Wanted Quest invite. Shared with every other task."""
        target = wanted_invite.find_reply(
            self._control, self._geometry, self._accept_wanted_quest
        )
        if target is None:
            return False
        self._invites_handled += 1
        logger.info(
            "Wanted Quest invite: %s at %s (tổng %d)",
            "chấp nhận" if self._accept_wanted_quest else "từ chối",
            target,
            self._invites_handled,
        )
        self._control.click(target)
        self._sleep(POPUP_SETTLE_SECONDS)
        return True

    def _handle_result_screen(self) -> bool:
        """Tap through the end of a battle, counting it once.

        Both roles do this, and it is the only thing a member does. The Victory
        banner is tapped as well as the reward screen: it advances on its own
        but slowly.
        """
        # One spot serves both, and it is nowhere near the middle. The middle
        # is where the loot and the line-up are drawn, and tapping there opens a
        # reward instead of dismissing the screen — which is what players
        # reported runs sticking on. See geometry.SOULS_RESULT_TAP.
        if (self._find(TPL_TAP_CONTINUE) is None
                and self._find(TPL_VICTORY) is None):
            return False
        target = self._result_tap

        # Rising edge only — the screen lingers for several passes.
        if not self._in_result:
            self._in_result = True
            self._completed += 1
            logger.info(
                "Battle %d/%s finished", self._completed, self._rounds or "∞"
            )

        self._control.click(target)
        self._sleep(AFTER_TAP_SECONDS)
        return True

    def _fight_is_lit(self) -> bool:
        """Whether the Fight button can actually be pressed.

        Measured, not matched: see the module docstring.
        """
        try:
            patch = self._control.part_shot(self._fight_patch)
        except CaptureError:
            return False
        if patch.size == 0:
            return False
        saturation = float(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)[:, :, 1].mean())
        lit = saturation >= geometry.SOULS_FIGHT_LIT_SATURATION
        if not lit:
            logger.debug("Fight button not lit (saturation %.1f)", saturation)
        return lit

    def _handle_fight_button(self) -> bool:
        """Start the next battle, but only once the room is actually ready."""
        if self._find(TPL_FIGHT) is None:
            return False
        if not self._fight_is_lit():
            # In the room, teammates not back yet. Wait rather than click.
            self._sleep(BATTLE_POLL_SECONDS)
            return True
        logger.info("Starting battle %d", self._completed + 1)
        self._control.click(self._fight_button)
        self._sleep(AFTER_FIGHT_SECONDS)
        return True
