"""The task centre UI.

The point of the restructure is that a new automation needs no widget code, so
what is pinned here is the wiring that makes that true: pages built from the
registry, settings that survive a restart, queues remembered per window, and —
most importantly — a task with no worker behind it being impossible to start
from anywhere in the interface.

The dashboard fixture and its stubs live in conftest.py.
"""
from __future__ import annotations

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")

import tasks  # noqa: E402
from conftest import SpyWorker, unbuilt_task_id  # noqa: E402
from ui.task_sidebar import HOME, wiki_key  # noqa: E402

RAID = "realm_raid"
BEANS = "beans"
UNBUILT = unbuilt_task_id()


@pytest.fixture
def relaunched(dashboard, isolated_settings):
    """A view of the settings as a *later launch* would see them.

    QSettings serves unsynced writes from its own cache, so reading back
    through the object that wrote them proves nothing about what reaches disk
    or in what type. This flushes, then reopens the store.
    """
    from PyQt5 import QtCore

    class Reader:
        def __init__(self, window):
            self._window = window

        def _load_configs(self):
            return self._window._load_configs()

        def _remembered_task(self, title):
            return self._window._remembered_task(title)

        def _remembered_options(self, title):
            return self._window._remembered_options(title)

    def open_again():
        dashboard._settings.sync()
        dashboard._settings = QtCore.QSettings(
            str(isolated_settings), QtCore.QSettings.IniFormat
        )
        return Reader(dashboard)

    return open_again


# ── the app name comes from one place ───────────────────────────────────────


def test_the_window_title_and_brand_follow_theme(dashboard):
    """Renaming the app should mean editing theme.APP_NAME and nothing else."""
    import theme

    assert theme.APP_NAME in dashboard.windowTitle()
    assert theme.APP_SUBTITLE in dashboard.windowTitle()

    brand = " ".join(
        child.text()
        for child in dashboard._sidebar.findChildren(QtWidgets.QLabel)
    )
    assert theme.APP_NAME.upper() in brand
    assert theme.APP_SUBTITLE in brand


def test_no_stale_name_is_hardcoded_in_the_shell(dashboard):
    """The old name must not survive anywhere the user can read it."""
    visible = [dashboard.windowTitle()] + [
        child.text() for child in dashboard.findChildren(QtWidgets.QLabel)
    ]
    stale = [text for text in visible if "Onmyoji Auto" in text]
    assert not stale, "the old app name is still on screen: %s" % stale


# ── the sidebar comes from the registry ─────────────────────────────────────


def test_every_task_gets_a_row(dashboard):
    rows = dashboard._sidebar._rows
    for spec in tasks.TASKS:
        assert spec.id in rows, "%s is missing from the sidebar" % spec.id
    assert HOME in rows


def test_the_wiki_sections_are_rows_in_the_one_sidebar(dashboard):
    """No second navigation column: 460px of nav was mostly empty."""
    from ui.wiki_page import SECTIONS

    for section, _name in SECTIONS:
        assert wiki_key(section) in dashboard._sidebar._rows


def test_the_sidebar_footer_survives_the_smallest_window(dashboard):
    """Adding rows once pushed "Quét cửa sổ" off the bottom instead of scrolling."""
    dashboard.resize(1120, 700)
    dashboard.show()
    QtWidgets.QApplication.processEvents()

    sidebar = dashboard._sidebar
    scan = [b for b in sidebar.findChildren(QtWidgets.QPushButton)
            if "Quét" in b.text()]
    assert scan, "the scan button is gone"
    button = scan[0]
    bottom = button.mapTo(sidebar, button.rect().bottomLeft()).y()
    assert bottom <= sidebar.height(), (
        "the scan button is cut off: ends at %dpx in a %dpx sidebar"
        % (bottom, sidebar.height())
    )
    assert button.height() >= 20, "the button was squashed to nothing"


