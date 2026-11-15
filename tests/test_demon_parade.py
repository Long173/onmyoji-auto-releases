"""The Demon Parade (Ném đậu) loop.

The loop is a state machine over four screens, so what these check is that it
recognises which one it is on and does the one thing that screen needs — and
in particular that it never presses Enter, which costs a ticket and commits,
on a screen where that is not what Enter means.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import cv2
import numpy as np

import pytest

import demon_parade
import geometry
from demon_parade import DemonParadeWorker


def stub_scroll(monkeypatch, read):
    """Stand in for the result scroll with ``(name, count[, rarity])`` tuples."""
    monkeypatch.setattr(
        demon_parade.parade_results, "read_cards",
        lambda frame, *scale: [
            demon_parade.parade_results.Card(*card) for card in read(frame, *scale)
        ],
    )

ENTRY, PICK, ROUND, RESULT, UNKNOWN = "entry", "pick", "round", "result", "?"
FROZEN = "round, under Freeze's frost"
TOWN = "town"

# A round played through to its result screen: one entry per decision pass.
PLAYED_A_ROUND = [ROUND, RESULT, ENTRY]

SCREEN_TEMPLATE = {
    demon_parade.TPL_ENTER: ENTRY,
    demon_parade.TPL_PICK: PICK,
    demon_parade.TPL_IN_ROUND: ROUND,
    demon_parade.TPL_IN_ROUND_FROZEN: FROZEN,
    demon_parade.TPL_TOWN_LANTERN: TOWN,
    demon_parade.TPL_RESULT: RESULT,
}


class StubControl:
    """Answers `find` from a scripted list of screens."""

    def __init__(self, screens, picks_at=None, ends_after_throws=None):
        self.client_width, self.client_height = geometry.REFERENCE_CLIENT_SIZE
        # Last screen repeats forever once the script runs out.
        self._screens = list(screens)
        # Which pick coordinate actually selects a shikigami. None means the
        # first one tried does, matching the easy case.
        self.picks_at = picks_at
        self.picked = False
        # Where the knob sits. 360 is the game's own default of 5 a throw.
        self.knob_x = 360
        # How many throws in the round ends underneath the loop. That is the
        # awkward moment: the result scroll opens while the loop is still
        # throwing, and a throw closes it.
        self.ends_after_throws = ends_after_throws
        self.throws = 0
        self.clicks = []
        # False stands in for the real control refusing to click
        # because the player's own cursor is over the game window.
        self.clicking = True
        self.drags = []
        self.closed = False
        self.passes = 0
        self._depth = 0

    @property
    def screen(self):
        index = min(self.passes, len(self._screens) - 1)
        return self._screens[index]

    def advance(self):
        self.passes += 1

    def find(self, template_path, threshold=0.9, region=None, gray=True, delay=0.1):
        time.sleep(0.001)
        if template_path == demon_parade.TPL_PICKED:
            return (10, 20) if self.picked else None
        return (10, 20) if SCREEN_TEMPLATE.get(template_path) == self.screen else None

    def withholding_clicks(self):
        """Whether the real control would refuse to click right now.

        `clicking = False` stands for the player's own cursor resting over the
        game window. The loops ask this before a pass, so a stub that cannot
        answer it makes every loop run passes the real one would skip.
        """
        return not self.clicking

    def click(self, point):
        self.clicks.append(tuple(point))
        if self.ends_after_throws is not None and self.screen == ROUND:
            self.throws += 1
            if self.throws >= self.ends_after_throws:
                # The round is over; the scroll is up. Advance without waiting
                # for the pass to end, because that is what really happens.
                self._screens = [RESULT] * 2 + [ENTRY]
                self.passes = 0
        if self.picks_at is not None and tuple(point) == tuple(self.picks_at):
            self.picked = True
        elif self.picks_at is None and self.screen == PICK:
            self.picked = True

    def drag(self, start, end, **kwargs):
        self.drags.append((tuple(start), tuple(end)))
        # Only a grab on the knob's middle moves it. ``knob_x`` is its rim —
        # the last gold pixel, which is what the worker reads — and the middle
        # is a radius to the left. Measured on the real slider: a click on the
        # track and a drag starting short of the knob both left it where it
        # was, and on an emulator a touch on the rim did too. The knob then
        # follows the pointer, and stops at the top of the track.
        middle = self.knob_x - geometry.PARADE_KNOB_RADIUS
        if abs(start[0] - middle) <= self.GRAB_TOLERANCE:
            self.knob_x = min(int(end[0]) + geometry.PARADE_KNOB_RADIUS,
                              self.TOP)

    def full_shot(self, gray=False):
        """A black screen with the beans slider painted on it.

        The slider has to be here because the loop finds the knob by looking:
        it is the right-hand end of the gold fill. The real one ignores a press
        anywhere but on the knob, which `drag` below imitates — that is the
        whole behaviour these tests exist to pin down.
        """
        frame = np.zeros((633, 1122, 3), dtype=np.uint8)
        frame[574:582, 200:self.knob_x] = (60, 170, 235)      # gold, BGR
        return frame

    GRAB_TOLERANCE = 6
    TOP = 520           # where the PC client's knob stops

    def describe(self):
        return "stub control"

    # One screen per *decision pass*, not per captured frame. Frames nest: the
    # throwing loop and the slider both capture inside a pass that is already
    # capturing, and counting those made the script race ahead of the loop by
    # a different amount depending on which branch ran.
    def begin_frame(self):
        self._depth += 1

    def end_frame(self):
        self._depth -= 1
        if self._depth <= 0:
            self._depth = 0
            self.advance()

    def invalidate_frame(self):
        pass

    def last_frame(self):
        return None

    def close(self):
        self.closed = True


@pytest.fixture
def worker(monkeypatch, tmp_path):
    """Builds workers over a scripted screen sequence and tears them down."""
    # The tally keeps crops it could not read. The stub hands back a black
    # frame, every slot of which looks "occupied", so without this the suite
    # quietly fills the user's own cache folder with junk — which it did.
    import paths as paths_module

    monkeypatch.setattr(paths_module, "CACHE_DIR", tmp_path / "cache")
    made = []

    # The time windows the tests below pass in look oddly small — 0.5 where a
    # real round is 30 seconds. That is deliberate, and they are all a quarter
    # of what they were: the throw loop is paced by the wall clock, and with
    # _sleep stubbed out just above it spins as fast as the CPU allows, so half
    # a second still runs the loop hundreds of times. Every time quantity was
    # scaled by the same factor, so the ratios the tests actually assert on —
    # the throwing window against the dump window, say — are unchanged. Took
    # this file from 53s to 17s.
    def build(screens, picks_at=None, throw_seconds=0,
              ends_after_throws=None, **kwargs):
        # Real rounds last 35 seconds and the loop waits them out. Tests that
        # care about throwing set throw_seconds; the rest skip straight past.
        monkeypatch.setattr(demon_parade, "ROUND_THROW_SECONDS", throw_seconds)
        monkeypatch.setattr(demon_parade, "ROUND_LIMIT_SECONDS", throw_seconds + 0.05)
        control = StubControl(screens, picks_at, ends_after_throws)
        w = DemonParadeWorker(hwnd=1, control=control, **kwargs)
        made.append(w)
        return w

    # The loop sleeps between throws and after every click; without this a
    # single round would take the best part of a minute.
    monkeypatch.setattr(DemonParadeWorker, "_sleep", lambda self, s: None)
    yield build
    for w in made:
        w.stop()
        if w.ident is not None:
            w.join(timeout=3)


def run(w, seconds=2.0):
    w.start()
    w.join(timeout=seconds)
    w.stop()
    w.join(timeout=2)


# ── configuration ───────────────────────────────────────────────────────────


def test_beans_per_throw_must_be_one_of_the_two_offered():
    with pytest.raises(ValueError, match="Beans per throw"):
        DemonParadeWorker(hwnd=1, beans=7, control=StubControl([ENTRY]))


def test_a_negative_round_count_is_refused():
    with pytest.raises(ValueError, match="negative"):
        DemonParadeWorker(hwnd=1, rounds=-1, control=StubControl([ENTRY]))


@pytest.mark.parametrize("beans, x", [(5, 360), (10, 520)])
def test_the_slider_target_matches_the_calibration(beans, x):
    """Read off the knob at each position on a live round; see geometry.py."""
    assert geometry.PARADE_SLIDER_X[beans] == x


# ── the screens ─────────────────────────────────────────────────────────────


def test_the_entry_screen_gets_one_press_of_enter(worker):
    w = worker([ENTRY, PICK])

    run(w, 0.25)

    assert w._control.clicks[0] == w._enter


def test_the_pick_screen_selects_before_starting(worker):
    """Start does nothing at all until a shikigami is chosen — a run that
    pressed Start first silently never began, and every later click landed
    back on the pick screen."""
    w = worker([PICK, ROUND])

    run(w, 0.25)

    assert w._control.clicks[0] in w._pick_points
    assert w._control.clicks[1] == w._start


def test_a_round_drags_the_slider_to_ten_beans(worker):
    w = worker([ROUND, RESULT], beans=10)

    run(w, 0.375)

    assert w._control.drags, "the slider was never touched"
    assert w._control.knob_x == geometry.PARADE_SLIDER_X[10]


def test_the_drag_starts_on_the_knob_where_it_actually_is(worker):
    """The slider ignores a press anywhere else. An earlier build assumed it
    could park the knob at the minimum first by pressing short of the track;
    the press did nothing, the drag then grabbed empty track, and the setting
    silently stayed at 5 for the whole run."""
    w = worker([ROUND, RESULT], beans=10)

    run(w, 0.375)

    start, _end = w._control.drags[0]
    middle = 360 - geometry.PARADE_KNOB_RADIUS
    assert abs(start[0] - middle) <= StubControl.GRAB_TOLERANCE, (
        "grabbed at %d, but the knob's middle was at %d" % (start[0], middle)
    )


def test_ten_is_reached_where_the_track_ends_further_right(worker):
    """BlueStacks stops the knob at about 544 where the PC stops at 520. Asked
    for 520 exactly, a knob at the top read as 24 px off and every round
    warned that ten could not be set."""
    class LongerTrack(StubControl):
        TOP = 544

    w = worker([ROUND, RESULT], beans=10)
    w._control.__class__ = LongerTrack

    run(w, 0.375)

    assert w._control.knob_x == 544
    assert len(w._control.drags) == 1


def test_a_slider_already_on_the_right_value_is_left_alone(worker):
    w = worker([ROUND, RESULT], beans=10)
    w._control.knob_x = geometry.PARADE_SLIDER_X[10]

    run(w, 0.375)

    assert w._control.drags == [], "dragged a slider that was already right"


def test_a_slider_that_will_not_move_is_reported(worker, caplog):
    """Silence here is what made the original bug invisible: the log said the
    beans were set and the game went on throwing five."""

    class Stuck(StubControl):
        def drag(self, start, end, **kwargs):
            self.drags.append((tuple(start), tuple(end)))   # never moves

    w = worker([ROUND, RESULT], beans=10)
    w._control.__class__ = Stuck

    with caplog.at_level("WARNING"):
        run(w, 0.5)

    assert "Could not set beans per throw" in caplog.text


def test_the_knob_is_read_on_the_gold_not_on_whatever_stands_beyond_it():
    """Live on BlueStacks at 1600x900: the slider sat at 5 and the log said
    "Beans per throw is 10 (already set)", round after round. The onmyoji in
    blue stands where the scan ends, and saturated-and-bright was all it took
    to count as gold, so his robe was read as the knob at the very top."""
    path = (Path(__file__).resolve().parent / "fixtures" / "demon_parade"
            / "emulator-slider-at-5.png")
    frame = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)

    control = StubControl([ROUND])
    control.client_height, control.client_width = frame.shape[:2]
    control.full_shot = lambda gray=False: frame
    w = DemonParadeWorker(hwnd=1, control=control)

    knob = w._find_knob() / w._geometry.scale[0]

    assert abs(knob - geometry.PARADE_SLIDER_X[5]) <= 2 * geometry.PARADE_SLIDER_TOLERANCE, knob


def test_five_beans_a_throw_lands_somewhere_else(worker):
    w = worker([ROUND, RESULT], beans=5)
    w._control.knob_x = geometry.PARADE_SLIDER_X[10]

    run(w, 0.375)

    assert w._control.knob_x == geometry.PARADE_SLIDER_X[5]


def test_the_throw_points_cover_the_whole_parade_band(worker):
    """Aimed fire scored no shards at all on a live round; a spray scored 26."""
    w = worker([ROUND])

    rows = {y for _x, y in w._throw_points}
    columns = {x for x, _y in w._throw_points}

    assert rows == set(geometry.PARADE_THROW_ROWS), "only one height is covered"
    assert len(columns) >= 8, "too few positions across the bridge: %d" % len(columns)


def test_successive_throws_move_along_the_band(worker):
    """Standing still would waste the spray on whatever happens to be there."""
    w = worker([ROUND] * 4 + [RESULT, ENTRY], throw_seconds=0.5)

    run(w, 0.75)

    throws = [c for c in w._control.clicks if c in w._throw_points]
    assert len(throws) > 2
    assert all(a != b for a, b in zip(throws, throws[1:])), "threw twice in a row at one spot"
    assert len({y for _x, y in throws}) == len(geometry.PARADE_THROW_ROWS)


def test_the_result_screen_is_counted_once_and_dismissed(worker):
    w = worker(PLAYED_A_ROUND)

    run(w, 0.5)

    assert w.progress == 1
    assert w._dismiss in w._control.clicks


def test_an_unknown_screen_is_left_alone(worker):
    """Clicking blindly on a screen the loop does not know is how a bot ends
    up somewhere expensive, like the summon room."""
    w = worker([UNKNOWN])

    run(w, 0.2)

    assert w._control.clicks == []


# ── stopping ────────────────────────────────────────────────────────────────


def test_the_run_stops_after_the_requested_rounds(worker):
    w = worker(PLAYED_A_ROUND, rounds=1)
    finished = []
    w._on_finished = finished.append

    run(w, 0.5)

    assert w.progress == 1
    assert finished and "1 vòng" in finished[0]


def test_enter_that_never_works_is_read_as_running_out_of_tickets(worker):
    """The entry screen staying put press after press is what running dry
    looks like from here; there is no counter to read."""
    w = worker([ENTRY])
    finished = []
    w._on_finished = finished.append

    run(w, 0.5)

    enters = [c for c in w._control.clicks if c == w._enter]
    assert len(enters) == demon_parade.ENTER_ATTEMPTS
    assert finished and "Hết vé" in finished[0]


def test_reaching_the_pick_screen_clears_the_out_of_tickets_count(worker):
    """Otherwise a long run would eventually mistake normal play for running
    dry, having pressed Enter more than the limit across many rounds."""
    w = worker([ENTRY, PICK])

    run(w, 0.25)

    assert w._enter_attempts == 0


def test_stopping_is_reported_as_stopped_not_finished(worker):
    w = worker([ROUND])
    finished = []
    w._on_finished = finished.append

    w.start()
    time.sleep(0.3)
    w.stop()
    w.join(timeout=3)

    assert not finished, "a stopped run announced itself as complete"


def test_the_control_is_closed_when_the_loop_ends(worker):
    w = worker(PLAYED_A_ROUND, rounds=1)

    run(w, 0.5)

    assert w._control.closed


def test_a_crash_is_reported_rather_than_swallowed(worker, monkeypatch):
    w = worker([ENTRY])
    errors = []
    w._on_error = errors.append
    monkeypatch.setattr(
        DemonParadeWorker, "_step",
        lambda self: (_ for _ in ()).throw(RuntimeError("hong roi")),
    )

    run(w, 0.25)

    assert errors and "hong roi" in errors[0]


def test_pausing_holds_the_loop_and_resuming_releases_it(worker):
    w = worker([ROUND])
    w.pause()
    w.start()
    time.sleep(0.25)
    parked = len(w._control.clicks)

    assert w.is_paused
    assert parked == 0, "a paused worker kept clicking"

    w.resume()
    time.sleep(0.3)
    assert not w.is_paused
    w.stop()
    w.join(timeout=3)


def test_a_result_screen_left_over_from_before_is_not_counted(worker):
    """Opening the task while a hand-played round's scroll is still up is
    ordinary. Counting it would make "stop after N" stop one short."""
    w = worker([RESULT, ENTRY])

    run(w, 0.25)

    assert w.progress == 0, "counted a round it never played"
    assert w._dismiss in w._control.clicks, "left the scroll in the way"


def test_a_round_this_loop_played_is_counted(worker):
    w = worker(PLAYED_A_ROUND)

    run(w, 0.5)

    assert w.progress == 1


def test_throwing_stops_promptly_when_the_result_appears(worker):
    """Every throw taken after the round ends is a tap on the result scroll,
    and the scroll closes on a tap anywhere. A live run checked only once per
    sweep of eighteen, dismissed its own result, found itself back at the entry
    screen with nothing to count, and spent a second ticket.
    """
    w = worker([ROUND, RESULT, ENTRY], throw_seconds=1.25, ends_after_throws=4)

    run(w, 0.75)

    throws = [c for c in w._control.clicks if c in w._throw_points]
    # One throw's grace: the check happens before each throw, so the round can
    # end in the gap and cost one more.
    assert len(throws) <= 5, (
        "kept throwing into the result screen: %d throws" % len(throws)
    )
    assert len(throws) < len(w._throw_points), "took a full sweep to notice"
    assert w.progress == 1, "the round it played was not counted"


def test_the_round_is_checked_before_every_single_throw(worker):
    """The result scroll closes on a tap anywhere, so a throw taken after the
    round ends destroys the very thing the loop is waiting to read. Checking
    every third throw — 1.8 seconds — lost the scroll on every live run and
    spent another ticket re-entering.

    The check shares its capture with the search for something to throw at, so
    doing it every time costs nothing extra.
    """
    w = worker([ROUND, RESULT, ENTRY], throw_seconds=1.25, ends_after_throws=1)

    run(w, 0.75)

    throws = [c for c in w._control.clicks if c in w._throw_points]
    assert len(throws) <= 2


# ── choosing a shikigami ────────────────────────────────────────────────────


def _candidate(column=1, taps=((600, 400), (600, 350))):
    return demon_parade.parade_pick.Candidate(
        column, 30000, 2.0, taps, np.ones((633, 1122), np.uint8))


def test_the_biggest_silhouette_is_picked_when_it_lights_up(worker, monkeypatch):
    """The boss most likely to be SSR/SP is chosen by silhouette size; the
    fixed spots are not touched when that works."""
    monkeypatch.setattr(demon_parade.parade_pick, "choose", lambda frame: _candidate())
    monkeypatch.setattr(demon_parade.parade_pick, "is_lit", lambda frame, c: True)
    w = worker([PICK, ROUND])

    run(w, 0.25)

    assert w._control.clicks[0] == w._geometry.point((600, 400))
    assert w._control.clicks[1] == w._start
    assert not any(c in w._pick_points for c in w._control.clicks[:2])


def test_a_silhouette_that_will_not_light_up_falls_back_to_the_fixed_spots(worker, monkeypatch):
    """A round with a blind pick still beats no round."""
    monkeypatch.setattr(demon_parade.parade_pick, "choose", lambda frame: _candidate())
    monkeypatch.setattr(demon_parade.parade_pick, "is_lit", lambda frame, c: False)
    w = worker([PICK, ROUND])

    run(w, 0.5)

    tapped = [w._geometry.point(t) for t in _candidate().taps]
    assert w._control.clicks[:2] == tapped
    assert any(c in w._pick_points for c in w._control.clicks)
    assert w._start in w._control.clicks


def test_a_pick_spot_that_misses_is_followed_by_another(worker):
    """The line-up changes every round and the figures differ in height, so one
    fixed spot lands in empty sky sooner or later — and empty sky *deselects*.
    """
    second = tuple(
        DemonParadeWorker(hwnd=1, control=StubControl([PICK]))._pick_points[1]
    )
    w = worker([PICK, PICK, PICK, ROUND], picks_at=second)

    run(w, 0.5)

    assert w._control.picked, "never managed to select anything"
    assert w._start in w._control.clicks, "gave up without starting"


def test_start_is_not_pressed_while_nothing_is_selected(worker):
    """Start is silently ignored with no selection. A build that pressed on
    regardless spent a whole run clicking it once every seven seconds."""
    w = worker([PICK], picks_at=(-1, -1))     # no spot ever works

    run(w, 0.5)

    assert w._start not in w._control.clicks


def test_every_pick_candidate_is_tried_before_giving_up(worker):
    w = worker([PICK], picks_at=(-1, -1))

    run(w, 0.5)

    tried = [c for c in w._control.clicks if c in w._pick_points]
    assert set(tried) == set(w._pick_points)


def test_throwing_stops_before_the_round_does(worker):
    """The last stretch of a round is left alone deliberately.

    Between any two end-of-round checks there is a throw, and a throw that
    lands on the result scroll closes it — the scroll goes on a tap anywhere.
    Two live runs lost a result that way and each spent an extra ticket
    re-entering. Checking more often narrows the window without closing it, so
    the loop stops throwing early instead and waits the rest out in silence.
    """
    # The counter reads 0 about nine seconds before Time's up; throwing stops
    # inside that. ROUND_THROW_SECONDS is only the cap when the 0 is never seen.
    assert demon_parade.LAST_FIGURE_THROW_SECONDS < 9, (
        "Time's up follows the last figure by ~9 s; throwing must stop before it"
    )
    assert demon_parade.ROUND_LIMIT_SECONDS > demon_parade.ROUND_THROW_SECONDS


def test_the_quiet_wait_does_not_click(worker, monkeypatch):
    """Whatever happens after the throwing window, no click may be posted."""
    w = worker([ROUND, RESULT, ENTRY])

    run(w, 0.5)

    throws = [c for c in w._control.clicks if c in w._throw_points]
    assert throws == [], "threw during the hands-off stretch"
    assert w.progress == 1, "the round was not counted"


# ── the shard tally ─────────────────────────────────────────────────────────


def test_shards_are_added_up_across_rounds(worker, monkeypatch):
    scrolls = iter([
        [("Koi", 3), ("Nurikabe", 4)],
        [("Koi", 2), ("Kusa", 5)],
    ])
    stub_scroll(monkeypatch, lambda frame, *scale: next(scrolls, []))
    w = worker(PLAYED_A_ROUND * 2, rounds=2)

    run(w, 0.75)

    assert w.shards == {"Kusa": 5, "Nurikabe": 4, "Koi": 5} or w.shards["Koi"] == 5
    assert sum(w.shards.values()) == 14


def test_the_tally_is_sorted_with_the_biggest_first(worker, monkeypatch):
    stub_scroll(monkeypatch, lambda frame, *scale: [("Koi", 1), ("Nurikabe", 9), ("Kusa", 4)])
    w = worker(PLAYED_A_ROUND, rounds=1)

    run(w, 0.5)

    assert list(w.shards) == ["Nurikabe", "Kusa", "Koi"]


def test_the_finish_message_names_what_was_won(worker, monkeypatch):
    stub_scroll(monkeypatch, lambda frame, *scale: [("Nurikabe", 4)])
    w = worker(PLAYED_A_ROUND, rounds=1)
    finished = []
    w._on_finished = finished.append

    run(w, 0.5)

    assert finished and "Nurikabe 4" in finished[0]
    assert "4 mảnh" in finished[0]


def test_an_ssr_is_counted_even_when_nothing_else_on_its_card_reads(worker, monkeypatch):
    """The parade is played for SSR and SP shards, and an SSR card is the one
    the scroll reader is worst at: its "x1" is too thin to read and its name is
    usually new. The letter's colour is all it takes to count it."""
    stub_scroll(monkeypatch, lambda frame, *scale: [
        (None, None, "SSR"), ("Koi", 3, "R"),
    ])
    w = worker(PLAYED_A_ROUND, rounds=1)

    run(w, 0.5)

    assert w.rare_hits == 1
    assert w.shards == {"Koi": 3}


