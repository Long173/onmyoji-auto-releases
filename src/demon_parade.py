"""Demon Parade (Ném đậu) automation loop.

Four screens, and the loop is simply whichever one is on::

    entry  --Enter-->  pick  --pick a shikigami, Start-->  round
      ^                                                      |
      +---------------- dismiss ------- result <-- 35s ------+

Each ``Enter`` costs one ticket and commits, so it is pressed only when the run
is going to be played out.

Throws are aimed at whatever is actually moving. Where a bean lands decides
what it is worth: a round spent throwing at an empty patch of sky came back
with one shikigami and 4 shards, against six shikigami and 18 shards for the
same number of throws put on the parade.

Finding the figures is cheap because the scene behind them does not move. The
median of a few frames is the bridge and the temple; anything that differs from
it is a shikigami. Measured, they cross at about 154 pixels a second and stand
some 160 wide, so between one throw and the next a target drifts well under
half its own width — near enough that the place it was last seen is still a
hit, with no need to lead it.

The picked boss is the exception, and it gets every bean while it is on
screen: it pays triple, so it is where SSR/SP shards come from. The game
marks it with an orbiting "Picked", and those beans are thrown as fast as the
game takes them and aimed ahead of it — see parade_boss.

Which figure to throw at is decided by **not** recognising it. The library
learns the common shikigami, and everything it cannot name is worth a bean —
see :mod:`parade_figures` for why that is the right way round, and for the
measurements that overturned the obvious alternative.

Beans, not time, are what runs out. 250 of them at 10 a throw is 25 throws,
gone in about 15 seconds of a 60-second round — so the loop cannot simply hit
everything it sees and hope a rare one is among them. It holds its beans for
figures it cannot name, and only in the last :data:`DUMP_LAST_SECONDS` spends
what is left on whoever happens to be there, because unspent beans are lost
when the round ends.

Measured live as the common library grew: throwing at everything (100% of the
figures on screen), then 33.6% once a person had labelled a batch, then 8.2%
once the library learned commons on its own. That ratio, not the shard count,
is what says whether the aiming is working.

Sweeping still matters once the loop is spending: each shikigami gives only a
few shards, so touching many of them beats hitting a few repeatedly. An early
version that circled the five largest blobs collected 9.5 shards a round
against 13.9 for a blind sweep; admitting the smaller figures and ordering them
by position brought it back to 12.5.

The game also rate-limits throwing. 315 clicks crammed into 26 seconds spent
only 217 beans — about 43 throws, near enough 1.6 a second. Clicking faster
than :data:`THROW_INTERVAL_SECONDS` buys nothing and just burns CPU.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, Optional

import cv2
import numpy as np

import geometry
import parade_boss
import parade_figures
import parade_pick
import parade_rare
import parade_results
import paths
import wanted_invite
from game_control import CaptureError, GameControl, read_image
from paths import template
from task_worker import Callback, TaskWorker

logger = logging.getLogger(__name__)


def _describe(tally) -> str:
    """The round's throws, split by what they were aimed at.

    Written out in full because the split is the measurement: a throw at a
    figure the library names as rare and a throw at one it cannot name are both
    deliberate, but only the first says anything about whether hitting a rare
    shikigami yields its shards.
    """
    return "%d at the boss, %d at helpers, %d at a named rare, %d at unnamed, %d leftover, %d held" % (
        tally.get("boss", 0), tally.get("helper", 0), tally["rare"], tally["unknown"],
        tally["leftover"], tally["held"],
    )


# --- Template images -------------------------------------------------------
# Cut from a live run at 1122x633 and scored against every captured screen.
# Separation between the screen each one names and every other screen:
# enter 0.494, pick 0.551, inRound 0.334, result 0.675.
TPL_ENTER = template("DemonParade", "enter.png")
TPL_PICK = template("DemonParade", "pick.png")
# The left cap of the beans slider. The obvious choice — the whole slider strip
# — was tried first and scored 0.611 against a screen it should not match at
# all, because the bean count and knob move about inside it.
TPL_IN_ROUND = template("DemonParade", "inRound.png")
# The same corner under Freeze's frost. Freeze holds the parade still for about
# nine seconds and lays a fixed frost over the screen's edges, slider and top
# bar alike: the plain template drops to 0.71 there, and the pick screen scores
# 0.67, so no threshold separates them. Taken for the end of the round, a
# freeze stopped the throwing at the one moment everything stands still. Cut
# from the frost itself, it scores 1.00 under it and at most 0.74 anywhere else.
TPL_IN_ROUND_FROZEN = template("DemonParade", "inRoundFrozen.png")
# Quitting the pick screen lands in the town, not on the parade's entry screen,
# and the parade's sign over the town leads back in. Two clients, two signs: a
# hanging lantern on the PC client and a wooden board on BlueStacks. The lantern
# sways, which costs it up to a quarter of its score — 0.73 to 1.00 on the town,
# never above 0.46 anywhere else.
TPL_TOWN_LANTERN = template("DemonParade", "townLantern.png")
TOWN_LANTERN_ACCURACY = 0.65
TPL_TOWN_SIGN = template("DemonParade", "townSign.png")
TOWN_SIGN_ACCURACY = 0.85
TPL_RESULT = template("DemonParade", "result.png")
# The gold "Pick" banner over whichever shikigami is selected. Scored 0.826 to
# 1.000 on screens with a selection against 0.404 without one.
TPL_PICKED = template("DemonParade", "picked.png")
# The "0" of the counter at the top centre, which counts the shikigami still
# to come: it reads 0 as the 36th and last walks in. Cut on BlueStacks, scored
# 1.000 on every frame of a round that showed 0 and at most 0.726 on the rest.
TPL_COUNTER_ZERO = template("DemonParade", "counterZero.png")
COUNTER_REGION = ((480, 0), (640, 60))
COUNTER_ZERO_ACCURACY = 0.9

# --- Tuning ----------------------------------------------------------------
DEFAULT_ACCURACY = 0.9
# The banner sits over artwork that changes every round, so it never reaches the
# 0.9 the other templates do. Measured 0.826 at worst with a selection, 0.404
# without: this sits between, with room either side.
PICKED_ACCURACY = 0.7

BEANS_CHOICES = (5, 10)
DEFAULT_BEANS = 10

# Between the *start* of two throws — not the pause after one. The game caps
# throwing at about 1.6 a second, and finding something to aim at costs real
# time: capture, subtract the background, label the blobs. Adding a flat pause
# on top of that work dropped a round from 33 throws to 24, which cost more in
# beans thrown than aiming won back.
THROW_INTERVAL_SECONDS = 0.6
# Pixels a frame must differ from the still background to count as a figure.
FIGURE_DIFFERENCE = 40
# What counts as one whole shikigami.
#
# These must stay in step with tools/collect_figures.py. The rarity library is
# built from crops that passed those filters, and a crop that passed different
# ones is not the same kind of picture — the histogram of half a figure, or of
# two blended together, matches nothing in the library.
#
# Measured with the two out of step, the finder admitting fragments 22 pixels
# tall while the library held whole figures 60 and up: the loop saw 8.3 shapes
# a frame where the collector saw 4.5, and 1,159 sightings in a round came back
# 67% unrecognised and **0% read as SP or SSR**. Three live rounds landed one
# throw on a rare figure.
#
# An earlier version did keep the threshold low, and had a reason: admitting
# only the five or six biggest figures collected 9.5 shards a round against
# 13.9 for a plain sweep. That reason belonged to a design that threw at
# everything and wanted breadth. This one holds its beans for two ranks, so
# being able to name what it sees matters more than seeing more of it — and
# the end-of-round dump still falls back to the sweep grid.
FIGURE_MIN_WIDTH = 55
FIGURE_MAX_WIDTH = 520
FIGURE_MIN_HEIGHT = 60
FIGURE_MAX_HEIGHT = 420
# A box this empty holds two figures with a gap between them, not one.
FIGURE_MIN_FILL = 0.25
# Two shikigami shoulder to shoulder merge into one wide blob whose colours are
# a blend of both, matching neither. 94% of known single figures are below this.
FIGURE_MAX_ASPECT = 1.4
# Smaller than this and it is a spark or a floating label.
FIGURE_MIN_AREA = 400
# Frames averaged into the still background at the start of a round. The median
# of them is what the scene looks like with the parade taken out.
BACKGROUND_FRAMES = 6
BACKGROUND_GAP_SECONDS = 0.25
# A round lasts 35 seconds. Throwing stops short of that on purpose and the
# loop then waits, clicking nothing, for the result to appear.
#
# Checking more often cannot fix this by itself: between any two checks there is
# a throw, and if the round ends in that gap the throw lands on the result
# scroll and dismisses it — the scroll closes on a tap anywhere. The loop then
# finds itself back at the entry screen with no result to count and spends
# another ticket. Seen twice on live runs, at every check interval tried.
#
# 250 beans at 10 a throw is 25 throws anyway, which at this pace is about 22
# seconds, so stopping at 30 gives up nothing.
# Only a safety cap now. Throwing really ends LAST_FIGURE_THROW_SECONDS after
# the counter reads 0. It was 30, on the belief that a round lasts 35 seconds:
# filmed on BlueStacks, the parade runs to about 65 seconds when the beans
# last, and the loop sat out its second half — the chosen boss walked by in it.
ROUND_THROW_SECONDS = 70.0
# Between throws until the last figure is in. 250 beans at 10 a throw is 25
# throws, and an empty purse ends the round on the spot: thrown at the game's
# pace they were gone at about 45 s with a dozen figures still to come. 25
# throws two seconds apart last about as long as the parade does. Ten rounds
# paced this way won 4.9 cards a round against 3.7 for the old pace.
PACED_THROW_SECONDS = 2.0
# From the counter reading 0 until Time's up is about nine seconds; stop short
# of it, since a throw that lands on the result scroll closes it.
LAST_FIGURE_THROW_SECONDS = 8.0
# Between throws while the picked boss is being followed: as fast as the game
# takes them (about 1.6 a second), because the boss is on screen for a few
# seconds at most and every bean that lands on it pays triple. See parade_boss.
BOSS_THROW_SECONDS = 0.3
# Back on the pick screen raises the quit dialog; OK on it lands in the town.
REROLL_BACK_SETTLE_SECONDS = 1.5
# Fliers labelled "Assist Up" or "Chance Up" need one hit; a second throw
# covers a miss. A second apart, so the first has landed before the next.
HELPER_THROWS = 2
HELPER_GAP_SECONDS = 1.0
# A "Got Beans" flier pays 40 beans for a 10-bean throw, and live it was
# missed once and then left alone. It is thrown at until it is gone — a hit
# takes it off the screen — paced so a bean lands (0.3–0.9 s) before the
# next, and capped in case a lookalike keeps the label in sight.
GOT_BEANS_GAP_SECONDS = 0.6
GOT_BEANS_MAX_THROWS = 15
HELPER_NAMES = {"assist": "Assist Up", "chance": "Chance Up", "beans": "Got Beans"}
# A Wanted Quest invite can open mid-round and sit over the stage: live, it hid
# the boss for the whole of one round. Looking for it costs 30–60 ms, so once a
# second rather than every throw; the dialog stays up far longer than that.
INVITE_CHECK_SECONDS = 1.0
# A tapped candidate lights up within about a second; 1.2 lit 255 of 255.
SURVEY_SETTLE_SECONDS = 1.2
REROLL_QUIT_SETTLE_SECONDS = 3.0
TOWN_SIGN_SETTLE_SECONDS = 2.0
# The slider can drop out of sight for a moment — freeze frost, a shard
# banner — and that is not the end of the round. Taking it for one restarted
# the throwing mid-parade, background and all.
ROUND_GONE_SECONDS = 2.5
# How long before throwing stops the loop gives up holding out for an SP or SSR
# and spends whatever beans are left on whoever is there.
#
# Beans do not carry over between rounds, so any still unspent when the round
# ends are simply lost, and the ticket has been paid either way. Holding them
# to the last second would mean a round with no rare visitor returns nothing at
# all.
#
# Sized to empty a full purse: 250 beans at 10 a throw is 25 throws, and 25
# throws at THROW_INTERVAL_SECONDS is 15 seconds. Shorter and the round ends
# with beans in hand — 10 seconds buys only about 16 throws, leaving 90 beans
# to evaporate.
DUMP_LAST_SECONDS = 15.0
# How long to wait after that for the result, before giving up and letting the
# outer loop work out where it is.
ROUND_LIMIT_SECONDS = 100.0

PICK_SETTLE_SECONDS = 3.0
# The line-up slides in after the pick screen appears. Measured silhouettes
# before it settles are a figure and a half of the frame, not the figure.
PICK_LINEUP_SETTLE_SECONDS = 1.5
# Start is ignored while the pick animation is still running — a run that gave
# it 2 seconds silently never started, and every later click landed on the pick
# screen instead.
START_SETTLE_SECONDS = 4.0
# After a boss picked by silhouette the pick animation is long over, so the
# round can be met sooner: the stage is empty for the 3-2-1 countdown, the
# moment to learn the background before the first figure walks in.
BOSS_START_SETTLE_SECONDS = 2.0
ENTER_SETTLE_SECONDS = 3.0
DISMISS_SETTLE_SECONDS = 3.0
# The result scroll slides in. Read too early and the grid is caught mid-travel:
# a real run cropped the rarity badge instead of the name and cut every name
# short, on a round whose cards were perfectly legible a second later.
RESULT_SETTLE_SECONDS = 1.5
POLL_SECONDS = 1.0
CAPTURE_RETRY_SECONDS = 1.0

# Entry screen still showing after this many presses of Enter means the press
# is not being honoured. Out of tickets is much the likeliest reason.
ENTER_ATTEMPTS = 3

# The gold fill on the beans slider, in HSV. Comfortably clear of the dark
# unfilled track beside it.
# Gold by hue as well, not just strong and bright. On BlueStacks the onmyoji in
# blue stands where the scan ends, and without the hue his robe passed for the
# fill: the knob read at the very top, the log said "10 (already set)", and the
# game threw 5 a time all run. The fill measures hue 17-20.
SLIDER_GOLD_HUE = (10, 35)
SLIDER_GOLD_SATURATION = 90
SLIDER_GOLD_VALUE = 130
SLIDER_ATTEMPTS = 3
SLIDER_DRAG_STEPS = 24
SLIDER_HOLD_SECONDS = 0.25
SLIDER_SETTLE_SECONDS = 0.8



class DemonParadeWorker(TaskWorker):
    """Runs parade rounds until stopped, the count is reached, or tickets end."""

    def __init__(
        self,
        hwnd: int,
        beans: int = DEFAULT_BEANS,
        rounds: int = 0,
        accept_wanted_quest: bool = False,
        accuracy: float = DEFAULT_ACCURACY,
        reroll_below: float = 0.0,
        on_finished: Callback = None,
        on_error: Callback = None,
        control: Optional[GameControl] = None,
    ) -> None:
        if beans not in BEANS_CHOICES:
            raise ValueError("Beans per throw must be one of %s" % (BEANS_CHOICES,))
        if rounds < 0:
            raise ValueError("Rounds cannot be negative")
        if reroll_below < 0:
            raise ValueError("The reroll threshold cannot be negative")
        super().__init__("DemonParadeWorker", hwnd, control, on_finished, on_error)
        self._beans = beans
        self._rounds = rounds          # 0 means keep going until stopped
        self._accuracy = accuracy
        self._accept_wanted_quest = accept_wanted_quest
        # 0 plays every line-up. Otherwise a line-up whose biggest silhouette
        # is smaller than this, relative to its column, is quit unplayed: see
        # _lineup_is_too_small.
        self._reroll_below = reroll_below

        self._enter = self._geometry.point(geometry.PARADE_ENTER)
        self._pick_points = tuple(
            self._geometry.point(p) for p in geometry.PARADE_PICK_POINTS
        )
        self._start = self._geometry.point(geometry.PARADE_START)
        self._back = self._geometry.point(geometry.PARADE_BACK)
        self._quit_ok = self._geometry.point(geometry.PARADE_QUIT_OK)
        self._dismiss = self._geometry.point(geometry.PARADE_DISMISS)
        self._throw_points = self._build_throw_points()

        self._completed = 0
        # Only a round this loop threw beans into gets counted; see _handle_result.
        self._played_a_round = False
        # The slider keeps its setting for the whole round, and each drag costs
        # about a second and a half of throwing time.
        self._slider_set = False
        # Which throw of the round this is. Belongs to the round, not to one
        # call: the throwing loop can be re-entered part way through, and
        # starting the count again would re-throw the same first few spots.
        self._throw_index = 0
        self._enter_attempts = 0
        self._out_of_tickets = False
        self._started_at: Optional[float] = None
        self._elapsed_at_pause = 0.0
        self._invites_handled = 0
        # name -> shards, summed over every round this run read.
        self._shards: Dict[str, int] = {}
        self._unreadable = 0
        # SSR and SP cards won this run — what the parade is played for. Counted
        # off the rarity letter alone, because an SSR card is the one whose name
        # and "x1" the scroll reader most often cannot make out.
        self._rare_hits = 0
        # Whether this pick screen already has our boss selected. Start does
        # not always take, and the loop then meets the pick screen again.
        self._boss_chosen = False
        # Line-ups quit unplayed this run, and whether one was just quit — the
        # town only gets a click while we are on our way back from a reroll.
        self._rerolls = 0
        self._rerolling = False
        # Cards marked "Pick" — the boss's own shards — won this run: the
        # measure of whether following the boss is landing beans on it.
        self._boss_hits = 0

    def _build_throw_points(self):
        start_x, stop_x = geometry.PARADE_THROW_X
        points = []
        for y in geometry.PARADE_THROW_ROWS:
            for x in range(start_x, stop_x, geometry.PARADE_THROW_STEP):
                points.append(self._geometry.point((x, y)))
        return tuple(points)

    # ---------- lifecycle ----------

    @property
    def progress(self) -> int:
        """Rounds played, counted from the result screens this loop dismissed."""
        return self._completed

    @property
    def shards(self) -> Dict[str, int]:
        """Shards won per shikigami this run, highest first."""
        return dict(
            sorted(self._shards.items(), key=lambda kv: (-kv[1], kv[0]))
        )

    @property
    def rare_hits(self) -> int:
        """SSR and SP cards won this run, whether or not their names read."""
        return self._rare_hits

    @property
    def rerolls(self) -> int:
        """Line-ups quit unplayed this run for having no likely SSR/SP."""
        return self._rerolls

    @property
    def boss_hits(self) -> int:
        """Cards of the picked boss's shards won this run."""
        return self._boss_hits

    def shard_summary(self) -> str:
        """One line for a notification, e.g.
        ``39 mảnh — Nurikabe 8, Koi 6 · quỷ vương: 2 · SSR/SP: 1``."""
        if not self._shards and not self._rare_hits and not self._boss_hits:
            return ""
        rare = "quỷ vương: %d · SSR/SP: %d" % (self._boss_hits, self._rare_hits)
        if not self._shards:
            return rare
        parts = ["%s %d" % (name, count) for name, count in self.shards.items()]
        total = sum(self._shards.values())
        return "%d mảnh — %s · %s" % (total, ", ".join(parts), rare)

    def run(self) -> None:
        logger.info(
            "Demon Parade worker starting — %d beans/throw, rounds=%s — %s",
            self._beans,
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
            logger.exception("Demon Parade loop crashed")
            self._notify(self._on_error, str(exc))
            return
        finally:
            self._end_timing()
            self._control.close()

        if self._shards:
            logger.info("Shards this run: %s", self.shard_summary())
        if self._unreadable:
            logger.info(
                "%d card(s) could not be read; add their crops to "
                "screenshots/DemonParade/names or /counts",
                self._unreadable,
            )

        if self._out_of_tickets:
            logger.info("Out of tickets after %d rounds", self._completed)
            self._notify(
                self._on_finished,
                self._with_shards("Hết vé ném đậu. Đã chạy %d vòng." % self._completed),
            )
        elif finished:
            logger.info("Demon Parade run finished after %d rounds", self._completed)
            self._notify(
                self._on_finished,
                self._with_shards("Xong %d vòng ném đậu." % self._completed),
            )
        else:
            logger.info("Demon Parade worker stopped after %d rounds", self._completed)

    def _with_shards(self, message: str) -> str:
        if self._rerolls:
            message = "%s Đã đổi lượt: %d." % (message, self._rerolls)
        summary = self.shard_summary()
        if not summary:
            return message
        return "%s Thu được %s" % (message, summary)

    # ---------- main loop ----------

    def _loop(self) -> bool:
        while not self._stop_event.is_set():
            self._wait_while_paused()
            if self._stop_event.is_set():
                break
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
        if self._holding_for_the_cursor():
            return False
        # An invite modal covers the window and swallows everything under it.
        if self._handle_wanted_invite():
            return False

        if self._find(TPL_RESULT) is not None:
            return self._handle_result()
        if self._in_round():
            self._throw_until_round_ends()
            return False
        if self._find(TPL_PICK) is not None:
            self._handle_pick()
            return False
        if self._find(TPL_ENTER) is not None:
            return self._handle_entry()
        if self._rerolling and self._handle_town():
            return False

        logger.debug("Unrecognised screen; waiting")
        self._sleep(POLL_SECONDS)
        return False

    # ---------- handlers ----------

    def _find(self, template_path: str, accuracy: Optional[float] = None):
        return self._control.find(
            template_path,
            threshold=self._accuracy if accuracy is None else accuracy,
        )

    def _handle_wanted_invite(self) -> bool:
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
        self._sleep(POLL_SECONDS)
        return True

    def _handle_entry(self) -> bool:
        """Press Enter, unless the run is done or the presses stop working."""
        self._rerolling = False
        if self._rounds > 0 and self._completed >= self._rounds:
            return True

        self._enter_attempts += 1
        if self._enter_attempts > ENTER_ATTEMPTS:
            # Every other reason for Enter doing nothing — a covering modal, a
            # mis-set window — would have moved something on screen by now.
            logger.warning(
                "Still on the entry screen after %d presses of Enter; assuming "
                "there are no tickets left",
                ENTER_ATTEMPTS,
            )
            self._out_of_tickets = True
            return True

        logger.info("Entering parade round %d", self._completed + 1)
        self._control.click(self._enter)
        self._sleep(ENTER_SETTLE_SECONDS)
        return False

    def _handle_pick(self) -> None:
        """Select a shikigami, confirm it took, then start.

        Confirming matters: Start is silently ignored without a selection, and
        a click that lands on empty ground *deselects*. A build that clicked one
        fixed spot and pressed on spent a whole run pressing Start at a screen
        with nothing chosen, once every seven seconds.
        """
        self._enter_attempts = 0        # Enter clearly worked
        self._slider_set = False        # a new round, so the slider is fresh
        self._throw_index = 0

        if self._boss_chosen and self._pick_still_selected():
            # Start did not take. Choosing again would be worse than useless:
            # the chosen boss is lit up in colour, not a silhouette any more,
            # so measuring leaves it out and picks a smaller one instead.
            logger.info("Starting round %d (again)", self._completed + 1)
            self._control.click(self._start)
            self._sleep(BOSS_START_SETTLE_SECONDS)
            return

        self._sleep(PICK_LINEUP_SETTLE_SECONDS)
        choice = self._measure_lineup()
        if self._reroll_below > 0 and choice is not None:
            rare = self._survey_for_rare()
            if rare is not None:
                choice = rare
            elif self._lineup_is_too_small(choice):
                self._reroll(choice)
                return

        self._boss_chosen = self._pick_the_biggest(choice)
        if self._boss_chosen:
            logger.info("Starting round %d", self._completed + 1)
            self._control.click(self._start)
            self._sleep(BOSS_START_SETTLE_SECONDS)
            return

        for point in self._pick_points:
            self._control.click(point)
            self._sleep(PICK_SETTLE_SECONDS)
            self._control.begin_frame()
            try:
                chosen = self._find(TPL_PICKED, PICKED_ACCURACY) is not None
            finally:
                self._control.end_frame()
            if chosen:
                logger.info("Picked the shikigami at %s", point)
                break
        else:
            logger.warning(
                "Could not select a shikigami at any of %d spots; not pressing "
                "Start, which would do nothing anyway",
                len(self._pick_points),
            )
            return

        logger.info("Starting round %d", self._completed + 1)
        self._control.click(self._start)
        self._sleep(START_SETTLE_SECONDS)

    def _pick_still_selected(self) -> bool:
        self._control.begin_frame()
        try:
            return self._find(TPL_PICKED, PICKED_ACCURACY) is not None
        finally:
            self._control.end_frame()

    def _measure_lineup(self):
        """The candidate most likely to be SSR/SP, or None if none measure."""
        try:
            return parade_pick.choose(self._control.full_shot())
        except CaptureError:
            return None

    def _survey_for_rare(self):
        """Light each candidate up and look it up among known SSR/SP pictures.

        Only while rerolling: it costs a few seconds a line-up, and it is what
        lets an SSR/SP of ordinary size be played rather than quit. Every lit
        candidate is also kept, unlabelled, so the library can grow — see
        :mod:`parade_rare`.
        """
        try:
            frame = self._control.full_shot()
        except CaptureError:
            return None
        found = None
        for candidate in parade_pick.candidates(frame):
            lit = self._light_up(candidate)
            if lit is None:
                continue
            try:
                parade_rare.save(lit, candidate)
            except Exception:
                logger.debug("Could not keep a lit candidate", exc_info=True)
            score, name = parade_rare.best_match(lit, candidate)
            if score >= parade_rare.MATCH_ACCURACY and (found is None or score > found[1]):
                found = (candidate, score, name)
        if found is None:
            return None
        candidate, score, name = found
        logger.info("Known SSR/SP in column %d (%s, %.2f)",
                    candidate.column + 1, name, score)
        return candidate

    def _light_up(self, candidate):
        """Tap a candidate until it lights up; the lit frame, or None."""
        for tap in candidate.taps:
            self._control.click(self._geometry.point(tap))
            self._sleep(SURVEY_SETTLE_SECONDS)
            try:
                frame = self._control.full_shot()
            except CaptureError:
                continue
            if parade_pick.is_lit(frame, candidate):
                return frame
        return None

    def _lineup_is_too_small(self, choice) -> bool:
        """Whether this line-up is worth quitting unplayed.

        An SSR/SP shard only comes from an SSR/SP boss, and only about one
        line-up in sixteen offers one. When it does, it is nearly always the
        biggest silhouette by a distance: of the 13 seen among 205 labelled
        line-ups, the 9 the size rule picked stood 1.5 to 3.7 times the usual
        size for their spot, most of them above 1.8. Quitting costs a ticket
        and some 12 seconds; playing costs over a minute. At 1.8, on those 205,
        only 18% of line-ups are played, 8 of the 13 SSR/SP are still played,
        and SSR/SP bosses per hour come out about 2.7 times higher — for about
        three times the tickets.

        A line-up that cannot be measured is played: no measurement is no
        evidence, and a blind round beats a ticket thrown away on a guess.
        """
        return (self._reroll_below > 0 and choice is not None
                and choice.relative < self._reroll_below)

    def _reroll(self, choice) -> None:
        """Quit this pick screen unplayed; the town's sign leads back in."""
        self._rerolls += 1
        self._rerolling = True
        logger.info(
            "Line-up too small (biggest %.1fx, want %.1fx) — quitting it "
            "(reroll %d)", choice.relative, self._reroll_below, self._rerolls,
        )
        self._control.click(self._back)
        self._sleep(REROLL_BACK_SETTLE_SECONDS)
        self._control.click(self._quit_ok)
        self._sleep(REROLL_QUIT_SETTLE_SECONDS)

    def _handle_town(self) -> bool:
        """Press the parade's sign in the town, if it is there."""
        sign = self._find(TPL_TOWN_LANTERN, TOWN_LANTERN_ACCURACY)
        if sign is None:
            sign = self._find(TPL_TOWN_SIGN, TOWN_SIGN_ACCURACY)
        if sign is None:
            return False
        self._control.click(sign)
        self._sleep(TOWN_SIGN_SETTLE_SECONDS)
        return True

    def _pick_the_biggest(self, choice) -> bool:
        """Select the measured candidate. False if it would not take.

        See :mod:`parade_pick` for why the biggest silhouette is the one. False
        hands back to the fixed spots below, which are known to select
        *something*: a round with a blind pick still beats no round.
        """
        if choice is None:
            logger.info("No boss silhouettes to measure; picking blind")
            return False
        for tap in choice.taps:
            self._control.click(self._geometry.point(tap))
            self._sleep(PICK_SETTLE_SECONDS)
            try:
                lit = parade_pick.is_lit(self._control.full_shot(), choice)
            except CaptureError:
                lit = False
            if lit:
                logger.info(
                    "Picked the boss in column %d — %.1fx the usual size there",
                    choice.column + 1, choice.relative,
                )
                return True
        logger.info("Column %d would not light up; picking blind", choice.column + 1)
        return False

    def _find_knob(self):
        """Where the slider knob is now, in client x. None if it cannot be seen.

        The knob sits at the right-hand end of the gold fill, so the last gold
        pixel along the track is it. Guessing instead does not work: the slider
        ignores a press anywhere but on the knob itself — measured, a click on
        the track at the target and a drag starting short of the knob both left
        it exactly where it was.
        """
        try:
            frame = self._control.full_shot()
        except CaptureError:
            return None
        scale_x, scale_y = self._geometry.scale
        y = round(geometry.PARADE_SLIDER_Y * scale_y)
        x1 = round(geometry.PARADE_SLIDER_SCAN[0] * scale_x)
        x2 = round(geometry.PARADE_SLIDER_SCAN[1] * scale_x)
        if y >= frame.shape[0] or x2 > frame.shape[1]:
            return None
        band = frame[max(0, y - 2):y + 3, x1:x2]
        if band.size == 0:
            return None
        hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
        hue = hsv[:, :, 0]
        gold = ((hue >= SLIDER_GOLD_HUE[0]) & (hue <= SLIDER_GOLD_HUE[1])
                & (hsv[:, :, 1] > SLIDER_GOLD_SATURATION)
                & (hsv[:, :, 2] > SLIDER_GOLD_VALUE)).mean(axis=0)
        lit = np.where(gold > 0.5)[0]
        if len(lit) == 0:
            return None
        return x1 + int(lit.max())

    def _set_beans_per_throw(self) -> None:
        """Drag the slider knob to the chosen value, and check that it went.

        The knob has to be grabbed where it actually is. An earlier version
        assumed it could be parked at the minimum first by pressing short of the
        track — but the slider ignores everything except a press on the knob, so
        the drag that followed grabbed empty track and the setting silently
        stayed at 5. Checking afterwards is what turns that from invisible into
        a warning in the log.
        """
        scale_x = self._geometry.scale[0]
        target_x = geometry.PARADE_SLIDER_X[self._beans]
        target = self._geometry.point((target_x, geometry.PARADE_SLIDER_Y))
        tolerance = max(1, round(geometry.PARADE_SLIDER_TOLERANCE * scale_x))
        radius = round(geometry.PARADE_KNOB_RADIUS * scale_x)
        # Ten is the top of the slider, and the top is not in the same place
        # everywhere: the PC client stops the knob at 520, BlueStacks at about
        # 544. So ten is "dragged as far right as it goes" — past the end, which
        # the slider clamps — and counted as reached once the knob is at or
        # beyond the PC's top. Five sits mid-track and needs a real position.
        most = max(geometry.PARADE_SLIDER_X.values())
        to_the_top = target_x == most
        drop_x = (self._geometry.point((geometry.PARADE_SLIDER_SCAN[1], 0))[0]
                  if to_the_top else target[0] - radius)

        for attempt in range(SLIDER_ATTEMPTS):
            self._control.invalidate_frame()
            self._control.begin_frame()
            try:
                knob = self._find_knob()
            finally:
                self._control.end_frame()
            if knob is None:
                logger.info("Beans slider not visible; leaving it alone")
                return
            if (knob >= target[0] - tolerance if to_the_top
                    else abs(knob - target[0]) <= tolerance):
                # Says which of the two it was, because they look identical in
                # a log and mean very different things: one is the setting
                # already being right, the other is a drag having worked.
                logger.info(
                    "Beans per throw is %d (%s)",
                    self._beans,
                    "already set" if attempt == 0 else "dragged there",
                )
                return
            # Grabbed by the middle and dropped so the rim — what is read back —
            # lands on the target.
            self._control.drag((knob - radius, target[1]), (drop_x, target[1]),
                               steps=SLIDER_DRAG_STEPS,
                               hold_seconds=SLIDER_HOLD_SECONDS)
            self._sleep(SLIDER_SETTLE_SECONDS)

        logger.warning(
            "Could not set beans per throw to %d after %d tries; the game is "
            "still throwing whatever the slider says",
            self._beans, SLIDER_ATTEMPTS,
        )

    def _learn_background(self):
        """The scene with the parade taken out: the median of a few frames.

        Anything a later frame disagrees with is something that moved, which on
        this screen means a shikigami.
        """
        frames = []
        for _ in range(BACKGROUND_FRAMES):
            if self._stop_event.is_set():
                break
            try:
                self._control.invalidate_frame()
                self._control.begin_frame()
                try:
                    frames.append(self._control.full_shot().copy())
                finally:
                    self._control.end_frame()
            except CaptureError:
                pass
            self._sleep(BACKGROUND_GAP_SECONDS)
        if len(frames) < 3:
            return None
        return np.median(np.stack(frames).astype(np.uint8), axis=0).astype(np.uint8)

    def _figures(self, frame, background):
        """Where the shikigami are in this frame, biggest first."""
        if background is None or frame is None or frame.shape != background.shape:
            return []
        difference = cv2.absdiff(frame, background).max(axis=2)
        mask = (difference > FIGURE_DIFFERENCE).astype(np.uint8) * 255
        top, bottom = geometry.PARADE_FIGURE_BAND
        scale_y = self._geometry.scale[1]
        mask[:round(top * scale_y)] = 0
        mask[round(bottom * scale_y):] = 0
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        total, labels, stats, centres = cv2.connectedComponentsWithStats(mask, 8)
        found = []
        for i in range(1, total):
            x, y, w, h, area = stats[i]
            if area <= FIGURE_MIN_AREA:
                continue
            if not (FIGURE_MIN_WIDTH <= w <= FIGURE_MAX_WIDTH):
                continue
            if not (FIGURE_MIN_HEIGHT <= h <= FIGURE_MAX_HEIGHT):
                continue
            if area < FIGURE_MIN_FILL * w * h:
                continue
            if w > FIGURE_MAX_ASPECT * h:
                continue
            # The figure with the scenery behind it blacked out, which is what
            # its colours have to be read from — the bridge and the temple
            # change as it walks and would drown the palette.
            cut = frame[y:y + h, x:x + w].copy()
            cut[labels[y:y + h, x:x + w] != i] = 0
            found.append((int(centres[i][0]), int(centres[i][1]), int(area), cut))
        # Left to right, not biggest first. Cycling a list ordered by size
        # walks back and forth across the bridge and keeps returning to the
        # same few; ordered by position it sweeps, which is what the plain grid
        # did well.
        found.sort(key=lambda f: f[0])
        return found

    def _choose(self, targets, spending_leftovers):
        """(where to throw, what it was) — or (None, "held") to keep the beans.

        While there are beans worth saving, only figures the common library
        cannot name are thrown at. Near the end of the round that reverses:
        beans do not carry over, so any still unspent are about to be lost, and
        a common shikigami's shards beat nothing at all.

        The second half of the return says which kind of figure was picked, and
        it is not decoration. A figure recognised as SP or SSR and one the
        library simply cannot name are both worth a bean, but only the first is
        evidence about whether hitting a rare shikigami yields its shards —
        counting them together makes that question unanswerable from a log.

        Among several worth hitting the sweep still moves along, so one figure
        is not hammered until it walks off screen.
        """
        named, unknown = [], []
        for x, y, _area, cut in targets:
            rarity = self._rarity(cut)
            if rarity in parade_figures.TARGET_RANKS:
                named.append((x, y))
            elif parade_figures.is_target(rarity):
                unknown.append((x, y))

        if named:
            return named[self._throw_index % len(named)], "rare"
        if unknown:
            return unknown[self._throw_index % len(unknown)], "unknown"
        if not spending_leftovers:
            return None, "held"
        if targets:
            return targets[self._throw_index % len(targets)][:2], "leftover"
        return self._throw_points[self._throw_index % len(self._throw_points)], "leftover"

    def _rarity(self, cut):
        try:
            return parade_figures.rarity_of(cut)
        except Exception:
            logger.debug("Could not read a figure's rarity", exc_info=True)
            return None

    def _throw_until_round_ends(self) -> None:
        """Throw at the parade until the round screen goes away.

        Paced over the whole parade rather than spent at the game's pace: see
        PACED_THROW_SECONDS. Once the counter reads 0 the last figure is in,
        and whatever is left goes at whoever is there.
        """
        self._played_a_round = True
        self._boss_chosen = False       # the next pick screen is a new one
        # Before the slider: the round opens on an empty stage for its 3-2-1,
        # and that is the background to subtract. Learnt after the slider, the
        # first figures were already walking and could be taken for scenery.
        background = self._learn_background()
        if background is None:
            logger.info("Could not read the background; sweeping instead")
        boss_background = self._at_reference(background)
        chase = parade_boss.BossChase()
        if not self._slider_set:
            self._set_beans_per_throw()
            self._slider_set = True
        deadline = time.monotonic() + ROUND_LIMIT_SECONDS
        thrown = 0
        stop_throwing = time.monotonic() + ROUND_THROW_SECONDS
        dump_from = stop_throwing - DUMP_LAST_SECONDS
        last_figure_at: Optional[float] = None
        slider_lost_at: Optional[float] = None
        tally = {"boss": 0, "helper": 0, "rare": 0, "unknown": 0, "leftover": 0, "held": 0}
        helper_throws: Dict[str, int] = {}
        helper_last: Dict[str, float] = {}
        last_was_beans = False
        invite_checked_at = float("-inf")
        while not self._stop_event.is_set() and time.monotonic() < stop_throwing:
            cycle_started = time.monotonic()
            # One capture serves every job: whether the round is still on,
            # whether the last figure is in, and what to throw at.
            frame = None
            self._control.invalidate_frame()
            self._control.begin_frame()
            try:
                if self._find(TPL_RESULT) is not None:
                    logger.info("Round %d: %d throws (%s), round over",
                                self._completed + 1, thrown, _describe(tally))
                    return
                if cycle_started - invite_checked_at >= INVITE_CHECK_SECONDS:
                    invite_checked_at = cycle_started
                    if self._handle_wanted_invite():
                        continue
                if not self._in_round():
                    if slider_lost_at is None:
                        slider_lost_at = cycle_started
                    if cycle_started - slider_lost_at >= ROUND_GONE_SECONDS:
                        logger.info("Round %d: %d throws (%s), round over",
                                    self._completed + 1, thrown, _describe(tally))
                        return
                else:
                    slider_lost_at = None
                    try:
                        frame = self._control.full_shot()
                    except CaptureError:
                        frame = None
            finally:
                self._control.end_frame()
            if frame is None:
                self._sleep(THROW_INTERVAL_SECONDS)
                continue

            if last_figure_at is None and self._last_figure_is_in(frame):
                last_figure_at = cycle_started
                stop_throwing = min(stop_throwing, cycle_started + LAST_FIGURE_THROW_SECONDS)
                logger.info("Round %d: the last figure is in after %d throws — "
                            "spending what is left", self._completed + 1, thrown)

            badge, bodies = self._boss_sighting(
                frame, boss_background, chase.is_following(cycle_started))
            if chase.see(cycle_started, badge, bodies):
                logger.info("Round %d: the boss is on stage after %d throws — "
                            "following it", self._completed + 1, thrown)
            aim = chase.aim(time.monotonic())
            helper = self._helper_target(frame, helper_throws, helper_last, cycle_started)
            # The boss comes first, except that a Got Beans flier in sight
            # takes every other throw: it pays more beans than it costs, and
            # it is gone in seconds too.
            if helper is not None and aim is not None and (
                    helper[0] != "beans" or last_was_beans):
                helper = None
            # Against the top of the cycle, like the throws below: the looking
            # took time, and a click now could land past the end of the window.
            if aim is not None and helper is None and cycle_started < stop_throwing:
                self._control.click(self._geometry.point(aim))
                self._throw_index += 1
                thrown += 1
                tally["boss"] += 1
                last_was_beans = False
                spent = time.monotonic() - cycle_started
                self._sleep(max(0.0, BOSS_THROW_SECONDS - spent))
                continue

            if helper is not None and cycle_started < stop_throwing:
                kind, point = helper
                self._control.click(self._geometry.point(point))
                helper_throws[kind] = helper_throws.get(kind, 0) + 1
                helper_last[kind] = cycle_started
                last_was_beans = kind == "beans"
                self._throw_index += 1
                thrown += 1
                tally["helper"] += 1
                logger.info("Round %d: a bean at the %s flier", self._completed + 1,
                            HELPER_NAMES.get(kind, kind))
                spent = time.monotonic() - cycle_started
                self._sleep(max(0.0, BOSS_THROW_SECONDS - spent))
                continue

            targets = self._figures(frame, background)
            # Read from the top of this cycle, not now: looking at the screen
            # takes time, and a fresh reading here can already be past the end
            # of the window the loop condition just admitted us into — which
            # let one throw slip out after the holding was supposed to stop.
            spending_leftovers = last_figure_at is not None or cycle_started >= dump_from
            if self._reroll_below > 0 and not spending_leftovers:
                # Rerolling means the round is played for its boss alone, and
                # the boss walks in at a random moment. Live, beans paced at
                # the others were mostly gone by the time a late boss came.
                point, kind = None, "held"
            else:
                point, kind = self._choose(targets, spending_leftovers)
            tally[kind] += 1
            interval = THROW_INTERVAL_SECONDS
            if point is not None:
                self._control.click(point)
                self._throw_index += 1
                thrown += 1
                if not spending_leftovers:
                    interval = PACED_THROW_SECONDS
            # Whatever is left of the interval after the looking and the
            # clicking, and nothing if that already took longer.
            spent = time.monotonic() - cycle_started
            self._sleep(max(0.0, interval - spent))
        logger.info(
            "Round %d: %d throws (%s), waiting it out",
            self._completed + 1, thrown, _describe(tally),
        )

        # Hands off from here. Every click now is a click the result scroll
        # might eat.
        while not self._stop_event.is_set() and time.monotonic() < deadline:
            if self._round_is_over():
                return
            self._sleep(POLL_SECONDS)

    def _in_round(self) -> bool:
        """Whether the beans slider is up, frosted over by Freeze or not."""
        return (self._find(TPL_IN_ROUND) is not None
                or self._find(TPL_IN_ROUND_FROZEN) is not None)

    def _helper_target(self, frame, throws, last, now):
        """(kind, point) of a labelled flier still owed a bean, or None.

        Assist Up and Got Beans fliers need one hit each, and the owner's rule
        is to give them that before the boss comes.
        """
        try:
            found = parade_boss.helpers(frame)
        except Exception:
            logger.debug("Could not look for helper fliers", exc_info=True)
            return None
        # Got Beans first: it is the one flier that may share throws with the boss.
        for kind, point in sorted(found, key=lambda item: item[0] != "beans"):
            most, gap = ((GOT_BEANS_MAX_THROWS, GOT_BEANS_GAP_SECONDS) if kind == "beans"
                         else (HELPER_THROWS, HELPER_GAP_SECONDS))
            if throws.get(kind, 0) >= most:
                continue
            if now - last.get(kind, float("-inf")) < gap:
                continue
            return kind, point
        return None

    def _at_reference(self, frame):
        """The frame at the reference size, or None if it is not an image."""
        if frame is None:
            return None
        try:
            return parade_pick.at_reference(frame)
        except Exception:
            logger.debug("Could not scale a frame to the reference size", exc_info=True)
            return None

    def _boss_sighting(self, frame, background, following=False):
        """(the "Picked" badge, the figures' bodies) in reference units.

        The bodies are only looked for when there is a boss to match them to —
        the badge is in sight, or the boss is being followed — since most of a
        round has no boss in it and the looking costs throwing time.

        Looking is never allowed to end a round: an unreadable frame is a frame
        with nothing in it.
        """
        try:
            small = parade_pick.at_reference(frame)
            badge = parade_boss.badge_at(small)
            if badge is None and not following:
                return None, []
            return badge, parade_boss.bodies(small, background)
        except Exception:
            logger.debug("Could not look for the boss", exc_info=True)
            return None, []

    def _last_figure_is_in(self, frame) -> bool:
        """Whether the counter at the top reads 0: the 36th figure is walking in."""
        try:
            small = parade_pick.at_reference(frame)
            (x1, y1), (x2, y2) = COUNTER_REGION
            zero = read_image(TPL_COUNTER_ZERO)
            score = cv2.matchTemplate(small[y1:y2, x1:x2], zero, cv2.TM_CCOEFF_NORMED).max()
        except Exception:
            logger.debug("Could not read the parade counter", exc_info=True)
            return False
        return float(score) >= COUNTER_ZERO_ACCURACY

    def _read_shards(self) -> None:
        """Tally what the scroll says, before the click that closes it.

        Nothing here is allowed to break a run: the tally is a nicety and the
        loop's job is to keep playing. A round whose scroll cannot be read is
        still a round played.
        """
        try:
            frame = self._control.full_shot()
            cards = parade_results.read_cards(frame, *self._geometry.scale)
        except Exception:
            logger.warning("Could not read the result scroll", exc_info=True)
            return
        try:
            boss = parade_results.boss_cards(frame)
        except Exception:
            logger.warning("Could not count the boss's cards", exc_info=True)
            boss = 0
        self._boss_hits += boss

        if not cards:
            logger.info("Round %d: no shards", self._completed + 1)
            return

        if any(None in card for card in cards):
            self._save_unknown(frame)

        got = []
        rare = 0
        for card in cards:
            if card.rarity in parade_results.RARE_RANKS:
                rare += 1
            got.append("[%s] %s x%s" % (
                card.rarity or "?", card.name or "?",
                card.count if card.count else "?",
            ))
            if card.name is None or card.count is None:
                self._unreadable += 1
                continue
            self._shards[card.name] = self._shards.get(card.name, 0) + card.count
        self._rare_hits += rare
        logger.info("Round %d shards: %s — boss cards: %d, SSR/SP: %d",
                    self._completed + 1, ", ".join(got), boss, rare)

    def _save_unknown(self, frame) -> None:
        """Keep the crops that could not be read, so the library can grow.

        There are hundreds of shikigami and the library starts with seven, so
        most of what a real run sees is new. Saving the crop turns "could not
        read" into a two-minute job: look at the picture, rename the file into
        `screenshots/DemonParade/names`. Without this the information is gone
        the moment the scroll is dismissed.
        """
        try:
            folder = paths.CACHE_DIR / "parade-unknown"
            folder.mkdir(parents=True, exist_ok=True)
            crops = parade_results.unknown_crops(frame, *self._geometry.scale)
            stamp = int(self.elapsed_seconds * 10)
            for label, patch in crops.items():
                target = folder / ("r%02d-%s-%05d.png" % (self._completed + 1, label, stamp))
                import cv2
                cv2.imencode(".png", patch)[1].tofile(str(target))
            if crops:
                logger.info("Saved %d unreadable crop(s) to %s", len(crops), folder)
        except Exception:
            logger.warning("Could not save the unreadable crops", exc_info=True)

    def _round_is_over(self) -> bool:
        """Whether the round has ended — checked often, and on purpose.

        This used to look only once every full sweep of the band, eighteen
        throws apart. That is long enough for the round to end, the result
        scroll to open, and the spray to *dismiss it* — the scroll takes a tap
        anywhere. The loop then found itself back on the entry screen with no
        result to count, pressed Enter, and spent another ticket. A live run
        entered twice and counted once.

        The result screen is tested as well as the absence of the round: they
        are not quite the same moment, and stopping at the first of them is
        what keeps the scroll on screen long enough to be counted.
        """
        self._control.begin_frame()
        try:
            if self._find(TPL_RESULT) is not None:
                return True
            return not self._in_round()
        finally:
            self._control.end_frame()

    def _handle_result(self) -> bool:
        """Dismiss the result scroll, and count the round if it was ours.

        Starting the task with a result scroll already on screen is ordinary —
        it is what a round played by hand a minute ago leaves behind. Counting
        that one would mean "stop after 5 rounds" stopping after four, so only
        a round this loop actually threw beans into is counted. Either way the
        scroll is dismissed, because it is in the way.
        """
        if not self._played_a_round:
            logger.info("Dismissing a result screen left over from before")
            self._control.click(self._dismiss)
            self._sleep(DISMISS_SETTLE_SECONDS)
            return False

        self._played_a_round = False
        self._sleep(RESULT_SETTLE_SECONDS)
        self._control.begin_frame()
        try:
            self._read_shards()
        finally:
            self._control.end_frame()
        self._completed += 1
        logger.info(
            "Round %d finished (%s)",
            self._completed,
            "%d/%d" % (self._completed, self._rounds) if self._rounds else "∞",
        )
        self._control.click(self._dismiss)
        self._sleep(DISMISS_SETTLE_SECONDS)
        return self._rounds > 0 and self._completed >= self._rounds
