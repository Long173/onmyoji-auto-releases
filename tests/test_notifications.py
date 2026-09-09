"""Finishing a run notifies Windows instead of opening a dialog.

A modal is the wrong shape for an unattended bot: it sits in front of
everything until clicked, and a second window finishing behind it stacks
another one. Notifications go to the Windows notification centre, so they are
still there when the user comes back.
"""
from __future__ import annotations

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")

from ui import notifications  # noqa: E402

# The icon itself is covered by test_app_icon.py.

# ── routing ─────────────────────────────────────────────────────────────────


class RecordingTray:
    def __init__(self):
        self.messages = []
        self.hidden = False

    def showMessage(self, title, body, kind, msecs):
        self.messages.append((title, body, kind))

    def setToolTip(self, text):
        pass

    def show(self):
        pass

    def hide(self):
        self.hidden = True


@pytest.fixture
def notifier(qt_app, monkeypatch):
    """A Notifier whose tray is replaced by a recorder."""
    made = notifications.Notifier()
    tray = RecordingTray()
    made._tray = tray
    monkeypatch.setattr(
        QtWidgets.QSystemTrayIcon, "supportsMessages", staticmethod(lambda: True)
    )
    return made, tray


def test_a_notification_goes_to_the_tray(notifier):
    made, tray = notifier
    made.notify("Xong", "Đã hoàn thành 27 trận.")

    assert tray.messages == [("Xong", "Đã hoàn thành 27 trận.", notifications.INFO)]


def test_errors_are_flagged_as_critical(notifier):
    made, tray = notifier
    made.notify("Lỗi", "Mất cửa sổ", notifications.CRITICAL)

    assert tray.messages[0][2] == notifications.CRITICAL


def test_without_a_tray_it_falls_back_to_a_dialog(qt_app, monkeypatch):
    """Better an intrusive dialog than a notice that vanishes."""
    monkeypatch.setattr(
        QtWidgets.QSystemTrayIcon,
        "isSystemTrayAvailable",
        staticmethod(lambda: False),
    )
    shown = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "information",
        staticmethod(lambda parent, title, body: shown.append((title, body))),
    )

    made = notifications.Notifier()
    assert not made.available
    made.notify("Xong", "Đã hoàn thành 27 trận.")

    assert shown == [("Xong", "Đã hoàn thành 27 trận.")]


def test_closing_hides_the_tray_icon(notifier):
    made, tray = notifier
    made.close()
    assert tray.hidden


# ── what the dashboard actually does ────────────────────────────────────────


@pytest.fixture
def captured(dashboard, monkeypatch):
    """Records notifications, and fails the test if a dialog is opened."""
    sent = []
    monkeypatch.setattr(
        dashboard._notifier, "notify",
        lambda title, body, kind=notifications.INFO: sent.append((title, body, kind)),
    )
    for name in ("information", "critical", "warning"):
        monkeypatch.setattr(
            QtWidgets.QMessageBox, name,
            staticmethod(lambda *a, **k: pytest.fail("a dialog was opened: %s" % name)),
        )
    return dashboard, sent


def test_finishing_notifies_instead_of_opening_a_dialog(captured):
    dashboard, sent = captured
    dashboard._manager.set_app_option("notify_on_finish", True)

    dashboard._on_session_finished("Hết vé phá kết giới.", 101)

    assert len(sent) == 1
    title, body, kind = sent[0]
    assert "hoàn thành" in title
    assert "Hết vé" in body, "the worker's own message was not passed through"
    assert kind == notifications.INFO


def test_the_toggle_still_gates_the_finish_notice(captured):
    dashboard, sent = captured
    dashboard._manager.set_app_option("notify_on_finish", False)

    dashboard._on_session_finished("Hết vé.", 101)

    assert sent == [], "it notified even though the toggle is off"


def test_a_finished_run_announces_once_and_stops(captured):
    """One task, one notification. An earlier version chained to the next task
    in a queue and sent a second "moving on" toast; there is no next task."""
    dashboard, sent = captured
    dashboard._manager.set_app_option("notify_on_finish", True)
    dashboard._manager.start(101)

    dashboard._on_session_finished("Hết vé.", 101)

    assert len(sent) == 1, "more than one notification for a single run"
    assert not dashboard._manager.get(101).is_running

def test_a_failure_notifies_as_critical(captured):
    dashboard, sent = captured

    dashboard._on_session_failed("Mất cửa sổ game", 101)

    assert len(sent) == 1
    title, body, kind = sent[0]
    assert "lỗi" in title
    assert "Mất cửa sổ game" in body
    assert kind == notifications.CRITICAL


def test_a_failure_still_marks_the_card(captured):
    """The toast is transient; the card must keep showing the error."""
    dashboard, _sent = captured

    dashboard._on_session_failed("Mất cửa sổ game", 101)

    session = dashboard._manager.get(101)
    assert session is not None
    assert session.status == "error"
    assert session.message == "Mất cửa sổ game"