def test_rare_hits_add_up_across_rounds(worker, monkeypatch):
    scrolls = iter([
        [("Kuzunoha", None, "SSR"), ("Koi", 3, "R")],
        [("Koi", 3, "R")],
        [(None, 1, "SSR"), (None, None, "SSR")],
    ])
    stub_scroll(monkeypatch, lambda frame, *scale: next(scrolls, []))
    w = worker(PLAYED_A_ROUND * 3, rounds=3)

    run(w, 1.0)

    assert w.rare_hits == 3


def test_the_finish_message_says_how_many_ssr_sp_were_won(worker, monkeypatch):
    stub_scroll(monkeypatch, lambda frame, *scale: [
        ("Nurikabe", 4, "N"), ("Kuzunoha", None, "SSR"),
    ])
    w = worker(PLAYED_A_ROUND, rounds=1)
    finished = []
    w._on_finished = finished.append

    run(w, 0.5)

    assert finished and "SSR/SP: 1" in finished[0]


def test_the_finish_message_says_so_when_no_ssr_sp_came(worker, monkeypatch):
    """Zero is the answer most rounds give, and it is still the number the
    player wants to see."""
    stub_scroll(monkeypatch, lambda frame, *scale: [("Nurikabe", 4, "N")])
    w = worker(PLAYED_A_ROUND, rounds=1)
    finished = []
    w._on_finished = finished.append

    run(w, 0.5)

    assert finished and "SSR/SP: 0" in finished[0]


