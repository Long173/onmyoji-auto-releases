"""Click sequence: the stored form, the loop, and the list on the task page.

Nothing here touches Windows: the control is stubbed, so these run headless and
never post input anywhere. The parts pinned are the ones that cost something
when wrong:

* **Points go out in the order they were listed, each once per round.** A
  sequence clicked out of order is a different sequence.
* **A step is held, never skipped.** A press withheld because the cursor was
  over the game is retried, or a round would count presses that never happened.
* **The round limit stops it, and says so.** "Dừng sau 3 vòng" that runs a
  fourth would be the clicker deciding for itself how long to play.
* **The stored text survives what the settings store does to it.** The
  registry hands comma-separated values back as lists of strings.
"""
from __future__ import annotations

import time

import pytest

import geometry
import sequence_clicker
import tasks
from sequence_clicker import SequenceClickerWorker

REFERENCE = geometry.REFERENCE_CLIENT_SIZE
STEPS = ((100, 200, 0.5), (300, 400, 0.5), (500, 100, 0.5))


class StubControl:
    def __init__(self, size=REFERENCE):
        self.client_width, self.client_height = size
        self.clicks: list = []
        self.clicking = True
        self.closed = False
        self.withhold_next = 0

    def describe(self):
        return "stub control"

    def find(self, *args, **kwargs):
        time.sleep(0.001)
        return None

    def withholding_clicks(self):
        return not self.clicking

    def click(self, point):
        if not self.clicking:
            return False
        if self.withhold_next:
            self.withhold_next -= 1
            return False
        self.clicks.append(tuple(point))
        return True

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
def worker(monkeypatch):
    created: list = []
    monkeypatch.setattr(sequence_clicker, "MIN_WAIT_SECONDS", 0.0)
    monkeypatch.setattr(sequence_clicker, "WITHHELD_RETRY_SECONDS", 0.001)
    monkeypatch.setattr(sequence_clicker.wanted_invite, "find_reply",
                        lambda control, geo, accept: None)

    def build(steps=((100, 200, 0.001), (300, 400, 0.001), (500, 100, 0.001)),
              size=REFERENCE, **kwargs):
        control = StubControl(size)
        made = SequenceClickerWorker(hwnd=1, steps=steps, control=control, **kwargs)
        made.control = control
        made.finished_with = []
        made._on_finished = made.finished_with.append
        created.append(made)
        return made

    yield build

    for made in created:
        made.stop()
        if made.ident is not None:
            made.join(3)


def run_until_done(made, timeout=3.0):
    made.start()
    made.join(timeout)
    assert not made.is_alive(), "the loop did not stop by itself"


def run_briefly(made, seconds=0.3):
    made.start()
    time.sleep(seconds)
    made.stop()
    made.join(3)


# ── stored form ─────────────────────────────────────────────────────────────


def test_text_round_trips():
    text = tasks.steps_text(STEPS)
    assert text == "100,200,0.5;300,400,0.5;500,100,0.5"
    assert tasks.as_steps(text) == STEPS


def test_a_registry_list_of_strings_reads_back_as_the_same_steps():
    """The registry splits a stored "a,b;c,d" on its commas."""
    flattened = tasks.steps_text(STEPS).split(",")
    assert tasks.as_steps(flattened) == STEPS


def test_a_list_of_tuples_is_accepted():
    assert tasks.as_steps([(1, 2, 3.0)]) == ((1, 2, 3.0),)


def test_a_broken_step_is_dropped_not_invented():
    """A made-up point in the middle of a sequence clicks somewhere unchosen."""
    assert tasks.as_steps("100,200,1;garbage;;300,x,1;400,500") == (
        (100, 200, 1.0), (400, 500, tasks.STEP_WAIT_DEFAULT))


def test_points_are_clamped_to_the_window_and_waits_to_the_range():
    width, height = REFERENCE
    low, high = tasks.STEP_WAIT_RANGE
    assert tasks.as_steps("-5,99999,0;10,10,9999") == (
        (0, height - 1, low), (10, 10, high))


def test_empty_values_mean_no_steps():
    for value in (None, "", " ", [], ()):
        assert tasks.as_steps(value) == ()


