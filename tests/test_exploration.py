"""The Exploration (Tham hiem chuong) loop.

Nothing here touches Windows: the capture, the clicks and the drags are stubbed,
so these run headless and never post input anywhere.

Four things are worth the space, and they are the four that cost something when
wrong:

* **A screen the loop does not recognise gets no input at all.** During a battle
  none of the ten templates match, and a loop that fell back to clicking a
  default point would be pressing into a fight — on a skill, on a shikigami,
  on whatever is under it. This is the one property that cannot be checked by
  looking at the app, because a stray click there usually does nothing visible.
* **An enemy badge is only clicked while the loop can see it is on the map.**
  The badge is small, plain artwork and it is exactly the kind of template that
  finds itself somewhere unrelated; the map check is what stops that mattering.
* **The sweep turns around.** A map that has run out of scroll in one direction
  looks identical to a map with nothing on it, and a loop that could not tell
  would sweep one way forever.
* **The templates still say what they were measured to say.** The truth table
  below is measured, not asserted from a reading of the artwork, and it is what
  every threshold in the module rests on.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

import exploration
import geometry
from exploration import ExplorationWorker

REFERENCE = geometry.REFERENCE_CLIENT_SIZE
RECORDINGS = Path(__file__).resolve().parents[1] / "recordings" / "map"
LIVE = Path(__file__).resolve().parents[1] / "recordings" / "map_live"


class StubControl:
    """Answers ``find`` from a table the test sets up; records what it is told to do."""

    def __init__(self, size=REFERENCE, seen=None, shots=None, gone_after=None,
                 appears_after=None):
        self.client_width, self.client_height = size
        self.seen = dict(seen or {})
        self.clicks: list = []
        # False stands in for the real control refusing to click
        # because the player's own cursor is over the game window.
        self.clicking = True
        self.drags: list = []
        self.dragging = True
        self.closed = False
        # Successive ``part_shot`` answers, so a test can say whether the view
        # moved. Exhausted, it repeats the last one — which reads as "static".
        self.shots = list(shots or [])
        self._shot_index = 0
        self.looked: list = []
        # ``{template: n}`` — stops answering for that template after n looks,
        # which is how a test says "the screen changed".
        self.gone_after = dict(gone_after or {})
        # The other direction: silent for the first n looks, then present. For a
        # screen the loop has to press something to arrive at.
        self.appears_after = dict(appears_after or {})

    hwnd = 1

    def describe(self):
        return "stub control"

    def find(self, template_path, threshold=0.9, region=None, gray=True, delay=0.1):
        self.looked.append(template_path)
        looks = self.looked.count(template_path)
        gone = self.gone_after.get(template_path)
        if gone is not None and looks > gone:
            return None
        if looks <= self.appears_after.get(template_path, 0):
            return None
        return self.seen.get(template_path)

    def withholding_clicks(self):
        """Whether the real control would refuse to click right now.

        `clicking = False` stands for the player's own cursor resting over the
        game window. The loops ask this before a pass, so a stub that cannot
        answer it makes every loop run passes the real one would skip.
        """
        return not self.clicking

    def click(self, point):
        self.clicks.append(tuple(point))

    def drag(self, start, end, **kwargs):
        # False stands for the real control withholding it while the player's
        # cursor is over the game window.
        if not self.dragging:
            return False
        self.drags.append((tuple(start), tuple(end)))
        return True

    def part_shot(self, region, gray=False):
        if not self.shots:
            return np.zeros((8, 8), dtype=np.uint8)
        index = min(self._shot_index, len(self.shots) - 1)
        self._shot_index += 1
        return self.shots[index]

    def close(self):
        self.closed = True

    def begin_frame(self):
        pass

    def end_frame(self):
        pass

    def invalidate_frame(self):
        pass

    def last_frame(self):
        return None


@pytest.fixture
def build(monkeypatch):
    """Builds workers whose waits are recorded instead of slept."""

    def make(seen=None, shots=None, size=REFERENCE, gone_after=None,
             appears_after=None, **kwargs):
        control = StubControl(size, seen, shots, gone_after, appears_after)
        worker = ExplorationWorker(hwnd=1, control=control, **kwargs)
        worker.waits = []
        monkeypatch.setattr(worker, "_sleep", lambda s: worker.waits.append(s))
        worker.control = control
        return worker

    return make


def frame_moved():
    """Two captures that a phase correlation reads as a real sideways shift."""
    rng = np.random.default_rng(3)
    first = rng.integers(0, 255, (120, 200), dtype=np.uint8)
    # Rolling by 30 px is inside the 40-184 px range the recording showed, and
    # well past the 8 px the module calls movement.
    return [first, np.roll(first, 30, axis=1)]


def frame_static():
    rng = np.random.default_rng(3)
    same = rng.integers(0, 255, (120, 200), dtype=np.uint8)
    return [same, same.copy()]


# ── the screens, one branch each ────────────────────────────────────────────


def test_a_badge_in_view_is_clicked(build):
    worker = build(seen={exploration.TPL_ON_MAP: (100, 600),
                         exploration.TPL_ENEMY: (440, 365)},
                   gone_after={exploration.TPL_ON_MAP: 1})

    worker._step()

    assert worker.control.clicks == [(440, 365)]
    assert worker.progress == 1


def test_a_press_that_never_starts_a_fight_is_not_counted(build):
    """Some presses miss. Counting the press reported five nests for four fights."""
    worker = build(seen={exploration.TPL_ON_MAP: (100, 600),
                         exploration.TPL_ENEMY: (1040, 259)})

    worker._step()

    assert worker.control.clicks == [(1040, 259)], "it did press"
    assert worker.progress == 0, "counted a fight that never started"


def test_the_claim_panel_is_closed_from_outside_itself(build):
    """A modal that leaves the map's furniture visible behind it.

    ``onMap`` still matches while it is up, so without this the loop decides it
    is on an empty map and drags — which a modal blocks. It cost a live run 110
    seconds of flipping direction before it was found.
    """
    worker = build(seen={exploration.TPL_ON_MAP: (100, 600),
                         exploration.TPL_CLAIM_REWARD: (560, 195)},
                   shots=frame_static())

    worker._step()

    assert worker.control.clicks == [geometry.EXPLORATION_CLAIM_DISMISS_POINT]
    assert worker.control.drags == [], "dragged behind a modal"


def test_the_claim_panel_is_not_tapped_on_its_own_title(build):
    """Tapping the panel leaves it open; tapping outside closes it. Measured."""
    worker = build(seen={exploration.TPL_ON_MAP: (100, 600),
                         exploration.TPL_CLAIM_REWARD: (560, 195)})

    worker._step()

    assert worker.control.clicks != [(560, 195)]


def test_sweeps_that_never_move_anything_are_reported(build, caplog):
    """Both ends of a map cannot both be the edge — say so instead of spinning."""
    worker = build(seen={exploration.TPL_ON_MAP: (100, 600)}, shots=frame_static())

    with caplog.at_level("WARNING"):
        for _ in range(exploration.STUCK_SWEEPS):
            worker._step()

    assert any("covering the map" in r.message for r in caplog.records)


def test_a_real_edge_is_not_reported_as_stuck(build, caplog):
    """One flip then movement is the ordinary way a sweep reaches an end."""
    worker = build(seen={exploration.TPL_ON_MAP: (100, 600)},
                   shots=frame_static() + frame_moved())

    with caplog.at_level("WARNING"):
        worker._step()
        worker._step()

    assert not [r for r in caplog.records if r.levelname == "WARNING"]
    assert worker._still_sweeps == 0, "a sweep that moved did not clear the count"


def test_a_reward_left_on_the_map_is_collected(build):
    """Beating the boss can leave the chapter's reward standing on the map."""
    worker = build(seen={exploration.TPL_ON_MAP: (100, 600),
                         exploration.TPL_MAP_REWARD: (456, 426)})

    worker._step()

    assert worker.control.clicks == [(456, 426)]
    assert worker._rewards == 1
    assert worker.progress == 0, "a gift is not a battle"


