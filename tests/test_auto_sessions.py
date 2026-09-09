"""Multi-window session tracking.

No real windows and no real workers: everything the session touches — the
window handle check, the resize, the worker class and GameControl — is stubbed,
so these run headless and never post input anywhere.
"""
from __future__ import annotations

import pytest

import realm_raid
import tasks
from auto import session as session_module
from auto.manager import SessionManager
from auto.session import DONE, ERROR, IDLE, RUNNING, GameSession
from auto.window_scanner import GameWindow

from conftest import unbuilt_task_id  # noqa: E402

RAID = "realm_raid"


class FakeWorker:
    """Stands in for a task worker: records what it was asked to do."""

    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.progress = 0
        self.elapsed_seconds = 0.0
        self.is_paused = False
        self.started = False
        self.stopped = False
        self._alive = False
        FakeWorker.instances.append(self)

    def start(self):
        self.started = True
        self._alive = True

    def stop(self):
        self.stopped = True
        self._alive = False

    def join(self, timeout=None):
        self._alive = False

    def is_alive(self):
        return self._alive

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def latest_frame(self):
        return "frame"


class FakeControl:
    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.client_width = 1122
        self.client_height = 633
        self.closed = False
        self.refreshed = 0

    def describe(self):
        return "fake control"

    def refresh_metrics(self):
        self.refreshed += 1

    def full_shot(self):
        return "idle-frame"

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def stub_environment(monkeypatch):
    FakeWorker.instances = []
    monkeypatch.setattr(session_module, "GameControl", FakeControl)
    monkeypatch.setattr(session_module, "is_alive", lambda hwnd: hwnd != 0)
    monkeypatch.setattr(realm_raid, "resize_game_window", lambda hwnd: None)
    monkeypatch.setattr(realm_raid, "RealmRaidWorker", FakeWorker)


def window(hwnd=1, title="陰陽師Onmyoji"):
    return GameWindow(hwnd, title, 1122, 633)


def raid_config(app=None, **overrides):
    """Exactly what the manager hands a builder: app layer, task layer on top."""
    return tasks.merge_layers(
        tasks.coerce_app(app), tasks.BY_ID[RAID].coerce(overrides)
    )


# ── window descriptor ───────────────────────────────────────────────────────


def test_descriptor_matches_the_design_caption():
    assert window(0x4A21C).descriptor == "HWND 0x0004A21C · 1122×633"


# ── scanner exclusions ──────────────────────────────────────────────────────
# A title match alone caught this app's own window and an Explorer window
# browsing the project folder, so both showed up as game windows.


@pytest.mark.parametrize(
    "class_name",
    ["CabinetWClass", "ExploreWClass", "Qt5152QWindowIcon", "Chrome_WidgetWin_1",
     "Progman", "ApplicationFrameWindow"],
)
def test_non_game_window_classes_are_excluded(class_name):
    from auto.window_scanner import is_excluded_class

    assert is_excluded_class(class_name)


@pytest.mark.parametrize("class_name", ["Win32Window", "UnityWndClass", "LDPlayerMainFrame"])
def test_game_window_classes_are_kept(class_name):
    from auto.window_scanner import is_excluded_class

    assert not is_excluded_class(class_name)


@pytest.mark.parametrize(
    "title",
    [
        "Onmyoji Tool — Trung tâm tác vụ",
        # The old name still has to be excluded: a copy that has not updated yet
        # carries it, and its title matches the game's search pattern.
        "Onmyoji Auto — Realm Raid",
        "Onmyoji Wiki",
    ],
)
def test_the_apps_own_windows_are_never_taken_for_the_game(title):
    from auto.window_scanner import EXCLUDED_TITLE_PREFIXES

    assert title.startswith(EXCLUDED_TITLE_PREFIXES)


def test_the_real_game_title_is_not_excluded():
    from auto.window_scanner import EXCLUDED_TITLE_PREFIXES

    assert not "陰陽師Onmyoji".startswith(EXCLUDED_TITLE_PREFIXES)


# ── the task queue ──────────────────────────────────────────────────────────


def test_a_new_session_starts_on_the_default_task():
    session = GameSession(window())
    assert session.selected == tasks.DEFAULT_TASK_ID
    assert session.task_id == RAID
    assert session.status == IDLE
    assert not session.is_running


