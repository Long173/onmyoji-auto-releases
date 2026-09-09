"""Exploration (Tham hiem chuong): sweep a chapter map and fight every enemy nest.

One hand-played lap was recorded — 77 frames, `recordings/map/` — and the loop
below is that lap, written down:

    world map          press the chapter row
    chapter panel      press Exploration
    exploration map    press a crossed-swords badge -> straight into battle
    battle             plays itself out
    victory / rewards  "Tap to continue"
    back on the map    next badge; when none is in view, drag sideways
    boss spawns        "Boss Found!", and a badge of its own — taken first
    boss cleared       a reward node may be left on the map — collect it
    reward node        opens a "Claim Reward" scroll; tap outside it to close
    nothing left       the game returns to the world map by itself

Two things about that flow decide the shape of this file.

**A badge click enters the battle directly.** There is no deploy board and no
confirm drum, unlike Realm Raid or an event — so between the click and the
victory screen there is nothing for the loop to do but wait.

**The map only scrolls horizontally.** Phase correlation over every consecutive
pair of the 77 frames gave dy about 0 throughout, and dx between 40 and 184 px
whenever the view was being dragged against about 0.5 px when it was not. That
gives a sweep with one axis and a dependable edge signal: drag, and if the
picture did not move, that end of the map has been reached.

Recognition is by template, and each one was scored against all 77 frames
before being kept, best-elsewhere in brackets:

    enemy.png        12 frames at 0.97-1.00   (median 0.555)
    onMap.png        14 frames at 0.99-1.00   (median 0.666)
    explore.png       2 frames at 0.99-1.00   (median 0.391)
    tapContinue.png  12 frames at 0.93-1.00   (median 0.311)
    worldMap.png      5 frames at 0.90-1.00   (next best 0.453)
    bossFound.png     2 frames at 1.00        (median 0.587)
    boss.png          2 frames at 0.88-0.92   (next best 0.564)
    mapReward.png     2 frames at 0.86-0.97   (median 0.612)
    claimReward.png   absent from all 77       (best 0.400)

**The boss is not the ordinary badge.** It was worth finding out the hard way:
with only the boss left on a live map, `enemy.png` scored **0.674** on it, so a
loop carrying one badge template fights every nest and then sits in front of the
boss forever. The two are the same motif — crossed swords on a dark disc — but
the boss disc is about 73 px against 48 and carries a scabbard, petals and
colour the plain one does not.

Scaling the plain badge up was tried first, because one scale-tolerant template
would also cover whatever the next chapter's boss looks like. It does not work:
against the live boss the plain badge scores 0.674 at its own size and *falls*
from there — 0.598 at x1.1, 0.546 at x1.2, 0.459 at x1.4. Same position
throughout, so it is finding the right thing and simply disagreeing with it. The
extra artwork is the difference, not the size, and a second template is the
honest answer.

`boss.png` was cut from a live capture of Chapter 28, and Chapter 28 is the only
place it has been measured. If another chapter's boss carries different artwork
this is where it will show up: the nests all clear and then nothing happens,
with the stall warning below in the log.

`onMap.png` is the words "Auto Rotation" in the bottom-left corner, and it is
the one that makes the rest safe: it matched 17 frames — the map, with and
without a nest in view — so "on the map with nothing to fight" is a state the
loop can name instead of guessing.

It is the words and not the pill they sit in, which is the second thing found by
running this against the live game rather than the recording. Cut with the pill's
blue icon included it scored 0.99-1.00 on every recorded frame and then **0.876,
0.879, 0.918 and 0.945 on four live captures** — the icon is a swirl that spins,
and a template holding a moving part scores whatever phase it was cut at. Below
threshold, the whole map branch goes dead and the loop idles in front of a map it
cannot see. Text only, the same frames score 0.936-1.000 with everything else at
0.494, and it finds three map frames the old cut missed.

`claimReward.png` is the one template no recorded frame contains, and the reason
it is here is worth the paragraph. A live run cleared the boss, collected the
reward node, and then spent **110 seconds flipping direction 75 times** — logging
nothing but "Reached the edge of the map" — because the reward opened a modal
scroll the loop could not see. The map's own furniture stays visible behind that
panel, so `onMap` read 0.999 and the loop concluded it was on an empty map;
dragging is what a modal blocks, so every sweep reported no movement and turned
around. Recognising the panel fixes this instance. `STUCK_SWEEPS` is there for
the next one: both ends of a map cannot both be the edge, so a run of sweeps that
move nothing now says so in the log instead of spinning quietly.

**When nothing at all is recognised the loop does nothing**: a battle is in progress, or a screen is
loading, and both resolve on their own. The alternative, clicking a default
point and hoping, is how a stray press lands on a skill mid-battle.

**Raiding in the middle of it.** With `raid_relay` on, every return to the
chapter panel reads the Realm Raid ticket counter in the top bar, and at exactly
30/30 this worker breaks off and runs the raid loop before coming back. Raid
tickets refill on a timer and stop accruing once full, so sitting at 30/30 while
farming a map throws tickets away.

It runs that loop **here, on this thread**, rather than handing the window to the
Realm Raid task. One worker keeps the window, the clock and the callbacks the
whole time, so Stop and Pause behave identically whichever loop is running and
there is no instant where the window belongs to nobody — which a hand-over
between two tasks would have, and which is exactly when a user presses Stop.
:meth:`TaskWorker.share_signals_with` is what makes the borrowed loop answer to
this worker's Stop.

Reading the counter is :mod:`raid_tickets`, and it reads the digits rather than
comparing a picture of the whole box — the difference between "is it full" and
"does it look a bit like full" is the difference between raiding and abandoning a
map to raid with no tickets.

Two limits worth knowing before leaving it unattended:

* **Out of sushi it will not say so.** Every battle costs sushi and the game
  answers an empty larder with a purchase panel, for which there is no template
  here — nothing in the recording shows one. What happens instead is that the
  loop keeps pressing the same badge and the badge stays put, so the stall
  guard below logs it. That is a symptom, not a diagnosis.
* **The reward node is the one from Chapter 28 on Hard.** Whether every chapter
  leaves one behind, and whether it always carries the same chest, is not
  known — only that this one does and that the game does not always hand the
  reward over unprompted.
* **The count is battles entered, not battles won.** A defeat also clears the
  badge from the map, and the loop cannot tell the two apart. It does at least
  not count a press that never started a fight — see :meth:`_enter_battle`.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional, Tuple

import cv2
import numpy as np

import geometry
import wanted_invite
from game_control import CaptureError, GameControl
from paths import template
from task_worker import Callback, TaskWorker
from raid_tickets import TicketReader

logger = logging.getLogger(__name__)

TPL_ENEMY = template("Exploration", "enemy.png")
TPL_ON_MAP = template("Exploration", "onMap.png")
TPL_EXPLORE = template("Exploration", "explore.png")
TPL_TAP_CONTINUE = template("Exploration", "tapContinue.png")
TPL_WORLD_MAP = template("Exploration", "worldMap.png")
TPL_BOSS_FOUND = template("Exploration", "bossFound.png")
TPL_BOSS = template("Exploration", "boss.png")
TPL_MAP_REWARD = template("Exploration", "mapReward.png")
TPL_CLAIM_REWARD = template("Exploration", "claimReward.png")
TPL_RAID_ENTRY = template("Exploration", "raidEntry.png")

# --- Tuning ----------------------------------------------------------------
# Thresholds. 0.9 everywhere the measured gap is wide; the world map is the one
# exception at 0.85, because the fifth frame that really is the world map scored
# 0.905 while the best frame that is not scored 0.453. Anything in between would
# do; 0.85 sits in the middle of a gap half the scale wide.
THRESHOLD = 0.9
WORLD_MAP_THRESHOLD = 0.85
# The boss badge scored 0.884 and 0.923 on the two recorded frames it appears in
# and 1.000 on the live capture it was cut from, against 0.564 for the best frame
# it is absent from. 0.85 sits in the middle of that gap.
BOSS_THRESHOLD = 0.85
# The reward node scored 0.969 on the recorded frame it appears in and 1.000 on
# the live capture it was cut from, against 0.692 for the best map frame with no
# reward on it.
REWARD_THRESHOLD = 0.85
# The Realm Raid button on the world map's bottom strip. It doubles as the
# second way of recognising the world map itself, and it is the better of the
# two: an opaque icon, it scored 0.944-1.000 across three different map
# backgrounds where `worldMap.png` — a half-transparent tab strip that takes on
# whatever is behind it — fell to 0.710 over a pale one. Neither is enough
# alone, so both are consulted; see :meth:`_on_world_map`.
RAID_ENTRY_THRESHOLD = 0.9
# Tries at a navigation step before giving up and going back to farming.
NAV_ATTEMPTS = 3
NAV_SETTLE_SECONDS = 2.5
# How long the borrowed raid loop may run before this worker takes the window
# back. It is a safety net, not a schedule: the raid loop ends on its own when
# tickets run out, and a full 30 tickets takes nowhere near this long.
#
# It exists because a loop that cannot end is not hypothetical here. A live run
# left the raid pressing the same attack button 107 times with no way out — that
# particular hole is closed now, but the map farm should not be able to hang on
# the next one. Overrunning costs a wasted quarter hour; hanging costs the night.
RAID_BUDGET_SECONDS = 15 * 60
RAID_WATCH_POLL_SECONDS = 0.5

# A drag of at least this many pixels counts as the view having moved. Real
# drags in the recording shifted 40-184 px and a static pair shifted 0.5, so
# there is nothing delicate about where this sits.
MOVED_PIXELS = 8.0

IDLE_SECONDS = 1.5          # nothing recognised: a battle or a loading screen
AFTER_CLICK_SECONDS = 1.0   # a badge press, before checking it took effect
# How long to keep checking that the map has gone after pressing a badge, and how
# often. A fixed wait was tried first and is why this exists: at two seconds a
# live run pressed one badge twice — "Nest 7 at (833, 251)" and then "Nest 8 at
# (833, 251)" 2.3 s later — because the map was still up when the second pass
# looked. The stray press lands on the battle and does nothing, but the count
# tells you eleven battles when there were ten, and a count that drifts is worse
# than no count. Waiting for the map to actually go also gives the time back on
# every transition faster than the fixed wait.
HANDOVER_SECONDS = 8.0
HANDOVER_POLL_SECONDS = 0.6
AFTER_TAP_SECONDS = 1.0     # a reward screen dismissed
AFTER_ENTER_SECONDS = 3.0   # the chapter loading in
AFTER_DRAG_SECONDS = 0.6    # the map coasting to a stop
POPUP_SETTLE_SECONDS = 1.0

# Sweeps in a row that moved nothing before saying so out loud. Two full
# direction cycles: a real edge flips once and the next sweep moves, so anything
# past this means the map is not scrolling at all — something is covering it.
# The number exists because the alternative was measured: a live run spent 110
# seconds flipping direction 75 times behind a panel this loop could not see, and
# logged nothing but "Reached the edge of the map" over and over.
STUCK_SWEEPS = 4

LOOP_LOG_EVERY = 30
# Passes with nothing to show before saying so. At IDLE_SECONDS a battle spans
# a handful of them, so this has to be well clear of one battle: 40 passes is
# about a minute of a screen the loop cannot act on, which no normal step
# reaches.
STALL_PASSES = 40


class ExplorationWorker(TaskWorker):
    """Fights its way across one chapter's exploration map, then does it again."""

    def __init__(
        self,
        hwnd: int,
        chapter_point: Optional[Tuple[int, int]] = None,
        accept_wanted_quest: bool = False,
        raid_relay: bool = False,
        on_finished: Callback = None,
        on_error: Callback = None,
        control: Optional[GameControl] = None,
    ) -> None:
        super().__init__("ExplorationWorker", hwnd, control, on_finished, on_error)
        self._accept_wanted_quest = accept_wanted_quest
        self._raid_relay = raid_relay
        # Built once, because it loads three glyph templates off disk. None when
        # the option is off, which is also what switches the check off entirely.
        self._tickets = TicketReader(self._control) if raid_relay else None
        self._raids = 0

        chosen = tuple(chapter_point) if chapter_point else geometry.EXPLORATION_CHAPTER_POINT
        self._chapter_point = self._geometry.point(chosen)
        self._drag_left = self._geometry.point(geometry.EXPLORATION_DRAG_LEFT)
        self._drag_right = self._geometry.point(geometry.EXPLORATION_DRAG_RIGHT)
        self._map_area = self._geometry.region(geometry.EXPLORATION_MAP_AREA)
        self._claim_dismiss = self._geometry.point(
            geometry.EXPLORATION_CLAIM_DISMISS_POINT
        )
        self._back_arrow = self._geometry.point(geometry.EXPLORATION_BACK_ARROW)
        self._raid_entry = self._geometry.point(geometry.RAID_ENTRY_POINT)
        self._raid_close = self._geometry.point(geometry.RAID_CLOSE_POINT)

        self._nests = 0
        self._rewards = 0
        # Entries into the exploration map, counted where the loop actually
        # presses Exploration. It used to count returns to the world map, which
        # under-reported: a finished chapter sometimes drops back to the world
        # map and sometimes straight to the chapter panel, and only the first
        # was being seen. A live run showed twelve nests over "0 laps".
        self._entries = 0
        self._invites_handled = 0
        # +1 sweeps the view one way, -1 the other. Flipped on reaching an edge.
        self._direction = 1
        self._idle_passes = 0
        self._still_sweeps = 0

    @property
    def progress(self) -> int:
        """Enemy nests entered. See the module docstring: entered, not won."""
        return self._nests

    def run(self) -> None:
        logger.info(
            "Exploration starting — chapter point=%s — %s",
            self._chapter_point, self._control.describe(),
        )
        if not self._geometry.is_reference_size:
            logger.warning(
                "Client area is %dx%d but the chapter point was saved against "
                "%dx%d — it has been scaled, which may not land where intended",
                self._geometry.client_width,
                self._geometry.client_height,
                *geometry.REFERENCE_CLIENT_SIZE,
            )
        self._begin_timing()
        try:
            self._loop()
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI below
            logger.exception("Exploration crashed")
            self._notify(self._on_error, str(exc))
            return
        finally:
            self._end_timing()
            self._control.close()
        logger.info(
            "Exploration stopped after %d nests, %d rewards, %d raids "
            "over %d entries",
            self._nests, self._rewards, self._raids, self._entries,
        )

    # ---------- main loop ----------

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self._wait_while_paused()
            if self._stop_event.is_set():
                break
            self._iteration += 1
            if self._iteration % LOOP_LOG_EVERY == 1:
                logger.info(
                    "loop iter=%d nests=%d rewards=%d entries=%d",
                    self._iteration, self._nests, self._rewards, self._entries,
                )
            try:
                self._control.begin_frame()
                self._step()
            except CaptureError:
                # Transient: the window resized, was minimised, or is being
                # rebuilt. Nothing to read this pass.
                self._sleep(IDLE_SECONDS)
            finally:
                self._control.end_frame()

    def _step(self) -> None:
        """One pass. Ordered so the screens that block everything go first."""
        if self._holding_for_the_cursor():
            return
        for act in (
            self._handle_wanted_invite,
            self._dismiss_reward,
            self._close_claim_panel,
            self._raid_if_tickets_are_full,
            self._enter_chapter,
            self._work_the_map,
            self._open_chapter,
        ):
            if act():
                self._idle_passes = 0
                return
        self._wait_it_out()

    # ---------- the screens ----------

    def _dismiss_reward(self) -> bool:
        """A victory or reward screen: tap the words it is asking to be tapped."""
        target = self._control.find(TPL_TAP_CONTINUE, THRESHOLD)
        if target is None:
            return False
        self._control.click(target)
        self._sleep(AFTER_TAP_SECONDS)
        return True

    def _close_claim_panel(self) -> bool:
        """Close the "Claim Reward" scroll a reward node opens.

        It has to be handled by name, because it does not look like a screen the
        loop is stuck on: the panel is modal but the map's own furniture stays
        visible behind it, so ``onMap`` still matches at 0.999 and the loop
        happily decides it is on an empty map and starts dragging. Dragging is
        exactly what a modal blocks, so the sweep reads "the view did not move",
        turns around, and does that forever.

        The tap goes outside the panel. Tapping the panel — its title included —
        leaves it open; both were tried live.
        """
        if self._control.find(TPL_CLAIM_REWARD, THRESHOLD) is None:
            return False
        logger.info("Closing the reward panel")
        self._control.click(self._claim_dismiss)
        self._sleep(AFTER_TAP_SECONDS)
        return True

    def _raid_if_tickets_are_full(self) -> bool:
        """On the chapter panel with 30/30 raid tickets: go and spend them.

        The counter only exists on this screen, which is why the check lives
        here rather than in the loop at large — and once a lap is the right
        cadence for it anyway. Tickets refill on a timer and stop accruing at
        30, so every minute spent at 30/30 is a wasted ticket.

        Anything other than a confident "full" carries on farming. That includes
        the counter being unreadable: see :mod:`raid_tickets` for why the two
        are kept apart.
        """
        if self._tickets is None:
            return False
        if self._control.find(TPL_EXPLORE, THRESHOLD) is None:
            return False
        if self._tickets.is_full() is not True:
            return False
        self._raid()
        return True

    def _raid(self) -> None:
        """Walk to the raid board, run the raid loop here, walk back.

        Not a handover to the other task: this worker keeps the window, the
        clock and the callbacks throughout, so Stop and Pause behave the same
        whichever loop happens to be running, and there is no moment where the
        window belongs to nobody.

        The walk is the part that was missing at first. The raid loop knows what
        to do once the board is up, but it cannot reach the board from a chapter
        panel — left to itself it simply sat in front of one for the whole run.
        So the route is walked explicitly, and every step is confirmed before the
        next: a navigation that presses on regardless is how a stray press ends
        up on the town screen opening Settings over everything, which is what
        happened while the route was being measured.
        """
        if not self._reach_the_raid_board():
            logger.warning("Could not reach the raid board — carrying on farming")
            return
        self._raids += 1
        logger.info("Tickets are 30/30 — raid %d starting", self._raids)
        spent = self._run_raid_loop()
        if self._stop_event.is_set():
            return
        logger.info(
            "Raid %d %s — leaving the board",
            self._raids,
            "done (out of tickets)" if spent else "ended early",
        )
        self._leave_the_raid_board()

    def _run_raid_loop(self) -> bool:
        import realm_raid

        raider = realm_raid.RealmRaidWorker(
            hwnd=self._control.hwnd,
            auto_refresh=True,
            stop_when_out_of_tickets=True,
            accept_wanted_quest=self._accept_wanted_quest,
            control=self._control,
        )
        # Pause is shared outright: whichever loop is running should hold still.
        self.share_pause_with(raider)
        # Stop is *relayed* rather than shared, which is the difference that
        # matters. Sharing it would mean the only way to end an overrunning raid
        # was to end this worker too; relaying lets the window be taken back
        # while the map farm carries on.
        guard = threading.Event()
        raider._stop_event = guard
        deadline = time.monotonic() + RAID_BUDGET_SECONDS
        watcher = threading.Thread(
            target=self._watch_raid, args=(guard, deadline),
            name="ExplorationRaidWatch", daemon=True,
        )
        watcher.start()
        try:
            return raider.raid_until_out_of_tickets()
        finally:
            guard.set()          # releases the watcher
            self._control.invalidate_frame()

    def _watch_raid(self, guard: threading.Event, deadline: float) -> None:
        """Stop the borrowed loop when this worker stops, or when it overruns."""
        while not guard.is_set():
            if self._stop_event.wait(RAID_WATCH_POLL_SECONDS):
                guard.set()
                return
            if time.monotonic() >= deadline:
                logger.warning(
                    "The raid has run for %.0f minutes without ending — taking "
                    "the window back and going to farm",
                    RAID_BUDGET_SECONDS / 60,
                )
                guard.set()
                return

    def _reach_the_raid_board(self) -> bool:
        """Chapter panel -> world map -> raid board, checking after each press."""
        # Out of the chapter panel. The arrow is only safe to press while that
        # panel is confirmed up: one screen further back the same coordinate is
        # the player's portrait, and it opens Settings over the whole game.
        if self._control.find(TPL_EXPLORE, THRESHOLD) is None:
            return False
        self._control.click(self._back_arrow)
        self._sleep(NAV_SETTLE_SECONDS)

        for _ in range(NAV_ATTEMPTS):
            if self._stop_event.is_set():
                return False
            entry = self._control.find(TPL_RAID_ENTRY, RAID_ENTRY_THRESHOLD)
            if entry is not None or self._on_world_map():
                # The matched centre when there is one; the measured position
                # when the world map was recognised by its other signal.
                self._control.click(entry if entry is not None else self._raid_entry)
                self._sleep(NAV_SETTLE_SECONDS)
                # The button is gone once the board is up, which is the only
                # confirmation available: the board itself is the raid task's
                # business, not this one's.
                return self._control.find(TPL_RAID_ENTRY, RAID_ENTRY_THRESHOLD) is None
            self._sleep(NAV_SETTLE_SECONDS)
        return False

    def _leave_the_raid_board(self) -> None:
        """Close the board and get back to the world map.

        The board ignores the top-left arrow entirely — pressing it there does
        nothing, measured — so this is the red X on its right-hand edge, pressed
        until the world map answers.
        """
        for _ in range(NAV_ATTEMPTS):
            if self._stop_event.is_set() or self._on_world_map():
                return
            self._control.click(self._raid_close)
            self._sleep(NAV_SETTLE_SECONDS)
        if not self._on_world_map():
            logger.warning(
                "Still not back on the world map after the raid — the loop will "
                "carry on from whatever screen this is"
            )

    def _enter_chapter(self) -> bool:
        """The chapter panel is open: press Exploration to go in.

        The difficulty toggle beside it is left alone — the game remembers the
        last one chosen, so whatever the user set by hand is what runs.
        """
        target = self._control.find(TPL_EXPLORE, THRESHOLD)
        if target is None:
            return False
        self._entries += 1
        logger.info("Entering the chapter (%d)", self._entries)
        self._control.click(target)
        self._sleep(AFTER_ENTER_SECONDS)
        return True

    def _work_the_map(self) -> bool:
        """On the exploration map: fight what is in view, or go looking."""
        if self._control.find(TPL_ON_MAP, THRESHOLD) is None:
            return False
        if self._control.find(TPL_BOSS_FOUND, THRESHOLD) is not None:
            logger.info("Boss found")
        # The boss goes first whenever it is on screen, ahead of any ordinary
        # nest still standing. The banner announces it as soon as it spawns
        # rather than once the map is clear — both badges were in view together
        # in the recording — so this is a real choice, and it is the user's:
        # beating the boss ends the chapter, and the chapter is what the lap is
        # for. Nests left behind cost nothing, where clearing them all first
        # spends sushi and minutes on the way to the same reward.
        # A reward node before any fight: it is free, and it is what the lap was
        # for. Beating the boss can leave one behind on the map — the game does
        # not always hand the chapter's reward over by itself.
        target = self._control.find(TPL_MAP_REWARD, REWARD_THRESHOLD)
        if target is not None:
            self._rewards += 1
            logger.info("Reward %d at %s — collecting", self._rewards, target)
            self._control.click(target)
            self._sleep(AFTER_TAP_SECONDS)
            return True
        target = self._control.find(TPL_BOSS, BOSS_THRESHOLD)
        if target is not None:
            return self._enter_battle(target, "Boss")
        target = self._control.find(TPL_ENEMY, THRESHOLD)
        if target is not None:
            return self._enter_battle(target, "Nest")
        self._sweep()
        return True

    def _enter_battle(self, target, what: str) -> bool:
        """Press a badge. There is no deploy board — this is the fight starting.

        Counted only once the map has actually gone. Some presses do not take —
        (1040, 259) near the right edge missed on roughly half the tries across
        three live runs — and counting the press rather than the battle reported
        five nests for four fights. The retry happens either way: the next pass
        sees the badge still standing and presses it again.
        """
        self._control.click(target)
        if not self._await_handover():
            logger.info("%s at %s — the press did not take; will try again",
                        what, target)
            return True
        self._nests += 1
        logger.info("%s %d at %s", what, self._nests, target)
        return True

    def _await_handover(self) -> bool:
        """Wait until the map has gone. False if it never did.

        Not a fixed wait: see ``HANDOVER_SECONDS``.
        """
        self._sleep(AFTER_CLICK_SECONDS)
        waited = AFTER_CLICK_SECONDS
        while waited < HANDOVER_SECONDS and not self._stop_event.is_set():
            if self._control.find(TPL_ON_MAP, THRESHOLD) is None:
                return True
            self._sleep(HANDOVER_POLL_SECONDS)
            waited += HANDOVER_POLL_SECONDS
        return False

    def _on_world_map(self) -> bool:
        """Either of the two world-map signals. Neither is dependable alone.

        `worldMap.png` is the "Main | Gameplay" tab strip, which is
        half-transparent: over a pale stretch of map it drops to 0.710, under
        threshold, and the loop then sits on a world map it cannot see.
        `raidEntry.png` is an opaque icon and holds up across backgrounds, but it
        missed one recorded frame at 0.758. No other screen scores above 0.53 on
        either, so taking the pair as an OR costs nothing.
        """
        return (
            self._control.find(TPL_WORLD_MAP, WORLD_MAP_THRESHOLD) is not None
            or self._control.find(TPL_RAID_ENTRY, RAID_ENTRY_THRESHOLD) is not None
        )

    def _open_chapter(self) -> bool:
        """Back on the world map, which means the chapter finished. Open it again."""
        if not self._on_world_map():
            return False
        logger.info("On the world map — opening the chapter")
        self._control.click(self._chapter_point)
        self._sleep(AFTER_ENTER_SECONDS)
        return True

    def _wait_it_out(self) -> None:
        """Nothing recognised: a battle, or a screen loading. Both pass."""
        self._idle_passes += 1
        if self._idle_passes % STALL_PASSES == 0:
            logger.warning(
                "%d passes with nothing to act on. A battle is not this long — "
                "out of sushi, or a screen this task does not know",
                self._idle_passes,
            )
        self._sleep(IDLE_SECONDS)

    # ---------- sweeping ----------

    def _sweep(self) -> None:
        """Drag the map sideways; on reaching an edge, turn around."""
        start = self._drag_right if self._direction > 0 else self._drag_left
        end = self._drag_left if self._direction > 0 else self._drag_right

        before = self._map_patch()
        if not self._control.drag(start, end):
            # Withheld while the player's cursor is over the game. The map has
            # not moved, and that says nothing about having reached its edge —
            # judging it here would turn the sweep around for no reason.
            return
        self._sleep(AFTER_DRAG_SECONDS)
        after = self._map_patch()

        if self._shift(before, after) >= MOVED_PIXELS:
            self._still_sweeps = 0
            return
        self._direction = -self._direction
        self._still_sweeps += 1
        if self._still_sweeps % STUCK_SWEEPS:
            logger.info("Reached the edge of the map — sweeping back the other way")
            return
        logger.warning(
            "%d sweeps in a row moved nothing. Both ends cannot be the edge — "
            "something is covering the map that this task does not recognise",
            self._still_sweeps,
        )
        self._sleep(IDLE_SECONDS)

    def _map_patch(self) -> np.ndarray:
        """The stretch of map that is compared to tell whether the view moved."""
        return self._control.part_shot(self._map_area, gray=True)

    @staticmethod
    def _shift(before: np.ndarray, after: np.ndarray) -> float:
        """How far the picture moved horizontally, in pixels.

        Phase correlation rather than a difference: two map positions overlap
        almost entirely, so they differ by very little pixel for pixel even when
        the view has plainly moved, and a threshold on that difference would sit
        somewhere arbitrary. The correlation answers with the shift itself.
        """
        if before.shape != after.shape:
            # A resize mid-drag. Treat it as movement so the sweep does not
            # conclude it has hit an edge on the strength of a bad comparison.
            return float("inf")
        (dx, _dy), _response = cv2.phaseCorrelate(
            np.float32(before), np.float32(after)
        )
        return abs(dx)

    # ---------- shared with every other task ----------

    def _handle_wanted_invite(self) -> bool:
        """Answer a co-op Wanted Quest invite; it covers and swallows clicks."""
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