def test_the_list_is_capped():
    text = ";".join("%d,%d,1" % (i, i) for i in range(tasks.MAX_STEPS + 5))
    assert len(tasks.as_steps(text)) == tasks.MAX_STEPS


def test_coerce_turns_a_stored_value_into_canonical_text():
    spec = tasks.get("sequence")
    config = spec.coerce({"steps": ["100", "200", "2;300", "400"]})
    assert config["steps"] == "100,200,2.0;300,400,2.0"


# ── the task in the registry ────────────────────────────────────────────────


def test_the_task_is_registered_and_startable():
    spec = tasks.get("sequence")
    assert spec is not None and spec.is_available
    assert spec.counts_progress


def test_building_with_no_points_is_refused_with_a_reason():
    spec = tasks.get("sequence")
    config = tasks.merge_layers(tasks.app_defaults(), spec.defaults())
    with pytest.raises(ValueError, match="điểm"):
        spec.build(hwnd=1, control=StubControl(), config=config,
                   on_finished=None, on_error=None)


def test_the_builder_passes_steps_and_rounds(monkeypatch):
    spec = tasks.get("sequence")
    seen = {}

    class Spy:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(sequence_clicker, "SequenceClickerWorker", Spy)
    config = tasks.merge_layers(tasks.app_defaults(), spec.coerce(
        {"steps": "100,200,1.5;300,400,2", "rounds": 7, "unlimited": False}))
    spec.build(hwnd=1, control=None, config=config, on_finished=None, on_error=None)
    assert seen["steps"] == ((100, 200, 1.5), (300, 400, 2.0))
    assert seen["rounds"] == 7

    config["unlimited"] = "true"   # as the registry returns it
    spec.build(hwnd=1, control=None, config=config, on_finished=None, on_error=None)
    assert seen["rounds"] == 0


# ── the loop ────────────────────────────────────────────────────────────────


def test_rejects_an_empty_sequence():
    with pytest.raises(ValueError):
        SequenceClickerWorker(hwnd=1, steps=(), control=StubControl())


def test_rejects_a_wait_below_the_floor():
    with pytest.raises(ValueError):
        SequenceClickerWorker(hwnd=1, steps=((1, 1, 0.0),), control=StubControl())


def test_clicks_in_order_once_per_round_and_stops_at_the_limit(worker):
    made = worker(rounds=3)
    run_until_done(made)

    expected = [(100, 200), (300, 400), (500, 100)] * 3
    assert made.control.clicks == expected
    assert made.progress == 3
    assert made.finished_with == ["Xong 3 vòng nhấn theo chuỗi."]
    assert made.control.closed


def test_unlimited_keeps_going_until_stopped(worker):
    made = worker(rounds=0)
    run_briefly(made)

    assert made.progress > 3
    assert made.finished_with == [], "a stopped run is not a finished run"


def test_a_withheld_click_is_retried_not_skipped(worker):
    made = worker(rounds=1)
    made.control.withhold_next = 2
    run_until_done(made)

    assert made.control.clicks == [(100, 200), (300, 400), (500, 100)]