def test_each_card_in_the_round_log_carries_its_rarity(worker, monkeypatch, caplog):
    stub_scroll(monkeypatch, lambda frame, *scale: [
        ("Koi", 3, "R"), (None, None, "SSR"), ("Mystery", 2, None),
    ])
    w = worker(PLAYED_A_ROUND, rounds=1)

    with caplog.at_level("INFO", logger="demon_parade"):
        run(w, 0.5)

    line = next(r.getMessage() for r in caplog.records
                if r.getMessage().startswith("Round 1 shards:"))
    assert "[R] Koi x3" in line
    assert "[SSR] ? x?" in line
    assert "[?] Mystery x2" in line
    assert line.endswith("SSR/SP: 1")


def test_a_round_with_no_shards_still_counts_as_played(worker, monkeypatch):
    """"Pact shards not received yet." is an ordinary outcome, not a failure."""
    stub_scroll(monkeypatch, lambda frame, *scale: [])
    w = worker(PLAYED_A_ROUND, rounds=1)

    run(w, 0.5)

    assert w.progress == 1
    assert w.shards == {}


def test_an_unreadable_card_does_not_lose_the_round(worker, monkeypatch):
    """The tally is a nicety; the loop's job is to keep playing."""
    stub_scroll(monkeypatch, lambda frame, *scale: [(None, 4), ("Koi", None)])
    w = worker(PLAYED_A_ROUND, rounds=1)

    run(w, 0.5)

    assert w.progress == 1
    assert w.shards == {}
    assert w._unreadable == 2