def test_a_queue_saved_by_an_older_build_becomes_its_first_task():
    """Windows used to hold a list of tasks and this one holds a single task.

    The setting is read back rather than discarded, so somebody returning from
    the older build finds their window still set to what they chose.
    """
    session = GameSession(window(), task_id=["beans", "da_xoa"])
    assert session.selected == "beans"


def test_a_saved_task_that_no_longer_exists_falls_back_to_the_default():
    assert GameSession(window(), task_id=["da_xoa"]).selected == tasks.DEFAULT_TASK_ID
    assert GameSession(window(), task_id="da_xoa").selected == tasks.DEFAULT_TASK_ID


def test_selecting_replaces_the_task_rather_than_adding_to_it():
    session = GameSession(window())
    session.select("beans")
    session.select("souls")
    assert session.selected == "souls"


def test_selecting_an_unknown_task_is_ignored():
    session = GameSession(window())
    session.select("khong-co-thuc")
    assert session.selected == RAID


def test_choosing_another_task_leaves_the_running_one_alone():
    """The selection says what the next start will do, not what is happening.

    Changing it mid-run must not make the window report that it is running
    something it is not — the stats and the stop button both key off that.
    """
    session = GameSession(window(), task_id=RAID)
    session.start(raid_config())

    session.select("beans")

    assert session.selected == "beans"
    assert session.task_id == RAID, "reported the new choice as the running task"
    assert session.is_running


# ── settings that belong to one window ──────────────────────────────────────


def test_two_windows_hold_different_roles(monkeypatch):
    """The whole point: a co-op room has one leader and the rest are members."""
    manager = managed(monkeypatch, [window(1), window(2)])
    manager.select(1, "souls")
    manager.select(2, "souls")

    manager.get(1).set_option("souls", "role", tasks.LEADER)
    manager.get(2).set_option("souls", "role", tasks.MEMBER)

    assert manager.config_for("souls", manager.get(1))["role"] == tasks.LEADER
    assert manager.config_for("souls", manager.get(2))["role"] == tasks.MEMBER


def test_a_window_without_a_choice_gets_the_default():
    session = GameSession(window())
    assert session.options_for("souls")["role"] == tasks.LEADER


def test_a_shared_setting_cannot_be_set_per_window():
    """Otherwise one window would silently diverge on a task-wide value."""
    session = GameSession(window())
    session.set_option("souls", "rounds", 5)

    assert "rounds" not in session.window_options.get("souls", {})


def test_the_window_layer_sits_on_top_of_the_task_layer(monkeypatch):
    manager = managed(monkeypatch, [window(1)])
    manager.set_option("souls", "rounds", 7)
    manager.get(1).set_option("souls", "role", tasks.MEMBER)

    config = manager.config_for("souls", manager.get(1))

    assert config["role"] == tasks.MEMBER, "the window's own choice was lost"
    assert config["rounds"] == 7, "the task-wide setting was lost"
    assert config["wanted_invite"] == tasks.REFUSE, "the app-wide setting was lost"


def test_without_a_session_only_the_shared_layers_apply(monkeypatch):
    manager = managed(monkeypatch, [window(1)])
    manager.get(1).set_option("souls", "role", tasks.MEMBER)

    assert manager.config_for("souls")["role"] == tasks.LEADER


def test_saved_window_options_are_restored():
    session = GameSession(window())
    session.load_options({"souls": {"role": tasks.MEMBER}})

    assert session.options_for("souls")["role"] == tasks.MEMBER


def test_saved_options_for_a_deleted_task_are_dropped():
    """Settings are keyed by window title and outlive the build that wrote them."""
    session = GameSession(window())
    session.load_options({"da_xoa": {"role": "gi do"}, "souls": {"lac": 1}})

    assert "da_xoa" not in session.window_options
    assert session.window_options.get("souls", {}) == {}


def test_the_role_reaches_the_worker(monkeypatch):
    """Through all three layers and the builder, not just into a dict."""
    import souls_dungeon

    made = []
    monkeypatch.setattr(
        souls_dungeon, "SoulsDungeonWorker",
        lambda **kwargs: made.append(kwargs) or FakeWorker(**kwargs),
    )
    manager = managed(monkeypatch, [window(1)])
    manager.select(1, "souls")
    manager.get(1).set_option("souls", "role", tasks.MEMBER)

    manager.start(1)

    assert made[-1]["role"] == souls_dungeon.ROLE_MEMBER


