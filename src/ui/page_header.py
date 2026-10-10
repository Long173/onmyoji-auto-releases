"""The band above the content: what page you are on, and the two big actions."""
from __future__ import annotations

from typing import Optional

from PyQt5 import QtCore, QtGui, QtWidgets

import theme
from ui import controls
from ui.primitives import body_text, eyebrow, hbox, label, text_width, vbox


def open_url(url: str) -> None:
    """Open a link in the player's browser. A seam for tests."""
    QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))


class PageHeader(QtWidgets.QWidget):
    """Kicker, title, one line of prose, and start / stop."""

    startRequested = QtCore.pyqtSignal()
    stopRequested = QtCore.pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        row = hbox(24, margins=(30, 24, 30, 18))

        text = vbox(7)
        self._kicker = eyebrow("")
        # Wraps rather than holding the row open: at a large text size the title
        # alone is wider than the room beside the buttons.
        self._title = label("", theme.display(36), wrap=True)
        self._summary = body_text("", 13.5, theme.TEXT_MUTED)
        text_width(self._summary, 680, "max")
        text.addWidget(self._kicker)
        text.addWidget(self._title)
        text.addWidget(self._summary)

        # One button, as on the cards and the overview rows. What it offers
        # follows the page below it; see `set_page`.
        self._toggle = controls.OutlineButton("▶  Bắt đầu tất cả", controls.ACCENT,
                                              padding="10px 18px")
        self._toggle.clicked.connect(self._on_toggle)
        self._running = False

        # The task's tutorial, when it has one. Neutral, beside the accent
        # button, so it never competes with starting the task.
        self._video = controls.OutlineButton("▷  Xem video hướng dẫn",
                                             padding="10px 18px")
        self._video.setToolTip("Mở video hướng dẫn trên YouTube")
        self._video.clicked.connect(self._on_video)
        self._video.setVisible(False)
        self._video_url = ""

        # Never narrower than their own words: at a large text size the row runs
        # short of room, and it is the summary that should wrap, not the buttons
        # that should lose their labels.
        for button in (self._video, self._toggle):
            button.setSizePolicy(QtWidgets.QSizePolicy.Minimum,
                                 QtWidgets.QSizePolicy.Fixed)

        actions = hbox(10)
        # Bottom-aligned so the row sits on the summary's last line rather than
        # centring against the whole block.
        actions.addWidget(self._video, 0, QtCore.Qt.AlignBottom)
        actions.addWidget(self._toggle, 0, QtCore.Qt.AlignBottom)

        row.addLayout(text, 1)
        row.addLayout(actions)
        self.setLayout(row)

    def set_page(self, kicker: str, title: str, summary: str,
                 start_label: str, can_start: bool = True,
                 running: bool = False, video: str = "") -> None:
        """`running` means there is nothing left here to start.

        Mixed — some windows going, some not — deliberately still reads as
        start. Start skips whatever is already running, so that press is
        harmless; a "Dừng" offered in the same state would stop running tasks
        from a press meant to start the others.
        """
        self._describe(kicker, title, summary)
        self._set_video(video)
        self._toggle.setVisible(True)
        self._running = running
        if running:
            self._toggle.setText("■  Dừng")
            self._toggle.set_tone(controls.DANGER)
            self._toggle.setEnabled(True)
        else:
            self._toggle.setText("▶  " + start_label)
            self._toggle.set_tone(controls.ACCENT)
            self._toggle.setEnabled(can_start)

    def set_plain_page(self, kicker: str, title: str, summary: str) -> None:
        """A page with nothing to start — the wiki, for instance."""
        self._describe(kicker, title, summary)
        self._set_video("")
        self._toggle.setVisible(False)

    def _set_video(self, url: str) -> None:
        self._video_url = url
        self._video.setVisible(bool(url))

    def _on_video(self) -> None:
        if self._video_url:
            open_url(self._video_url)

    def _on_toggle(self) -> None:
        """Whichever the button currently stands for, read from the state."""
        if self._running:
            self.stopRequested.emit()
        else:
            self.startRequested.emit()

    def _describe(self, kicker: str, title: str, summary: str) -> None:
        self._kicker.setText(kicker.upper())
        self._title.setText(title)
        self._summary.setText(summary)
