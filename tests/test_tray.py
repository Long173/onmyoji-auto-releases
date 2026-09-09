"""Hiding the window to the system tray instead of quitting.

The app is meant to be left running for hours, so a window that has to sit on
the taskbar the whole time is in the way. Pressing X hides it; the tray icon —
which already existed, because notifications come from it — is how it comes
back.

Three things here are worth more than the rest, and all three are ways this can
go wrong rather than ways it goes right:

* **Hiding must not stop anything.** The entire reason for the feature is to keep
  running, so a close that hides has nothing to confirm and must leave every
  worker alone.
* **With no tray, X must still quit.** Hidden with no icon to click, the app is
  unreachable and unclosable except through Task Manager. The setting is the
  user's wish; the tray existing is what makes it safe to grant.
* **The tray's own Thoát has to actually quit**, and go through the normal
  confirmation on the way, or the only exit left is Task Manager again.
"""
from __future__ import annotations

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")
from PyQt5 import QtCore, QtGui  # noqa: E402

import tasks  # noqa: E402
from conftest import SpyWorker  # noqa: E402

RAID = "realm_raid"


def close_it(window):
    """Press X, the way Qt delivers it."""
    event = QtGui.QCloseEvent()
    window.closeEvent(event)
    return event.isAccepted()


class FakeNotifier:
    """Stands in for the real notifier, tray and all.

    The real one is swapped out rather than poked at. Putting a plain object
    where its ``QSystemTrayIcon`` goes crashed the interpreter outright — an
    access violation, not an exception — and letting its dialog fallback run for
    real opens a modal box that no test can dismiss.
    """

    def __init__(self, has_tray: bool):
        self.has_tray = has_tray
        self.available = has_tray
        self.said: list = []
        self.closed = False
        self.running_source = None
        self.tooltip_running = None

    def notify(self, title, body, kind=None):
        self.said.append(body)

    def close(self):
        self.closed = True

    def watch_running(self, source):
        self.running_source = source

    def set_running(self, running):
        self.tooltip_running = running


def set_tray(window, present: bool) -> FakeNotifier:
    """Pretend the system tray is or is not there."""
    fake = FakeNotifier(present)
    window._notifier = fake
    return fake


def with_setting(window, on: bool):
    window._manager.set_app_option("close_to_tray", on)


def dont_tear_down(window, monkeypatch):
    """Let a close be decided without running the whole shutdown.

    What these tests check is which branch ``closeEvent`` takes. Stopping the
    manager and the wiki for real is not part of that, and doing it twice — once
    here, once in the fixture — is asking for trouble.
    """
    monkeypatch.setattr(window._manager, "shutdown", lambda: None)
    monkeypatch.setattr(window._update_banner, "stop", lambda: None)
    monkeypatch.setattr(window, "_unregister_hotkeys", lambda: None)


# ── hiding ──────────────────────────────────────────────────────────────────


def test_pressing_x_hides_instead_of_closing(dashboard):
    set_tray(dashboard, True)
    with_setting(dashboard, True)
    dashboard.show()

    accepted = close_it(dashboard)

    assert not accepted, "the close went through"
    assert not dashboard.isVisible()


def test_hiding_stops_nothing(dashboard):
    """The whole point. A close that hides has nothing to confirm."""
    set_tray(dashboard, True)
    with_setting(dashboard, True)
    dashboard._on_start(101)
    running = dashboard._manager.running_count
    assert running == 1

    close_it(dashboard)

    assert dashboard._manager.running_count == running
    assert SpyWorker.live[-1].is_alive()


def test_hiding_never_asks_anything(dashboard, monkeypatch):
    """A confirmation for a close that does not close would be nonsense."""
    asked = []
    monkeypatch.setattr(dashboard, "_confirm_exit",
                        lambda running: asked.append(running) or True)
    set_tray(dashboard, True)
    with_setting(dashboard, True)
    dashboard._on_start(101)

    close_it(dashboard)

    assert asked == []


def test_the_window_comes_back_from_the_tray(dashboard):
    set_tray(dashboard, True)
    with_setting(dashboard, True)
    dashboard.show()
    close_it(dashboard)
    assert not dashboard.isVisible()

    dashboard._show_from_tray()

    assert dashboard.isVisible()