# ── session lifecycle ───────────────────────────────────────────────────────


def test_start_builds_the_worker_from_the_task_config():
    session = GameSession(window())

    session.start(raid_config(auto_refresh=False, stop_when_out_of_tickets=False))

    assert session.status == RUNNING and session.is_running
    worker = FakeWorker.instances[-1]
    assert worker.kwargs["auto_refresh"] is False
    assert worker.kwargs["stop_when_out_of_tickets"] is False
    assert worker.kwargs["accept_wanted_quest"] is False, "invite reply not passed on"
    # One GameControl is shared, so the preview and the loop use one capture path.
    assert isinstance(worker.kwargs["control"], FakeControl)
    assert worker.kwargs["control"].refreshed == 1, "metrics not re-read after resize"


def test_starting_twice_does_not_spawn_a_second_worker():
    session = GameSession(window())
    session.start(raid_config())
    session.start(raid_config())
    assert len(FakeWorker.instances) == 1


def test_start_refuses_a_closed_window():
    session = GameSession(window(hwnd=0))

    with pytest.raises(RuntimeError):
        session.start(raid_config())

    assert session.status == ERROR


def test_start_refuses_a_task_that_has_no_worker():
    """The registry lists tasks that are declared but not written yet."""
    session = GameSession(window(), task_id=unbuilt_task_id())

    with pytest.raises(RuntimeError, match="chưa được cài đặt"):
        session.start({})

    assert not FakeWorker.instances, "an unimplemented task started something"


def test_start_refuses_a_window_pointing_at_nothing():
    session = GameSession(window())
    session.selected = ""

    with pytest.raises(RuntimeError, match="chưa được gán"):
        session.start({})


def test_the_chosen_task_is_what_runs():
    session = GameSession(window(), task_id=unbuilt_task_id())

    with pytest.raises(RuntimeError):
        session.start({})

    session.select(RAID)
    session.start(raid_config())
    assert session.is_running


def test_stats_survive_the_worker_being_torn_down():
    session = GameSession(window())
    session.start(raid_config())
    worker = FakeWorker.instances[-1]
    worker.progress = 12
    worker.elapsed_seconds = 87.0

    session.stop()

    assert session.status == IDLE
    assert session.progress == 12, "progress was lost on stop"
    assert session.elapsed_seconds == 87.0


class CountlessWorker:
    """A worker with no `progress` at all — which is what Realm Raid now is.

    Every other fake here happens to define `progress`, so without this the
    optional half of the protocol is never actually exercised.
    """

    elapsed_seconds = 12.0
    is_paused = False

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self._alive = False

    def start(self):
        self._alive = True

    def stop(self):
        self._alive = False

    def join(self, timeout=None):
        self._alive = False

    def is_alive(self):
        return self._alive

    def latest_frame(self):
        return None


@pytest.fixture
def countless(monkeypatch):
    monkeypatch.setattr(realm_raid, "RealmRaidWorker", CountlessWorker)


def test_a_worker_that_reports_no_count_reads_as_zero(countless):
    session = GameSession(window())
    session.start(raid_config())

    assert session.progress == 0
    assert session.elapsed_seconds == 12.0


def test_stopping_a_worker_that_reports_no_count_does_not_raise(countless):
    """stop() reads the stats through before the worker goes away."""
    session = GameSession(window())
    session.start(raid_config())

    session.stop()

    assert session.status == IDLE
    assert session.progress == 0
    assert session.elapsed_seconds == 12.0


def test_finishing_a_worker_that_reports_no_count_does_not_raise(countless):
    session = GameSession(window())
    session.start(raid_config())

    assert session.mark_finished("Hết vé phá kết giới.") == RAID
    assert session.progress == 0


def test_stats_for_copes_with_no_count(countless):
    session = GameSession(window())
    session.start(raid_config())

    assert session.stats_for(RAID) == (0, 12.0)


def test_progress_resets_when_a_new_run_begins():
    session = GameSession(window())
    session.start(raid_config())
    FakeWorker.instances[-1].progress = 9
    session.stop()

    session.start(raid_config())

    assert session.progress == 0, "the previous run's count carried over"


def test_pause_toggles_between_running_and_paused():
    session = GameSession(window())
    session.start(raid_config())

    session.toggle_pause()
    assert session.status == "paused"
    session.toggle_pause()
    assert session.status == RUNNING


