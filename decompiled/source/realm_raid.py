"""Realm Raid (Phá Kết Giới) automation loop.

Each pass captures one frame and walks an ordered chain of handlers; the first
one whose template matches acts and ends the pass. The order encodes priority:
end-of-run and popup states are checked before anything that clicks into a
fight, so the bot never attacks while a modal is covering the board.
"""
from __future__ import annotations

import logging
import time
from typing import Optional, Tuple

import win32gui

import cv2

import dpi
import geometry
import ticket_counter
from game_control import CaptureError, GameControl, read_image
from geometry import Point
from paths import template
from task_worker import Callback, TaskWorker

logger = logging.getLogger(__name__)

# --- Template images -------------------------------------------------------
TPL_START = template("RealmRaid", "start.png")
TPL_SECTION = template("RealmRaid", "section.png")
TPL_FINISHED_BATTLE = template("RealmRaid", "finished1.png")
TPL_CLAIM_REWARD = template("RealmRaid", "finished2.png")
TPL_FAILED = template("RealmRaid", "failed.png")
TPL_RAID_ENTRY = template("RealmRaid", "realmRaid.png")
TPL_REFRESH = template("RealmRaid", "refresh.PNG")
# The mark a lost battle leaves on an opponent's card: a gold arrow on a lit
# background, cut from a live board right after a loss.
#
# Both fought states carry that arrow, so what separates them is the ground it
# sits on — lit for a loss, grey with a red KO stamp for a win. Matched in
# colour for the same reason. Measured on the frame it came from: 1.000 on the
# lost card against 0.393-0.445 on all eight others, KO and untouched alike, and
# at most 0.486 anywhere on a board where nobody had lost yet.
TPL_LOST = template("RealmRaid", "lost.png")
# The sentence on "Sure you want to leave the battle?" — the only screen that
# carries it. Measured 1.000 on the dialog against at most 0.386 across 92 other
# frames, the raid board and every recorded souls screen included.
TPL_LEAVE_BATTLE = template("RealmRaid", "leaveBattle.png")
# There is no template for the board's own title bar any more. rank.PNG held it
# and gated a branch that pressed Refresh whenever the board was up with no
# enemies left — which the game does not need, because it hands out a new board
# by itself once all nine are beaten. The branch could not have run anyway:
# rank.PNG was cut from a window roughly 20% larger and scores 0.599 on a live
# board, where section.png scores 0.959 and refresh.PNG 0.921 on the same frame.
# Refresh is now pressed for one reason only, a defeat. The file is left in
# screenshots/RealmRaid beside the other six nothing references.
# The numerator glyph of the ticket counter, cut from a live "0/30".
TPL_TICKET_ZERO = template("RealmRaid", "ticketZero.png")
# The game's own words when an attack is refused for want of passes: "Not
# enough Realm Challenge Passes". Cut tight to the lettering, because the card
# behind it changes with whichever enemy is open.
#
# This outranks everything else here. Reading the counter is guesswork — a live
# "6/30" scored 0.745 against the stored "0", over the 0.72 the reader trusted —
# and watching for a battle that never comes only says something did not
# happen. The message says why. Measured 1.000 on the frame it came from
# against 0.381 on an unrelated screen.
TPL_NO_PASSES = template("RealmRaid", "noPasses.png")
TPL_IN_BATTLE = template("RealmRaid", "battle.png")
TPL_OK = template("RealmRaid", "ok.png")
TPL_FROG = template("RealmRaid", "frog.png")
TPL_READY_CLICK = template("RealmRaid", "click.png")
TPL_READY_TAP = template("RealmRaid", "tap.png")
TPL_COOLDOWN = template("RealmRaid", "cooldown.png")
TPL_WANTED_ACCEPT = template("RealmRaid", "wantedAccept.png")
TPL_WANTED_REFUSE = template("RealmRaid", "wantedRefuse.png")

# --- Tuning ----------------------------------------------------------------
DEFAULT_ACCURACY = 0.9
COOLDOWN_ACCURACY = 0.85
# Below this the attack button is absent rather than mid-animation, so clicking
# the best match would be clicking noise. Set from a real failing run, where an
# absent button scored 0.32-0.44; deliberately left low so that anything which
# might genuinely be the button still gets clicked. See `_click_attack`.
ATTACK_FLOOR = 0.5
# The invite buttons are matched in colour — the green tick and the red cross
# are near-identical once greyscaled. Measured separation on real frames was
# 1.00 on the dialog against 0.58 anywhere else, so 0.75 has room either way.
WANTED_ACCURACY = 0.75
# After this many consecutive frames stuck on the same screen, assume an
# invisible modal is swallowing clicks and dismiss it.
STUCK_LIMIT = 10
# Presses of the attack button, in a row, with no battle following, before the
# loop stops believing the button will ever work.
#
# The game refuses an attack it has no ticket for with a toast that is gone in
# about a second. Catch it and the run ends tidily; miss it and — measured on a
# live run — the loop presses the same button 107 times and never stops. It
# cannot fall back on the ticket counter either, because with an enemy card open
# the attack button is on screen, `_handle_start_button` claims the pass, and the
# branch that reads the counter is never reached.
#
# What is never missed is that nothing happened. Eight presses is well past any
# genuine mis-timing — a real attack is answered on the first or second.
START_REFUSAL_LIMIT = 8
LOOP_LOG_EVERY = 20

# Consecutive passes in which no template matched anything, before the loop
# accepts it is parked on a screen it has no picture of.
#
# Nothing used to notice this at all. `_stuck_count` cannot: it is bumped only
# by handlers that *did* match, and a pass where nothing matched reset it to
# zero — so on a screen with no template the counter sat at 0 for ever. Two
# live logs show what that cost: 2340 passes over 12.5 minutes, ended only by
# the user pressing Stop, and 1200 passes over 6 minutes.
#
# It has to clear a whole fight, and that is what the first version got wrong.
# A raid battle matches *nothing*: battle.png scored 0.780 against a live fight,
# under the 0.9 threshold, and "Battle in progress" has never once been logged
# on this account — so the loop is blind for every fight it runs, not
# occasionally. Fights measure 15-25 seconds; at ~0.6s a pass the old limit of
# 30 landed inside that window and the escape went off mid-fight.
#
# 300 passes is roughly three minutes: longer than any fight, and still a small
# fraction of the 12.5-minute silent stall this exists to break.
UNKNOWN_SCREEN_LIMIT = 300
# Escapes that click an empty corner. Nothing follows them — see
# _escape_unknown_screen.
UNKNOWN_SCREEN_CORNER_ESCAPES = 2

