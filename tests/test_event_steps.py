"""Event's added points: the stored form, the loop, and the list on the task page.

Contributed as a task of its own ("Nhấn theo chuỗi") and folded into Event,
which is the same loop with one point. Nothing here touches Windows: the
control is stubbed, so these run headless and never post input anywhere. The
parts pinned are the ones that cost something when wrong:

* **With no points added, Event is what it was.** Every player already on it
  has an empty list, and their runs must not change under them.
* **Points go out in the order they were listed, after the main one.** A
  sequence clicked out of order is a different sequence.
* **A step is held, never skipped.** A press withheld because the cursor was
  over the game is retried, so the next press is never one step ahead.
* **The stored text survives what the settings store does to it.** The
  registry hands comma-separated values back as lists of strings.
"""
from __future__ import annotations

import time

import pytest

import event_clicker
import geometry
import tasks
from event_clicker import EventClickerWorker

REFERENCE = geometry.REFERENCE_CLIENT_SIZE
STEPS = ((100, 200, 0.5), (300, 400, 0.5), (500, 100, 0.5))
MAIN = (1030, 549)


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
    monkeypatch.setattr(event_clicker, "MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(event_clicker.wanted_invite, "find_reply",
                        lambda control, geo, accept: None)

    def build(steps=((100, 200, 0.001), (300, 400, 0.001)), size=REFERENCE,
              interval=0.001, **kwargs):
        control = StubControl(size)
        made = EventClickerWorker(hwnd=1, point=MAIN, interval=interval,
                                  steps=steps, control=control, **kwargs)
        made.control = control
        created.append(made)
        return made

    yield build

    for made in created:
        made.stop()
        if made.ident is not None:
            made.join(3)


def run_until(made, clicks, timeout=3.0):
    """Run until at least ``clicks`` presses went out, then stop."""
    made.start()
    deadline = time.monotonic() + timeout
    while len(made.control.clicks) < clicks and time.monotonic() < deadline:
        time.sleep(0.005)
    made.stop()
    made.join(3)
    assert len(made.control.clicks) >= clicks, "only %d clicks" % len(made.control.clicks)
    return made.control.clicks[:clicks]


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
    config = tasks.get("event").coerce({"extra_steps": ["100", "200", "2;300", "400"]})
    assert config["extra_steps"] == "100,200,2.0;300,400,2.0"


# ── the builder ─────────────────────────────────────────────────────────────


def test_there_is_no_separate_sequence_task():
    """Folded into Event: one task for "press fixed points over and over"."""
    assert tasks.get("sequence") is None


def test_by_default_no_points_are_added():
    config = tasks.merge_layers(tasks.app_defaults(), tasks.get("event").defaults())
    assert tasks.as_steps(config["extra_steps"]) == ()


def test_the_builder_passes_the_added_points(monkeypatch):
    spec = tasks.get("event")
    seen = {}

    class Spy:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(event_clicker, "EventClickerWorker", Spy)
    config = tasks.merge_layers(tasks.app_defaults(), spec.coerce(
        {"extra_steps": "100,200,1.5;300,400,2"}))
    spec.build(hwnd=1, control=None, config=config, on_finished=None, on_error=None)

    assert seen["steps"] == ((100, 200, 1.5), (300, 400, 2.0))


# ── the loop ────────────────────────────────────────────────────────────────


def test_rejects_a_wait_below_the_floor():
    with pytest.raises(ValueError):
        EventClickerWorker(hwnd=1, steps=((1, 1, 0.0),), control=StubControl())


def test_with_nothing_added_only_the_main_point_is_pressed(worker):
    assert set(run_until(worker(steps=()), 5)) == {MAIN}


def test_the_main_point_then_each_added_point_in_order(worker):
    clicks = run_until(worker(), 6)
    assert clicks == [MAIN, (100, 200), (300, 400)] * 2


def test_each_point_waits_its_own_time(worker):
    made = worker(steps=((100, 200, 0.25),), interval=0.001)
    waits = []
    made._sleep = lambda seconds: (waits.append(seconds), time.sleep(0.001))
    run_until(made, 4)

    assert waits[:4] == [0.001, 0.25, 0.001, 0.25]


