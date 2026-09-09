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

import numpy as np

import pytest

import demon_parade
import geometry
from demon_parade import DemonParadeWorker

ENTRY, PICK, ROUND, RESULT, UNKNOWN = "entry", "pick", "round", "result", "?"

# A round played through to its result screen: one entry per decision pass.
PLAYED_A_ROUND = [ROUND, RESULT, ENTRY]

SCREEN_TEMPLATE = {
    demon_parade.TPL_ENTER: ENTRY,
    demon_parade.TPL_PICK: PICK,
    demon_parade.TPL_IN_ROUND: ROUND,
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
        # Only a grab that lands on the knob moves it. Measured on the real
        # slider: a click on the track and a drag starting short of the knob
        # both left it exactly where it was.
        if abs(start[0] - self.knob_x) <= self.GRAB_TOLERANCE:
            self.knob_x = int(end[0])

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
    assert abs(start[0] - 360) <= StubControl.GRAB_TOLERANCE, (
        "grabbed at %d, but the knob was at 360" % start[0]
    )


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
    assert demon_parade.ROUND_THROW_SECONDS < 35, (
        "a round is 35 seconds; throwing must stop before it ends"
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
    monkeypatch.setattr(
        demon_parade.parade_results, "read_scroll",
        lambda frame, *scale: next(scrolls, []),
    )
    w = worker(PLAYED_A_ROUND * 2, rounds=2)

    run(w, 0.75)

    assert w.shards == {"Kusa": 5, "Nurikabe": 4, "Koi": 5} or w.shards["Koi"] == 5
    assert sum(w.shards.values()) == 14


def test_the_tally_is_sorted_with_the_biggest_first(worker, monkeypatch):
    monkeypatch.setattr(
        demon_parade.parade_results, "read_scroll",
        lambda frame, *scale: [("Koi", 1), ("Nurikabe", 9), ("Kusa", 4)],
    )
    w = worker(PLAYED_A_ROUND, rounds=1)

    run(w, 0.5)

    assert list(w.shards) == ["Nurikabe", "Kusa", "Koi"]


def test_the_finish_message_names_what_was_won(worker, monkeypatch):
    monkeypatch.setattr(
        demon_parade.parade_results, "read_scroll",
        lambda frame, *scale: [("Nurikabe", 4)],
    )
    w = worker(PLAYED_A_ROUND, rounds=1)
    finished = []
    w._on_finished = finished.append

    run(w, 0.5)

    assert finished and "Nurikabe 4" in finished[0]
    assert "4 mảnh" in finished[0]


def test_a_round_with_no_shards_still_counts_as_played(worker, monkeypatch):
    """"Pact shards not received yet." is an ordinary outcome, not a failure."""
    monkeypatch.setattr(
        demon_parade.parade_results, "read_scroll", lambda frame, *scale: []
    )
    w = worker(PLAYED_A_ROUND, rounds=1)

    run(w, 0.5)

    assert w.progress == 1
    assert w.shards == {}


def test_an_unreadable_card_does_not_lose_the_round(worker, monkeypatch):
    """The tally is a nicety; the loop's job is to keep playing."""
    monkeypatch.setattr(
        demon_parade.parade_results, "read_scroll",
        lambda frame, *scale: [(None, 4), ("Koi", None)],
    )
    w = worker(PLAYED_A_ROUND, rounds=1)

    run(w, 0.5)

    assert w.progress == 1
    assert w.shards == {}
    assert w._unreadable == 2


def test_a_scroll_that_cannot_be_captured_does_not_crash_the_run(worker, monkeypatch):
    def boom(frame, *scale):
        raise RuntimeError("hong anh")

    monkeypatch.setattr(demon_parade.parade_results, "read_scroll", boom)
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
    monkeypatch.setattr(
        demon_parade.parade_results, "read_scroll",
        lambda frame, *scale: [(None, 4)],
    )
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
    monkeypatch.setattr(
        demon_parade.parade_results, "read_scroll",
        lambda frame, *scale: [("Koi", 3)],
    )
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

    monkeypatch.setattr(
        demon_parade.parade_results, "read_scroll",
        lambda frame, *scale: [(None, None)],
    )
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
