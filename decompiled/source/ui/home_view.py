"""The overview page: four figures, then every window and the task it runs."""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from PyQt5 import QtCore, QtWidgets

import tasks
import theme
from auto.session import GameSession
from ui import controls
from ui.primitives import (Badge, Divider, ElidedLabel, StatusDot, body_text, hbox,
                           label, section_label, vbox)

# 1.5fr 1.4fr 1fr 0.8fr 190px, as integers because Qt stretch is integral.
COLUMN_STRETCH = (15, 14, 10, 8)
ACTION_COLUMN_WIDTH = 388   # Bắt đầu/Kết thúc + Chụp + Quay + thư mục


class StatCell(QtWidgets.QWidget):
    """One figure in the strip across the top."""

    def __init__(self, caption: str, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        block = vbox(8, margins=(22, 18, 22, 18))
        block.addWidget(section_label(caption))
        self._value = label("—", theme.tabular(26))
        block.addWidget(self._value)
        self.setLayout(block)

    def set_value(self, value: str) -> None:
        self._value.setText(value)


class WindowRow(QtWidgets.QWidget):
    """One line of the table: window, task, status, elapsed, actions."""

    startRequested = QtCore.pyqtSignal(int)
    stopRequested = QtCore.pyqtSignal(int)
    captureRequested = QtCore.pyqtSignal(int)
    recordRequested = QtCore.pyqtSignal(int)
    revealRequested = QtCore.pyqtSignal(int)

    def __init__(self, session: GameSession, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.hwnd = session.hwnd
        # What the chip currently shows. update_from runs every second, and
        # rebuilding it each time left the outgoing one painting its border
        # until the event loop got round to deleting it.
        self._shown_task: Optional[str] = None

        row = hbox(16, margins=(0, 15, 0, 15))

        identity = vbox(3)
        # Elided, not plain: a long account name would otherwise widen the
        # whole column and squeeze the task chip out of the row.
        self._title = ElidedLabel(theme.display(19))
        self._hwnd = ElidedLabel(theme.mono(10, tracking=0.06), theme.TEXT_FAINT)
        identity.addWidget(self._title)
        identity.addWidget(self._hwnd)

        self._queue_host = QtWidgets.QWidget()
        self._queue = hbox(6)
        self._queue_host.setLayout(self._queue)

        status = hbox(8)
        self._dot = StatusDot(theme.TEXT_DIM, diameter=7)
        self._status = label("", theme.body(13), theme.TEXT_DIM)
        status.addWidget(self._dot)
        status.addWidget(self._status)
        status.addStretch()

        self._elapsed = label("", theme.tabular(13), theme.TEXT_SECONDARY)

        actions = hbox(8)
        actions.addStretch()
        # One cell for both, as on the task cards. A window is either running or
        # it is not, so the other button was always disabled — and this row is
        # the narrower of the two places to spend a cell on nothing.
        self._toggle = controls.OutlineButton(
            "Bắt đầu", controls.ACCENT, size=12.5, padding="8px 14px"
        )
        self._toggle.clicked.connect(self._on_toggle)
        self._running = False
        # Never disabled, unlike the other two: a screenshot is worth taking
        # whether the window is running a task or sitting idle, and the times
        # somebody wants one most are the times something looks wrong.
        self._capture = controls.OutlineButton(
            "Chụp", controls.NEUTRAL, size=12.5, padding="8px 12px"
        )
        self._capture.setToolTip("Chụp ảnh cửa sổ game này")
        self._capture.clicked.connect(lambda: self.captureRequested.emit(self.hwnd))
        self._record = controls.OutlineButton(
            "Quay", controls.NEUTRAL, size=12.5, padding="8px 12px"
        )
        self._record.setToolTip("Quay video cửa sổ game này")
        self._record.clicked.connect(lambda: self.recordRequested.emit(self.hwnd))
        actions.addWidget(self._toggle)
        actions.addWidget(self._capture)
        self._reveal = controls.OutlineButton(
            "📁", controls.NEUTRAL, size=12.5, padding="8px 10px"
        )
        self._reveal.setToolTip("Mở thư mục video đã quay")
        self._reveal.clicked.connect(lambda: self.revealRequested.emit(self.hwnd))
        actions.addWidget(self._record)
        actions.addWidget(self._reveal)

        action_host = QtWidgets.QWidget()
        action_host.setFixedWidth(ACTION_COLUMN_WIDTH)
        action_host.setLayout(actions)

        row.addLayout(identity, COLUMN_STRETCH[0])
        row.addWidget(self._queue_host, COLUMN_STRETCH[1])
        row.addLayout(status, COLUMN_STRETCH[2])
        row.addWidget(self._elapsed, COLUMN_STRETCH[3])
        row.addWidget(action_host)

        # A real rule rather than a CSS border: children with their own
        # background paint over a border drawn on the row itself, so it came
        # out as disconnected fragments under some columns only.
        column = vbox(0)
        column.addLayout(row)
        column.addWidget(Divider(color=theme.ROW_RULE))
        self.setLayout(column)

    def _on_toggle(self) -> None:
        """Start or stop, whichever the button currently stands for.

        Read from the flag `update_from` sets rather than from the button's own
        text, so the wiring does not depend on the wording.
        """
        if self._running:
            self.stopRequested.emit(self.hwnd)
        else:
            self.startRequested.emit(self.hwnd)

    def set_recording(self, seconds: float = 0.0, megabytes: float = 0.0,
                      on: bool = False) -> None:
        """Say on the button whether this window is being recorded, and for how long.

        The elapsed time and the size are on the button itself rather than
        tucked in a tooltip. A recording left running is the one thing in this
        app that quietly fills a disk — about 26 MB a minute — so the number has
        to be somewhere it cannot be missed.
        """
        if not on:
            self._record.setText("Quay")
            self._record.setToolTip("Quay video cửa sổ game này")
            return
        self._record.setText("■ %d:%02d · %.0f MB" % (
            int(seconds) // 60, int(seconds) % 60, megabytes))
        self._record.setToolTip("Đang quay — bấm để dừng và lưu")

    def update_from(self, session: GameSession) -> None:
        self._title.setText(session.title)
        self._hwnd.setText(session.window.descriptor)

        colour, _border, text = theme.STATUS.get(
            session.status, theme.STATUS["idle"]
        )
        running = session.is_running
        self._dot.set_color(colour)
        self._dot.set_pulsing(running and session.status != "paused")
        self._status.setText(session.message if session.status == "error" else text)
        self._status.setStyleSheet("color: %s; background: transparent;" % colour)
        self._elapsed.setText(GameSession.format_elapsed(session.elapsed_seconds))

        self._running = running
        if running:
            self._toggle.setText("Kết thúc")
            self._toggle.set_tone(controls.DANGER)
            self._toggle.setToolTip("Dừng tác vụ đang chạy trên cửa sổ này")
            self._toggle.setEnabled(True)
        else:
            self._toggle.setText("Bắt đầu")
            self._toggle.set_tone(controls.ACCENT)
            self._toggle.setToolTip("")
            # Still gated on the task behind it: a queue led by something with
            # no worker must not offer to start.
            self._toggle.setEnabled(_can_run(session))
        self._rebuild_task(session)

    def _rebuild_task(self, session: GameSession) -> None:
        task_id = session.task_id
        if task_id == self._shown_task:
            return
        self._shown_task = task_id

        while self._queue.count():
            item = self._queue.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Unparent before deleting: deleteLater alone leaves the widget
                # on screen, drawn at its last position, until the loop runs.
                widget.setParent(None)
                widget.deleteLater()

        spec = tasks.get(task_id) if task_id else None
        if spec is not None:
            if spec.is_available:
                colour, border = theme.ACCENT, theme.BORDER_HOVER
            else:
                colour, border = theme.TEXT_FAINT, theme.CONTROL
            chip = Badge(spec.name, colour, border)
            if not spec.is_available:
                chip.setToolTip("Chưa cài đặt — %s" % spec.todo)
            self._queue.addWidget(chip)
        self._queue.addStretch()


def _can_run(session: GameSession) -> bool:
    return tasks.is_available(session.task_id or "")


class HomeView(QtWidgets.QWidget):
    """Stats strip plus the window table."""

    startRequested = QtCore.pyqtSignal(int)
    stopRequested = QtCore.pyqtSignal(int)
    captureRequested = QtCore.pyqtSignal(int)
    recordRequested = QtCore.pyqtSignal(int)
    revealRequested = QtCore.pyqtSignal(int)

    CAPTIONS = ("Cửa sổ đang chạy", "Tổng lượt hôm nay", "Tác vụ khả dụng", "Tổng thời gian")

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._rows: Dict[int, WindowRow] = {}

        column = vbox(0)
        column.addWidget(self._build_stats())
        column.addWidget(Divider())

        holder = QtWidgets.QWidget()
        inner = vbox(0, margins=(30, 22, 30, 30))
        inner.addWidget(section_label("Cửa sổ & tác vụ"))
        inner.addSpacing(10)
        inner.addWidget(self._build_header())

        self._table_host = QtWidgets.QWidget()
        self._table = vbox(0)
        self._table_host.setLayout(self._table)
        inner.addWidget(self._table_host)

        self._empty = body_text(
            "Chưa thấy cửa sổ game nào. Mở Onmyoji rồi bấm “Quét cửa sổ”.",
            14, theme.TEXT_MUTED,
        )
        self._empty.setAlignment(QtCore.Qt.AlignCenter)
        self._empty.setContentsMargins(0, 40, 0, 0)
        inner.addWidget(self._empty)
        inner.addStretch()
        holder.setLayout(inner)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setWidget(holder)
        column.addWidget(scroll, 1)
        self.setLayout(column)

    def _build_stats(self) -> QtWidgets.QWidget:
        strip = QtWidgets.QWidget()
        row = hbox(0)
        self._stats: List[StatCell] = []
        for index, caption in enumerate(self.CAPTIONS):
            cell = StatCell(caption)
            self._stats.append(cell)
            row.addWidget(cell, 1)
            if index < len(self.CAPTIONS) - 1:
                row.addWidget(Divider(horizontal=False))
        strip.setLayout(row)
        return strip

    def _build_header(self) -> QtWidgets.QWidget:
        header = QtWidgets.QWidget()
        row = hbox(16, margins=(0, 0, 0, 9))
        captions = ("Cửa sổ", "Tác vụ", "Trạng thái", "Thời gian")
        for caption, stretch in zip(captions, COLUMN_STRETCH):
            row.addWidget(section_label(caption), stretch)
        spacer = QtWidgets.QWidget()
        spacer.setFixedWidth(ACTION_COLUMN_WIDTH)
        row.addWidget(spacer)

        column = vbox(0)
        column.addLayout(row)
        column.addWidget(Divider(color=theme.CONTROL))
        header.setLayout(column)
        self._header = header
        return header

    # ── refresh ─────────────────────────────────────────────────────────────

    def set_sessions(self, sessions: Sequence[GameSession]) -> None:
        """Reconcile the visible rows with the sessions that exist."""
        wanted = {session.hwnd for session in sessions}
        for hwnd in list(self._rows):
            if hwnd not in wanted:
                row = self._rows.pop(hwnd)
                self._table.removeWidget(row)
                row.deleteLater()

        for index, session in enumerate(sessions):
            row = self._rows.get(session.hwnd)
            if row is None:
                row = WindowRow(session)
                row.startRequested.connect(self.startRequested)
                row.stopRequested.connect(self.stopRequested)
                row.captureRequested.connect(self.captureRequested)
                row.recordRequested.connect(self.recordRequested)
                row.revealRequested.connect(self.revealRequested)
                self._rows[session.hwnd] = row
            self._table.insertWidget(index, row)

        has_windows = bool(sessions)
        self._empty.setVisible(not has_windows)
        self._table_host.setVisible(has_windows)
        self._header.setVisible(has_windows)

    def refresh(self, sessions: Sequence[GameSession], stats: Sequence[str]) -> None:
        for value, cell in zip(stats, self._stats):
            cell.set_value(value)
        for session in sessions:
            row = self._rows.get(session.hwnd)
            if row is not None:
                row.update_from(session)