def test_a_reward_is_collected_before_any_fight(build):
    """It is free, and it is what the lap was for."""
    worker = build(seen={exploration.TPL_ON_MAP: (100, 600),
                         exploration.TPL_MAP_REWARD: (456, 426),
                         exploration.TPL_BOSS: (245, 248),
                         exploration.TPL_ENEMY: (440, 365)})

    worker._step()

    assert worker.control.clicks == [(456, 426)]


def test_a_map_holding_only_a_reward_is_not_swept(build):
    worker = build(seen={exploration.TPL_ON_MAP: (100, 600),
                         exploration.TPL_MAP_REWARD: (456, 426)},
                   shots=frame_static())

    worker._step()

    assert worker.control.drags == []


def test_the_boss_badge_is_fought_once_the_nests_are_gone(build):
    """It is a template of its own; see the module docstring for why."""
    worker = build(seen={exploration.TPL_ON_MAP: (100, 600),
                         exploration.TPL_BOSS: (245, 248)},
                   gone_after={exploration.TPL_ON_MAP: 1})

    worker._step()

    assert worker.control.clicks == [(245, 248)]
    assert worker.progress == 1


def test_the_boss_is_taken_ahead_of_any_nest_still_standing(build):
    """The boss ends the chapter, and the chapter is what the lap is for.

    Both badges are on screen here, which is a state the recording really shows —
    the banner fires when the boss spawns, not once the map is clear. Clearing
    the leftover nests first would spend sushi and minutes on the way to the same
    reward, so the boss wins.
    """
    worker = build(seen={exploration.TPL_ON_MAP: (100, 600),
                         exploration.TPL_BOSS_FOUND: (496, 198),
                         exploration.TPL_BOSS: (245, 248),
                         exploration.TPL_ENEMY: (440, 365)})

    worker._step()

    assert worker.control.clicks == [(245, 248)]


