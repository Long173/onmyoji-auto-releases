"""The task registry.

This is the file a new automation gets added to, so what is tested here is the
contract that makes that safe: settings written by an older build cannot feed a
stale value into a worker, and a task declared without an implementation must
be impossible to start rather than quietly doing nothing.
"""
from __future__ import annotations

import pytest

import tasks


# ── the registry itself ─────────────────────────────────────────────────────


def test_realm_raid_is_the_default_and_is_implemented():
    assert tasks.DEFAULT_TASK_ID == "realm_raid"
    assert tasks.is_available("realm_raid")


def test_every_task_id_is_unique():
    ids = [spec.id for spec in tasks.TASKS]
    assert len(ids) == len(set(ids))


def test_a_declared_task_without_a_worker_is_not_available():
    """The registry's extension point, checked on a spec built here.

    It used to require that the shipped registry hold at least one unbuilt task
    and read the property off that. Every shipped task is implemented now, so
    that assertion would fail for a reason that says nothing about the code —
    and passing it by keeping a placeholder in the product is the wrong way
    round.
    """
    declared = tasks.TaskSpec(id="chua-lam", name="Chưa làm", kicker="k",
                              summary="Chưa có worker.",
                              todo="Cần viết worker.")

    assert not declared.is_available
    assert declared.defaults() == {}, "controls that change nothing"


def test_any_unbuilt_task_in_the_registry_says_what_it_needs():
    for spec in tasks.TASKS:
        if spec.is_available:
            continue
        assert not tasks.is_available(spec.id)
        assert spec.todo, "%s gives no hint of what implementing it needs" % spec.id


def test_an_unimplemented_task_declares_no_settings():
    """Controls that change nothing would read as working configuration."""
    for spec in tasks.TASKS:
        if not spec.is_available:
            assert spec.defaults() == {}


def test_an_unknown_id_is_not_available():
    assert not tasks.is_available("khong-co-thuc")
    assert tasks.get("khong-co-thuc") is None


# ── the two settings layers ─────────────────────────────────────────────────


def test_the_invite_reply_is_app_wide_not_a_raid_setting():
    """The dialog blocks every task, so the answer cannot belong to one of them."""
    app_keys = {f.key for f in tasks.APP_FIELDS if f.holds_value}
    assert "wanted_invite" in app_keys
    for spec in tasks.TASKS:
        assert "wanted_invite" not in spec.defaults(), (
            "%s still declares its own invite reply" % spec.id
        )


def test_no_task_key_shadows_an_app_key():
    """The layers are merged with the task on top, so a clash would silently win.

    A task field named like an app field would override the app-wide value for
    that task only — invisible in the settings dialog, and impossible to guess
    from the UI.
    """
    app_keys = {f.key for f in tasks.APP_FIELDS if f.holds_value}
    for spec in tasks.TASKS:
        clashes = app_keys & set(spec.defaults())
        assert not clashes, "%s shadows app setting(s) %s" % (spec.id, clashes)


def test_the_merge_puts_the_task_layer_on_top():
    merged = tasks.merge_layers({"a": 1, "b": 2}, {"b": 99})
    assert merged == {"a": 1, "b": 99}


def test_the_merge_does_not_mutate_either_layer():
    app, task = {"a": 1}, {"b": 2}
    tasks.merge_layers(app, task)
    assert app == {"a": 1} and task == {"b": 2}


def test_app_settings_are_coerced_like_task_settings():
    assert tasks.coerce_app({"wanted_invite": "khong-co-thuc"})["wanted_invite"] == (
        tasks.REFUSE
    )
    assert tasks.coerce_app({"notify_on_finish": "false"})["notify_on_finish"] is False
    assert tasks.coerce_app(None) == tasks.app_defaults()


# ── per-window versus shared settings ───────────────────────────────────────


def souls():
    return tasks.BY_ID["souls"]


def test_the_room_role_belongs_to_the_window_not_the_task():
    """A co-op room has exactly one leader, so this cannot be one shared value."""
    assert [f.key for f in souls().window_fields] == ["role"]
    assert "role" not in {f.key for f in souls().shared_fields}


def test_shared_and_window_fields_together_are_all_of_them():
    spec = souls()
    assert set(f.key for f in spec.shared_fields) | set(
        f.key for f in spec.window_fields
    ) == set(f.key for f in spec.fields)


def test_window_fields_never_include_a_note():
    """Notes carry no value, so they have nothing to store per window."""
    for spec in tasks.TASKS:
        assert all(f.holds_value for f in spec.window_fields)