def test_a_withheld_click_is_retried_not_skipped(worker):
    made = worker()
    made.control.withhold_next = 2
    assert run_until(made, 3) == [MAIN, (100, 200), (300, 400)]


def test_the_count_is_still_clicks(worker):
    made = worker()
    run_until(made, 5)
    assert made.progress == len(made.control.clicks)


def test_added_points_are_scaled_to_a_window_of_another_size(worker):
    half = (REFERENCE[0] // 2, REFERENCE[1] // 2)
    clicks = run_until(worker(steps=((1000, 500, 0.001),), size=half), 2)
    assert clicks[1] == (500, 250)


# ── the list on the task page ───────────────────────────────────────────────


@pytest.fixture
def form(qt_app, monkeypatch):
    from ui import fields as fields_module
    from ui import point_picker

    picks: list = []
    asked: list = []

    def choose(start, *args, **kwargs):
        asked.append(kwargs)
        return picks.pop(0) if picks else None

    monkeypatch.setattr(point_picker, "choose_point", choose)
    spec = tasks.get("event")

    def build(stored=""):
        values = dict(spec.defaults(), extra_steps=stored)
        made = fields_module.FieldForm(spec.shared_fields, values)
        made.emitted = []
        made.changed.connect(lambda key, value: made.emitted.append((key, value)))
        made.picks = picks
        made.asked = asked
        return made

    return build


def _buttons(form):
    from PyQt5 import QtWidgets

    return {b.text(): b for b in form.findChildren(QtWidgets.QPushButton)}


def _listing(form):
    from PyQt5 import QtWidgets

    return form.findChild(QtWidgets.QListWidget, "pointList")


def test_the_page_lists_stored_steps(form):
    made = form("100,200,1.5;1050,560,2")
    assert _listing(made).count() == 2


def test_adding_a_point_emits_the_stored_text(form):
    made = form("")
    made.picks.extend([(10, 20), (30, 40)])
    _buttons(made)["Thêm điểm"].click()
    _buttons(made)["Thêm điểm"].click()

    assert made.emitted[-1] == ("extra_steps", "10,20,2.0;30,40,2.0")
    assert _listing(made).count() == 2


def test_a_cancelled_pick_changes_nothing(form):
    made = form("100,200,1.5")
    _buttons(made)["Thêm điểm"].click()   # no pick queued: the picker was cancelled

    assert made.emitted == []


def test_removing_and_rewaiting_a_step(form):
    from PyQt5 import QtWidgets

    made = form("1,1,1;2,2,1;3,3,1")
    listing = _listing(made)
    listing.setCurrentRow(0)
    _buttons(made)["Xoá"].click()
    assert made.emitted[-1] == ("extra_steps", "2,2,1.0;3,3,1.0")

    listing.setCurrentRow(1)
    made.findChild(QtWidgets.QDoubleSpinBox).setValue(4.5)
    assert made.emitted[-1] == ("extra_steps", "2,2,1.0;3,3,4.5")


def test_the_list_has_no_up_and_down_buttons(form):
    """Taken out as clutter: re-picking a point puts a short list in order."""
    buttons = _buttons(form(""))
    assert "Lên" not in buttons and "Xuống" not in buttons


def test_repicking_replaces_only_that_point(form):
    made = form("1,1,1;2,2,3")
    _listing(made).setCurrentRow(1)
    made.picks.append((9, 9))
    _buttons(made)["Chọn lại"].click()

    assert made.emitted[-1] == ("extra_steps", "1,1,1.0;9,9,3.0")


def test_the_list_carries_no_warning(form):
    """Mid-screen points used to be flagged; taken out at the owner's request."""
    made = form("1050,560,2;500,300,2")
    listing = _listing(made)

    assert [listing.item(i).text() for i in range(2)] == [
        "1.  1050, 560  ·  2 giây", "2.  500, 300  ·  2 giây"]


# ── through the app: saved, reloaded, handed to the worker ──────────────────


def test_steps_are_stored_as_plain_text(dashboard):
    dashboard._on_option_changed("event", "extra_steps", "10,20,1.5;30,40,2.0")

    stored = dashboard._settings.value("tasks/event/extra_steps")
    assert stored == "10,20,1.5;30,40,2.0", "stored as %r" % (stored,)


def test_steps_survive_a_restart(dashboard, isolated_settings):
    from PyQt5 import QtCore

    dashboard._on_option_changed("event", "extra_steps", "10,20,1.5;30,40,2.0")
    dashboard._settings.sync()
    reopened = QtCore.QSettings(str(isolated_settings), QtCore.QSettings.IniFormat)
    raw = reopened.value("tasks/event/extra_steps")

    assert tasks.as_steps(raw) == ((10, 20, 1.5), (30, 40, 2.0)), "read back %r" % (raw,)


def test_steps_reach_the_worker(dashboard):
    from conftest import SpyWorker

    dashboard._on_option_changed("event", "extra_steps", "10,20,1.5;30,40,2.0")
    dashboard._on_select(101, "event")
    dashboard._on_start(101)

    assert SpyWorker.live[-1].kwargs["steps"] == ((10, 20, 1.5), (30, 40, 2.0))


def test_the_event_page_carries_the_list(dashboard):
    from PyQt5 import QtWidgets

    dashboard._show_page("event")
    assert dashboard.findChild(QtWidgets.QListWidget, "pointList") is not None


# ── the points already chosen, shown while picking the next ─────────────────


def test_adding_a_point_shows_the_main_point_and_the_others_numbered(form):
    made = form("100,200,1;300,400,1")
    made.picks.append((10, 20))
    _buttons(made)["Thêm điểm"].click()

    asked = made.asked[-1]
    assert asked["marks"] == [("C", MAIN), ("1", (100, 200)), ("2", (300, 400))]
    assert asked["label"] == "3"


def test_repicking_shows_the_others_and_keeps_its_own_number(form):
    made = form("100,200,1;300,400,1;500,100,1")
    _listing(made).setCurrentRow(1)
    _buttons(made)["Chọn lại"].click()

    asked = made.asked[-1]
    assert asked["marks"] == [("C", MAIN), ("1", (100, 200)), ("3", (500, 100))]
    assert asked["label"] == "2"


def test_the_main_point_shown_is_the_one_on_the_page_now(form):
    """Moved a moment ago with its own picker: that is where it is shown."""
    made = form("")
    made.changed.emit("click_point", (640, 480))
    _buttons(made)["Thêm điểm"].click()

    assert made.asked[-1]["marks"][0] == ("C", (640, 480))


@pytest.mark.parametrize("count", [1, 3, 8, 20])
def test_the_list_grows_to_show_every_step_without_scrolling(form, count):
    """A box a few rows tall with scrollbars inside the page was what this replaced.

    At the width the task page gives its settings column, with the widest
    numbers a row can carry.
    """
    from ui import task_view

    stored = ";".join("%d,%d,60" % (1045 - i, 565 - i) for i in range(count))
    made = form(stored)
    made.resize(task_view.CONFIG_WIDTH, 2000)
    made.show()
    try:
        listing = _listing(made)
        assert listing.count() == count
        assert listing.verticalScrollBar().maximum() == 0, "it scrolls inside"
        last = listing.visualItemRect(listing.item(count - 1))
        assert last.bottom() <= listing.viewport().rect().bottom(), "last row cut off"
        widest = max(listing.fontMetrics().horizontalAdvance(listing.item(i).text())
                     for i in range(count))
        assert widest < listing.viewport().width(), "a row's text runs off the side"
    finally:
        made.close()


def test_the_list_gets_taller_as_steps_are_added(form):
    made = form("1,1,1")
    short = _listing(made).height()
    made.picks.extend([(2, 2), (3, 3), (4, 4)])
    for _ in range(3):
        _buttons(made)["Thêm điểm"].click()

    assert _listing(made).height() > short
