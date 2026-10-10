"""Duel (Đấu PvP) automation loop: queue, let the game pick and fight, repeat.

Built from a recording of 18 ranked matches (recordings/pvp, Tier 1 to Tier 5).
One match is about a minute and always runs through the same screens:

    lobby ── Battle ──> matching ──> pick ──> battle ──> result ──> lobby
                                                           │
                                  new tier / achievement <─┘ (sometimes)

Every decision here is made by reading a button whose *label shows its state*,
so every click is one that cannot be undone by clicking again:

* **Pick, simultaneous kind** (a "Fight" title and a 30 s count): the saved
  lineup is placed by the game, and "Ready" is lettered red until pressed, grey
  after. Matched in grey, red scores 0.95 against at most 0.84 grey, and the
  task presses only the red one.
* **Pick, draft kind** (a drum calling "Round 1…4"): starts with auto pick off
  every time, its button reading "Auto Deploy". Pressed, it reads "Cancel Auto"
  and the game makes every pick and confirms the lineup itself.
* **Battle**: every match starts in Manual — the bottom-left gear says
  "Manual" — and pressing it switches to Auto. The recording had the player
  doing this by hand in nearly every match.
* **Result**, **new tier**, **achievement**: tapped away. The first 1, 3 and 5
  wins of the week pay out through the achievement popup; "Wins This" rewards
  are credited without a tap.

Win or loss is never looked at — both results draw the same "Tap to continue".

Two things end a run besides Stop. A target score (2400, 2700, Danh sĩ at 3000)
is checked in the lobby before every queue, reading the score under the tier;
see :mod:`duel_score`. And outside PvP hours the Battle drum becomes "Prac."
(practice), which the task will not press.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, Optional

import geometry
import wanted_invite
from duel_score import CELEBRITY, ScoreReader
from game_control import CaptureError, GameControl
from paths import template
from task_worker import Callback, TaskWorker

logger = logging.getLogger(__name__)

# --- Template images -------------------------------------------------------
# Cut from recordings/pvp (1136x640) and scaled to the reference size. Best
# score on the frames that show each one / best anywhere else in the recording:
TPL_BATTLE = template("Duel", "battle.png")              # 0.97 / 0.66
TPL_PRAC = template("Duel", "prac.png")                  # (sent by a player) / 0.60
TPL_READY = template("Duel", "ready.png")                # red 0.95 / grey 0.84
TPL_MANUAL = template("Duel", "manual.png")              # 0.85 / 0.59 ("Auto")
TPL_AUTO_DEPLOY = template("Duel", "autoDeploy.png")     # 0.99 / 0.57
TPL_TAP_CONTINUE = template("Duel", "tapContinue.png")   # 0.87 / 0.77 (fading)
TPL_TAP_SKIP = template("Duel", "tapSkip.png")           # 0.89 / 0.50
TPL_ACHIEVEMENT = template("Duel", "achievement.png")    # 0.95 / 0.35

DEFAULT_ACCURACY = 0.85
# Higher for Ready: the pressed (grey) button reaches 0.84, and pressing it
# again is the one click here whose effect is not known.
READY_ACCURACY = 0.9
MANUAL_ACCURACY = 0.8

# --- Where each one is looked for (reference coordinates) ------------------
BATTLE_REGION = ((960, 470), (1122, 633))     # also where "Prac." sits
READY_REGION = ((940, 450), (1122, 633))
MANUAL_REGION = ((0, 520), (170, 633))
AUTO_DEPLOY_REGION = ((0, 60), (150, 200))
PROMPT_REGION = ((380, 570), (760, 633))      # "Tap to continue" / "…to skip"
ACHIEVEMENT_REGION = ((380, 440), (760, 600))

# --- Targets ---------------------------------------------------------------
DANH_SI_SCORE = 3000

# --- Tuning ----------------------------------------------------------------
LOOP_LOG_EVERY = 30
POLL_SECONDS = 1.0
AFTER_TAP_SECONDS = 1.5
AFTER_CLICK_SECONDS = 1.5
AFTER_BATTLE_SECONDS = 3.0
# Each of these buttons is a switch whose label changes a moment after it is
# pressed — Ready fades from red to grey over about a second, Manual becomes
# Auto. A second press inside that moment would switch it straight back, so a
# button is pressed at most once per this long. Ready is given longer: its fade
# kept scoring as red for up to a second and a half on the recording.
REPEAT_SECONDS = 3.0
READY_REPEAT_SECONDS = 5.0
# The lobby's Battle drum is pressed at most once per this long. Pressed, the
# lobby gives way to matching; a second press on a lobby slow to go would land
# on whatever the drum has become.
BATTLE_REPEAT_SECONDS = 6.0
# Lobby passes in a row whose score will not read before the run stops. A
# popup fading over the lobby costs one or two; something that stays costs the
# run, rather than letting it queue past a target it cannot see.
UNREADABLE_LOBBY_LIMIT = 6
CAPTURE_RETRY_SECONDS = 1.0


class DuelWorker(TaskWorker):
    """Runs ranked Duel matches until stopped, the target score, or closing time."""

    def __init__(
        self,
        hwnd: int,
        target: int = 0,
        accept_wanted_quest: bool = False,
        accuracy: float = DEFAULT_ACCURACY,
        on_finished: Callback = None,
        on_error: Callback = None,
        control: Optional[GameControl] = None,
        reader: Optional[ScoreReader] = None,
    ) -> None:
        if target < 0:
            raise ValueError("Target score cannot be negative")
        super().__init__("DuelWorker", hwnd, control, on_finished, on_error)
        self._target = target            # 0 means keep going until stopped
        self._accuracy = accuracy
        self._accept_wanted_quest = accept_wanted_quest
        # Loaded in ``run`` when not given, so a missing glyph file is reported
        # as this run's error rather than raised on the UI thread that built it.
        self._reader = reader

        g = self._geometry
        self._tap = g.point(geometry.DUEL_TAP)
        self._battle_region = g.region(BATTLE_REGION)
        self._ready_region = g.region(READY_REGION)
        self._manual_region = g.region(MANUAL_REGION)
        self._auto_deploy_region = g.region(AUTO_DEPLOY_REGION)
        self._prompt_region = g.region(PROMPT_REGION)
        self._achievement_region = g.region(ACHIEVEMENT_REGION)

        self._completed = 0
        # A result is counted when it appears, and the count is re-armed only by
        # a screen of the next match — not by the result going away. After an
        # achievement popup is tapped, the same result screen comes back
        # (293.9 s on the recording); re-arming on its absence counted it twice.
        #
        # Starts unarmed, as the souls loop does: a run started on a result left
        # over from the last one must not count it.
        self._result_armed = False
        # When each button was last pressed, by template.
        self._pressed_at: Dict[str, float] = {}
        self._unreadable_lobbies = 0
        self._last_score: Optional[int] = None
        self._finish_message = ""
        self._invites_handled = 0

    @property
    def progress(self) -> int:
        """Matches finished, counted from result screens this run saw."""
        return self._completed

    def run(self) -> None:
        logger.info(
            "Duel worker starting — target=%s — %s",
            self._target or "không",
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
            if self._reader is None:
                self._reader = ScoreReader()
            finished = self._loop()
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI below
            logger.exception("Duel loop crashed")
            self._notify(self._on_error, str(exc))
            return
        finally:
            self._end_timing()
            self._control.close()

        if finished:
            logger.info("Duel run over after %d matches: %s",
                        self._completed, self._finish_message)
            self._notify(self._on_finished, self._finish_message)
        else:
            logger.info("Duel worker stopped after %d matches", self._completed)

    # ---------- main loop ----------

    def _loop(self) -> bool:
        """Returns True when the run ended by itself rather than by Stop."""
        while not self._stop_event.is_set():
            self._wait_while_paused()
            if self._stop_event.is_set():
                break
            self._iteration += 1
            if self._iteration % LOOP_LOG_EVERY == 1:
                logger.info("loop iter=%d matches=%d score=%s",
                            self._iteration, self._completed, self._last_score)
            try:
                self._control.begin_frame()
                if self._step():
                    return True
            except CaptureError:
                self._sleep(CAPTURE_RETRY_SECONDS)
            finally:
                self._control.end_frame()
        return False

    def _step(self) -> bool:
        """One decision pass. Returns True when the run is over."""
        # Counting only looks, so it happens before the cursor check: a result
        # that comes and goes under the player's mouse still counts.
        holding = self._holding_for_the_cursor()
        invite = self._invite_target()
        on_result = invite is None and self._find(
            TPL_TAP_CONTINUE, region=self._prompt_region) is not None
        if on_result:
            self._count_result()
        if holding:
            return False

        if invite is not None:
            self._answer_invite(invite)
            return False

        # Screens that cover others come first. The achievement popup and the
        # new-tier screen are drawn over the lobby, whose Battle drum still
        # matches straight through them.
        if (self._find(TPL_ACHIEVEMENT, region=self._achievement_region)
                or self._find(TPL_TAP_SKIP, region=self._prompt_region)
                or on_result):
            self._tap_away()
            return False

        # Every screen from here down belongs to a match in progress or the
        # lobby before one, so seeing any of them re-arms the result count.
        if self._press(TPL_AUTO_DEPLOY, self._auto_deploy_region,
                       "Auto Deploy — turning on auto pick"):
            self._result_armed = True
            return False
        if self._press(TPL_READY, self._ready_region,
                       "Pick screen — pressing Ready",
                       accuracy=READY_ACCURACY, repeat=READY_REPEAT_SECONDS):
            self._result_armed = True
            return False
        if self._press(TPL_MANUAL, self._manual_region,
                       "Battle in Manual — switching to Auto",
                       accuracy=MANUAL_ACCURACY):
            self._result_armed = True
            return False

        if self._find(TPL_PRAC, region=self._battle_region) is not None:
            self._finish_message = ("Ngoài giờ đấu PvP (nút Battle đã thành "
                                    "Prac.) — dừng sau %d trận."
                                    % self._completed)
            return True
        battle = self._find(TPL_BATTLE, region=self._battle_region)
        if battle is not None:
            self._result_armed = True
            return self._in_lobby(battle)

        # Matching, loading, the draft playing itself, a battle on Auto.
        self._sleep(POLL_SECONDS)
        return False

    # ---------- handlers ----------

    def _find(self, template_path: str, accuracy: Optional[float] = None, **kwargs):
        return self._control.find(
            template_path,
            threshold=self._accuracy if accuracy is None else accuracy,
            **kwargs,
        )

    def _invite_target(self):
        return wanted_invite.find_reply(
            self._control, self._geometry, self._accept_wanted_quest
        )

    def _answer_invite(self, target) -> None:
        self._invites_handled += 1
        logger.info(
            "Wanted Quest invite: %s at %s (tổng %d)",
            "chấp nhận" if self._accept_wanted_quest else "từ chối",
            target,
            self._invites_handled,
        )
        self._control.click(target)
        self._sleep(AFTER_TAP_SECONDS)

    def _count_result(self) -> None:
        """Count a match on its result screen, once per match."""
        if self._result_armed:
            self._result_armed = False
            self._completed += 1
            logger.info("Match %d finished", self._completed)

    def _tap_away(self) -> None:
        self._control.click(self._tap)
        self._sleep(AFTER_TAP_SECONDS)

    def _press(self, template_path: str, region, what: str,
               accuracy: Optional[float] = None,
               repeat: float = REPEAT_SECONDS) -> bool:
        """Press a switch where it was found, if its label says it is off.

        True when the button was on screen, pressed or not: a button still
        showing within ``repeat`` of its last press is mid-change, and the pass
        waits for it rather than going on to look for anything else.
        """
        where = self._find(template_path, accuracy=accuracy, region=region)
        if where is None:
            return False
        now = time.monotonic()
        last = self._pressed_at.get(template_path)
        if last is not None and now - last < repeat:
            self._sleep(POLL_SECONDS)
            return True
        logger.info(what)
        # Only a click that was really sent starts the wait. One withheld for
        # the player's cursor changed nothing on screen to wait for.
        if self._control.click(where):
            self._pressed_at[template_path] = now
        self._sleep(AFTER_CLICK_SECONDS)
        return True

    def _in_lobby(self, battle) -> bool:
        """Check the target, then queue. True when the target is reached."""
        if self._target:
            reading = self._reader.read(self._control.reference_shot(gray=True))
            if reading is None:
                self._unreadable_lobbies += 1
                logger.info("Lobby score unreadable (%d/%d)",
                            self._unreadable_lobbies, UNREADABLE_LOBBY_LIMIT)
                if self._unreadable_lobbies >= UNREADABLE_LOBBY_LIMIT:
                    self._finish_message = (
                        "Không đọc được điểm ở sảnh (có bảng che?). Dừng để "
                        "không đánh quá mục tiêu (đã đánh %d trận)."
                        % self._completed)
                    return True
                self._sleep(POLL_SECONDS)
                return False
            self._unreadable_lobbies = 0
            if reading == CELEBRITY:
                # Danh sĩ is 3000, the highest target there is: reached.
                self._finish_message = ("Đã lên Danh sĩ sau %d trận."
                                        % self._completed)
                return True
            score = reading[0]
            if score != self._last_score:
                logger.info("Duel score %d/%d (target %d)",
                            score, reading[1], self._target)
                self._last_score = score
            if score >= self._target:
                self._finish_message = (
                    "Đã đạt %d điểm (mục tiêu %d) sau %d trận."
                    % (score, self._target, self._completed))
                return True
        now = time.monotonic()
        last = self._pressed_at.get(TPL_BATTLE)
        if last is not None and now - last < BATTLE_REPEAT_SECONDS:
            self._sleep(POLL_SECONDS)
            return False
        logger.info("Lobby — pressing Battle (match %d)", self._completed + 1)
        if self._control.click(battle):
            self._pressed_at[TPL_BATTLE] = now
        self._sleep(AFTER_BATTLE_SECONDS)
        return False