def test_a_map_holding_only_the_boss_is_not_swept(build):
    """The bug this template exists for: nests cleared, then dragging forever."""
    worker = build(seen={exploration.TPL_ON_MAP: (100, 600),
                         exploration.TPL_BOSS: (245, 248)},
                   shots=frame_static())

    worker._step()

    assert worker.control.drags == []


def test_pressing_a_badge_waits_for_the_map_to_go(build):
    """One press, one battle, one count — see HANDOVER_SECONDS for the bug."""
    worker = build(seen={exploration.TPL_ON_MAP: (100, 600),
                         exploration.TPL_ENEMY: (440, 365)},
                   gone_after={exploration.TPL_ON_MAP: 3})

    worker._step()

    assert worker.control.clicks == [(440, 365)]
    assert worker.progress == 1
    # Four looks: one is the gate in _work_the_map that decides the loop is on
    # the map at all, then the handover polls until the third of those finds it
    # gone. The point is that it stopped there rather than sitting out the whole
    # budget.
    assert worker.control.looked.count(exploration.TPL_ON_MAP) == 4
    assert sum(worker.waits) < exploration.HANDOVER_SECONDS


def test_a_map_that_never_goes_away_does_not_hang_the_loop(build):
    """A press that missed. The next pass will see the badge and press again."""
    worker = build(seen={exploration.TPL_ON_MAP: (100, 600),
                         exploration.TPL_ENEMY: (440, 365)})

    worker._step()

    assert sum(worker.waits) == pytest.approx(exploration.HANDOVER_SECONDS, abs=1.0)


def test_the_chapter_panel_is_entered(build):
    worker = build(seen={exploration.TPL_EXPLORE: (1005, 550)})

    worker._step()

    assert worker.control.clicks == [(1005, 550)]


def test_entries_are_counted_where_the_chapter_is_actually_entered(build):
    """Not on returns to the world map: a finished chapter sometimes drops back
    to the chapter panel instead, and counting only the world map reported
    twelve nests over "0 laps" in a live run.
    """
    worker = build(seen={exploration.TPL_EXPLORE: (1005, 550)})

    worker._step()
    worker._step()

    assert worker._entries == 2


def test_a_reward_screen_is_tapped(build):
    worker = build(seen={exploration.TPL_TAP_CONTINUE: (561, 612)})

    worker._step()

    assert worker.control.clicks == [(561, 612)]