def test_the_nav_scrolls_rather_than_clipping(dashboard):
    scroll = dashboard._sidebar.findChild(QtWidgets.QScrollArea)
    assert scroll is not None, "the nav list cannot scroll"
    assert scroll.widget().sizeHint().height() > 0


def test_an_unimplemented_task_is_marked_inert(dashboard):
    row = dashboard._sidebar._rows[UNBUILT]
    assert not row._enabled
    assert row._count.text() == "—", "it showed a window count it cannot act on"
    assert "Chưa cài đặt" in row.toolTip()


def test_the_count_beside_each_task_is_the_windows_set_to_it(dashboard):
    """It used to count every window with the task somewhere in its queue, so
    two windows could both count towards several tasks at once."""
    assert dashboard._sidebar._rows[RAID]._count.text() == "2"

    dashboard._manager.select(101, "souls")
    dashboard._rebuild()

    assert dashboard._sidebar._rows[RAID]._count.text() == "1"
    assert dashboard._sidebar._rows["souls"]._count.text() == "1"


# ── navigation ──────────────────────────────────────────────────────────────


def test_opening_a_task_builds_its_page_once(dashboard):
    dashboard._show_page(RAID)
    first = dashboard._views[RAID]

    dashboard._show_page(HOME)
    dashboard._show_page(RAID)

    assert dashboard._views[RAID] is first, "the page was rebuilt on every visit"
    assert dashboard._stack.currentWidget() is first


def test_opening_a_page_shows_its_windows_straight_away(dashboard):
    """It used to need a rescan first: the page opened with an empty list."""
    dashboard._show_page(RAID)

    cards = dashboard._views[RAID]._cards
    assert set(cards) == {s.hwnd for s in dashboard._manager.sessions}


def test_the_header_follows_the_page(dashboard):
    dashboard._show_page(RAID)
    assert "Phá Kết Giới" == dashboard._header._title.text()
    assert dashboard._header._toggle.isEnabled()

    dashboard._show_page(HOME)
    assert "Bảng điều khiển" == dashboard._header._title.text()


def test_the_header_start_button_is_dead_for_an_unbuilt_task(dashboard):
    dashboard._show_page(UNBUILT)

    assert not dashboard._header._toggle.isEnabled()


def test_the_header_button_turns_into_stop_once_everything_runs(dashboard):
    """One cell here too, and it follows the page it sits above."""
    dashboard._show_page(RAID)
    assert "Bắt đầu" in dashboard._header._toggle.text()

    for hwnd in (101, 102):
        dashboard._manager.select(hwnd, RAID)
        dashboard._on_start(hwnd)
    dashboard._rebuild()

    assert "Dừng" in dashboard._header._toggle.text()
    assert dashboard._header._toggle.isEnabled()


def test_the_header_button_still_offers_to_start_the_rest(dashboard):
    """Mixed is the case a single button has to take a side on.

    It takes the harmless one: with a window left to start it still reads
    "Bắt đầu", because start-all skips whatever is already running, while a
    "Dừng" shown here would stop running tasks from a press meant to start the
    others.
    """
    dashboard._manager.select(101, RAID)
    dashboard._manager.select(102, RAID)
    dashboard._show_page(RAID)
    dashboard._on_start(101)                    # one of the two
    dashboard._rebuild()

    assert "Bắt đầu" in dashboard._header._toggle.text()
    assert dashboard._header._toggle.isEnabled()


def test_the_header_button_stops_everything_when_it_reads_stop(dashboard):
    dashboard._show_page(RAID)
    for hwnd in (101, 102):
        dashboard._manager.select(hwnd, RAID)
        dashboard._on_start(hwnd)
    dashboard._rebuild()

    dashboard._header._toggle.click()

    assert dashboard._manager.running_count == 0


def test_an_unknown_page_is_ignored(dashboard):
    """A stale saved page must not leave the stack pointing at nothing."""
    dashboard._show_page(HOME)
    dashboard._show_page("khong-co-thuc")
    assert dashboard._stack.currentWidget() is dashboard._home