def test_a_scroll_that_cannot_be_captured_does_not_crash_the_run(worker, monkeypatch):
    def boom(frame, *scale):
        raise RuntimeError("hong anh")

    stub_scroll(monkeypatch, boom)
    w = worker(PLAYED_A_ROUND, rounds=1)
    errors = []
    w._on_error = errors.append

    run(w, 0.5)

    assert not errors
    assert w.progress == 1


def test_unreadable_cards_are_saved_for_labelling(worker, monkeypatch, tmp_path):
    """There are hundreds of shikigami and the library starts with seven, so
    most of what a real run sees is new. Saving the crop is what lets the
    library grow instead of the information vanishing with the scroll."""
    import paths as paths_module

    monkeypatch.setattr(paths_module, "CACHE_DIR", tmp_path)
    stub_scroll(monkeypatch, lambda frame, *scale: [(None, 4)])
    monkeypatch.setattr(
        demon_parade.parade_results, "unknown_crops",
        lambda frame, *scale: {"name-0": np.zeros((10, 30, 3), dtype=np.uint8)},
    )
    w = worker(PLAYED_A_ROUND, rounds=1)

    run(w, 0.5)

    saved = list((tmp_path / "parade-unknown").glob("*.png"))
    assert saved, "nothing was kept to label"


def test_a_fully_readable_round_saves_nothing(worker, monkeypatch, tmp_path):
    import paths as paths_module

    monkeypatch.setattr(paths_module, "CACHE_DIR", tmp_path)
    # Rarity included: a card whose letter could not be placed is not fully
    # read, and is kept — that is how the first SP gets captured.
    stub_scroll(monkeypatch, lambda frame, *scale: [("Koi", 3, "R")])
    called = []
    monkeypatch.setattr(
        demon_parade.parade_results, "unknown_crops",
        lambda frame, *scale: called.append(1) or {},
    )
    w = worker(PLAYED_A_ROUND, rounds=1)

    run(w, 0.5)

    assert called == [], "went looking for unknowns when everything was read"


def test_the_suite_never_writes_into_the_real_cache(worker, monkeypatch):
    """It did: a black stub frame looks like eight occupied card slots, and the
    crops landed in the user's own cache directory."""
    import paths as paths_module

    stub_scroll(monkeypatch, lambda frame, *scale: [(None, None)])
    w = worker(PLAYED_A_ROUND, rounds=1)

    run(w, 0.5)

    assert "tmp" in str(paths_module.CACHE_DIR).lower() or not str(
        paths_module.CACHE_DIR
    ).startswith(str(Path(__file__).resolve().parents[1]))


# ── aiming at what is actually there ────────────────────────────────────────


def test_throws_go_where_the_figures_are(worker, monkeypatch):
    """Where a bean lands decides what it is worth. A round spent throwing at
    an empty patch of sky came back with one shikigami and 4 shards, against
    six shikigami and 18 shards for the same throws put on the parade."""
    spots = [(300, 400), (700, 430)]
    blank = np.zeros((40, 40, 3), dtype=np.uint8)
    monkeypatch.setattr(
        DemonParadeWorker, "_learn_background", lambda self: "a background"
    )
    monkeypatch.setattr(
        DemonParadeWorker, "_figures",
        lambda self, f, b: [(x, y, 1000, blank) for x, y in spots],
    )
    w = worker([ROUND] * 6 + [RESULT, ENTRY], throw_seconds=0.5)

    run(w, 0.75)

    thrown = [c for c in w._control.clicks if c in spots]
    assert thrown, "nothing was thrown at the figures"
    assert set(thrown) == set(spots), "only ever threw at one of them"


def test_a_frame_with_nothing_in_it_falls_back_to_the_spray(worker, monkeypatch):
    """Better a blind spray than no throws at all."""
    monkeypatch.setattr(
        DemonParadeWorker, "_learn_background", lambda self: "a background"
    )
    monkeypatch.setattr(DemonParadeWorker, "_figures", lambda self, f, b: [])
    w = worker([ROUND] * 6 + [RESULT, ENTRY], throw_seconds=0.5)

    run(w, 0.75)

    assert [c for c in w._control.clicks if c in w._throw_points]


def test_a_background_that_cannot_be_learnt_still_throws(worker, monkeypatch):
    monkeypatch.setattr(DemonParadeWorker, "_learn_background", lambda self: None)
    w = worker([ROUND] * 6 + [RESULT, ENTRY], throw_seconds=0.5)

    run(w, 0.75)

    assert [c for c in w._control.clicks if c in w._throw_points]