def test_finishing_records_the_message_and_names_the_task():
    session = GameSession(window())
    session.start(raid_config())

    finished = session.mark_finished("Hết vé")

    assert finished == RAID
    assert session.status == DONE
    assert session.message == "Hết vé"
    assert not session.is_running


def test_sync_flags_a_window_that_disappeared(monkeypatch):
    session = GameSession(window())
    monkeypatch.setattr(session_module, "is_alive", lambda hwnd: False)

    session.sync_status()

    assert session.status == ERROR
    assert session.message == "Mất cửa sổ"


def test_sync_leaves_a_finished_session_alone():
    session = GameSession(window())
    session.mark_finished("xong")
    session.sync_status()
    assert session.status == DONE


@pytest.mark.parametrize(
    "seconds, expected",
    [(0, "00:00"), (9, "00:09"), (75, "01:15"), (3600, "1:00:00"), (3725, "1:02:05")],
)
def test_elapsed_formatting(seconds, expected):
    assert GameSession.format_elapsed(seconds) == expected


# ── previews ────────────────────────────────────────────────────────────────


def test_preview_uses_the_workers_frame_while_running():
    """Capturing here as well would drive the same GDI handles from two threads."""
    session = GameSession(window())
    session.start(raid_config())
    assert session.preview_frame() == "frame"


def test_preview_captures_directly_when_idle():
    session = GameSession(window())
    assert session.preview_frame() == "idle-frame"


# ── manager ─────────────────────────────────────────────────────────────────


def managed(monkeypatch, windows, configs=None):
    manager = SessionManager(configs)
    monkeypatch.setattr(
        "auto.manager.window_scanner.scan", lambda patterns=None: list(windows)
    )
    manager.scan()
    return manager


def test_scan_creates_one_session_per_window(monkeypatch):
    manager = managed(monkeypatch, [window(1), window(2)])
    assert [s.hwnd for s in manager.sessions] == [1, 2]
    assert manager.running_count == 0


def test_rescanning_keeps_the_chosen_task(monkeypatch):
    manager = managed(monkeypatch, [window(1)])
    manager.select(1, "beans")

    manager.scan()

    assert manager.get(1).selected == "beans", "the rescan reset the choice"


def test_rescanning_drops_a_window_that_closed(monkeypatch):
    scan_result = [window(1), window(2)]
    manager = SessionManager()
    monkeypatch.setattr(
        "auto.manager.window_scanner.scan", lambda patterns=None: scan_result
    )
    manager.scan()

    scan_result = [window(1)]
    manager.scan()

    assert [s.hwnd for s in manager.sessions] == [1]


def test_a_running_window_is_kept_even_if_the_scan_misses_it(monkeypatch):
    """Losing the card mid-run would hide the failure instead of showing it."""
    scan_result = [window(1)]
    manager = SessionManager()
    monkeypatch.setattr(
        "auto.manager.window_scanner.scan", lambda patterns=None: scan_result
    )
    manager.scan()
    manager.start(1)

    scan_result = []
    manager.scan()

    assert [s.hwnd for s in manager.sessions] == [1]


# ── shared task settings ────────────────────────────────────────────────────


def test_settings_are_shared_by_every_window_running_that_task(monkeypatch):
    manager = managed(monkeypatch, [window(1), window(2)])
    manager.set_option(RAID, "auto_refresh", False)

    manager.start_all()

    assert [w.kwargs["auto_refresh"] for w in FakeWorker.instances] == [False, False]


def test_stored_settings_are_coerced_on_the_way_in(monkeypatch):
    """An old settings file must never feed a worker a key it no longer has.

    "target" is the real case: the raid's deployment-slot option, removed once
    measuring showed a tap there could not place anything. A file written by
    3.10 still carries it. The toggle beside it proves the keys that *are* still
    offered come through, and come through typed.
    """
    manager = managed(monkeypatch, [window(1)],
                      configs={RAID: {"target": "9", "auto_refresh": "0"}})

    manager.start(1)

    kwargs = FakeWorker.instances[-1].kwargs
    assert "slot" not in kwargs and "target" not in kwargs
    assert kwargs["auto_refresh"] is False, "a stored string stayed a string"


def test_config_for_hands_back_a_copy(monkeypatch):
    manager = managed(monkeypatch, [window(1)])
    manager.config_for(RAID)["auto_refresh"] = False
    assert manager.config_for(RAID)["auto_refresh"] is True,         "the shared config was mutated"