# ── starting is refused where there is no worker ────────────────────────────


def test_start_all_on_an_unbuilt_page_starts_nothing(dashboard):
    dashboard._manager.select(101, UNBUILT)
    dashboard._show_page(UNBUILT)

    dashboard._on_start_all()

    assert dashboard._manager.running_count == 0
    assert not SpyWorker.live


def test_the_row_start_button_is_disabled_when_the_queue_leads_with_an_unbuilt_task(
    dashboard,
):
    dashboard._manager.select(101, UNBUILT)
    dashboard._rebuild()

    row = dashboard._home._rows[101]
    assert not row._toggle.isEnabled()

    dashboard._manager.select(101, RAID)
    dashboard._rebuild()
    assert dashboard._home._rows[101]._toggle.isEnabled()


def test_the_home_row_has_one_button_that_becomes_stop_while_running(dashboard):
    """Same single cell as the task cards, on the overview table.

    The row is the narrower of the two places, so the button that was always
    disabled cost more here than on a card.
    """
    row = dashboard._home._rows[101]
    assert "Bắt đầu" in row._toggle.text()

    dashboard._on_start(101)
    dashboard._rebuild()

    row = dashboard._home._rows[101]
    assert "Kết thúc" in row._toggle.text()
    assert row._toggle.isEnabled()


def test_the_home_row_button_stops_a_running_task(dashboard):
    """It follows the state, not the label it happens to be showing."""
    dashboard._on_start(101)
    dashboard._rebuild()

    dashboard._home._rows[101]._toggle.click()

    assert not dashboard._manager.get(101).is_running


def test_start_all_from_home_skips_the_unbuildable_and_starts_the_rest(dashboard):
    dashboard._manager.select(101, UNBUILT)

    dashboard._on_start_all()

    assert dashboard._manager.running_count == 1
    assert not dashboard._manager.get(101).is_running
    assert dashboard._manager.get(102).is_running


# ── assigning ───────────────────────────────────────────────────────────────


def test_choosing_a_task_moves_the_window_onto_that_page(dashboard):
    dashboard._manager.select(102, UNBUILT)
    dashboard._show_page(RAID)
    view = dashboard._views[RAID]
    assert 102 not in view._cards

    dashboard._on_select(102, RAID)

    assert 102 in view._cards


def test_choosing_a_task_takes_the_window_off_its_old_page(dashboard):
    """A window runs one task, so arriving on one page means leaving another."""
    dashboard._show_page(RAID)
    view = dashboard._views[RAID]
    assert 101 in view._cards

    dashboard._on_select(101, UNBUILT)

    assert 101 not in view._cards
    assert dashboard._manager.get(101).selected == UNBUILT


def test_the_choice_is_written_where_the_next_launch_will_find_it(dashboard, relaunched):
    """Kept by window title, because handles change every launch."""
    dashboard._on_select(101, UNBUILT)

    assert relaunched()._remembered_task("陰陽師Onmyoji") == UNBUILT


def test_a_remembered_choice_is_applied_on_the_next_scan(dashboard):
    dashboard._on_select(101, UNBUILT)
    # Whatever a rescan finds, the saved choice is what the window comes back with.
    dashboard._manager.get(101).selected = RAID

    dashboard._on_scan()

    assert dashboard._manager.get(101).selected == UNBUILT


def test_a_saved_choice_naming_a_deleted_task_is_ignored(dashboard, isolated_settings):
    dashboard._settings.setValue("queues/陰陽師Onmyoji", ["da_xoa"])

    dashboard._on_scan()

    assert dashboard._manager.get(101).selected == RAID, "a dead task id was restored"


def test_realm_raid_shows_no_battle_counter(dashboard):
    """It could only be inferred from reward panels, so the figure drifted."""
    dashboard._show_page(RAID)

    card = dashboard._views[RAID]._cards[101]
    assert card._progress is None
    labels = [child.text() for child in card.findChildren(QtWidgets.QLabel)]
    assert not [text for text in labels if "trận" in text]
    assert any("thời gian chạy" in text for text in labels), "elapsed went too"


