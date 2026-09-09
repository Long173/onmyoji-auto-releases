"""Windows notifications, via Qt's system-tray channel.

A modal dialog is the wrong shape for a bot that runs unattended for hours: it
sits in front of everything until someone clicks it, and a second window
finishing behind it stacks another one.

``QSystemTrayIcon.showMessage`` hands the text to the Windows notification
centre instead — it appears as a toast, it is still there later if the user was
away, and nothing blocks. No extra dependency: this ships with Qt.

The tray icon must exist and be visible for messages to appear at all, so one
is created for the lifetime of the app.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from PyQt5 import QtCore, QtWidgets

import theme
from ui.app_icon import build_icon

logger = logging.getLogger(__name__)

TOAST_MS = 8000

INFO = QtWidgets.QSystemTrayIcon.Information
WARNING = QtWidgets.QSystemTrayIcon.Warning
CRITICAL = QtWidgets.QSystemTrayIcon.Critical


class Notifier(QtCore.QObject):
    """Sends Windows notifications, and owns the tray icon they come from.

    The second job is here rather than in its own class because an app gets one
    sensible tray icon: a second ``QSystemTrayIcon`` puts a second picture in
    the tray, and this one has to stay alive anyway or notifications stop
    arriving. So the window's "hide me down there instead of quitting" menu
    hangs off the same icon.

    The two signals are what the window connects to. They are signals rather
    than callbacks passed in, so this object never needs to know what a window
    is.
    """

    showRequested = QtCore.pyqtSignal()
    stopRequested = QtCore.pyqtSignal()
    quitRequested = QtCore.pyqtSignal()
    # Somebody clicked the last notification. Passed straight through: what it
    # should do depends on what the notification was about, which is the
    # window's business rather than this object's.
    messageClicked = QtCore.pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._parent = parent
        self._tray: Optional[QtWidgets.QSystemTrayIcon] = None
        self._menu: Optional[QtWidgets.QMenu] = None
        self._stop_action: Optional[QtWidgets.QAction] = None
        # Asked when the menu opens rather than pushed in every second: the only
        # moment the count has to be right is the moment somebody reads it.
        self._running_count: Callable[[], int] = lambda: 0

        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("No system tray: notifications fall back to dialogs")
            return

        self._tray = QtWidgets.QSystemTrayIcon(build_icon(), self)
        self._tray.setToolTip("%s — %s" % (theme.APP_NAME, theme.APP_SUBTITLE))
        self._build_menu()
        self._tray.activated.connect(self._on_activated)
        self._tray.messageClicked.connect(self.messageClicked.emit)
        self._tray.show()

    def _build_menu(self) -> None:
        """Open, Stop and Quit, on the right-click menu.

        Quit has to be here. With the window hidden and no taskbar button, this
        menu is the only way left to end the app — a build that hid to the tray
        without it would need Task Manager to close.

        Stop is here for the same reason in a milder form: with the window down
        in the tray, reaching the stop button means opening the window first,
        and the one time somebody wants to stop everything in a hurry is the one
        time that is annoying.

        It greys out when nothing is running rather than hiding. Hiding was the
        first attempt and it was worse: right-clicking with nothing running shows
        a menu with no Stop in it, which is indistinguishable from a build that
        never had the feature — the first person to try it reported it missing.
        Greyed out, the menu says both that the entry exists and why it cannot be
        used.
        """
        menu = QtWidgets.QMenu()
        opening = menu.addAction("Mở %s" % theme.APP_NAME)
        opening.triggered.connect(self.showRequested.emit)
        self._stop_action = menu.addAction("Dừng tất cả")
        self._stop_action.triggered.connect(self.stopRequested.emit)
        menu.addSeparator()
        quitting = menu.addAction("Thoát")
        quitting.triggered.connect(self.quitRequested.emit)
        menu.aboutToShow.connect(self._refresh_menu)
        self._menu = menu
        if self._tray is not None:
            self._tray.setContextMenu(menu)

    def watch_running(self, source: Callable[[], int]) -> None:
        """Where the menu should ask how many windows are running."""
        self._running_count = source

    def _refresh_menu(self) -> None:
        """Bring the menu up to date as it opens, if the signal arrives.

        Belt and braces. :meth:`set_running` is what actually keeps the entry
        current, because ``aboutToShow`` is not dependable for a tray menu —
        the entry stayed stale in a live build with a worker plainly running,
        and the two candidate causes both stop mattering once the state is
        pushed in rather than pulled out.
        """
        self.set_running(self._running_count())

    def set_running(self, running: int) -> None:
        """Take the number of running windows, and show it two ways.

        On the tooltip, because hovering the icon is the cheapest way to answer
        "is my auto still going" — the question somebody who hid the window will
        have. And on the Stop entry, which is enabled only when there is
        something to stop.

        Called every refresh tick, which is about once a second: cheap, and it
        means the menu is already correct whenever it opens rather than relying
        on being told that it did.
        """
        if self._stop_action is not None:
            self._stop_action.setEnabled(running > 0)
            self._stop_action.setText(
                "Dừng tất cả (%d cửa sổ)" % running if running else "Dừng tất cả"
            )
        if self._tray is None:
            return
        state = "đang chạy %d cửa sổ" % running if running else "đang nghỉ"
        self._tray.setToolTip("%s — %s" % (theme.APP_NAME, state))

    def _on_activated(self, reason) -> None:
        # Double-click and plain click both open it, which is what every other
        # tray app on Windows does. The right-click menu arrives on Context and
        # must not also open the window.
        if reason in (QtWidgets.QSystemTrayIcon.DoubleClick,
                      QtWidgets.QSystemTrayIcon.Trigger):
            self.showRequested.emit()

    @property
    def has_tray(self) -> bool:
        """Whether there is an icon in the tray at all.

        Distinct from :attr:`available`, which is about *messages*: a tray can
        exist on a system that refuses to show notifications, and hiding the
        window is fine there while a toast is not.
        """
        return self._tray is not None

    @property
    def available(self) -> bool:
        return self._tray is not None and QtWidgets.QSystemTrayIcon.supportsMessages()

    def notify(self, title: str, body: str, kind=INFO) -> None:
        """Show a notification. Falls back to a dialog only if it must."""
        if self.available and self._tray is not None:
            logger.info("Notification: %s — %s", title, body)
            self._tray.showMessage(title, body, kind, TOAST_MS)
            return

        logger.info("Notification (as dialog): %s — %s", title, body)
        if kind == CRITICAL:
            QtWidgets.QMessageBox.critical(self._parent, title, body)
        else:
            QtWidgets.QMessageBox.information(self._parent, title, body)

    def close(self) -> None:
        if self._tray is not None:
            self._tray.hide()
            self._tray = None
        self._menu = None