def test_the_world_map_opens_the_chapter_again(build):
    worker = build(seen={exploration.TPL_WORLD_MAP: (990, 417)})

    worker._step()

    assert worker.control.clicks == [geometry.EXPLORATION_CHAPTER_POINT]


def test_the_chapter_point_can_be_moved(build):
    """Farming a different chapter is a setting, not a new template."""
    worker = build(seen={exploration.TPL_WORLD_MAP: (990, 417)},
                   chapter_point=(880, 229))

    worker._step()

    assert worker.control.clicks == [(880, 229)]


# ── the screen with no branch ───────────────────────────────────────────────


def test_an_unrecognised_screen_gets_no_input_at_all(build):
    """A battle in progress. Anything clicked here lands on the fight."""
    worker = build(seen={})

    worker._step()

    assert worker.control.clicks == []
    assert worker.control.drags == []
    assert worker.waits == [exploration.IDLE_SECONDS]


def test_a_long_unrecognised_stretch_is_logged(build, caplog):
    """Out of sushi looks exactly like this, and the log is all there is."""
    worker = build(seen={})

    with caplog.at_level("WARNING"):
        for _ in range(exploration.STALL_PASSES):
            worker._step()

    assert any("nothing to act on" in r.message for r in caplog.records)


def test_a_badge_off_the_map_is_left_alone(build):
    """The badge is small plain artwork; the map check is what contains it."""
    worker = build(seen={exploration.TPL_ENEMY: (440, 365)})

    worker._step()

    assert worker.control.clicks == []
    assert worker.progress == 0


# ── precedence ──────────────────────────────────────────────────────────────


def test_an_invite_wins_over_everything_underneath(build, monkeypatch):
    """It covers the screen and swallows every click, so nothing else can work."""
    monkeypatch.setattr(exploration.wanted_invite, "find_reply",
                        lambda *a, **k: (700, 400))
    worker = build(seen={exploration.TPL_ON_MAP: (100, 600),
                         exploration.TPL_ENEMY: (440, 365)})

    worker._step()

    assert worker.control.clicks == [(700, 400)]
    assert worker.progress == 0, "counted a nest it never entered"


def test_a_reward_screen_is_cleared_before_the_map_is_read(build):
    """Both can match while a reward panel sits over the map."""
    worker = build(seen={exploration.TPL_TAP_CONTINUE: (561, 612),
                         exploration.TPL_ON_MAP: (100, 600),
                         exploration.TPL_ENEMY: (440, 365)})

    worker._step()

    assert worker.control.clicks == [(561, 612)]


# ── sweeping ────────────────────────────────────────────────────────────────


def test_an_empty_map_is_swept(build):
    worker = build(seen={exploration.TPL_ON_MAP: (100, 600)}, shots=frame_moved())

    worker._step()

    assert worker.control.drags == [
        (geometry.EXPLORATION_DRAG_RIGHT, geometry.EXPLORATION_DRAG_LEFT)
    ]
    assert worker.control.clicks == []


def test_a_sweep_that_moved_the_view_keeps_going_the_same_way(build):
    worker = build(seen={exploration.TPL_ON_MAP: (100, 600)},
                   shots=frame_moved() + frame_moved())

    worker._step()
    worker._step()

    assert worker.control.drags[0] == worker.control.drags[1]


def test_reaching_the_edge_turns_the_sweep_around(build):
    """A map out of scroll looks the same as a map with nothing left on it."""
    worker = build(seen={exploration.TPL_ON_MAP: (100, 600)}, shots=frame_static())

    worker._step()
    worker._step()

    first, second = worker.control.drags
    assert first == (geometry.EXPLORATION_DRAG_RIGHT, geometry.EXPLORATION_DRAG_LEFT)
    assert second == (geometry.EXPLORATION_DRAG_LEFT, geometry.EXPLORATION_DRAG_RIGHT)