def test_a_task_that_does_count_still_shows_its_counter(dashboard):
    """Removing the raid count must not remove the machinery."""
    dashboard._show_page(UNBUILT)
    dashboard._manager.select(101, UNBUILT)
    dashboard._rebuild()

    card = dashboard._views[UNBUILT]._cards[101]
    assert card._progress is not None
    labels = [child.text() for child in card.findChildren(QtWidgets.QLabel)]
    assert any(tasks.BY_ID[UNBUILT].progress_label in text for text in labels)


def test_the_overview_total_reads_as_unavailable_when_nothing_counts(dashboard):
    """A hard zero would look like the app failed to count something."""
    stats = dashboard._stats(dashboard._manager.sessions, 0)

    assert stats[1] == "—"


def test_a_card_shows_only_its_own_tasks_figures(dashboard):
    """Switching a window to another task must not carry the old count over.

    The window raided and earned a number. Moved to a different task, its card
    on that task's page has to start from nothing — the figure belongs to the
    run that produced it, not to the window.
    """
    dashboard._on_start(101)                      # runs realm_raid
    SpyWorker.live[-1].progress = 27
    dashboard._manager.get(101).stop()

    dashboard._on_select(101, UNBUILT)
    dashboard._show_page(UNBUILT)
    dashboard._rebuild()

    card = dashboard._views[UNBUILT]._cards[101]
    assert card._progress.text() == "0"
    assert card._elapsed.text() == "00:00"


# ── settings that belong to one window ──────────────────────────────────────

SOULS = "souls"


def test_the_role_control_is_on_the_card_not_the_panel(dashboard):
    """One value per window, so it cannot live on the task's shared panel."""
    import tasks
    from ui import controls

    dashboard._manager.select(101, SOULS)
    dashboard._show_page(SOULS)
    view = dashboard._views[SOULS]

    from ui.task_view import ConfigPanel

    card = view._cards[101]
    card_chips = [chip.text() for chip in card.findChildren(controls.Chip)]
    assert tasks.LEADER in card_chips and tasks.MEMBER in card_chips

    panel = view.findChild(ConfigPanel)
    assert panel is not None, "the shared config panel is gone"
    panel_chips = [chip.text() for chip in panel.findChildren(controls.Chip)]
    assert tasks.LEADER not in panel_chips, "the role is also on the shared panel"


def test_a_card_does_not_balloon_when_only_one_column_fits(dashboard):
    """A stretched card doubles the size of its 16:9 thumbnail for no reason."""
    from ui.task_view import MAX_CARD_WIDTH

    dashboard._manager.select(101, SOULS)
    dashboard.resize(1120, 700)
    dashboard._show_page(SOULS)
    QtWidgets.QApplication.processEvents()

    card = dashboard._views[SOULS]._cards[101]
    assert card.maximumWidth() == MAX_CARD_WIDTH
    assert card.width() <= MAX_CARD_WIDTH, (
        "card is %dpx wide, cap is %d" % (card.width(), MAX_CARD_WIDTH)
    )


def test_choosing_a_role_reaches_that_window_only(dashboard):
    import tasks

    dashboard._manager.select(101, SOULS)
    dashboard._manager.select(102, SOULS)
    dashboard._show_page(SOULS)

    dashboard._on_window_option_changed(101, "role", tasks.MEMBER)

    assert dashboard._manager.get(101).options_for(SOULS)["role"] == tasks.MEMBER
    assert dashboard._manager.get(102).options_for(SOULS)["role"] == tasks.LEADER


def test_a_window_role_is_remembered_for_the_next_launch(dashboard, relaunched):
    import tasks

    dashboard._manager.select(101, SOULS)
    dashboard._show_page(SOULS)
    dashboard._on_window_option_changed(101, "role", tasks.MEMBER)

    stored = relaunched()._remembered_options("陰陽師Onmyoji")

    assert stored.get(SOULS, {}).get("role") == tasks.MEMBER