# The ticket counter is only believed after this many readings in a row, spaced
# by the pause below. One reading is not enough: the region is fixed, so a
# screen sliding in or out can put something round in front of it for a frame.
TICKET_ZERO_CONFIRMATIONS = 3
# Test attacks that must all fail before the account is called empty. One
# failure is as likely to be a click that missed as an empty account.
TICKET_PROBE_ATTEMPTS = 3
TICKET_RECHECK_SECONDS = 1.0

# What the counter says, once the board is confirmed to be on screen.
TICKETS_LEFT = "left"
TICKETS_PENDING = "pending"   # read zero, not confirmed yet
TICKETS_PROBE = "probe"       # read zero; attack once and see if it works
TICKETS_GONE = "gone"

READY_SETTLE_SECONDS = 3.0
BATTLE_POLL_SECONDS = 5.0
REWARD_CLICK_GAP_SECONDS = 0.5
POPUP_SETTLE_SECONDS = 1.0
# After the attack lands, how long to wait for the raid board to leave the
# screen before carrying on.
#
# Without this the loop came straight back round about a second later, found the
# board still painted mid-transition, clicked another enemy — and that click went
# nowhere, because by the time it landed the board was gone. Every second attack
# in a live log failed that way:
#
#     14:43:50  Attack button score=0.943 - clicking
#     14:43:51  Enemy found (section) at (684, 377)
#     14:43:52  Attack button not on screen (score=0.370)
#
# Tickets then sat unspent while the loop looked busy. Waiting for the board to
# actually go is the only way to know the attack took.
ATTACK_HANDOVER_SECONDS = 6.0
ATTACK_HANDOVER_POLL = 0.4

# Resizing to an exact client size takes more than one go: the game adjusts its
# own window afterwards to keep an aspect ratio.
RESIZE_PASSES = 3
RESIZE_TOLERANCE = 1        # px; landing a pixel out is not worth another pass
RESIZE_SETTLE_SECONDS = 0.25
# Roughly what a window frame adds, only for telling the user how much screen
# the window needs. Not used to size anything — that frame is measured.
RESIZE_FRAME_ALLOWANCE = (16, 39)
REFRESH_SETTLE_SECONDS = 2.0
# Passes to keep looking for the Refresh button after a defeat before giving up.
#
# The board does not come back the instant the defeat panel closes: measured on
# the one defeat in the logs, six seconds passed between "Defeated" and the
# enemy list matching again. At the ~0.6s a pass takes on a live run that is
# about ten passes, so this leaves well over double.
#
# It has to end, though, and not only because of timing: a *guild* raid board
# has no Refresh button at all — the individual one does, bottom right, measured
# 0.921 on a live frame. On a guild raid this wait will always expire.
REFRESH_WAIT_PASSES = 25
# Consecutive passes with the board up and nothing attackable on it before the
# list is re-rolled.
#
# Absence needs confirming in a way presence does not: a board caught sliding in
# has no enemies on it yet either, and re-rolling then throws away opponents
# nobody has fought.
EMPTY_BOARD_CONFIRMATIONS = 3
# Times Refresh may be pressed in a row while the board stays exactly as it was.
#
# Pressing it opens "Raid log progress will be reset if you refresh. Continue?",
# and the board — the lost marker included — is still matchable through that
# dialog. Answering the dialog is the fix; this is the net under it, for
# whatever sits on the board next. Without it a live run pressed Refresh once
# every 2.2 seconds for 2200 passes and only stopped when it was killed.
REFRESH_PRESS_LIMIT = 3
# How close two points have to be to count as the same opponent card. Cards sit
# about 118px apart on the board, and the matched point drifts a few pixels
# between passes, so this only has to be bigger than the drift.
SAME_ENEMY_WITHIN = 50
CAPTURE_RETRY_SECONDS = 1.0