def test_points_are_scaled_to_a_window_of_another_size(worker):
    half = (REFERENCE[0] // 2, REFERENCE[1] // 2)
    made = worker(steps=((1000, 500, 0.001),), size=half, rounds=1)
    run_until_done(made)

    assert made.control.clicks == [(500, 250)]


def test_stopping_mid_round_does_not_count_the_round(worker, monkeypatch):
    made = worker(steps=((1, 1, 0.001), (2, 2, 5.0)), rounds=0)
    run_briefly(made, 0.2)

    assert made.control.clicks == [(1, 1), (2, 2)]
    assert made.progress == 0


def test_answers_a_wanted_invite_before_the_next_point(worker, monkeypatch):
    monkeypatch.setattr(sequence_clicker, "POPUP_SETTLE_SECONDS", 0.001)
    answered = []

    def reply(control, geo, accept):
        if not answered:
            answered.append(True)
            return (600, 300)
        return None

    monkeypatch.setattr(sequence_clicker.wanted_invite, "find_reply", reply)
    made = worker(rounds=1)
    run_until_done(made)

    assert made.control.clicks == [(600, 300), (100, 200), (300, 400), (500, 100)]


# ── the list on the task page ───────────────────────────────────────────────


@pytest.fixture
def form(qt_app, monkeypatch):
    from ui import fields as fields_module
    from ui import point_picker

    picks: list = []
    monkeypatch.setattr(point_picker, "choose_point",
                        lambda start, *a, **k: picks.pop(0) if picks else None)
    spec = tasks.get("sequence")

    def build(stored=""):
        values = dict(spec.defaults(), steps=stored)
        made = fields_module.FieldForm(spec.shared_fields, values)
        made.emitted = []
        made.changed.connect(lambda key, value: made.emitted.append((key, value)))
        made.picks = picks
        return made

    return build


def _buttons(form):
    from PyQt5 import QtWidgets

    return {b.text(): b for b in form.findChildren(QtWidgets.QPushButton)}


def _listing(form):
    from PyQt5 import QtWidgets

    return form.findChild(QtWidgets.QListWidget, "pointList")


def test_the_page_lists_stored_steps(form):
    made = form("100,200,1.5;300,400,2")
    assert _listing(made).count() == 2


def test_adding_a_point_emits_the_stored_text(form):
    made = form("")
    made.picks.extend([(10, 20), (30, 40)])
    _buttons(made)["Thêm điểm"].click()
    _buttons(made)["Thêm điểm"].click()

    assert made.emitted[-1] == ("steps", "10,20,2.0;30,40,2.0")
    assert _listing(made).count() == 2


def test_a_cancelled_pick_changes_nothing(form):
    made = form("100,200,1.5")
    _buttons(made)["Thêm điểm"].click()   # no pick queued: the picker was cancelled

    assert made.emitted == []


def test_moving_removing_and_rewaiting_a_step(form):
    from PyQt5 import QtWidgets

    made = form("1,1,1;2,2,1;3,3,1")
    listing = _listing(made)
    listing.setCurrentRow(2)
    _buttons(made)["Lên"].click()
    assert made.emitted[-1] == ("steps", "1,1,1.0;3,3,1.0;2,2,1.0")

    listing.setCurrentRow(0)
    _buttons(made)["Xoá"].click()
    assert made.emitted[-1] == ("steps", "3,3,1.0;2,2,1.0")

    listing.setCurrentRow(1)
    made.findChild(QtWidgets.QDoubleSpinBox).setValue(4.5)
    assert made.emitted[-1] == ("steps", "3,3,1.0;2,2,4.5")


def test_repicking_replaces_only_that_point(form):
    made = form("1,1,1;2,2,3")
    _listing(made).setCurrentRow(1)
    made.picks.append((9, 9))
    _buttons(made)["Chọn lại"].click()

    assert made.emitted[-1] == ("steps", "1,1,1.0;9,9,3.0")


# ── through the app: saved, reloaded, handed to the worker ──────────────────


def test_steps_are_stored_as_plain_text(dashboard):
    dashboard._on_option_changed("sequence", "steps", "10,20,1.5;30,40,2.0")

    stored = dashboard._settings.value("tasks/sequence/steps")
    assert stored == "10,20,1.5;30,40,2.0", "stored as %r" % (stored,)


def test_steps_survive_a_restart(dashboard, isolated_settings):
    from PyQt5 import QtCore

    dashboard._on_option_changed("sequence", "steps", "10,20,1.5;30,40,2.0")
    dashboard._settings.sync()
    reopened = QtCore.QSettings(str(isolated_settings), QtCore.QSettings.IniFormat)
    raw = reopened.value("tasks/sequence/steps")

    assert tasks.as_steps(raw) == ((10, 20, 1.5), (30, 40, 2.0)), "read back %r" % (raw,)


def test_steps_reach_the_worker(dashboard):
    from conftest import SpyWorker

    dashboard._on_option_changed("sequence", "steps", "10,20,1.5;30,40,2.0")
    dashboard._on_option_changed("sequence", "rounds", 4)
    dashboard._on_select(101, "sequence")
    dashboard._on_start(101)

    kwargs = SpyWorker.live[-1].kwargs
    assert kwargs["steps"] == ((10, 20, 1.5), (30, 40, 2.0))
    assert kwargs["rounds"] == 4


def test_the_task_page_builds(dashboard):
    from PyQt5 import QtWidgets

    dashboard._show_page("sequence")
    assert dashboard.findChild(QtWidgets.QListWidget, "pointList") is not None