def test_a_task_with_no_per_window_settings_says_so():
    assert tasks.BY_ID["realm_raid"].window_fields == ()


# ── running forever ─────────────────────────────────────────────────────────


def test_the_round_count_defaults_to_thirty():
    assert souls().coerce(None)["rounds"] == 30
    assert souls().coerce(None)["unlimited"] is False


def test_the_round_count_is_switched_off_by_the_forever_checkbox():
    """The number is greyed out rather than left looking live but ignored."""
    rounds = next(f for f in souls().fields if f.key == "rounds")
    assert rounds.disabled_when == ("unlimited", True)


def test_a_round_count_below_one_is_clamped():
    """Zero used to mean "forever"; the checkbox says that now."""
    assert souls().coerce({"rounds": 0})["rounds"] == 1
    assert souls().coerce({"rounds": -5})["rounds"] == 1


def test_a_round_count_above_the_maximum_is_clamped():
    assert souls().coerce({"rounds": 5000})["rounds"] == 999


def test_a_nonsense_round_count_falls_back_to_the_default():
    assert souls().coerce({"rounds": "nhieu"})["rounds"] == 30


# ── config coercion ─────────────────────────────────────────────────────────


def raid():
    return tasks.BY_ID["realm_raid"]


def test_defaults_cover_every_value_field():
    config = raid().defaults()
    keys = {f.key for f in raid().fields if f.holds_value}
    assert set(config) == keys
    assert config["auto_refresh"] is True


def test_a_note_holds_no_value():
    notes = [f for f in raid().fields if f.kind == tasks.NOTE]
    assert notes and all(not f.holds_value for f in notes)


def test_saved_settings_win_over_defaults():
    config = raid().coerce({"auto_refresh": False})
    assert config["auto_refresh"] is False
    assert config["stop_when_out_of_tickets"] is True, "untouched default was lost"


def test_a_value_no_longer_offered_falls_back():
    """An old settings file must not put a choice the UI cannot make into a worker.

    Shown on Ném đậu, which is where a multi-valued option still lives — the
    raid's own one was removed. See geometry for why.
    """
    beans = tasks.BY_ID["beans"]
    config = beans.coerce({"beans": "999 đậu"})

    assert config["beans"] == beans.defaults()["beans"]


def test_unknown_keys_are_dropped():
    """Including "target", which a settings file written by 3.10 still holds."""
    config = raid().coerce({"target": "2", "khong_con_dung": "gi do"})

    assert "khong_con_dung" not in config
    assert "target" not in config


def test_toggles_are_forced_to_bool():
    config = raid().coerce({"auto_refresh": 0, "stop_when_out_of_tickets": 1})
    assert config["auto_refresh"] is False
    assert config["stop_when_out_of_tickets"] is True


@pytest.mark.parametrize(
    "stored, expected",
    [("false", False), ("true", True), ("FALSE", False), (" True ", True),
     ("0", False), ("1", True), ("", False),
     (False, False), (True, True), (0, False), (1, True)],
)
def test_a_toggle_stored_as_text_reads_back_correctly(stored, expected):
    """The Windows registry returns 'false' as a string, and bool('false') is True.

    Without this, a setting the user switched off comes back on after a
    restart. The test suite's own settings backend (an INI file) hands back
    real booleans, so only a check at this level can catch it.
    """
    assert raid().coerce({"auto_refresh": stored})["auto_refresh"] is expected


def test_as_bool_is_what_does_it():
    assert tasks.as_bool("false") is False
    assert tasks.as_bool("yes") is True
    assert tasks.as_bool(None) is False


def test_nothing_saved_yields_the_defaults():
    assert raid().coerce(None) == raid().defaults()


# ── the raid builder ────────────────────────────────────────────────────────


class FakeWorker:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


@pytest.fixture
def captured(monkeypatch):
    import realm_raid

    made = []
    monkeypatch.setattr(
        realm_raid, "RealmRaidWorker",
        lambda **kwargs: made.append(FakeWorker(**kwargs)) or made[-1],
    )
    return made


def build(captured, app=None, **overrides):
    # merge_layers because that is the dict the manager actually passes; feeding
    # a builder only its own layer would hide a broken merge.
    config = tasks.merge_layers(tasks.coerce_app(app), raid().coerce(overrides))
    tasks.build_realm_raid(
        hwnd=42, control="ctl", config=config, on_finished=None, on_error=None
    )
    return captured[-1].kwargs


def test_a_removed_option_never_reaches_the_worker(captured):
    """The worker no longer takes a slot, and a stale setting must not revive one."""
    kwargs = build(captured, target="5")

    assert "slot" not in kwargs and "target" not in kwargs