class RealmRaidWorker(TaskWorker):
    """Runs the raid loop until stopped, tickets run out, or the loop crashes.

    Stopping is cooperative: ``stop()`` sets an event that the loop and every
    sleep honours. The previous build injected ``SystemExit`` into the thread
    with ``PyThreadState_SetAsyncExc``, which could land mid-GDI-call and leak
    device contexts.
    """

    def __init__(
        self,
        hwnd: int,
        auto_refresh: bool = False,
        accuracy: float = DEFAULT_ACCURACY,
        on_finished: Callback = None,
        on_error: Callback = None,
        stop_when_out_of_tickets: bool = True,
        accept_wanted_quest: bool = False,
        control: Optional[GameControl] = None,
    ) -> None:
        # A caller running several windows at once shares one GameControl per
        # window with the UI, so the preview and the loop capture through the
        # same device contexts instead of two competing sets — hence `control`
        # being passed down rather than a handle alone.
        super().__init__("RealmRaidWorker", hwnd, control, on_finished, on_error)
        self._accuracy = accuracy
        self._auto_refresh = auto_refresh
        self._stop_when_out_of_tickets = stop_when_out_of_tickets
        self._accept_wanted_quest = accept_wanted_quest
        self._leave_cancel = self._geometry.point(geometry.RAID_LEAVE_CANCEL)
        self._ready_button = self._geometry.point(geometry.TAP_READY_BUTTON)
        self._popup_dismiss = self._geometry.point(geometry.POPUP_DISMISS_POINT)
        self._ticket_region = self._geometry.region(geometry.TICKET_TEXT_REGION)
        self._guild_tab = self._geometry.region(geometry.GUILD_TAB_PATCH)
        self._individual_tab = self._geometry.region(
            geometry.INDIVIDUAL_TAB_PATCH)
        self._guild_attempts = self._geometry.region(geometry.GUILD_ATTEMPTS_REGION)
        self._zero_template = read_image(
            TPL_TICKET_ZERO, cv2.IMREAD_GRAYSCALE
        )
        self._wanted_gap = self._geometry.point((0, geometry.WANTED_BUTTON_GAP))[1]

        self._stuck_count = 0
        self._refresh_pending = False
        # Passes spent looking for the Refresh button. See REFRESH_WAIT_PASSES.
        self._refresh_waits = 0
        # Consecutive passes seeing a board with nothing left to attack, and
        # Refresh presses that have not changed anything. See REFRESH_PRESS_LIMIT.
        self._empty_reads = 0
        self._refresh_presses = 0
        # Opponents this board has refused, and the one being attacked now.
        # Cleared when the list is re-rolled, because the cards change with it.
        self._refused: list = []
        self._last_enemy: Optional[Point] = None
        self._out_of_tickets_logged = False
        # Whether a zero reading is currently being tested by attacking,
        # whether that test produced a battle, and how many tests in a row have
        # produced none. See _ticket_verdict.
        self._probing = False
        self._saw_battle = False
        self._failed_probes = 0
        self._passes_refused = False
        self._zero_reads = 0
        self._invites_handled = 0
        # Attack presses since the last battle, and the flag that ends the run
        # once they have plainly stopped working. See START_REFUSAL_LIMIT.
        self._start_clicks = 0
        self._finish_now = False
        # Passes with nothing recognised, and escapes attempted since the last
        # screen the loop did understand. See UNKNOWN_SCREEN_LIMIT.
        self._unknown_passes = 0
        self._escapes = 0

    # ---------- lifecycle ----------

    # Only the log lines are this loop's own; the state changes are the base
    # class's. This is a long-running task somebody leaves unattended, so the
    # log has to say when it stopped doing anything and when it started again.
    def pause(self) -> None:
        super().pause()
        logger.info("Paused")

    def resume(self) -> None:
        super().resume()
        logger.info("Resumed")

    # No `progress` property: this loop reports no count. The number of battles
    # was only ever displayed, and it came from counting reward panels — which
    # miss whenever the panel is skipped or matched late, so the figure drifted
    # away from reality over a long run. `progress` is optional in the worker
    # protocol (see :mod:`tasks`); a task without it simply shows no counter.

    def run(self) -> None:
        logger.info("Raid worker starting — %s", self._control.describe())
        if not self._geometry.is_reference_size:
            logger.warning(
                "Client area is %dx%d but templates were captured at %dx%d "
                "(scale %.3fx%.3f) — detection accuracy will suffer",
                self._geometry.client_width,
                self._geometry.client_height,
                *geometry.REFERENCE_CLIENT_SIZE,
                *self._geometry.scale,
            )
        self._begin_timing()
        try:
            finished = self._loop()
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI below
            logger.exception("Raid loop crashed")
            self._notify(self._on_error, str(exc))
            return
        finally:
            self._end_timing()
            self._control.close()

        if finished:
            logger.info("Raid run finished (out of tickets)")
            self._notify(self._on_finished, "Hết vé phá kết giới.")
        else:
            logger.info("Raid worker stopped")

    def raid_until_out_of_tickets(self) -> bool:
        """Run the raid loop on the **calling** thread; True if tickets ran out.

        ``run`` is the thread entry point and does more than the loop: it starts
        the clock, closes the window's device contexts and tells the UI the task
        finished. A caller that already owns the window and the clock — the map
        farm, which raids and then goes back to the map — wants the loop and
        none of that, so it gets a door of its own instead of reaching in for
        ``_loop``.
        """
        return self._loop()

    # ---------- main loop ----------

    def _loop(self) -> bool:
        """Returns True when the run completed on its own (tickets exhausted)."""
        while not self._stop_event.is_set():
            self._wait_while_paused()
            if self._stop_event.is_set():
                break
            self._iteration += 1
            if self._iteration % LOOP_LOG_EVERY == 1:
                logger.info(
                    "loop iter=%d stuck=%d refresh_pending=%s zero_reads=%d "
                    "unknown=%d",
                    self._iteration,
                    self._stuck_count,
                    self._refresh_pending,
                    self._zero_reads,
                    self._unknown_passes,
                )
            try:
                # One capture serves every template read in this pass; clicks
                # and sleeps invalidate it so nothing matches a stale frame.
                self._control.begin_frame()
                if self._step():
                    return True
            except CaptureError:
                # Transient: the window was resized, minimised or is being
                # recreated. Device contexts were dropped; retry shortly.
                self._sleep(CAPTURE_RETRY_SECONDS)
            finally:
                self._control.end_frame()
        return False

    def _step(self) -> bool:
        """One decision pass. Returns True when the run is over."""
        if self._holding_for_the_cursor():
            return False
        if self._finish_now:
            return True
        if self._handle_pending_refresh():
            self._recognised()
            return False

        blocking = [
            # First: an invite dialog sits on top of everything and swallows
            # every click underneath it, so nothing else can make progress.
            self._handle_wanted_invite,
            # Then the one modal that costs something to ignore: a fight is
            # running behind it, and the board still matches straight through.
            self._handle_leave_battle,
            self._handle_cooldown_popup,
            # Before anything reads the board: a confirmation dialog is drawn
            # over it and the board still matches straight through the dialog,
            # so judging the board first means acting on a screen that is not
            # actually reachable.
            self._handle_ok_dialog,
            self._handle_claim_reward,
            self._handle_ready_prompt,
            self._handle_in_battle,
            # The panels are gone, so the board underneath can be judged: decide
            # whether it is worth attacking before anything attacks it.
            self._handle_board_needs_refresh,
        ]
        # The panel handlers above still run while a re-roll is owed — the
        # Refresh button often only becomes reachable once a result panel has
        # been cleared. What must not run is anything that starts a fight,
        # because that would put the bot back into the list it just lost to,
        # which is the whole point of the option.
        if not self._owes_a_refresh:
            blocking.append(self._handle_start_button)
        blocking.append(self._handle_raid_entry)
        for handler in blocking:
            if handler():
                self._recognised()
                return False

        # The enemy list is the one positive sign that the raid board itself is
        # up with nothing over it, and that is the only state where reading the
        # ticket counter means anything — see _ticket_verdict.
        section = self._pick_enemy()
        if section is not None:
            # The board being up is a screen this loop understands, including in
            # the passes where it deliberately does nothing but re-read the
            # counter — those must not look like being adrift.
            self._recognised()
            if self._owes_a_refresh:
                # Recognised, deliberately idle: waiting for Refresh, not stuck.
                return False
            verdict = self._ticket_verdict()
            if verdict == TICKETS_GONE:
                return True
            if verdict == TICKETS_PENDING:
                # Hold still rather than attack: a click would start a battle
                # and the next reading would land on the wrong screen again.
                return False
            # TICKETS_LEFT, or TICKETS_PROBE — which attacks in exactly the
            # same way, and is judged by whether a battle follows.
            if self._handle_enemy_section(section):
                return False

        # Nothing above matched, so we are not stuck on a battle screen.
        self._stuck_count = 0

        idle = (
            self._handle_frog,
            self._handle_battle_finished,
            self._handle_defeat,
        )
        for handler in idle:
            if handler():
                self._recognised()
                return False

        if section is None:
            self._nothing_recognised()
        return False

    # ---------- handlers ----------

    def _find(self, template_path: str, accuracy: Optional[float] = None, **kwargs):
        return self._control.find(
            template_path,
            threshold=self._accuracy if accuracy is None else accuracy,
            **kwargs,
        )

    def _handle_pending_refresh(self) -> bool:
        """Re-roll the enemy list after a defeat, if the user enabled it."""
        if not self._owes_a_refresh:
            return False
        position = self._find(TPL_REFRESH)
        if position is None:
            # Kept rather than dropped. This used to clear the flag *before*
            # looking, so the re-roll only happened if the button was already on
            # screen in that same frame — and it never was, because the board
            # takes seconds to come back. On the single defeat in the logs the
            # flag was gone by the next line and the bot attacked the same list.
            self._refresh_waits += 1
            if self._refresh_waits >= REFRESH_WAIT_PASSES:
                logger.info(
                    "No Refresh button after %d passes; carrying on without "
                    "re-rolling (a guild raid board has none)",
                    self._refresh_waits,
                )
                self._refresh_pending = False
                self._refresh_waits = 0
            return False
        if not self._press_refresh(position):
            # Withheld, not spent: the defeat is still owed a new list.
            return False
        self._refresh_pending = False
        self._refresh_waits = 0
        logger.info("Refreshed the enemy list after a defeat, at %s", position)
        return True

    def _handle_board_needs_refresh(self) -> bool:
        """Re-roll the list because of what the board itself shows.

        Two reasons, and neither needs the deferred flag a defeat does: both are
        only visible with the board up, which is also the only time the button is
        there to press.

        The game hands out a new board by itself once every barrier is broken —
        but a *lost* opponent is not broken. That card stops being attackable
        without counting as cleared, so a board holding one loss never renews on
        its own; measured on a live board, the four template hits on the card
        that won dropped to zero and stayed there over ten seconds.

        Gated on the button rather than on which raid mode this is: a guild board
        has no Refresh at all, and whether the button is there is exactly the
        question "can this list be re-rolled".
        """
        position = self._find(TPL_REFRESH)
        if position is None:
            self._empty_reads = 0
            self._refresh_presses = 0
            return False

        reason = None
        if self._auto_refresh and self._find(TPL_LOST, gray=False) is not None:
            reason = "a lost opponent is on the board"
        elif self._pick_enemy() is not None:
            self._empty_reads = 0
        else:
            self._empty_reads += 1
            if self._empty_reads >= EMPTY_BOARD_CONFIRMATIONS:
                reason = "nothing attackable is left"
            else:
                logger.info("Nothing attackable on the board (%d/%d) — "
                            "re-checking", self._empty_reads,
                            EMPTY_BOARD_CONFIRMATIONS)

        if reason is None:
            self._refresh_presses = 0
            return False

        if self._refresh_presses >= REFRESH_PRESS_LIMIT:
            # Pressed this many times and the board is unchanged, so something
            # is sitting on top of it that this handler cannot see. Stand down
            # rather than press again, and let the rest of the pass run — the
            # handlers that clear things away are in it.
            logger.warning(
                "Refresh pressed %d times and the board has not changed; "
                "leaving it alone until something else does",
                self._refresh_presses,
            )
            return False

        if not self._press_refresh(position):
            return False
        self._empty_reads = 0
        self._refresh_presses += 1
        logger.info("Re-rolled the list: %s (lan %d)",
                    reason, self._refresh_presses)
        return True

    def _press_refresh(self, position: Point) -> bool:
        """Re-roll the list. False when the press was withheld.

        The control refuses to click while the player's cursor is over the game,
        and everything here turns on whether the board actually changed: the
        list of opponents that refused is only meaningless once a *new* board is
        dealt. Clearing it after a press that never left would send the loop
        back at the same broken barrier.
        """
        if not self._control.click(position):
            return False
        # Every card changes with the new list, so nothing on the old one means
        # anything any more.
        self._refused.clear()
        self._last_enemy = None
        self._sleep(REFRESH_SETTLE_SECONDS)
        return True

    @property
    def _owes_a_refresh(self) -> bool:
        """A defeat is still waiting to be answered with a fresh list."""
        return self._auto_refresh and self._refresh_pending

    def _on_guild_board(self) -> bool:
        """Whether the guild board is showing: whichever tab is the brighter.

        Brightness rather than a template, for the same reason the souls Fight
        button is read that way — the two tabs carry the same word and differ
        only in how they are lit. Compared against each other rather than
        against a fixed value, because the game dims the whole board behind an
        open enemy card and a fixed line does not survive that. See
        geometry.GUILD_TAB_PATCH for the measurements.
        """
        try:
            guild = self._control.part_shot(self._guild_tab)
            individual = self._control.part_shot(self._individual_tab)
        except CaptureError:
            return False
        if guild.size == 0 or individual.size == 0:
            return False
        return self._brightness(guild) > self._brightness(individual)

    @staticmethod
    def _brightness(patch) -> float:
        return float(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)[:, :, 2].mean())

    def _tickets_exhausted(self) -> bool:
        """True when whichever counter this board carries has run down to zero.

        Read by segmenting the counter rather than matching a picture of it:
        see ``ticket_counter`` for why a whole-string match cannot work.

        Which counter depends on the board. The guild one is dark text on a
        light panel — the opposite of the ticket pill — so it is inverted first;
        the segmenter treats the bright pixels as ink. Both count down to zero,
        so the same "is the first digit a 0" question answers both.
        """
        guild = self._on_guild_board()
        region = self._guild_attempts if guild else self._ticket_region
        try:
            counter = self._control.part_shot(region, gray=True)
        except CaptureError:
            return False
        if guild:
            counter = 255 - counter
        return ticket_counter.is_zero(counter, self._zero_template)

    def _ticket_verdict(self) -> str:
        """What the counter says, checked against what actually happens.

        The counter alone is not trusted, and it never was reliable enough to
        be: a live account with six tickets had the "6" of "6/30" score 0.745
        against the stored "0", over the 0.72 the reader believed. Reading it
        wrong ends a run that still had tickets.

        So a zero reading only ever means "try attacking and see". A battle
        starting proves a ticket was there to spend. No battle, repeatedly, is
        what actually means the tickets are gone.

        Two older guards still apply. The counter region is a fixed rectangle on
        the board, and during a battle it frames unrelated artwork that segments
        into a convincing "0" — so this is reached only with the enemy list
        matched. And one reading is never enough even then, because a screen
        sliding in can cover the counter for a frame.
        """
        if not self._tickets_exhausted():
            self._reset_ticket_doubt()
            return TICKETS_LEFT

        if self._passes_refused:
            # The game said so itself, which needs no confirming.
            if self._stop_when_out_of_tickets:
                logger.info("Game says there are no passes left; ending the run")
                return TICKETS_GONE
            if not self._out_of_tickets_logged:
                logger.info("Out of tickets; staying up because auto-stop is off")
                self._out_of_tickets_logged = True
            self._reset_ticket_doubt()
            self._sleep(TICKET_RECHECK_SECONDS)
            return TICKETS_PENDING

        if self._probing and self._saw_battle:
            # Checked before anything else: a battle having happened settles the
            # question outright, and making it wait for three more readings of a
            # counter already known to be wrong only delays the obvious.
            logger.info(
                "Counter read zero but the test attack started a battle — "
                "tickets remain; ignoring the reading"
            )
            self._reset_ticket_doubt()
            return TICKETS_LEFT

        self._zero_reads += 1
        if self._zero_reads < TICKET_ZERO_CONFIRMATIONS:
            logger.info(
                "Ticket counter read zero (%d/%d) — holding to re-check",
                self._zero_reads,
                TICKET_ZERO_CONFIRMATIONS,
            )
            self._sleep(TICKET_RECHECK_SECONDS)
            return TICKETS_PENDING

        if self._on_guild_board():
            # No probe here, and the reason is the game's own rule rather than a
            # shortcut: a guild board still lets a fight start with the count at
            # zero. Measured on a live run — the loop attacked at 0/6, the fight
            # ran through to "Battle finished", and the probe read that battle as
            # proof the count was wrong and started the whole cycle again. It had
            # been doing that for as long as the task was left running.
            #
            # The individual board refuses the attack outright when the tickets
            # are gone, which is exactly what makes a probe meaningful there and
            # meaningless here. So on this board the reading stands on its own,
            # confirmed by TICKET_ZERO_CONFIRMATIONS readings and nothing else.
            if self._stop_when_out_of_tickets:
                logger.info(
                    "Guild raid attempts read zero over %d readings; ending the "
                    "run — a battle here would prove nothing, the board allows "
                    "them at zero",
                    self._zero_reads,
                )
                return TICKETS_GONE
            if not self._out_of_tickets_logged:
                logger.info("Guild attempts are gone; staying up because "
                            "auto-stop is off")
                self._out_of_tickets_logged = True
            self._reset_ticket_doubt()
            self._sleep(TICKET_RECHECK_SECONDS)
            return TICKETS_PENDING

        if self._probing:
            # The probe attacked and nothing followed. One of those can be a
            # missed click rather than an empty account, so it takes a few.
            self._failed_probes += 1
            if self._failed_probes < TICKET_PROBE_ATTEMPTS:
                logger.info(
                    "Test attack %d/%d started no battle — trying again",
                    self._failed_probes,
                    TICKET_PROBE_ATTEMPTS,
                )
                return self._begin_probe()
            if self._stop_when_out_of_tickets:
                logger.info(
                    "%d test attacks started no battle — out of tickets; "
                    "ending the run",
                    self._failed_probes,
                )
                return TICKETS_GONE
            if not self._out_of_tickets_logged:
                logger.info("Out of tickets; staying up because auto-stop is off")
                self._out_of_tickets_logged = True
            # Start over rather than settling here. Tickets come back, and a
            # loop that has stopped asking would never notice: one live run sat
            # at zero_reads=511 doing nothing at all.
            self._reset_ticket_doubt()
            self._sleep(TICKET_RECHECK_SECONDS)
            return TICKETS_PENDING

        logger.info(
            "Counter reads zero over %d readings — attacking to check, because "
            "the reading alone is not reliable enough to end a run",
            self._zero_reads,
        )
        return self._begin_probe()

    def _begin_probe(self) -> str:
        """Attack once and let the next pass judge what came of it."""
        self._probing = True
        self._saw_battle = False
        self._zero_reads = 0
        return TICKETS_PROBE

    def _reset_ticket_doubt(self) -> None:
        self._probing = False
        self._saw_battle = False
        self._failed_probes = 0
        self._passes_refused = False
        self._zero_reads = 0



    def _handle_leave_battle(self) -> bool:
        """Answer "Sure you want to leave the battle?" with Cancel.

        Always Cancel. Confirm ends a fight this loop paid a ticket to start,
        and no coordinate for it exists anywhere in the app.

        The loop no longer opens this dialog itself — the blind back-arrow press
        that used to is gone — but a person can, and a bot that walks past it
        leaves the fight sitting behind a modal.
        """
        if self._find(TPL_LEAVE_BATTLE) is None:
            return False
        logger.info("Dialog: leave the battle? — cancelling")
        self._control.click(self._leave_cancel)
        self._sleep(POPUP_SETTLE_SECONDS)
        return True

    def _handle_wanted_invite(self) -> bool:
        """Answer a co-op Wanted Quest invite so the raid loop can continue.

        Another player's invite opens a modal that blocks every click on the
        board underneath, which is what used to stall a run indefinitely. The
        dialog is always answered — leaving it up is the stall — so the only
        choice is which button.

        Both buttons must be found, stacked and aligned, before anything is
        clicked. Matching a single green tick would be enough to fire on any
        other confirmation dialog in the game; the pair only occurs here.
        """
        # The frame is already captured for this pass, so no extra delay.
        accept = self._find(TPL_WANTED_ACCEPT, WANTED_ACCURACY, gray=False, delay=0)
        if accept is None:
            return False
        refuse = self._find(TPL_WANTED_REFUSE, WANTED_ACCURACY, gray=False, delay=0)
        if refuse is None:
            return False

        if abs(refuse[0] - accept[0]) > geometry.WANTED_ALIGN_TOLERANCE:
            logger.debug("Invite buttons not aligned: %s vs %s", accept, refuse)
            return False
        if abs((refuse[1] - accept[1]) - self._wanted_gap) > geometry.WANTED_GAP_TOLERANCE:
            logger.debug(
                "Invite button gap %d, expected ~%d",
                refuse[1] - accept[1],
                self._wanted_gap,
            )
            return False

        target = accept if self._accept_wanted_quest else refuse
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

    def _handle_cooldown_popup(self) -> bool:
        """Dismiss "Cooldown time is not yet up!" and move on to another target."""
        if self._find(TPL_COOLDOWN, COOLDOWN_ACCURACY) is None:
            return False
        logger.info("Target on cooldown; dismissing popup")
        self._dismiss_popup()
        return True

    def _handle_claim_reward(self) -> bool:
        position = self._find(TPL_CLAIM_REWARD)
        if position is None:
            return False
        self._note_battle()
        self._stuck_count = 0
        logger.info("Claiming reward")
        # Two clicks: the first closes the result panel, the second confirms.
        self._control.click(position)
        self._sleep(REWARD_CLICK_GAP_SECONDS)
        self._control.click(position)
        return True

    def _handle_ready_prompt(self) -> bool:
        """Press Ready on the deployment screen.

        Both templates are only *detectors*. Neither position is clickable:
        click.png is a 41x24 crop of one letter out of the banner's sentence,
        and the banner itself has no centre worth pressing — so the press goes
        to the Ready button's fixed spot bottom-right either way. Measured on
        the live screen: the banner matches 0.999, the glyph 0.526, and the
        stored coordinate lands on the drum.
        """
        if self._find(TPL_READY_CLICK) is None and self._find(TPL_READY_TAP) is None:
            return False
        logger.info("Ready prompt detected")
        self._sleep(READY_SETTLE_SECONDS)
        self._control.click(self._ready_button)
        return True

    def _handle_in_battle(self) -> bool:
        if self._find(TPL_IN_BATTLE) is None:
            return False
        self._note_battle()
        self._stuck_count = 0
        logger.info("Battle in progress")
        self._sleep(BATTLE_POLL_SECONDS)
        return True

    def _handle_start_button(self) -> bool:
        position = self._find(TPL_START)
        if position is None:
            # Deliberately *not* reset here. The refusal cycle closes the enemy
            # card and reopens it, so the button disappears between presses —
            # counting only consecutive sightings never got past four while the
            # same button was pressed 107 times. What this counts is presses
            # since the last real battle, and only a battle clears it.
            return False
        # Whose button this is, rather than whichever card the loop last
        # looked at. Set before the give-up check below, because that is what
        # strikes _last_enemy off the board: on the run that found this it
        # struck off (929, 490) after eight presses that had all landed on
        # (633, 252)'s button, so the card that was really refusing stayed
        # eligible and was attacked for as long as the task ran.
        self._last_enemy = self._card_owning(position)
        if self._bump_stuck("START"):
            return True
        # Counted separately from _stuck_count, which other handlers reset for
        # their own reasons — on the live run that found this, it oscillated
        # between 1 and 4 and never reached its limit while the button was
        # pressed 107 times. This one only resets when a battle really happens.
        if self._start_clicks >= START_REFUSAL_LIMIT:
            return self._give_up_on_attacking()
        # Logged only once it has gone out, and counted on the same terms.
        # The control refuses to click while the player's own cursor is over
        # the game, and a press that never reached it says nothing about
        # whether the game would have refused it. Written the other way round,
        # this line reported a hundred attacks on a barrier nothing had
        # touched, and that is what the one report of this bug described.
        if self._control.click(position):
            self._start_clicks += 1
            logger.info("Clicked START at %s — card %s (stuck=%d)",
                        position, self._last_enemy, self._stuck_count)
        return True

    def _give_up_on_attacking(self) -> bool:
        """The attack button is not working. Close the card and decide why.

        Out of tickets is the ordinary reason and ends the run. Anything else —
        a cooldown, a barrier somebody else has already broken — is put on a
        list and skipped from here on, because dismissing the card alone was
        never enough: the same card is the board's best match, so the next pass
        opened it again.
        """
        logger.warning(
            "Pressed attack %d times with no battle — the game is refusing it; "
            "leaving %s alone",
            self._start_clicks, self._last_enemy,
        )
        self._start_clicks = 0
        if self._last_enemy is not None and not self._has_refused(self._last_enemy):
            self._refused.append(self._last_enemy)
        self._dismiss_popup()
        if self._stop_when_out_of_tickets and self._tickets_exhausted():
            logger.info("Counter reads zero and the attack is refused — run over")
            self._finish_now = True
        return True

    def _handle_raid_entry(self) -> bool:
        position = self._find(TPL_RAID_ENTRY)
        if position is None:
            return False
        logger.info("Opening the Realm Raid screen")
        self._control.click(position)
        return True

    def _pick_enemy(self) -> Optional[Point]:
        """The next opponent worth opening, in the board's own order.

        Every card, not just the best-scoring one. `match` answers with a single
        global maximum, and on a live board the nine cards scored between 0.943
        and 0.990 — so the same card won every pass. When that card could not be
        attacked, the loop opened it, pressed attack nine times, dismissed it,
        and opened it again; a live log did that for as long as the task ran, on
        a barrier somebody else had already broken.
        """
        for point in self._control.find_all(
                TPL_SECTION, threshold=self._accuracy):
            if not self._has_refused(point):
                return point
        return None

    def _card_owning(self, button: Point) -> Point:
        """The card an Attack button belongs to.

        The popup opens over its own card, so the button's position names its
        owner outright. Worth asking, because ``match`` answers with a single
        global best over the whole screen and will happily hand back the button
        of a popup that was already open — one belonging to a card the loop
        never chose. See geometry.ATTACK_BUTTON_OFFSET for the measurements.
        """
        dx, dy = self._geometry.point(geometry.ATTACK_BUTTON_OFFSET)
        return (button[0] - dx, button[1] - dy)

    def _button_belongs_to(self, button: Point, card: Point) -> bool:
        """Whether this button is the one the given card opens."""
        owner = self._card_owning(button)
        tolerance = max(1, self._geometry.point(
            (geometry.ATTACK_BUTTON_TOLERANCE, 0))[0])
        return (abs(owner[0] - card[0]) <= tolerance
                and abs(owner[1] - card[1]) <= tolerance)

    def _has_refused(self, point: Point) -> bool:
        return any(abs(point[0] - x) < SAME_ENEMY_WITHIN
                   and abs(point[1] - y) < SAME_ENEMY_WITHIN
                   for x, y in self._refused)

    def _handle_enemy_section(self, position: Optional[Point] = None) -> bool:
        # The caller has usually already picked one to decide whether the board
        # is worth attacking; reuse that rather than searching the frame twice.
        if position is None:
            position = self._pick_enemy()
        if position is None:
            return False
        if self._bump_stuck("SECTION"):
            return True
        self._last_enemy = position
        logger.info("Enemy found (section) at %s", position)
        self._control.click(position)
        self._sleep(POPUP_SETTLE_SECONDS)
        self._click_attack(opened=position)
        return True

    def _handle_frog(self) -> bool:
        position = self._find(TPL_FROG)
        if position is None:
            return False
        logger.info("Enemy found (frog) at %s", position)
        self._control.click(position)
        self._sleep(REWARD_CLICK_GAP_SECONDS)
        self._click_attack()
        return True

    def _handle_battle_finished(self) -> bool:
        position = self._find(TPL_FINISHED_BATTLE, gray=False)
        if position is None:
            return False
        self._note_battle()
        logger.info("Battle finished")
        self._control.click(position)
        return True

    def _note_battle(self) -> None:
        """Record that a battle happened, whichever screen proved it.

        Hooked to several handlers on purpose. The first version of this only
        watched the in-battle banner, and on a live account that banner never
        matched once in 281 completed battles — so the probe always concluded
        the tickets were gone. A defeat counts too: the ticket was still spent.
        """
        self._saw_battle = True
        # An attack that produced a battle is an attack that worked.
        self._start_clicks = 0
        # And a board that can be fought is a board that is not stuck.
        self._refresh_presses = 0

    def _handle_defeat(self) -> bool:
        position = self._find(TPL_FAILED, gray=False)
        if position is None:
            return False
        logger.info("Defeated; will refresh the enemy list")
        self._control.click(position)
        self._refresh_pending = True
        return True

    def _handle_ok_dialog(self) -> bool:
        position = self._find(TPL_OK)
        if position is None:
            return False
        logger.info("Dismissing dialog (OK)")
        self._control.click(position)
        return True

    # ---------- shared behaviour ----------

    def _recognised(self) -> None:
        """Something on screen was understood, so the loop is not adrift."""
        self._unknown_passes = 0
        self._escapes = 0

    def _nothing_recognised(self) -> None:
        """A pass in which no template matched anything at all.

        A few in a row are ordinary — screens slide in and out, and a frame
        caught mid-transition matches nothing. Enough of them means the loop is
        parked somewhere it has no picture of, which is the one situation the
        rest of this class cannot see: every other counter here is bumped by a
        handler that matched.
        """
        self._unknown_passes += 1
        if self._unknown_passes < UNKNOWN_SCREEN_LIMIT:
            return
        self._unknown_passes = 0
        self._escapes += 1
        self._escape_unknown_screen()

    def _escape_unknown_screen(self) -> None:
        """Try to get off a screen with no template, then say so and stop.

        An empty corner is the only press left, and that is deliberate. This
        used to press the top-left back arrow as a last resort, which during a
        fight opens "Sure you want to leave the battle?" — a dialog a loop that
        cannot read the screen must never be one stray press away from
        confirming. Blind navigation is withdrawn; past the corner it only keeps
        saying so, which is what the silent version never did.
        """
        if self._escapes <= UNKNOWN_SCREEN_CORNER_ESCAPES:
            logger.warning(
                "Nothing recognised for %d passes; clicking an empty corner in "
                "case a popup is swallowing everything (attempt %d/%d)",
                UNKNOWN_SCREEN_LIMIT, self._escapes, UNKNOWN_SCREEN_CORNER_ESCAPES,
            )
            self._dismiss_popup()
            return
        logger.warning(
            "Nothing recognised for %d more passes and %d escapes have not "
            "helped. The loop is parked on a screen it has no template for; it "
            "will keep watching but will not click blindly. Check the game "
            "window.",
            UNKNOWN_SCREEN_LIMIT, self._escapes - 1,
        )

    def _bump_stuck(self, screen: str) -> bool:
        """Count repeat sightings of a screen; dismiss a popup once over limit.

        Returns True when the caller should stop and let the next pass retry.
        """
        self._stuck_count += 1
        if self._stuck_count < STUCK_LIMIT:
            return False
        logger.warning(
            "Stuck on %s for %d frames; dismissing popup and retrying",
            screen,
            self._stuck_count,
        )
        self._stuck_count = 0
        self._dismiss_popup()
        return True

    def _dismiss_popup(self) -> None:
        self._control.click(self._popup_dismiss)
        self._sleep(POPUP_SETTLE_SECONDS)

    def _click_attack(self, opened: Optional[Point] = None) -> None:
        """Click the attack button belonging to ``opened``.

        The score is deliberately not held to the usual threshold: right after
        the enemy card opens the button is still animating in and rarely clears
        it, while its position is already correct.

        There is still a floor, though. A run on a 125% laptop logged scores of
        0.32 to 0.44 over and over, which is not a button fading in — it is no
        button on screen at all, because the click that should have opened the
        card never landed. Clicking the best match then means clicking whatever
        noise happened to score highest, somewhere unrelated. Better to do
        nothing and let the next pass try again.
        """
        score, position = self._control.match(TPL_START)
        if score < ATTACK_FLOOR:
            logger.warning(
                "Attack button not on screen (score=%.3f, best guess %s) — the "
                "enemy card did not open, so the click before this did not "
                "register. Not clicking.",
                score,
                position,
            )
            return
        if opened is not None and not self._button_belongs_to(position, opened):
            # The popup on screen is somebody else's. The click meant to open
            # this card went into a modal that was already up and did nothing,
            # so pressing what is there attacks a card the loop never chose —
            # and, before this check existed, blamed the refusal on this one.
            # Leave it: the next pass finds the stale popup through
            # _handle_start_button, which knows whose it is.
            logger.info(
                "Attack button at %s belongs to the card at %s, not the %s "
                "just opened — the card did not open. Not clicking.",
                position, self._card_owning(position), opened,
            )
            return
        if not self._control.click(position):
            # Withheld: the player's cursor is over the game. Nothing was sent,
            # so there is no battle to wait for and nothing to report.
            return
        logger.info("Attack button score=%.3f at %s — clicked", score, position)
        self._wait_for_battle_to_take_over()

    def _wait_for_battle_to_take_over(self) -> None:
        """Wait until the raid board is off screen, or give up and move on.

        The board going away is the signal that the attack registered. Coming
        back before it does means clicking into a screen that is already on its
        way out, which lands nowhere and wastes the pass.
        """
        deadline = time.monotonic() + ATTACK_HANDOVER_SECONDS
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                return
            self._control.invalidate_frame()
            if self._find(TPL_NO_PASSES) is not None:
                logger.info("Game refused the attack: not enough passes")
                self._passes_refused = True
                return
            if self._find(TPL_SECTION) is None:
                return
            self._sleep(ATTACK_HANDOVER_POLL)
        logger.info(
            "Board still up %.0fs after the attack — carrying on anyway",
            ATTACK_HANDOVER_SECONDS,
        )


