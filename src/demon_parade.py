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
import parade_figures
import parade_results
import paths
import wanted_invite
from game_control import CaptureError, GameControl
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
    return "%d at a named rare, %d at unnamed, %d leftover, %d held" % (
        tally["rare"], tally["unknown"], tally["leftover"], tally["held"],
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
TPL_RESULT = template("DemonParade", "result.png")
# The gold "Pick" banner over whichever shikigami is selected. Scored 0.826 to
# 1.000 on screens with a selection against 0.404 without one.
TPL_PICKED = template("DemonParade", "picked.png")

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
ROUND_THROW_SECONDS = 30.0
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
ROUND_LIMIT_SECONDS = 60.0

PICK_SETTLE_SECONDS = 3.0
# Start is ignored while the pick animation is still running — a run that gave
# it 2 seconds silently never started, and every later click landed on the pick
# screen instead.
START_SETTLE_SECONDS = 4.0
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
        on_finished: Callback = None,
        on_error: Callback = None,
        control: Optional[GameControl] = None,
    ) -> None:
        if beans not in BEANS_CHOICES:
            raise ValueError("Beans per throw must be one of %s" % (BEANS_CHOICES,))
        if rounds < 0:
            raise ValueError("Rounds cannot be negative")
        super().__init__("DemonParadeWorker", hwnd, control, on_finished, on_error)
        self._beans = beans
        self._rounds = rounds          # 0 means keep going until stopped
        self._accuracy = accuracy
        self._accept_wanted_quest = accept_wanted_quest

        self._enter = self._geometry.point(geometry.PARADE_ENTER)
        self._pick_points = tuple(
            self._geometry.point(p) for p in geometry.PARADE_PICK_POINTS
        )
        self._start = self._geometry.point(geometry.PARADE_START)
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

    def shard_summary(self) -> str:
        """One line for a notification, e.g. ``Nurikabe 8, Koi 6`` (39 mảnh)."""
        if not self._shards:
            return ""
        parts = ["%s %d" % (name, count) for name, count in self.shards.items()]
        total = sum(self._shards.values())
        return "%d mảnh — %s" % (total, ", ".join(parts))

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
        if self._find(TPL_IN_ROUND) is not None:
            self._throw_until_round_ends()
            return False
        if self._find(TPL_PICK) is not None:
            self._handle_pick()
            return False
        if self._find(TPL_ENTER) is not None:
            return self._handle_entry()

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
        gold = ((hsv[:, :, 1] > SLIDER_GOLD_SATURATION)
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
        target_x = geometry.PARADE_SLIDER_X[self._beans]
        target = self._geometry.point((target_x, geometry.PARADE_SLIDER_Y))
        tolerance = max(
            1, round(geometry.PARADE_SLIDER_TOLERANCE * self._geometry.scale[0])
        )

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
            if abs(knob - target[0]) <= tolerance:
                # Says which of the two it was, because they look identical in
                # a log and mean very different things: one is the setting
                # already being right, the other is a drag having worked.
                logger.info(
                    "Beans per throw is %d (%s)",
                    self._beans,
                    "already set" if attempt == 0 else "dragged there",
                )
                return
            self._control.drag((knob, target[1]), target,
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
        """Throw at the parade until the round screen goes away."""
        self._played_a_round = True
        if not self._slider_set:
            self._set_beans_per_throw()
            self._slider_set = True
        background = self._learn_background()
        if background is None:
            logger.info("Could not read the background; sweeping instead")
        deadline = time.monotonic() + ROUND_LIMIT_SECONDS
        thrown = 0
        stop_throwing = time.monotonic() + ROUND_THROW_SECONDS
        dump_from = stop_throwing - DUMP_LAST_SECONDS
        tally = {"rare": 0, "unknown": 0, "leftover": 0, "held": 0}
        while not self._stop_event.is_set() and time.monotonic() < stop_throwing:
            cycle_started = time.monotonic()
            # One capture serves both jobs: deciding whether the round is still
            # on, and finding what to throw at.
            self._control.invalidate_frame()
            self._control.begin_frame()
            try:
                if (self._find(TPL_RESULT) is not None
                        or self._find(TPL_IN_ROUND) is None):
                    logger.info(
                        "Round %d: %d throws (%s), round over",
                        self._completed + 1, thrown, _describe(tally),
                    )
                    return
                try:
                    targets = self._figures(self._control.full_shot(), background)
                except CaptureError:
                    targets = []
            finally:
                self._control.end_frame()

            # Read from the top of this cycle, not now: looking at the screen
            # takes time, and a fresh reading here can already be past the end
            # of the window the loop condition just admitted us into — which
            # let one throw slip out after the holding was supposed to stop.
            spending_leftovers = cycle_started >= dump_from
            point, kind = self._choose(targets, spending_leftovers)
            tally[kind] += 1
            if point is not None:
                self._control.click(point)
                self._throw_index += 1
                thrown += 1
            # Whatever is left of the interval after the looking and the
            # clicking, and nothing if that already took longer.
            spent = time.monotonic() - cycle_started
            self._sleep(max(0.0, THROW_INTERVAL_SECONDS - spent))
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

    def _read_shards(self) -> None:
        """Tally what the scroll says, before the click that closes it.

        Nothing here is allowed to break a run: the tally is a nicety and the
        loop's job is to keep playing. A round whose scroll cannot be read is
        still a round played.
        """
        try:
            frame = self._control.full_shot()
            cards = parade_results.read_scroll(frame, *self._geometry.scale)
        except Exception:
            logger.warning("Could not read the result scroll", exc_info=True)
            return

        if not cards:
            logger.info("Round %d: no shards", self._completed + 1)
            return

        if any(name is None or count is None for name, count in cards):
            self._save_unknown(frame)

        got = []
        for name, count in cards:
            if name is None or count is None:
                self._unreadable += 1
                got.append("%s x%s" % (name or "?", count if count else "?"))
                continue
            self._shards[name] = self._shards.get(name, 0) + count
            got.append("%s x%d" % (name, count))
        logger.info("Round %d shards: %s", self._completed + 1, ", ".join(got))

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
            return self._find(TPL_IN_ROUND) is None
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