def test_a_window_hidden_while_minimised_comes_back_unminimised(dashboard):
    """Otherwise the icon is clicked and nothing appears to happen."""
    set_tray(dashboard, True)
    with_setting(dashboard, True)
    dashboard.show()
    dashboard.showMinimized()
    close_it(dashboard)

    dashboard._show_from_tray()

    assert not dashboard.isMinimized()


# ── the ways it must still quit ─────────────────────────────────────────────


def test_with_no_tray_x_still_quits(dashboard, monkeypatch):
    """Hidden with no icon to click, the app could only be killed."""
    set_tray(dashboard, False)
    with_setting(dashboard, True)
    dont_tear_down(dashboard, monkeypatch)

    assert close_it(dashboard), "hid itself with nowhere to hide"


def test_with_the_setting_off_x_quits(dashboard, monkeypatch):
    set_tray(dashboard, True)
    with_setting(dashboard, False)
    dont_tear_down(dashboard, monkeypatch)

    assert close_it(dashboard)


def test_the_tray_menu_quit_really_quits(dashboard, monkeypatch):
    set_tray(dashboard, True)
    with_setting(dashboard, True)
    dont_tear_down(dashboard, monkeypatch)
    closed = []
    # closeEvent is what actually tears down; record that it ran to completion
    # rather than driving the whole Qt shutdown inside a test.
    real = dashboard.closeEvent

    def spy(event):
        real(event)
        closed.append(event.isAccepted())

    dashboard.closeEvent = spy

    dashboard._quit_from_tray()

    assert closed == [True], "the tray's Thoát hid the window instead"


def test_the_update_handler_can_still_force_a_real_close(dashboard, monkeypatch):
    """A helper is waiting on this process to exit; hiding would strand it."""
    set_tray(dashboard, True)
    with_setting(dashboard, True)
    dashboard._force_close = True
    dont_tear_down(dashboard, monkeypatch)

    assert close_it(dashboard)


# ── silence ─────────────────────────────────────────────────────────────────


def test_hiding_says_nothing(dashboard):
    """No toast on the way down. Asked for, and it is the right default.

    An earlier build announced where the window had gone, once per launch. It
    was removed: the behaviour is learned after one use, and a notification for
    something the user just did themselves is an interruption, not news.
    """
    fake = set_tray(dashboard, True)
    with_setting(dashboard, True)

    close_it(dashboard)

    assert fake.said == []


def test_hiding_still_says_nothing_with_workers_running(dashboard):
    """The case the announcement existed for. Still silent."""
    fake = set_tray(dashboard, True)
    with_setting(dashboard, True)
    dashboard._on_start(101)

    close_it(dashboard)

    assert fake.said == []


# ── stopping from the tray ──────────────────────────────────────────────────


def test_the_tray_can_stop_everything(dashboard):
    set_tray(dashboard, True)
    dashboard._on_start(101)
    dashboard._on_start(102)
    assert dashboard._manager.running_count == 2

    dashboard._stop_all_from_tray()

    assert dashboard._manager.running_count == 0


def test_stopping_from_the_tray_says_nothing(dashboard):
    """No toast here either.

    Not feedback-free, which is why removing it is safe: the refresh that
    follows puts "đang nghỉ" on the tooltip, so hovering the icon answers what
    happened.
    """
    fake = set_tray(dashboard, True)
    dashboard._on_start(101)

    dashboard._stop_all_from_tray()

    assert fake.said == []
    assert fake.tooltip_running == 0, "the tooltip did not follow"


def test_the_tray_stops_windows_on_other_pages_too(dashboard):
    """The page-scoped rule of the header button would be a trap here.

    Read from the tray there is no page in sight, so "Dừng tất cả" has to mean
    all of them — a menu that silently spared the windows on another task would
    be worse than no menu.
    """
    set_tray(dashboard, True)
    dashboard._on_select(101, "beans")
    dashboard._on_start(101)
    dashboard._on_select(102, RAID)
    dashboard._on_start(102)
    dashboard._show_page(RAID)          # only the raid page is open
    assert dashboard._manager.running_count == 2

    dashboard._stop_all_from_tray()

    assert dashboard._manager.running_count == 0


def test_the_menu_is_told_where_to_ask_how_many_are_running(dashboard):
    """It asks when it opens; the window never has to push the number in."""
    fake = set_tray(dashboard, True)
    dashboard._notifier.watch_running(lambda: dashboard._manager.running_count)
    dashboard._on_start(101)

    assert fake.running_source() == 1