def test_the_invite_chip_becomes_a_boolean(captured):
    """It is an app-wide setting now, so it arrives through the app layer."""
    accepting = build(captured, app={"wanted_invite": tasks.ACCEPT})
    refusing = build(captured, app={"wanted_invite": tasks.REFUSE})

    assert accepting["accept_wanted_quest"] is True
    assert refusing["accept_wanted_quest"] is False


def test_refusing_the_invite_is_the_default(captured):
    """Accepting drags the account into somebody else's quest."""
    assert build(captured)["accept_wanted_quest"] is False


def test_the_shared_control_is_handed_over(captured):
    """One capture path for the preview and the loop, not two."""
    assert build(captured)["control"] == "ctl"


def test_toggles_reach_the_worker(captured):
    kwargs = build(captured, auto_refresh=False, stop_when_out_of_tickets=False)
    assert kwargs["auto_refresh"] is False
    assert kwargs["stop_when_out_of_tickets"] is False


# ── the souls builder ───────────────────────────────────────────────────────


@pytest.fixture
def souls_worker(monkeypatch):
    """Capture the kwargs the souls builder hands its worker."""
    import souls_dungeon

    made = []
    monkeypatch.setattr(
        souls_dungeon, "SoulsDungeonWorker", lambda **kwargs: made.append(kwargs)
    )
    return made


def build_souls(made, **overrides):
    config = tasks.merge_layers(tasks.coerce_app(None), souls().coerce(overrides))
    tasks.build_souls_dungeon(
        hwnd=1, control="ctl", config=config, on_finished=None, on_error=None
    )
    return made[-1]


def test_the_forever_checkbox_reaches_the_worker(souls_worker):
    """Otherwise ticking it would still stop after the count it is meant to ignore."""
    assert build_souls(souls_worker, unlimited=True, rounds=30)["rounds"] == 0


def test_without_the_checkbox_the_count_is_passed_through(souls_worker):
    assert build_souls(souls_worker, unlimited=False, rounds=12)["rounds"] == 12


def test_the_role_becomes_the_workers_own_constant(souls_worker):
    import souls_dungeon

    assert build_souls(souls_worker, role=tasks.LEADER)["role"] == souls_dungeon.ROLE_LEADER
    assert build_souls(souls_worker, role=tasks.MEMBER)["role"] == souls_dungeon.ROLE_MEMBER


def test_the_app_wide_invite_reply_reaches_the_souls_worker(souls_worker):
    """It blocks this task too, so the setting has to flow all the way down."""
    config = tasks.merge_layers(
        tasks.coerce_app({"wanted_invite": tasks.ACCEPT}), souls().coerce(None)
    )
    tasks.build_souls_dungeon(
        hwnd=1, control="ctl", config=config, on_finished=None, on_error=None
    )

    assert souls_worker[-1]["accept_wanted_quest"] is True


# ── reading back a saved choice ─────────────────────────────────────────────


def test_clean_task_drops_an_id_that_no_longer_exists():
    """A choice is saved per window title and outlives the build that wrote it."""
    assert tasks.clean_task("da_xoa") is None
    assert tasks.clean_task("realm_raid") == "realm_raid"


def test_clean_task_reads_a_queue_saved_by_an_older_build():
    """Windows used to hold a list of tasks. Take the first one still known,
    so somebody returning from that build keeps their choice."""
    assert tasks.clean_task(["beans", "realm_raid"]) == "beans"
    assert tasks.clean_task(["da_xoa", "realm_raid"]) == "realm_raid"


def test_clean_task_copes_with_nothing():
    assert tasks.clean_task(None) is None
    assert tasks.clean_task([]) is None
    assert tasks.clean_task(["da_xoa"]) is None


def test_every_implemented_task_is_stubbed_for_the_ui_tests():
    """A task with a `build` must have its worker swapped out in conftest.

    Miss one and the UI tests construct the real worker, which captures a
    window that is not there, fails, and calls back into Qt from its own
    thread. On Windows that is an access violation: the whole run dies without
    naming a test, which is a miserable way to find out.
    """
    from conftest import STUBBED_WORKERS

    implemented = {spec.id for spec in tasks.TASKS if spec.build is not None}

    assert implemented == set(STUBBED_WORKERS), (
        "implemented tasks and stubbed workers have drifted apart — "
        "only stubbed: %s, only implemented: %s"
        % (sorted(set(STUBBED_WORKERS) - implemented),
           sorted(implemented - set(STUBBED_WORKERS)))
    )