def test_a_remembered_role_is_applied_on_the_next_scan(dashboard):
    import tasks

    dashboard._manager.select(101, SOULS)
    dashboard._show_page(SOULS)
    dashboard._on_window_option_changed(101, "role", tasks.MEMBER)
    dashboard._manager.get(101).window_options.clear()

    dashboard._on_scan()

    assert dashboard._manager.get(101).options_for(SOULS)["role"] == tasks.MEMBER


# ── settings ────────────────────────────────────────────────────────────────


@pytest.fixture
def dialogs(dashboard, monkeypatch):
    """Records message boxes and tray notifications *separately*.

    Both have to be watched to prove anything here: with no system tray the
    notifier falls back to a message box on its own, so a test that only counted
    dialogs would pass whichever route the code took.
    """
    shown, notified = [], []
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "information",
        staticmethod(lambda parent, title, body, *a, **k: shown.append((title, body))),
    )
    monkeypatch.setattr(
        dashboard._notifier, "notify",
        lambda title, body, *a, **k: notified.append((title, body)),
    )
    return dashboard, shown, notified


def test_the_hover_pause_setting_reaches_the_control(dashboard, monkeypatch):
    """Read at click time, so it applies at once.

    That is what separates it from a task's settings, which a worker reads when
    it is built — and why this one gets no "stop and start again" dialog.
    """
    import game_control

    seen = []
    monkeypatch.setattr(game_control, "set_pause_while_hovering", seen.append)

    dashboard._on_app_setting("pause_while_hovering", False)

    assert seen == [False]


def test_changing_an_option_mid_run_says_it_will_not_apply_yet(dialogs):
    """A worker reads its settings once, when it is built.

    So a change made while the task runs looks applied and is not — which is how
    somebody comes to believe "Tự dừng khi hết vé" was on for a run that never
    had it. A dialog rather than a tray notification because this one only fires
    in response to the person's own click, so they are at the keyboard: the
    reason notifications.py gives for avoiding modals does not apply.
    """
    dashboard, shown, notified = dialogs
    dashboard._on_start(101)                      # runs realm_raid
    trayed = len(notified)

    dashboard._on_option_changed(RAID, "stop_when_out_of_tickets", False)

    assert shown, "changed an option on a running task and said nothing"
    assert len(notified) == trayed, "went to the tray instead of opening a dialog"
    title, body = shown[-1]
    assert tasks.BY_ID[RAID].name in title
    assert "dừng rồi bật lại" in body, body


def test_changing_an_option_while_nothing_runs_is_quiet(dialogs):
    """Nothing to warn about: the next start reads the new value."""
    dashboard, shown, notified = dialogs

    dashboard._on_option_changed(RAID, "stop_when_out_of_tickets", False)

    assert shown == [] and notified == []


def test_only_the_running_task_is_warned_about(dialogs):
    """Another task's options are not affected by this one running."""
    dashboard, shown, notified = dialogs
    dashboard._on_start(101)                      # runs realm_raid
    trayed = len(notified)

    dashboard._on_option_changed(BEANS, "beans", tasks.BEANS_5)

    assert shown == [] and len(notified) == trayed


def test_changing_an_option_reaches_the_manager_and_the_store(dashboard):
    dashboard._on_option_changed(RAID, "auto_refresh", False)

    assert dashboard._manager.config_for(RAID)["auto_refresh"] is False
    assert tasks.as_bool(
        dashboard._settings.value("tasks/%s/auto_refresh" % RAID)
    ) is False


def test_a_saved_option_is_read_back_on_the_next_launch(dashboard, relaunched):
    dashboard._on_option_changed(RAID, "auto_refresh", False)
    dashboard._on_option_changed(BEANS, "beans", tasks.BEANS_5)

    reloaded = relaunched()._load_configs()

    assert reloaded[RAID]["auto_refresh"] is False, "a bool came back as a string"
    assert reloaded[BEANS]["beans"] == tasks.BEANS_5, "a chip value was lost"