def test_figures_outside_the_parade_band_are_ignored(worker):
    """The timer at the top and the bean counter at the bottom both change, and
    neither is a shikigami."""
    import numpy as np

    w = worker([ROUND])
    background = np.zeros((633, 1122, 3), dtype=np.uint8)
    frame = background.copy()
    frame[20:80, 500:600] = 255        # the timer, above the band
    frame[560:610, 200:300] = 255      # the bean counter, below it
    frame[300:420, 400:520] = 255      # a shikigami, inside it

    found = w._figures(frame, background)

    assert len(found) == 1
    assert 300 <= found[0][1] <= 420


def test_the_pause_between_throws_accounts_for_the_looking(worker, monkeypatch):
    """Looking for a target costs time, and a flat pause on top of it throws
    away throws. A live round dropped from 33 to 24 that way — which cost more
    beans unthrown than aiming won back."""
    slept = []
    monkeypatch.setattr(DemonParadeWorker, "_sleep", lambda self, s: slept.append(s))
    monkeypatch.setattr(
        DemonParadeWorker, "_learn_background", lambda self: "a background"
    )

    def slow_figures(self, frame, background):
        time.sleep(demon_parade.THROW_INTERVAL_SECONDS + 0.05)
        return [(300, 400)]

    monkeypatch.setattr(DemonParadeWorker, "_figures", slow_figures)
    w = worker([ROUND, ROUND, RESULT, ENTRY], throw_seconds=0.25)

    run(w, 1)

    throw_pauses = [s for s in slept if 0 < s <= demon_parade.THROW_INTERVAL_SECONDS]
    assert 0.0 in slept or not throw_pauses, (
        "still paused a full interval after work that already took longer: %s" % slept[:6]
    )


@pytest.mark.parametrize("capture, is_in", [
    ("round-counter-0.jpg", True),
    ("round-counter-2.jpg", False),
])
def test_the_last_figure_is_known_by_the_counter_reading_zero(capture, is_in):
    """The number at the top counts the shikigami still to come; it reaches 0
    as the 36th walks in. Read on live BlueStacks frames."""
    path = Path(__file__).resolve().parent / "fixtures" / "demon_parade" / capture
    frame = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
    w = DemonParadeWorker(hwnd=1, control=StubControl([ROUND]))

    assert w._last_figure_is_in(frame) is is_in


def test_beans_are_paced_across_the_parade(worker, monkeypatch):
    """Ten a throw is 25 throws, and an empty purse ends the round — live, a
    dozen figures were still to come when it did. So until the last figure is
    in, one throw waits PACED_THROW_SECONDS for the next."""
    slept = []
    monkeypatch.setattr(DemonParadeWorker, "_sleep", lambda self, s: slept.append(s))
    monkeypatch.setattr(DemonParadeWorker, "_learn_background", lambda self: "bg")
    monkeypatch.setattr(DemonParadeWorker, "_figures", lambda self, f, b: [(300, 400, 900, None)])
    monkeypatch.setattr(DemonParadeWorker, "_choose", lambda self, t, s: ((300, 400), "unknown"))
    monkeypatch.setattr(demon_parade, "DUMP_LAST_SECONDS", 0)
    w = worker([ROUND, ROUND, ROUND, RESULT, ENTRY], throw_seconds=0.25)

    run(w, 1)

    assert any(demon_parade.THROW_INTERVAL_SECONDS < s <= demon_parade.PACED_THROW_SECONDS
               for s in slept), slept[:8]


def test_throwing_stops_soon_after_the_last_figure_comes_in(worker, monkeypatch, caplog):
    """Time's up follows about nine seconds after the counter reads 0, and a
    throw that lands on the result scroll closes it."""
    monkeypatch.setattr(DemonParadeWorker, "_learn_background", lambda self: "bg")
    monkeypatch.setattr(DemonParadeWorker, "_figures", lambda self, f, b: [])
    monkeypatch.setattr(DemonParadeWorker, "_last_figure_is_in", lambda self, frame: True)
    monkeypatch.setattr(demon_parade, "LAST_FIGURE_THROW_SECONDS", 0.05)
    w = worker([ROUND], throw_seconds=5)

    with caplog.at_level("INFO", logger="demon_parade"):
        run(w, 0.5)

    assert "last figure is in" in caplog.text
    assert "waiting it out" in caplog.text, "kept throwing after the last figure's window"


def test_the_figure_finder_still_works_for_when_it_is_wanted(worker):
    import numpy as np

    w = worker([ROUND])
    background = np.zeros((633, 1122, 3), dtype=np.uint8)
    frame = background.copy()
    frame[300:420, 400:520] = 255

    assert len(w._figures(frame, background)) == 1


# ── choosing by rarity ──────────────────────────────────────────────────────


def _figure(x, y, tint):
    """A figure at (x, y) painted one flat colour, so its rarity is decidable."""
    cut = np.zeros((60, 40, 3), dtype=np.uint8)
    cut[10:50, 5:35] = tint
    return (x, y, 1500, cut)


def test_the_rare_figure_on_screen_is_the_one_thrown_at(worker, monkeypatch):
    """The whole reason for aiming. A rare shikigami's shards are worth more
    than a common one's, and where the bean lands decides which you get."""
    import parade_figures

    # BGR: the rare one is painted red, so channel 2 is what tells them apart.
    common = _figure(200, 400, (200, 40, 40))
    rare = _figure(800, 420, (40, 40, 200))
    monkeypatch.setattr(
        DemonParadeWorker, "_learn_background", lambda self: "a background"
    )
    monkeypatch.setattr(
        DemonParadeWorker, "_figures", lambda self, f, b: [common, rare]
    )
    monkeypatch.setattr(
        parade_figures, "rarity_of",
        lambda cut: "SSR" if cut[20, 10, 2] > 100 else "N",
    )
    # Never reach the end-of-round dump, or the common one becomes fair game
    # and the test would pass without proving anything about aiming.
    monkeypatch.setattr(demon_parade, "DUMP_LAST_SECONDS", 0)
    w = worker([ROUND] * 6 + [RESULT, ENTRY], throw_seconds=0.5)

    run(w, 0.75)

    thrown = [c for c in w._control.clicks if c in ((200, 400), (800, 420))]
    assert thrown, "nothing was thrown"
    assert all(c == (800, 420) for c in thrown), (
        "threw at the common one while a rare one was on screen: %s" % thrown
    )


def _all_one_rarity(monkeypatch, rarity, spots):
    import parade_figures

    monkeypatch.setattr(
        DemonParadeWorker, "_learn_background", lambda self: "a background"
    )
    monkeypatch.setattr(
        DemonParadeWorker, "_figures",
        lambda self, f, b: [_figure(x, y, (80, 80, 80)) for x, y in spots],
    )
    monkeypatch.setattr(parade_figures, "rarity_of", lambda cut: rarity)


def test_beans_are_held_while_only_common_figures_are_about(worker, monkeypatch):
    """The point of the whole design.

    A round holds 25 throws at 10 beans each. Spent on whoever walks past
    first, there is nothing left when an SSR arrives — so while the round still
    has time to bring one, the loop throws nothing at all.
    """
    spots = [(200, 400), (500, 410), (800, 420)]
    _all_one_rarity(monkeypatch, "N", spots)
    # Never reach the end-of-round dump, so only the holding is under test.
    monkeypatch.setattr(demon_parade, "DUMP_LAST_SECONDS", 0)
    w = worker([ROUND] * 8 + [RESULT, ENTRY], throw_seconds=0.75)

    run(w, 1)

    thrown = [c for c in w._control.clicks if c in spots]
    assert not thrown, "spent beans on common figures with the round still young: %s" % thrown