def find_game_window(title: str) -> int:
    """Handle of the game window, raising a readable error if it is missing."""
    hwnd = win32gui.FindWindow(None, title)
    if not hwnd:
        raise RuntimeError("Không tìm thấy cửa sổ game: %s" % title)
    return hwnd


def resize_game_window(
    hwnd: int, client_size: Tuple[int, int] = geometry.REFERENCE_CLIENT_SIZE
) -> None:
    """Resize the window so its *client area* matches the reference size.

    It used to set the outer window to a fixed 1138x672 and call that done.
    That number was measured on one machine, where the frame happens to eat
    16px across and 39px down — so 1122x633 of client came out and everything
    matched. The frame is not a constant. At 125% display scaling it grows to
    21x50, and the same outer size leaves a client of 1117x623: 10px short,
    every template off, the raid clicking at nothing.

    So the frame is measured on the window in front of us and added to the
    client size we actually want. The loop is for the game itself, which nudges
    its own window afterwards to hold an aspect ratio; one pass often lands a
    pixel or two out, and a second settles it.
    """
    want_w, want_h = client_size
    for _ in range(RESIZE_PASSES):
        # In the game's coordinate space throughout — the reference client size
        # is what the game draws, not what the screen measures. See dpi.py.
        with dpi.window_space(hwnd):
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            _, _, client_w, client_h = win32gui.GetClientRect(hwnd)
            if client_w <= 0 or client_h <= 0:
                # Minimised or mid-creation; nothing meaningful to measure.
                return
            if abs(client_w - want_w) <= RESIZE_TOLERANCE and \
                    abs(client_h - want_h) <= RESIZE_TOLERANCE:
                return
            frame_w = (right - left) - client_w
            frame_h = (bottom - top) - client_h
            win32gui.MoveWindow(
                hwnd, left, top, want_w + frame_w, want_h + frame_h, True
            )
        time.sleep(RESIZE_SETTLE_SECONDS)

    with dpi.window_space(hwnd):
        _, _, client_w, client_h = win32gui.GetClientRect(hwnd)
    if (client_w, client_h) == (want_w, want_h):
        return

    # Say which of the two reasons it is, because they need different answers
    # from the user. The window is asked for in the game's units but occupies
    # scaling-many real pixels, so at a high enough scaling it simply cannot fit
    # on the screen and Windows clamps it. Measured on a 1920x1080 display:
    # 100%, 125% and 150% all land exactly on 1122x633; 175% needs 1992x1176 of
    # screen and settles at 1063x599 instead.
    scale = dpi.scaling_percent(hwnd) or 100
    needed_w = round((want_w + RESIZE_FRAME_ALLOWANCE[0]) * scale / 100)
    needed_h = round((want_h + RESIZE_FRAME_ALLOWANCE[1]) * scale / 100)
    screen_w, screen_h = dpi.screen_size()
    if screen_w and (needed_w > screen_w or needed_h > screen_h):
        logger.warning(
            "Client settled at %dx%d instead of %dx%d: at %d%% display scaling "
            "the game window needs %dx%d real pixels and the screen is only "
            "%dx%d. Lower the scaling in Windows display settings, or use a "
            "larger screen — detection accuracy will suffer until then.",
            client_w, client_h, want_w, want_h, scale,
            needed_w, needed_h, screen_w, screen_h,
        )
    else:
        logger.warning(
            "Client settled at %dx%d, wanted %dx%d — the game is holding its "
            "own aspect ratio; detection accuracy will suffer",
            client_w, client_h, want_w, want_h,
        )


# `client_size(hwnd)` used to live here and had no callers. Removed rather than
# left lying about: it read GetClientRect outside dpi.game_space, so anyone who
# reached for it would have got screen pixels where every other measurement in
# the app is in the game's own units — the exact confusion that broke the raid
# at 125% scaling. GameControl.client_width/height is the one to use.