def test_a_saved_option_survives_all_the_way_into_the_worker(dashboard, relaunched):
    """The round trip that matters: what a restart actually clicks in the game."""
    dashboard._on_option_changed(RAID, "auto_refresh", False)
    fresh = relaunched()

    manager = type(dashboard._manager)(fresh._load_configs())

    assert manager.config_for(RAID)["auto_refresh"] is False


EVENT = "event"


def test_a_click_point_is_stored_as_plain_text(dashboard):
    """Not as a pickled blob, which is what QSettings does with a tuple.

    Worth pinning: the value is one a person may well want to read or edit in
    their own settings, and a pickle ties it to the PyQt version that wrote it.
    """
    dashboard._on_option_changed(EVENT, "click_point", (900, 400))

    stored = dashboard._settings.value("tasks/%s/click_point" % EVENT)
    assert stored == "900,400", "stored as %r" % (stored,)


def test_a_click_point_survives_a_restart_and_reaches_the_worker(dashboard,
                                                                relaunched):
    """The round trip that matters: where a restart actually clicks."""
    dashboard._on_option_changed(EVENT, "click_point", (900, 400))
    fresh = relaunched()

    manager = type(dashboard._manager)(fresh._load_configs())

    assert manager.config_for(EVENT)["click_point"] == (900, 400)


def test_a_click_point_reaches_the_worker(dashboard):
    dashboard._on_option_changed(EVENT, "click_point", (900, 400))
    dashboard._on_select(101, EVENT)
    dashboard._on_start(101)

    assert SpyWorker.live[-1].kwargs["point"] == (900, 400)


def test_the_chosen_option_reaches_the_worker(dashboard):
    dashboard._on_option_changed(RAID, "auto_refresh", False)

    dashboard._on_start(101)

    assert SpyWorker.live[-1].kwargs["auto_refresh"] is False


def test_the_invite_setting_reaches_the_worker(dashboard):
    dashboard._on_option_changed(RAID, "wanted_invite", tasks.ACCEPT)

    dashboard._on_start(101)

    assert SpyWorker.live[-1].kwargs["accept_wanted_quest"] is True


# ── upgrading from v2 ───────────────────────────────────────────────────────


def carry_over(dashboard, **legacy):
    """Write v2-shaped keys, then run the migration the way a launch would."""
    for key, value in legacy.items():
        dashboard._settings.setValue(key.replace("__", "/"), value)
    dashboard._settings.remove("tasks")
    dashboard._migrate_legacy_settings()
    return dashboard._load_configs()


def test_the_v2_target_slot_is_dropped_rather_than_carried_over(dashboard):
    """There is nothing left to carry it into.

    v2 kept a raid target per window title under `slots/`. The option it fed was
    removed once measuring against the live game showed a tap there deploys
    nothing — it opens the shikigami picker — so migrating the value would
    restore a setting no code reads. The dead key still has to go.
    """
    config = carry_over(dashboard, slots__陰陽師Onmyoji=4)

    assert "target" not in config.get(RAID, {})
    assert dashboard._settings.value("slots/陰陽師Onmyoji") is None


def test_the_v2_invite_reply_becomes_an_app_setting(dashboard):
    dashboard._settings.remove("wanted_invite")
    dashboard._settings.setValue("accept_wanted_quest", True)

    dashboard._migrate_legacy_settings()

    assert dashboard._load_app_config()["wanted_invite"] == tasks.ACCEPT


def test_an_invite_reply_saved_per_task_moves_up_to_the_app(dashboard):
    """It briefly lived under the Realm Raid task; that value must not be lost."""
    dashboard._settings.remove("wanted_invite")
    dashboard._settings.setValue("tasks/%s/wanted_invite" % RAID, tasks.ACCEPT)

    dashboard._migrate_legacy_settings()

    assert dashboard._load_app_config()["wanted_invite"] == tasks.ACCEPT
    assert dashboard._settings.value("tasks/%s/wanted_invite" % RAID) is None