def test_an_unrecognised_figure_does_get_a_bean(worker, monkeypatch):
    """Unknown is a target, and that is the point rather than an oversight.

    Rare shikigami appear in one round and never again, so the library can
    never hold the next one. Commons repeat and can be learned. Whatever is
    left after ruling out the commons is where the rare figures are.
    """
    spots = [(200, 400), (800, 420)]
    _all_one_rarity(monkeypatch, None, spots)
    monkeypatch.setattr(demon_parade, "DUMP_LAST_SECONDS", 0)
    w = worker([ROUND] * 8 + [RESULT, ENTRY], throw_seconds=0.75)

    run(w, 1)

    thrown = [c for c in w._control.clicks if c in spots]
    assert thrown, "passed over every figure the library could not name"


def test_leftover_beans_are_spent_before_the_round_ends(worker, monkeypatch):
    """Beans do not carry over, so holding them to the last second wastes them.

    The ticket is paid either way — a common shikigami's shards beat nothing.
    """
    spots = [(200, 400), (500, 410), (800, 420)]
    _all_one_rarity(monkeypatch, "N", spots)
    # Well past the throwing window, so the loop is spending from the start.
    monkeypatch.setattr(demon_parade, "DUMP_LAST_SECONDS", 24.75)
    w = worker([ROUND] * 8 + [RESULT, ENTRY], throw_seconds=0.75)

    run(w, 1)

    thrown = [c for c in w._control.clicks if c in spots]
    assert thrown, "let the round end with beans unspent"
    assert len(set(thrown)) > 1, "stood still and threw at one spot: %s" % thrown


def test_a_rarity_lookup_that_throws_does_not_stop_the_round(worker, monkeypatch):
    import parade_figures

    monkeypatch.setattr(
        DemonParadeWorker, "_learn_background", lambda self: "a background"
    )
    monkeypatch.setattr(
        DemonParadeWorker, "_figures", lambda self, f, b: [_figure(300, 400, (9, 9, 9))]
    )

    def boom(cut):
        raise RuntimeError("hong")

    monkeypatch.setattr(parade_figures, "rarity_of", boom)
    w = worker([ROUND] * 4 + [RESULT, ENTRY], throw_seconds=0.375)
    errors = []
    w._on_error = errors.append

    run(w, 0.75)

    assert not errors
    assert (300, 400) in w._control.clicks


# ── following the boss ──────────────────────────────────────────────────────


def test_beans_go_at_the_boss_and_nowhere_else_while_it_is_followed(worker, monkeypatch):
    """The boss is what the pick was for; a bean at anyone else is a bean the
    boss does not get."""
    slept = []
    monkeypatch.setattr(DemonParadeWorker, "_sleep", lambda self, s: slept.append(s))
    monkeypatch.setattr(DemonParadeWorker, "_learn_background", lambda self: "bg")
    monkeypatch.setattr(DemonParadeWorker, "_figures", lambda self, f, b: [(300, 400, 900, None)])
    monkeypatch.setattr(DemonParadeWorker, "_choose", lambda self, t, s: ((300, 400), "unknown"))
    monkeypatch.setattr(DemonParadeWorker, "_boss_sighting",
                        lambda self, frame, background, following: ((600, 300), [(600, 330)]))
    # No fliers here; looking for them would also eat into the paced sleep.
    monkeypatch.setattr(demon_parade.parade_boss, "helpers", lambda frame: [])
    w = worker([ROUND] * 6 + [RESULT, ENTRY], throw_seconds=0.25)

    run(w, 1)

    thrown = [c for c in w._control.clicks if c != tuple(w._dismiss)]
    assert thrown, "nothing was thrown"
    assert (300, 400) not in thrown, "threw at a figure that was not the boss"
    # Ahead of the figure, which walks left.
    assert all(x < 600 and y == 330 for x, y in thrown), thrown
    assert demon_parade.BOSS_THROW_SECONDS in slept


def test_throwing_goes_back_to_the_parade_when_no_boss_is_seen(worker, monkeypatch):
    monkeypatch.setattr(DemonParadeWorker, "_learn_background", lambda self: "bg")
    monkeypatch.setattr(DemonParadeWorker, "_figures", lambda self, f, b: [(300, 400, 900, None)])
    monkeypatch.setattr(DemonParadeWorker, "_choose", lambda self, t, s: ((300, 400), "unknown"))
    monkeypatch.setattr(DemonParadeWorker, "_boss_sighting",
                        lambda self, frame, background, following: (None, [(600, 330)]))
    w = worker([ROUND] * 6 + [RESULT, ENTRY], throw_seconds=0.25)

    run(w, 1)

    assert (300, 400) in w._control.clicks


def test_a_sighting_that_cannot_be_read_does_not_stop_the_round(worker):
    """The stub's background is not an image at all; the round goes on."""
    w = worker([ROUND])

    assert w._boss_sighting(np.zeros((633, 1122, 3), np.uint8), None) == (None, [])


def test_boss_cards_are_counted_from_the_scroll(worker, monkeypatch, caplog):
    stub_scroll(monkeypatch, lambda frame, *scale: [("Koi", 3, "R"), ("Kappa", 6, "R")])
    monkeypatch.setattr(demon_parade.parade_results, "boss_cards", lambda frame: 2)
    w = worker(PLAYED_A_ROUND * 2, rounds=2)

    with caplog.at_level("INFO", logger="demon_parade"):
        run(w, 1.0)

    assert w.boss_hits == 4
    line = next(r.getMessage() for r in caplog.records
                if r.getMessage().startswith("Round 1 shards:"))
    assert "boss cards: 2" in line


def test_the_finish_message_says_how_often_the_boss_was_hit(worker, monkeypatch):
    stub_scroll(monkeypatch, lambda frame, *scale: [("Koi", 3, "R")])
    monkeypatch.setattr(demon_parade.parade_results, "boss_cards", lambda frame: 1)
    w = worker(PLAYED_A_ROUND, rounds=1)
    finished = []
    w._on_finished = finished.append

    run(w, 0.5)

    assert finished and "quỷ vương: 1" in finished[0]


# ── Freeze ──────────────────────────────────────────────────────────────────


FIXTURES = Path(__file__).parent / "fixtures" / "demon_parade"


def _best(template_path, fixture):
    from game_control import read_image

    frame = read_image(str(FIXTURES / fixture))
    return float(cv2.matchTemplate(frame, read_image(template_path), cv2.TM_CCOEFF_NORMED).max())


def test_freeze_frosts_the_slider_past_recognition():
    """Why the frozen template exists: under the frost the plain one scores
    0.71, and the pick screen scores 0.67 — no threshold sits between them."""
    assert _best(demon_parade.TPL_IN_ROUND, "round-frozen.jpg") < demon_parade.DEFAULT_ACCURACY
    assert _best(demon_parade.TPL_IN_ROUND_FROZEN, "round-frozen.jpg") >= demon_parade.DEFAULT_ACCURACY


@pytest.mark.parametrize("fixture", ["pick.png", "entry.png", "no-shards.png",
                                     "result-two-boss-cards.jpg", "round-counter-2.jpg"])
def test_the_frozen_slider_is_not_seen_anywhere_else(fixture):
    assert _best(demon_parade.TPL_IN_ROUND_FROZEN, fixture) < demon_parade.DEFAULT_ACCURACY


def test_a_frozen_round_is_still_a_round(worker, monkeypatch):
    """Freeze holds the parade still for about nine seconds — the easiest
    moment of the round to hit anything — and its frost hides the slider.
    Taken for the end of the round, it stopped the throwing and relearnt the
    background with the figures standing in it."""
    monkeypatch.setattr(DemonParadeWorker, "_learn_background", lambda self: "bg")
    monkeypatch.setattr(DemonParadeWorker, "_figures", lambda self, f, b: [(300, 400, 900, None)])
    monkeypatch.setattr(DemonParadeWorker, "_choose", lambda self, t, s: ((300, 400), "unknown"))
    monkeypatch.setattr(demon_parade, "ROUND_GONE_SECONDS", 0)
    w = worker([ROUND] + [FROZEN] * 40 + [RESULT, ENTRY], throw_seconds=0.25)

    run(w, 1)

    assert w._control.clicks.count((300, 400)) > 5