def test_a_resize_mid_drag_is_not_read_as_an_edge(build):
    """Two captures of different sizes cannot be compared; assume it moved."""
    odd = [np.zeros((120, 200), dtype=np.uint8), np.zeros((90, 150), dtype=np.uint8)]
    worker = build(seen={exploration.TPL_ON_MAP: (100, 600)}, shots=odd)

    worker._step()

    assert worker._direction == 1, "turned around on a comparison it could not make"


def test_the_shift_is_measured_in_pixels():
    """The numbers the module's threshold was chosen against."""
    before, after = frame_moved()

    assert exploration.ExplorationWorker._shift(before, after) == pytest.approx(30, abs=1)
    assert exploration.ExplorationWorker._shift(before, before) < 1.0


# ── the points ──────────────────────────────────────────────────────────────


def test_a_saved_point_is_scaled_to_the_window(build):
    """Points are stored against the reference size, not the window's own."""
    worker = build(seen={exploration.TPL_WORLD_MAP: (990, 417)},
                   size=(REFERENCE[0] * 2, REFERENCE[1] * 2))

    worker._step()

    x, y = worker.control.clicks[0]
    assert x == pytest.approx(geometry.EXPLORATION_CHAPTER_POINT[0] * 2, abs=2)
    assert y == pytest.approx(geometry.EXPLORATION_CHAPTER_POINT[1] * 2, abs=2)


def test_the_drag_stays_clear_of_the_fixed_furniture():
    """The sweep must not start or end on the UI strips it drags past."""
    (x1, y1), (x2, y2) = geometry.EXPLORATION_MAP_AREA
    for point in (geometry.EXPLORATION_DRAG_LEFT, geometry.EXPLORATION_DRAG_RIGHT):
        assert x1 < point[0] < x2, "%s is outside the map area" % (point,)
        assert y1 < point[1] < y2, "%s is outside the map area" % (point,)


# ── breaking off to raid ────────────────────────────────────────────────────


@pytest.fixture
def raider(monkeypatch):
    """Stands in for the raid loop, and records how it was set up and run."""
    import realm_raid

    calls = {"built": None, "ran": 0, "signals": None}

    class FakeRaider:
        def __init__(self, **kwargs):
            calls["built"] = kwargs
            self._stop_event = None
            self._resume_event = None

        def raid_until_out_of_tickets(self):
            calls["ran"] += 1
            calls["signals"] = (self._stop_event, self._resume_event)
            return True

    monkeypatch.setattr(realm_raid, "RealmRaidWorker", FakeRaider)
    return calls


def full(value):
    """A ticket reader that answers ``value`` — True, False or None."""
    class Reader:
        def __init__(self):
            self.reads = 0

        def is_full(self):
            self.reads += 1
            return value

    return Reader()


def test_the_counter_is_never_read_while_the_option_is_off(build):
    """It costs a capture and three template loads; off means off."""
    worker = build(seen={exploration.TPL_EXPLORE: (1005, 550)})

    assert worker._tickets is None

    worker._step()

    assert worker.control.clicks == [(1005, 550)], "it should just enter the chapter"


def on_the_way_to_the_board():
    """A stub set up so the walk to the raid board succeeds.

    The chapter panel is up, the world map is behind it, and the Realm Raid
    button stops answering after the press that opens the board — which is the
    only confirmation the walk has that it worked.
    """
    return dict(
        seen={exploration.TPL_EXPLORE: (1005, 550),
              exploration.TPL_WORLD_MAP: (1026, 165),
              exploration.TPL_RAID_ENTRY: (248, 584)},
        gone_after={exploration.TPL_RAID_ENTRY: 1},
        # The board covers the world map while the raid runs, so the tab strip
        # only answers once the board has been closed again.
        appears_after={exploration.TPL_WORLD_MAP: 1},
    )


def test_a_full_counter_on_the_chapter_panel_starts_a_raid(build, raider):
    worker = build(raid_relay=True, **on_the_way_to_the_board())
    worker._tickets = full(True)

    worker._step()

    assert raider["ran"] == 1
    assert worker._raids == 1