def test_an_existing_app_level_reply_is_not_overwritten(dashboard):
    dashboard._settings.setValue("wanted_invite", tasks.REFUSE)
    dashboard._settings.setValue("accept_wanted_quest", True)

    dashboard._migrate_legacy_settings()

    assert dashboard._load_app_config()["wanted_invite"] == tasks.REFUSE


def test_dead_v2_keys_are_cleared_out(dashboard):
    for key in ("vitri", "refresh", "slot", "window_title"):
        dashboard._settings.setValue(key, "x")
    dashboard._settings.setValue("slots/陰陽師Onmyoji", 4)

    dashboard._migrate_legacy_settings()

    left = dashboard._settings.allKeys()
    assert not [key for key in left
                if key in ("vitri", "refresh", "slot", "window_title")
                or key.startswith("slots/")]


# ── the config panel is generated ───────────────────────────────────────────


def test_the_panel_renders_a_control_per_declared_field(dashboard):
    """Declaring a field is all a new task should have to do to get a control."""
    from ui import controls

    # Ném đậu rather than the raid: it declares both kinds, so the chip half of
    # this cannot quietly become 0 == 0 the way it did when the raid's only
    # multi-valued option was removed.
    dashboard._show_page(BEANS)
    view = dashboard._views[BEANS]
    spec = tasks.BY_ID[BEANS]

    expected_chips = sum(
        len(f.options) for f in spec.fields if f.kind == tasks.SEGMENTED
    )
    assert expected_chips, "picked a task with no chips to count"
    assert len(view.findChildren(controls.Toggle)) == sum(
        1 for f in spec.fields if f.kind == tasks.TOGGLE
    )
    assert len(view.findChildren(controls.Chip)) == expected_chips


def test_the_chip_that_matches_the_saved_value_starts_selected(dashboard):
    from ui import controls

    dashboard._on_option_changed(BEANS, "beans", tasks.BEANS_5)
    dashboard._views.pop(BEANS, None)          # force a fresh page
    dashboard._show_page(BEANS)

    checked = [
        chip.text()
        for chip in dashboard._views[BEANS].findChildren(controls.Chip)
        if chip.isChecked()
    ]
    assert tasks.BEANS_5 in checked and tasks.BEANS_10 not in checked


def test_an_unbuilt_task_shows_what_it_would_take_instead_of_controls(dashboard):
    from ui import controls

    dashboard._show_page(UNBUILT)
    view = dashboard._views[UNBUILT]

    assert not view.findChildren(controls.Toggle), "dead controls were rendered"
    assert not view.findChildren(controls.Chip)
    text = " ".join(
        child.text() for child in view.findChildren(QtWidgets.QLabel)
    )
    assert "CHƯA CÀI ĐẶT" in text
    assert tasks.BY_ID[UNBUILT].todo[:20] in text


def test_the_card_has_one_button_that_becomes_stop_while_running(dashboard):
    """Start and stop share one cell, so only the applicable one is on screen.

    With both present one of the two was always dead, and the dead one still
    took the widest cell on the card.
    """
    dashboard._show_page(RAID)
    assert "Bắt đầu" in dashboard._views[RAID]._cards[101]._toggle.text()

    dashboard._on_start(101)
    dashboard._rebuild()

    toggle = dashboard._views[RAID]._cards[101]._toggle
    assert "Kết thúc" in toggle.text()
    assert toggle.isEnabled(), "the only button left has to still work"


def test_the_one_button_stops_a_running_task_rather_than_restarting_it(dashboard):
    """What it does follows the state, not the label it happens to be showing."""
    dashboard._show_page(RAID)
    dashboard._on_start(101)
    dashboard._rebuild()

    dashboard._views[RAID]._cards[101]._toggle.click()

    assert not dashboard._manager.get(101).is_running