def test_a_start_that_did_not_take_is_pressed_again_without_choosing_again(worker, monkeypatch):
    """Once chosen, the boss is lit up in colour and no longer a silhouette, so
    measuring again leaves it out — live, a 1.6x boss was swapped for a 0.7x one
    because Start had not taken the first time."""
    chosen = []

    def pick(self, choice):
        chosen.append(1)
        self._control.click((100, 300))      # selects, on the stub's pick screen
        return True

    monkeypatch.setattr(DemonParadeWorker, "_pick_the_biggest", pick)
    w = worker([ENTRY, PICK, PICK, PICK, UNKNOWN])

    run(w, 0.5)

    assert len(chosen) == 1
    assert w._control.clicks.count(tuple(w._start)) == 3



# ── rerolling a line-up with no likely SSR/SP ───────────────────────────────


def _lineup(relative):
    return demon_parade.parade_pick.Candidate(
        1, 30000, relative, ((600, 400),), np.ones((633, 1122), np.uint8))


def test_a_lineup_with_nothing_big_is_quit_without_playing(worker, monkeypatch):
    """Only about one line-up in sixteen offers an SSR/SP, and it is nearly
    always the biggest silhouette by a distance. Playing the rest costs a
    minute each and cannot yield an SSR/SP shard."""
    monkeypatch.setattr(demon_parade.parade_pick, "choose", lambda frame: _lineup(1.3))
    w = worker([PICK, UNKNOWN], reroll_below=1.8)

    run(w, 0.25)

    clicks = w._control.clicks
    assert clicks[:2] == [w._back, w._quit_ok]
    assert w._start not in clicks
    assert w.rerolls == 1


def test_a_lineup_with_a_big_one_is_played(worker, monkeypatch):
    monkeypatch.setattr(demon_parade.parade_pick, "choose", lambda frame: _lineup(2.4))
    monkeypatch.setattr(demon_parade.parade_pick, "is_lit", lambda frame, c: True)
    w = worker([PICK, ROUND], reroll_below=1.8)

    run(w, 0.25)

    assert w._back not in w._control.clicks
    assert w._start in w._control.clicks
    assert w.rerolls == 0


def test_every_lineup_is_played_when_rerolling_is_off(worker, monkeypatch):
    monkeypatch.setattr(demon_parade.parade_pick, "choose", lambda frame: _lineup(0.8))
    monkeypatch.setattr(demon_parade.parade_pick, "is_lit", lambda frame, c: True)
    w = worker([PICK, ROUND])

    run(w, 0.25)

    assert w._start in w._control.clicks


def test_a_lineup_that_cannot_be_measured_is_played(worker, monkeypatch):
    """No measurement is no evidence either way; a blind round beats a ticket
    thrown away on a guess."""
    monkeypatch.setattr(demon_parade.parade_pick, "choose", lambda frame: None)
    w = worker([PICK, ROUND], reroll_below=1.8)

    run(w, 0.5)

    assert w._back not in w._control.clicks
    assert w._start in w._control.clicks


def test_after_a_reroll_the_town_lantern_leads_back_in(worker, monkeypatch):
    """Quitting the pick screen lands in the town, not on the parade."""
    monkeypatch.setattr(demon_parade.parade_pick, "choose", lambda frame: _lineup(1.0))
    w = worker([PICK, TOWN, UNKNOWN], reroll_below=1.8)

    run(w, 0.5)

    assert w._control.clicks[2] == (10, 20), "did not press the lantern"


def test_the_town_is_left_alone_when_no_reroll_sent_us_there(worker):
    """The town flashes by between ordinary rounds too, and the player may be
    there on purpose."""
    w = worker([TOWN])

    run(w, 0.25)

    assert w._control.clicks == []


def test_reaching_the_entry_screen_ends_the_reroll(worker, monkeypatch):
    monkeypatch.setattr(demon_parade.parade_pick, "choose", lambda frame: _lineup(1.0))
    w = worker([PICK, ENTRY, TOWN, UNKNOWN], reroll_below=1.8, rounds=5)

    run(w, 0.5)

    assert (10, 20) not in w._control.clicks[2:], "pressed the lantern after the reroll was over"


def test_the_finish_message_says_how_many_lineups_were_rerolled(worker, monkeypatch):
    monkeypatch.setattr(demon_parade.parade_pick, "choose", lambda frame: _lineup(1.0))
    w = worker([PICK, ENTRY], reroll_below=1.8, rounds=0)
    w._control.clicking = True
    finished = []
    w._on_finished = finished.append
    # One reroll, then the entry screen stops answering: out of tickets.
    monkeypatch.setattr(demon_parade, "ENTER_ATTEMPTS", 0)

    run(w, 0.5)

    assert finished and "đổi lượt: 1" in finished[0]


def test_a_negative_reroll_threshold_is_refused():
    with pytest.raises(ValueError):
        DemonParadeWorker(hwnd=1, control=StubControl([ENTRY]), reroll_below=-1)


@pytest.mark.parametrize("fixture", ["town-lanterns.png", "town-lanterns-swaying.png"])
def test_the_demon_parade_lantern_is_found_in_the_town(fixture):
    """It sways, which costs the match up to a quarter of its score."""
    assert _best(demon_parade.TPL_TOWN_LANTERN, fixture) >= demon_parade.TOWN_LANTERN_ACCURACY


@pytest.mark.parametrize("fixture", ["entry.png", "pick.png", "round-counter-2.jpg",
                                     "round-frozen.jpg", "result-two-boss-cards.jpg"])
def test_the_lantern_is_not_seen_anywhere_else(fixture):
    assert _best(demon_parade.TPL_TOWN_LANTERN, fixture) < demon_parade.TOWN_LANTERN_ACCURACY


@pytest.mark.parametrize("stored", [{}, {"reroll": "1.8x"}])
def test_rerolling_is_not_offered_and_every_lineup_is_played(monkeypatch, stored):
    """The size threshold was too hard to explain, so the setting was taken out.
    A value saved by an older version must not switch rerolling back on."""
    import tasks

    seen = []
    monkeypatch.setattr(demon_parade, "DemonParadeWorker", lambda **kw: seen.append(kw))
    spec = tasks.get("beans")
    config = tasks.merge_layers(tasks.app_defaults(), spec.coerce(stored))
    spec.build(hwnd=1, control=None, config=config, on_finished=None, on_error=None)

    assert "reroll" not in {f.key for f in spec.fields}
    assert seen[-1].get("reroll_below", 0.0) == 0.0


def test_with_rerolling_on_beans_are_saved_for_the_boss(worker, monkeypatch):
    """Rerolling means only the boss matters. Live, beans paced at the others
    were mostly gone by the time a late boss walked in."""
    monkeypatch.setattr(DemonParadeWorker, "_learn_background", lambda self: "bg")
    monkeypatch.setattr(DemonParadeWorker, "_figures", lambda self, f, b: [(300, 400, 900, None)])
    monkeypatch.setattr(DemonParadeWorker, "_choose", lambda self, t, s: ((300, 400), "unknown"))
    monkeypatch.setattr(demon_parade, "DUMP_LAST_SECONDS", 0)
    w = worker([ROUND] * 6 + [RESULT, ENTRY], throw_seconds=0.25, reroll_below=1.8)

    run(w, 1)

    assert (300, 400) not in w._control.clicks


def test_with_rerolling_on_the_leftovers_still_go_once_the_last_figure_is_in(worker, monkeypatch):
    monkeypatch.setattr(DemonParadeWorker, "_learn_background", lambda self: "bg")
    monkeypatch.setattr(DemonParadeWorker, "_figures", lambda self, f, b: [(300, 400, 900, None)])
    monkeypatch.setattr(DemonParadeWorker, "_choose", lambda self, t, s: ((300, 400), "leftover"))
    monkeypatch.setattr(DemonParadeWorker, "_last_figure_is_in", lambda self, frame: True)
    w = worker([ROUND] * 6 + [RESULT, ENTRY], throw_seconds=0.25, reroll_below=1.8)

    run(w, 1)

    assert (300, 400) in w._control.clicks