def test_the_tooltip_follows_whether_anything_is_running(dashboard):
    """Hovering the icon is the cheapest way to ask "is it still going"."""
    fake = set_tray(dashboard, True)

    dashboard._refresh()
    assert fake.tooltip_running == 0

    dashboard._on_start(101)
    dashboard._refresh()
    assert fake.tooltip_running == 1


# ── the menu itself ─────────────────────────────────────────────────────────
#
# The real Notifier, not the fake. On a machine with no system tray — which the
# test runner is — the constructor builds no menu at all, so these drive
# ``_build_menu`` directly. That is the only way to reach this logic here, and it
# is worth reaching: the show/hide rule is the whole of what was asked for.


@pytest.fixture
def menu_notifier(qt_app):
    from ui import notifications

    made = notifications.Notifier()
    made._build_menu()
    yield made
    made.close()


def entry_texts(notifier):
    return [a.text() for a in notifier._menu.actions() if a.isVisible()]


def test_the_menu_offers_open_and_quit_always(menu_notifier):
    menu_notifier.watch_running(lambda: 0)
    menu_notifier._refresh_menu()

    texts = entry_texts(menu_notifier)
    assert any("Mở" in t for t in texts)
    assert "Thoát" in texts


def test_the_stop_entry_is_greyed_out_while_nothing_runs(menu_notifier):
    """Greyed, not hidden.

    Hiding it was the first attempt and it read as a missing feature: the first
    person to right-click with nothing running reported that the option was not
    there. An entry that is present but unavailable says both that it exists and
    why it cannot be used.
    """
    menu_notifier.set_running(0)

    assert menu_notifier._stop_action.isVisible(), "hidden reads as absent"
    assert not menu_notifier._stop_action.isEnabled()


def test_the_stop_entry_comes_alive_with_the_count_on_it(menu_notifier):
    menu_notifier.set_running(3)

    assert menu_notifier._stop_action.isEnabled()
    assert "3" in menu_notifier._stop_action.text()


def test_the_entry_is_kept_current_without_the_menu_being_opened(menu_notifier):
    """``aboutToShow`` is not dependable for a tray menu.

    The entry stayed stale in a live build with a worker plainly running, which
    is why the state is pushed in on every refresh tick rather than pulled out
    when the menu opens.
    """
    menu_notifier.set_running(0)
    assert not menu_notifier._stop_action.isEnabled()

    menu_notifier.set_running(1)

    assert menu_notifier._stop_action.isEnabled(), "only updated on open"


def test_the_stop_entry_emits_rather_than_calling_anything(menu_notifier):
    """The notifier never needs to know what a window is."""
    fired = []
    menu_notifier.stopRequested.connect(lambda: fired.append(True))

    menu_notifier._stop_action.trigger()

    assert fired == [True]


def test_opening_the_menu_also_refreshes_it(menu_notifier):
    """Kept as belt and braces, on top of the pushed state."""
    count = [0]
    menu_notifier.watch_running(lambda: count[0])
    menu_notifier._refresh_menu()
    assert not menu_notifier._stop_action.isEnabled()

    count[0] = 2
    menu_notifier._menu.aboutToShow.emit()

    assert menu_notifier._stop_action.isEnabled()
    assert "2" in menu_notifier._stop_action.text()


# ── the setting itself ──────────────────────────────────────────────────────


def test_the_setting_is_on_by_default(dashboard):
    """What a game launcher does, and what was asked for."""
    assert tasks.as_bool(dashboard._manager.app_config.get("close_to_tray"))


def test_the_setting_survives_a_restart(dashboard, isolated_settings):
    """Turned off, it has to stay off — and the registry returns 'false'.

    ``as_bool`` exists for exactly this: the packaged app stores settings in the
    Windows registry, which hands a boolean back as the string ``'false'``, and
    plain ``bool('false')`` is ``True``.
    """
    from PyQt5 import QtCore

    # Written the way the settings dialog writes it.
    dashboard._manager.set_app_option("close_to_tray", False)
    dashboard._settings.setValue("close_to_tray", False)
    dashboard._settings.sync()

    # Reopened, the way a later launch would see it.
    dashboard._settings = QtCore.QSettings(
        str(isolated_settings), QtCore.QSettings.IniFormat
    )

    assert tasks.as_bool(dashboard._load_app_config().get("close_to_tray")) is False