def test_the_one_button_stays_dead_for_a_task_with_no_worker(dashboard):
    """The rule this whole page exists to hold: an unbuilt task cannot start.

    Worth pinning again here, because merging the two buttons moved the
    condition that enforced it.
    """
    dashboard._manager.select(101, UNBUILT)
    dashboard._show_page(UNBUILT)
    dashboard._rebuild()

    toggle = dashboard._views[UNBUILT]._cards[101]._toggle
    assert "Bắt đầu" in toggle.text()
    assert not toggle.isEnabled()


def test_the_card_start_button_starts_the_task_whose_page_it_is_on(dashboard):
    """It started whatever was queued first instead.

    Pressing Bắt đầu on the Ném đậu page started Phá Kết Giới, and the beans
    card then read "Trong hàng chờ" — the window was busy with another task.
    The header's "start all" beside it already promoted correctly, so the two
    buttons disagreed.
    """
    dashboard._manager.select(101, "beans")
    dashboard._show_page("beans")

    dashboard._on_start(101)

    assert dashboard._manager.get(101).task_id == "beans"


def test_the_home_page_start_button_runs_whatever_the_window_is_set_to(dashboard):
    """No page means no opinion about which task — run the window's own."""
    dashboard._manager.select(101, "beans")
    dashboard._show_page(HOME)

    dashboard._on_start(101)

    assert dashboard._manager.get(101).task_id == "beans"


def test_starting_from_a_page_switches_the_window_to_that_task(dashboard):
    """The button sits on a task's page, so it must start that task.

    It used to start whatever was first in the window's queue, which is how
    Bắt đầu on the Ném đậu page came to launch Phá Kết Giới.
    """
    dashboard._manager.select(101, "souls")
    dashboard._show_page("beans")

    dashboard._on_start(101)

    assert dashboard._manager.get(101).task_id == "beans"


# ── the shard tally on the page ─────────────────────────────────────────────


def shard_panel(dashboard, task_id="beans"):
    dashboard._show_page(task_id)
    return dashboard._task_view(task_id)


def test_the_shard_panel_stays_hidden_until_there_is_something_to_show(dashboard):
    """A heading over an empty list is worse than no heading."""
    view = shard_panel(dashboard)
    dashboard._refresh()

    assert not view._shards.isVisible()


def test_collected_shards_are_listed_by_name(dashboard):
    dashboard._manager.select(101, "beans")
    view = shard_panel(dashboard)
    session = dashboard._manager.get(101)
    session._stats_task = "beans"
    session._shards = {"Nurikabe": 9, "Koi": 4}

    view.refresh([session], capture=False)

    texts = [w.text() for w in view._shards.findChildren(QtWidgets.QLabel)]
    assert "Nurikabe" in texts and "9" in texts
    assert "Koi" in texts and "4" in texts
    assert "13 mảnh" in texts


def test_shards_from_every_window_are_added_together(dashboard):
    """Several windows farming the same parade are one pile to whoever reads it."""
    for hwnd in (101, 102):
        dashboard._manager.select(hwnd, "beans")
    view = shard_panel(dashboard)
    sessions = []
    for hwnd, tally in ((101, {"Koi": 3}), (102, {"Koi": 5, "Kusa": 2})):
        session = dashboard._manager.get(hwnd)
        session._stats_task = "beans"
        session._shards = tally
        sessions.append(session)

    view.refresh(sessions, capture=False)

    assert view._merged_shards(sessions) == {"Koi": 8, "Kusa": 2}


def test_another_tasks_haul_is_not_shown_under_this_one(dashboard):
    """A window that ran Ném đậu and then Phá Kết Giới must not show its beans
    under the raid's heading."""
    dashboard._manager.select(101, "beans")
    view = shard_panel(dashboard, RAID)
    session = dashboard._manager.get(101)
    session._stats_task = "beans"
    session._shards = {"Koi": 3}

    assert view._merged_shards([session]) == {}