# ── recognising a known SSR/SP while rerolling ──────────────────────────────


def _column(column, relative):
    return demon_parade.parade_pick.Candidate(
        column, 20000, relative, ((150 + 300 * column, 400),), np.ones((633, 1122), np.uint8))


def _survey(monkeypatch, lineup, rare_column=None, saved=None):
    monkeypatch.setattr(demon_parade.parade_pick, "choose",
                        lambda frame: max(lineup, key=lambda c: c.relative))
    monkeypatch.setattr(demon_parade.parade_pick, "candidates", lambda frame: lineup)
    monkeypatch.setattr(demon_parade.parade_pick, "is_lit", lambda frame, c: True)
    monkeypatch.setattr(demon_parade.parade_rare, "best_match",
                        lambda lit, c: (0.9, "known") if c.column == rare_column else (0.5, "other"))
    monkeypatch.setattr(demon_parade.parade_rare, "save",
                        lambda lit, c: (saved if saved is not None else []).append(c.column))


def test_a_known_ssr_of_ordinary_size_is_played_not_rerolled(worker, monkeypatch):
    """Several SSR/SP stand no bigger than the commons beside them; size alone
    quit six line-ups that held one."""
    _survey(monkeypatch, [_column(0, 1.0), _column(1, 1.3), _column(2, 0.9)], rare_column=2)
    w = worker([PICK, ROUND], reroll_below=1.8)

    run(w, 0.25)

    clicks = w._control.clicks
    assert w._back not in clicks
    start = clicks.index(w._start)
    assert clicks[start - 1] == w._geometry.point((750, 400)), "the known SSR/SP was not the one chosen"


def test_without_a_known_ssr_a_small_lineup_is_still_rerolled(worker, monkeypatch):
    _survey(monkeypatch, [_column(0, 1.0), _column(1, 1.3)], rare_column=None)
    w = worker([PICK, UNKNOWN], reroll_below=1.8)

    run(w, 0.25)

    clicks = w._control.clicks
    assert clicks[:2] == [w._geometry.point((150, 400)), w._geometry.point((450, 400))], "not every candidate was looked at"
    assert w._back in clicks and w._start not in clicks


def test_every_lit_candidate_is_kept_for_labelling(worker, monkeypatch):
    saved = []
    _survey(monkeypatch, [_column(0, 1.0), _column(1, 1.3), _column(2, 0.9)], saved=saved)
    w = worker([PICK, UNKNOWN], reroll_below=1.8)

    run(w, 0.25)

    assert saved == [0, 1, 2]


def test_no_candidate_is_tapped_through_when_rerolling_is_off(worker, monkeypatch):
    looked = []
    _survey(monkeypatch, [_column(0, 1.0), _column(1, 1.3)])
    monkeypatch.setattr(demon_parade.parade_rare, "best_match",
                        lambda lit, c: looked.append(c) or (0.0, None))
    w = worker([PICK, ROUND])

    run(w, 0.25)

    assert looked == []


# ── helper fliers: Assist Up, Got Beans ─────────────────────────────────────


ASSIST_AT, CHANCE_AT, BEANS_AT = (400, 200), (500, 210), (800, 180)
ALL_HELPERS = [("assist", ASSIST_AT), ("chance", CHANCE_AT), ("beans", BEANS_AT)]


def _helper_round(monkeypatch, sighting=(None, []), helpers=lambda frame: ALL_HELPERS):
    monkeypatch.setattr(DemonParadeWorker, "_learn_background", lambda self: "bg")
    monkeypatch.setattr(DemonParadeWorker, "_figures", lambda self, f, b: [])
    monkeypatch.setattr(DemonParadeWorker, "_choose", lambda self, t, s: (None, "held"))
    monkeypatch.setattr(DemonParadeWorker, "_boss_sighting",
                        lambda self, frame, background, following: sighting)
    monkeypatch.setattr(demon_parade.parade_boss, "helpers", helpers)
    monkeypatch.setattr(demon_parade, "HELPER_GAP_SECONDS", 0)
    monkeypatch.setattr(demon_parade, "GOT_BEANS_GAP_SECONDS", 0)


def test_assist_up_and_chance_up_get_a_bean_or_two_and_no_more(worker, monkeypatch):
    """One hit is all an Assist Up or Chance Up flier needs; the rest of the
    beans are the boss's."""
    _helper_round(monkeypatch)
    w = worker([ROUND] * 40 + [RESULT, ENTRY], throw_seconds=30)

    run(w, 1)

    clicks = w._control.clicks
    assert 1 <= clicks.count(ASSIST_AT) <= demon_parade.HELPER_THROWS
    assert 1 <= clicks.count(CHANCE_AT) <= demon_parade.HELPER_THROWS


def test_a_got_beans_flier_is_thrown_at_until_it_is_gone(worker, monkeypatch):
    """Live, one miss and the flier was left alone. It pays 40 beans for 10:
    keep throwing while it is in sight, and stop once a hit takes it away."""
    seen = {"frames": 0}

    def helpers(frame):
        seen["frames"] += 1
        return [("beans", BEANS_AT)] if seen["frames"] <= 5 else []

    _helper_round(monkeypatch, helpers=helpers)
    w = worker([ROUND] * 20 + [RESULT, ENTRY], throw_seconds=30)

    run(w, 1)

    assert w._control.clicks.count(BEANS_AT) == 5


def test_got_beans_throws_are_capped_if_the_label_never_goes(worker, monkeypatch):
    _helper_round(monkeypatch, helpers=lambda frame: [("beans", BEANS_AT)])
    w = worker([ROUND] * 40 + [RESULT, ENTRY], throw_seconds=30)

    run(w, 1)

    assert w._control.clicks.count(BEANS_AT) == demon_parade.GOT_BEANS_MAX_THROWS


def test_the_boss_comes_before_assist_up_and_chance_up(worker, monkeypatch):
    _helper_round(monkeypatch, sighting=((600, 300), [(600, 330)]),
                  helpers=lambda frame: [("assist", ASSIST_AT), ("chance", CHANCE_AT)])
    w = worker([ROUND] * 8 + [RESULT, ENTRY], throw_seconds=30)

    run(w, 1)

    assert ASSIST_AT not in w._control.clicks
    assert CHANCE_AT not in w._control.clicks


def test_an_invite_that_opens_mid_round_is_answered_while_throwing(worker, monkeypatch):
    """Live, a Wanted Quest invite sat over the stage for a whole round and
    hid the boss; nothing in the throwing loop looked for it."""
    asked = {"times": 0}

    def find_reply(control, layout, accept):
        asked["times"] += 1
        # Not there when the round starts; it opens a few looks later, and
        # only the round itself has it — so only the throwing loop can see it.
        return (700, 500) if asked["times"] == 3 and control.screen == ROUND else None

    monkeypatch.setattr(demon_parade.wanted_invite, "find_reply", find_reply)
    monkeypatch.setattr(demon_parade, "INVITE_CHECK_SECONDS", 0)
    _helper_round(monkeypatch, helpers=lambda frame: [])
    w = worker([ROUND] * 20 + [RESULT, ENTRY], throw_seconds=30)

    run(w, 1)

    assert (700, 500) in w._control.clicks


def test_got_beans_shares_throws_with_the_boss(worker, monkeypatch):
    """Both are on screen for seconds only: every other throw each."""
    _helper_round(monkeypatch, sighting=((600, 300), [(600, 330)]))
    w = worker([ROUND] * 8 + [RESULT, ENTRY], throw_seconds=30)

    run(w, 1)

    clicks = w._control.clicks
    beans = clicks.count(BEANS_AT)
    assert beans >= 2
    assert len(clicks) - beans >= beans - 1, "the boss still gets every other throw"
    assert ASSIST_AT not in clicks