def test_the_walk_to_the_board_leaves_the_panel_then_presses_realm_raid(build, raider):
    """The step that was missing: the raid loop cannot reach the board itself."""
    worker = build(raid_relay=True, **on_the_way_to_the_board())
    worker._tickets = full(True)

    worker._step()

    assert worker.control.clicks[:2] == [
        geometry.EXPLORATION_BACK_ARROW, (248, 584)
    ], worker.control.clicks


def test_the_board_is_closed_with_its_own_x_not_the_back_arrow(build, raider):
    """The board ignores the top-left arrow entirely. Measured on the game."""
    worker = build(raid_relay=True, **on_the_way_to_the_board())
    worker._tickets = full(True)

    worker._step()

    assert worker.control.clicks[-1] == geometry.RAID_CLOSE_POINT
    assert worker.control.clicks.count(geometry.EXPLORATION_BACK_ARROW) == 1


def test_the_back_arrow_is_not_pressed_without_the_panel_in_front_of_it(build, raider):
    """One screen further back it is the player's portrait, and it opens Settings."""
    worker = build(seen={exploration.TPL_WORLD_MAP: (1026, 165),
                         exploration.TPL_RAID_ENTRY: (248, 584)},
                   raid_relay=True)
    worker._tickets = full(True)

    worker._raid()

    assert geometry.EXPLORATION_BACK_ARROW not in worker.control.clicks
    assert raider["ran"] == 0
    assert worker._raids == 0, "counted a raid it never reached"


def test_a_walk_that_never_finds_the_world_map_goes_back_to_farming(build, raider, caplog):
    """Better a wasted check than a loop stranded on an unknown screen."""
    worker = build(seen={exploration.TPL_EXPLORE: (1005, 550)}, raid_relay=True)
    worker._tickets = full(True)

    with caplog.at_level("WARNING"):
        worker._raid()

    assert raider["ran"] == 0
    assert worker._raids == 0
    assert any("Could not reach the raid board" in r.message for r in caplog.records)


def test_the_raid_holds_still_when_this_worker_is_paused(build, raider):
    """Pause is shared outright, so it reaches whichever loop is running."""
    worker = build(raid_relay=True, **on_the_way_to_the_board())
    worker._tickets = full(True)

    worker._step()

    _stop, resume = raider["signals"]
    assert resume is worker._resume_event


def test_the_raid_gets_its_own_stop_signal_not_this_workers(build, raider):
    """So an overrunning raid can be cut short without ending the map farm.

    Sharing the event outright would mean the only way to take the window back
    from a raid that had stopped making progress was to stop everything.
    """
    worker = build(raid_relay=True, **on_the_way_to_the_board())
    worker._tickets = full(True)

    worker._step()

    stop, _resume = raider["signals"]
    assert stop is not worker._stop_event


def test_stopping_this_worker_stops_the_raid_it_borrowed(build):
    """The property that matters: one press of Stop ends whatever is running."""
    import threading

    worker = build(raid_relay=True)
    guard = threading.Event()
    watcher = threading.Thread(
        target=worker._watch_raid, args=(guard, float("inf")), daemon=True
    )
    watcher.start()
    try:
        worker._stop_event.set()

        assert guard.wait(3.0), "Stop never reached the borrowed loop"
    finally:
        guard.set()
        watcher.join(timeout=2.0)


def test_a_raid_that_never_ends_gives_the_window_back(build, caplog):
    """A loop that cannot end is not hypothetical here — see RAID_BUDGET_SECONDS."""
    import threading

    worker = build(raid_relay=True)
    guard = threading.Event()
    watcher = threading.Thread(
        target=worker._watch_raid, args=(guard, 0.0), daemon=True  # already overdue
    )
    with caplog.at_level("WARNING"):
        watcher.start()

        assert guard.wait(3.0), "the raid was left running past its budget"
    watcher.join(timeout=2.0)
    assert any("taking the window back" in r.message for r in caplog.records)


def test_the_raid_borrows_this_workers_own_window(build, raider):
    """No target slot is handed over any more: the raid has none to take.

    What still matters is the capture — a second one on the same window means
    two sets of device contexts competing over one handle.
    """
    worker = build(raid_relay=True, **on_the_way_to_the_board())
    worker._tickets = full(True)

    worker._step()

    assert "slot" not in raider["built"], "a deployment slot came back"
    assert raider["built"]["control"] is worker.control, "it opened a second capture"
    assert raider["built"]["stop_when_out_of_tickets"] is True, "it would never come back"