# ── starting and stopping ───────────────────────────────────────────────────


def test_start_all_skips_windows_already_running(monkeypatch):
    manager = managed(monkeypatch, [window(1), window(2)])
    manager.start(1)

    manager.start_all()

    assert len(FakeWorker.instances) == 2, "an already-running window was restarted"
    assert manager.running_count == 2


def test_start_all_reports_the_windows_it_could_not_start(monkeypatch):
    manager = managed(monkeypatch, [window(1), window(0, "đã đóng")])

    errors = manager.start_all()

    assert len(errors) == 1 and "đã đóng" in errors[0]
    assert manager.running_count == 1, "one bad window stopped the others"


def test_starting_one_task_only_touches_windows_set_to_it(monkeypatch):
    manager = managed(monkeypatch, [window(1), window(2)])
    manager.select(2, "beans")

    manager.start_all(task_id=RAID)

    assert manager.running_count == 1
    assert manager.get(1).is_running and not manager.get(2).is_running


def test_start_all_skips_a_window_whose_task_has_no_worker(monkeypatch):
    """Its start button is disabled too — a sweep must not raise a dialog per window."""
    manager = managed(monkeypatch, [window(1), window(2)])
    manager.select(2, unbuilt_task_id())

    errors = manager.start_all()

    assert errors == [], "an unimplemented task was reported as a failure"
    assert manager.running_count == 1


def test_a_sweep_leaves_a_window_set_to_another_task_alone(monkeypatch):
    """A sweep from one page must not take a window off the job it is set to.

    Switching a window over is a deliberate act with its own button; a start
    button on a page it is not listed under should not do it silently.
    """
    manager = managed(monkeypatch, [window(1)])
    manager.select(1, "beans")

    errors = manager.start_all(task_id=RAID)

    assert not errors
    assert manager.get(1).selected == "beans"
    assert not manager.get(1).is_running


def test_stopping_one_task_leaves_the_others_running(monkeypatch):
    manager = managed(monkeypatch, [window(1), window(2)])
    manager.select(2, "beans")
    manager.start_all(task_id=RAID)
    manager.start_all(task_id="beans")

    manager.stop_all(task_id="beans")

    assert manager.get(1).is_running, "a window without that task was stopped"
    assert not manager.get(2).is_running


def test_counts_are_reported_per_task(monkeypatch):
    manager = managed(monkeypatch, [window(1), window(2)])
    manager.select(2, "beans")
    manager.start(1)

    assert len(manager.sessions_for(RAID)) == 1
    assert len(manager.sessions_for("beans")) == 1
    assert manager.running_count_for(RAID) == 1
    assert manager.running_count_for("beans") == 0


def test_stop_all_and_shutdown_clear_everything(monkeypatch):
    manager = managed(monkeypatch, [window(1), window(2)])
    manager.start_all()

    manager.stop_all()
    assert manager.running_count == 0

    manager.shutdown()
    assert manager.sessions == []


# ── chaining ────────────────────────────────────────────────────────────────


@pytest.fixture
def two_real_tasks(monkeypatch):
    """Make a second task implemented, so chaining has somewhere to go."""
    beans = tasks.BY_ID["beans"]
    runnable = tasks.TaskSpec(
        id=beans.id, name=beans.name, kicker=beans.kicker, summary=beans.summary,
        progress_label=beans.progress_label,
        build=lambda **kwargs: FakeWorker(**kwargs),
    )
    monkeypatch.setitem(tasks.BY_ID, "beans", runnable)
    return runnable


def test_a_finished_run_does_not_start_anything_else(monkeypatch):
    """A window runs the one task it is set to, and then stops.

    An earlier version kept a list per window and started the next entry when
    one finished. Nobody was chaining tasks — they opened the task they wanted
    and ran it — and the chaining made the start button on a task's own page
    launch something else.
    """
    manager = managed(monkeypatch, [window(1)])
    manager.start(1)
    before = len(FakeWorker.instances)

    manager.get(1).mark_finished("xong")

    assert not manager.get(1).is_running
    assert len(FakeWorker.instances) == before, "something else was started"
    assert not hasattr(manager, "advance"), "the chaining entry point came back"


def test_shards_are_only_reported_for_the_task_that_won_them():
    session = GameSession(window(), task_id="beans")
    session._stats_task = "beans"
    session._shards = {"Koi": 3}

    assert session.shards_for("beans") == {"Koi": 3}
    assert session.shards_for(RAID) == {}


def test_a_task_that_collects_nothing_reports_an_empty_tally():
    """`shards` is optional in the worker protocol, like `progress`."""
    session = GameSession(window(), task_id=RAID)

    assert session.shards == {}


# ── windows that have been closed ───────────────────────────────────────────
#
# A card used to sit there until the next scan, and a *running* one sat there
# indefinitely — deliberately, so a failing run would not silently vanish. What
# that produced in practice, on a live instance for half an hour:
#
#     WARNING Capture failed ((1400, 'GetWindowDC', 'Invalid window handle.'))
#
# once or twice a second, for a window the user had closed. Nothing was shown,
# nothing recovered, and the dead handle went on counting as a game window —
# which is what left the screenshot hotkey unable to say which of "two" games
# to photograph. A handle Windows has destroyed is never reissued, so there is
# nothing to wait for: stop it, say so if it was working, and drop it.


def test_a_closed_window_is_dropped_without_waiting_for_a_scan(monkeypatch):
    manager = managed(monkeypatch, [window(1), window(2)])
    monkeypatch.setattr("auto.manager.window_scanner.is_gone",
                        lambda hwnd: hwnd == 2)

    dropped = manager.drop_closed_windows()

    assert [s.hwnd for s in dropped] == [2]
    assert [s.hwnd for s in manager.sessions] == [1]


def test_a_window_that_is_merely_hidden_is_kept(monkeypatch):
    """Hidden is not closed. A minimised game, or one on another desktop, comes
    back — and dropping its card would throw away the task chosen for it."""
    manager = managed(monkeypatch, [window(1)])
    monkeypatch.setattr(session_module, "is_alive", lambda hwnd: False)
    monkeypatch.setattr("auto.manager.window_scanner.is_gone", lambda hwnd: False)

    assert manager.drop_closed_windows() == []
    assert [s.hwnd for s in manager.sessions] == [1]


def test_dropping_a_closed_window_stops_the_task_it_was_running(monkeypatch):
    """The half that was actually costing something: the worker kept going,
    capturing a handle that no longer existed, until the app was restarted."""
    manager = managed(monkeypatch, [window(1)])
    manager.start(1)
    worker = FakeWorker.instances[-1]
    monkeypatch.setattr("auto.manager.window_scanner.is_gone", lambda hwnd: True)

    manager.drop_closed_windows()

    assert worker.stopped, "left a worker running on a destroyed window"
    assert manager.sessions == []


def test_a_closed_window_is_reported_as_having_been_running(monkeypatch):
    """So the dashboard can tell the user their run ended, rather than letting
    a working card disappear without a word."""
    manager = managed(monkeypatch, [window(1), window(2)])
    manager.start(1)
    monkeypatch.setattr("auto.manager.window_scanner.is_gone", lambda hwnd: True)

    dropped = manager.drop_closed_windows()

    assert [s.hwnd for s in dropped] == [1, 2]
    assert [s.hwnd for s in dropped if s.was_running] == [1]


# ── closed, versus merely out of sight ──────────────────────────────────────


def fake_win32(monkeypatch, *, exists, visible):
    from auto import window_scanner

    monkeypatch.setattr(window_scanner.win32gui, "IsWindow", lambda h: exists)
    monkeypatch.setattr(window_scanner.win32gui, "IsWindowVisible",
                        lambda h: visible)
    return window_scanner


def test_a_destroyed_handle_is_gone(monkeypatch):
    scanner = fake_win32(monkeypatch, exists=False, visible=False)

    assert scanner.is_gone(1) is True


def test_a_hidden_window_still_exists(monkeypatch):
    """The distinction the whole thing turns on.

    `is_alive` is False for a minimised game or one on another virtual desktop,
    and that window comes back. Treating it as closed would stop its task and
    throw away the card — so `is_gone` must ask a different question, not the
    same one negated.
    """
    scanner = fake_win32(monkeypatch, exists=True, visible=False)

    assert scanner.is_alive(1) is False
    assert scanner.is_gone(1) is False, "dropped a window that was only hidden"


def test_an_open_window_is_neither(monkeypatch):
    scanner = fake_win32(monkeypatch, exists=True, visible=True)

    assert scanner.is_alive(1) is True
    assert scanner.is_gone(1) is False