def test_a_counter_that_is_not_full_just_carries_on(build, raider):
    worker = build(seen={exploration.TPL_EXPLORE: (1005, 550)}, raid_relay=True)
    worker._tickets = full(False)

    worker._step()

    assert raider["ran"] == 0
    assert worker.control.clicks == [(1005, 550)], "it should enter the chapter"


def test_an_unreadable_counter_carries_on_farming(build, raider):
    """Unreadable is not full. Treating it as full raids with no tickets."""
    worker = build(seen={exploration.TPL_EXPLORE: (1005, 550)}, raid_relay=True)
    worker._tickets = full(None)

    worker._step()

    assert raider["ran"] == 0
    assert worker.control.clicks == [(1005, 550)]


def test_the_counter_is_only_read_where_it_exists(build, raider):
    """It lives on the chapter panel. On the map there is no counter to read."""
    worker = build(seen={exploration.TPL_ON_MAP: (100, 600),
                         exploration.TPL_ENEMY: (440, 365)},
                   gone_after={exploration.TPL_ON_MAP: 1},
                   raid_relay=True)
    worker._tickets = full(True)

    worker._step()

    assert worker._tickets.reads == 0, "read the counter off a screen without one"
    assert raider["ran"] == 0
    assert worker.progress == 1, "it should have fought the nest"


def test_a_reward_panel_is_cleared_before_the_counter_is_read(build, raider):
    """A modal over the chapter panel could sit over the counter too."""
    worker = build(seen={exploration.TPL_EXPLORE: (1005, 550),
                         exploration.TPL_CLAIM_REWARD: (560, 195)},
                   raid_relay=True)
    worker._tickets = full(True)

    worker._step()

    assert worker._tickets.reads == 0
    assert worker.control.clicks == [geometry.EXPLORATION_CLAIM_DISMISS_POINT]


def test_the_world_map_is_recognised_by_either_signal(build):
    """The tab strip is half-transparent and sinks to 0.710 over a pale map.

    Losing that signal used to mean the loop sat on a world map it could not
    see, doing nothing, once a chapter finished. The Realm Raid icon is opaque
    and carries it.
    """
    by_icon = build(seen={exploration.TPL_RAID_ENTRY: (248, 584)})
    by_tabs = build(seen={exploration.TPL_WORLD_MAP: (1026, 165)})

    by_icon._step()
    by_tabs._step()

    assert by_icon.control.clicks == [geometry.EXPLORATION_CHAPTER_POINT]
    assert by_tabs.control.clicks == [geometry.EXPLORATION_CHAPTER_POINT]


# ── the templates, against the frames they were measured on ─────────────────

# Measured over the recorded lap: for each frame, every template that scores
# above threshold. Everything absent from a row scored 0.697 or less, so each of
# these states is separated from the others by a fifth of the whole scale.
#
# The rows carry their reason, because that is what makes a failure here
# readable: a template that stops matching its own state has been replaced or
# re-cut, and one that starts matching a state it is not in is the more
# dangerous half.
TRUTH = (
    ("01_0000.0s.png", "world map", {"worldMap", "raidEntry"}),
    ("02_0017.6s.png", "chapter panel", {"explore"}),
    ("06_0022.9s.png", "map with a nest in view", {"onMap", "enemy"}),
    ("14_0031.7s.png", "victory, tap to continue", {"tapContinue"}),
    ("42_0063.5s.png", "boss found, on the map",
     {"bossFound", "onMap", "enemy", "boss"}),
    ("43_0064.5s.png", "the boss badge on the map",
     {"bossFound", "onMap", "enemy", "boss"}),
    ("55_0077.4s.png", "a reward left on the map", {"mapReward", "onMap"}),
    ("59_0083.4s.png", "back on the world map", {"worldMap", "raidEntry"}),
    # The frame that matters most: mid-battle, nothing to act on.
    ("21_0039.4s.png", "mid-battle", set()),
    ("62_0087.6s.png", "chapter panel again", {"explore"}),
)


@pytest.fixture(scope="module")
def templates():
    folder = Path(exploration.TPL_ENEMY).parent
    found = {}
    for path in sorted(folder.glob("*.png")):
        image = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_GRAYSCALE)
        assert image is not None, "unreadable template %s" % path
        found[path.stem] = image
    return found


def test_all_ten_templates_ship(templates):
    assert set(templates) == {"boss", "bossFound", "claimReward", "enemy",
                              "explore", "mapReward", "onMap", "raidEntry",
                              "tapContinue", "worldMap"}


# The three live captures where the first cut of ``onMap`` fell under threshold,
# with the score it managed on each. Only the pill and a margin round it is kept,
# which is all the template needs and 48 KB instead of 4 MB.
#
# These are the evidence for cutting the words out of the pill rather than the
# pill itself: recorded frames alone said 0.99-1.00 and would have shipped the
# fault. Anything that re-cuts this template has to clear them.
LIVE_PILLS = (("pill_map.png", 0.918), ("pill_boss.png", 0.879),
              ("pill_reward.png", 0.945))


@pytest.mark.skipif(not LIVE.is_dir(), reason="the live crops are not present")
@pytest.mark.parametrize("crop,old_score", LIVE_PILLS)
def test_the_map_is_recognised_on_the_live_captures_that_used_to_fail(templates, crop, old_score):
    """The animated icon is out of the template, so a moving part cannot sink it."""
    image = cv2.imdecode(np.fromfile(str(LIVE / crop), np.uint8), cv2.IMREAD_GRAYSCALE)
    assert image is not None, "unreadable crop %s" % crop

    score = float(cv2.minMaxLoc(
        cv2.matchTemplate(image, templates["onMap"], cv2.TM_CCOEFF_NORMED))[1])

    assert score > exploration.THRESHOLD, (
        "%s scores %.3f — the cut before this one managed %.3f here, which is "
        "under threshold and leaves the whole map branch dead"
        % (crop, score, old_score)
    )


@pytest.mark.skipif(not RECORDINGS.is_dir(), reason="the recorded lap is not present")
@pytest.mark.parametrize("frame,state,expected", TRUTH,
                         ids=[row[1].replace(" ", "-") for row in TRUTH])
def test_each_recorded_screen_is_recognised_for_what_it_is(templates, frame, state, expected):
    raw = cv2.imdecode(np.fromfile(str(RECORDINGS / frame), np.uint8),
                       cv2.IMREAD_GRAYSCALE)
    assert raw is not None, "unreadable frame %s" % frame
    # The same normalisation the matcher does before comparing anything.
    image = cv2.resize(raw, tuple(REFERENCE), interpolation=cv2.INTER_CUBIC)

    scores = {
        name: float(cv2.minMaxLoc(cv2.matchTemplate(image, tpl, cv2.TM_CCOEFF_NORMED))[1])
        for name, tpl in templates.items()
    }
    threshold = {"worldMap": exploration.WORLD_MAP_THRESHOLD,
                 "boss": exploration.BOSS_THRESHOLD,
                 "mapReward": exploration.REWARD_THRESHOLD,
                 "raidEntry": exploration.RAID_ENTRY_THRESHOLD}
    matched = {n for n, s in scores.items()
               if s > threshold.get(n, exploration.THRESHOLD)}

    assert matched == expected, "%s (%s): %s" % (
        frame, state, ", ".join("%s=%.3f" % kv for kv in sorted(scores.items()))
    )


def test_a_withheld_drag_does_not_turn_the_sweep_around(build):
    """The map standing still means "edge reached" only if it was pushed.

    Clicks and drags are withheld while the player's cursor is over the game.
    A drag that never left the app moves nothing, and reading that as an edge
    would reverse the sweep for no reason — and keep reversing it.
    """
    worker = build(**on_the_way_to_the_board())
    worker._control.dragging = False
    facing = worker._direction

    worker._sweep()

    assert worker._direction == facing, "turned around on a drag never sent"
    assert worker._control.drags == []
