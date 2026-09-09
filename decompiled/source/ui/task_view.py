"""One task's page: its settings on the left, the windows running it on the right.

Both halves are generated from the task's :class:`~tasks.TaskSpec`, so a new
automation gets a working page without any widget code being written for it.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence

from PyQt5 import QtCore, QtGui, QtWidgets

import tasks
import theme
from auto.session import GameSession
from ui import controls, fields, preview
from ui.fields import FieldForm
from ui.primitives import (Card, Divider, ElidedLabel, FlowLayout, HatchFrame,
                           StatusDot, body_text, hbox, label, section_label, vbox)

CONFIG_WIDTH = 336
MAX_CARD_COLUMNS = 2
# Below this a card cannot show both figures and all three buttons without
# clipping, so the grid drops to a single column instead.
MIN_CARD_WIDTH = 300
# And above this a card stops growing. Without a cap, a single column stretches
# one card across the whole panel and its 16:9 thumbnail balloons to twice the
# size it has when two columns fit — the same card, wildly different picture.
MAX_CARD_WIDTH = 340


class ConfigPanel(QtWidgets.QWidget):
    """The declarative settings form for one task."""

    optionChanged = QtCore.pyqtSignal(str, str, object)   # task id, key, value

    def __init__(self, spec: tasks.TaskSpec, config: Dict[str, object],
                 frame_source: Optional[Callable[[], Optional[Any]]] = None,
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.spec = spec
        self.setFixedWidth(CONFIG_WIDTH)

        column = vbox(0, margins=(26, 24, 26, 24))
        column.addWidget(section_label("Cấu hình tác vụ"))
        column.addSpacing(16)

        if not spec.is_available:
            column.addWidget(self._build_todo())
        else:
            # Shared only: per-window settings render on each window's card.
            form = FieldForm(
                spec.shared_fields, fields.values_of(spec.shared_fields, config),
                frame_source=frame_source,
            )
            form.changed.connect(
                lambda key, value: self.optionChanged.emit(spec.id, key, value)
            )
            column.addWidget(form)
            column.addWidget(self._build_app_pointer())
        column.addStretch()
        self.setLayout(column)

    @staticmethod
    def _build_app_pointer() -> QtWidgets.QWidget:
        """Say where the settings that are not on this page live.

        Without it, moving the Wanted Quest reply out of here just looks like it
        went missing.
        """
        holder = QtWidgets.QWidget()
        block = vbox(8)
        block.addWidget(Divider())
        block.addSpacing(6)
        block.addWidget(section_label("Áp dụng cho mọi tác vụ"))
        block.addWidget(body_text(
            "Lời mời truy và thông báo nằm ở “Cài đặt chung” (F9) — chúng đúng "
            "cho mọi tác vụ, không riêng tác vụ này.", 12.5, theme.TEXT_LABEL,
        ))
        holder.setLayout(block)
        return holder

    def _build_todo(self) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        block = vbox(10)
        block.addWidget(
            label("CHƯA CÀI ĐẶT", theme.mono(10, tracking=0.22), theme.DANGER)
        )
        block.addWidget(body_text(
            "Tác vụ này mới chỉ được khai báo để chỗ trong giao diện — chưa có "
            "phần chạy thật, nên nút bắt đầu bị khoá.", 13, theme.TEXT_MUTED,
        ))
        block.addWidget(Divider())
        block.addWidget(section_label("Để làm được cần gì"))
        block.addWidget(body_text(self.spec.todo, 12.5, theme.TEXT_LABEL, justify=True))
        holder.setLayout(block)
        return holder


class AspectHatch(HatchFrame):
    """A hatched image frame that keeps the game window's aspect ratio.

    Height follows width instead of being fixed, so the thumbnail stays
    correctly proportioned whether the grid is showing one column or two.
    """

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt naming
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt naming
        return preview.height_for(width)

    def sizeHint(self) -> QtCore.QSize:
        width = max(self.width(), 240)
        return QtCore.QSize(width, preview.height_for(width))

    def resizeEvent(self, event) -> None:
        # A plain widget in a vertical layout is given a height from its size
        # hint, not from heightForWidth, so the box is set here as well.
        self.setMinimumHeight(preview.height_for(self.width()))
        super().resizeEvent(event)


class TaskWindowCard(Card):
    """One window set to this task."""

    startRequested = QtCore.pyqtSignal(int)
    stopRequested = QtCore.pyqtSignal(int)
    captureRequested = QtCore.pyqtSignal(int)
    recordRequested = QtCore.pyqtSignal(int)
    revealRequested = QtCore.pyqtSignal(int)
    optionChanged = QtCore.pyqtSignal(int, str, object)   # hwnd, key, value

    def __init__(self, session: GameSession, spec: tasks.TaskSpec,
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent=parent)
        self.hwnd = session.hwnd
        self._spec = spec
        self.setMaximumWidth(MAX_CARD_WIDTH)
        # A freshly built card has nothing to show, so its first refresh always
        # captures rather than waiting for the throttle to come round.
        self._needs_frame = True

        block = vbox(0, margins=(17, 16, 17, 16))

        top = hbox(12)
        identity = vbox(4)
        # Elided: an unwrapped title reports its full width as a minimum, which
        # pushed the second column of cards off the edge of the window.
        self._title = ElidedLabel(theme.display(20))
        self._hwnd = ElidedLabel(theme.mono(10, tracking=0.06), theme.TEXT_FAINT)
        identity.addWidget(self._title)
        identity.addWidget(self._hwnd)

        status = hbox(7)
        self._dot = StatusDot(theme.TEXT_DIM, diameter=7)
        self._status = label("", theme.mono(10, tracking=0.12), theme.TEXT_DIM)
        status.addWidget(self._dot)
        status.addWidget(self._status)

        status_host = QtWidgets.QWidget()
        status_host.setLayout(status)
        status_host.setSizePolicy(
            QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred
        )

        top.addLayout(identity, 1)
        top.addWidget(status_host)
        block.addLayout(top)

        block.addSpacing(12)
        block.addWidget(self._build_thumbnail())
        block.addSpacing(14)

        # Settings this window owns rather than the task — a co-op room has one
        # leader, so the role cannot be one value shared by every window.
        if spec.window_fields:
            block.addSpacing(14)
            block.addWidget(Divider())
            block.addSpacing(12)
            form = FieldForm(
                spec.window_fields,
                session.options_for(spec.id),
                spacing=10,
            )
            form.changed.connect(
                lambda key, value: self.optionChanged.emit(self.hwnd, key, value)
            )
            block.addWidget(form)

        figures = hbox(24)
        # Only tasks that can count honestly get a counter; the rest show just
        # the running time rather than a figure stuck at zero.
        self._progress = None
        if spec.counts_progress:
            self._progress, progress_block = self._figure(spec.progress_label)
            figures.addLayout(progress_block)
        self._elapsed, elapsed_block = self._figure("thời gian chạy")
        figures.addLayout(elapsed_block)
        figures.addStretch()
        block.addLayout(figures)

        block.addSpacing(16)
        actions = hbox(9)
        # One cell for both. A card can only ever offer one of the two — the
        # window either runs this task or it does not — so the other button was
        # always sitting there disabled, taking the widest cell on the card.
        self._toggle = controls.OutlineButton("▶  Bắt đầu", controls.ACCENT,
                                             padding="10px 0")
        self._toggle.clicked.connect(self._on_toggle)
        self._running = False
        # No "remove" button. A window always has exactly one task, so taking
        # this one away would leave nothing to put in its place — switching is
        # done by choosing another task, not by unassigning this one.
        # Never disabled: a screenshot is worth taking whether or not the task
        # is running, and the moment somebody wants one is usually the moment
        # something looks wrong.
        self._capture = controls.OutlineButton(
            "Chụp", controls.NEUTRAL, padding="10px 0"
        )
        self._capture.setToolTip("Chụp ảnh cửa sổ game này")
        self._capture.clicked.connect(lambda: self.captureRequested.emit(self.hwnd))
        self._record = controls.OutlineButton(
            "Quay", controls.NEUTRAL, padding="10px 0"
        )
        self._record.setToolTip("Quay video cửa sổ game này")
        self._record.clicked.connect(lambda: self.recordRequested.emit(self.hwnd))
        actions.addWidget(self._toggle, 2)
        actions.addWidget(self._capture, 1)
        self._reveal = controls.OutlineButton("📁", controls.NEUTRAL, padding="10px 0")
        self._reveal.setToolTip("Mở thư mục video đã quay")
        self._reveal.clicked.connect(lambda: self.revealRequested.emit(self.hwnd))
        actions.addWidget(self._record, 1)
        actions.addWidget(self._reveal, 1)
        block.addLayout(actions)

        self.setLayout(block)

    def _on_toggle(self) -> None:
        """Start or stop, whichever the button currently stands for.

        Decided from the flag `update_from` sets, not from the button's own
        text: the text is for the person reading it, and matching on it would
        break the day the wording changes.
        """
        if self._running:
            self.stopRequested.emit(self.hwnd)
        else:
            self.startRequested.emit(self.hwnd)

    def _build_thumbnail(self) -> QtWidgets.QWidget:
        """A live view of the game window, framed and letterboxed."""
        frame = QtWidgets.QFrame()
        frame.setObjectName("previewFrame")
        frame.setStyleSheet(
            "#previewFrame { background: %s; border: 1px solid %s; border-radius: %dpx; }"
            % (theme.INSET, theme.BORDER, theme.RADIUS_SMALL)
        )
        box = vbox(0, margins=(1, 1, 1, 1))
        self._thumbnail = AspectHatch("ĐANG CHỜ ẢNH")
        box.addWidget(self._thumbnail)
        frame.setLayout(box)
        return frame

    @staticmethod
    def _figure(caption: str):
        value = label("0", theme.tabular(18))
        block = vbox(2)
        block.addWidget(value)
        block.addWidget(label(caption, theme.body(11.5), theme.TEXT_LABEL))
        return value, block

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

    def update_from(self, session: GameSession, capture: bool = True) -> None:
        self._refresh_thumbnail(session, capture)
        self._title.setText(session.title)
        # Handle only: two cards to a row leaves no space for the client size,
        # which is the same for every game window anyway.
        self._hwnd.setText(session.window.handle_text)

        running = session.is_running and session.task_id == self._spec.id
        colour, _border, text = theme.STATUS.get(
            session.status, theme.STATUS["idle"]
        )
        self._dot.set_color(colour)
        self._dot.set_pulsing(running and session.status != "paused")
        self._status.setText(text.upper())
        self._status.setStyleSheet("color: %s; background: transparent;" % colour)
        self.set_border("#4a3d28" if running else theme.BORDER)

        # Only this task's own figures: a window that ran another task before
        # being assigned here must not show that task's numbers on this card.
        progress, elapsed = session.stats_for(self._spec.id)
        if self._progress is not None:
            self._progress.setText(str(progress))
        self._elapsed.setText(GameSession.format_elapsed(elapsed))
        self._running = running
        if running:
            self._toggle.setText("■  Kết thúc")
            self._toggle.set_tone(controls.DANGER)
            self._toggle.setToolTip("Dừng tác vụ đang chạy trên cửa sổ này")
            self._toggle.setEnabled(True)
        else:
            self._toggle.setText("▶  Bắt đầu")
            self._toggle.set_tone(controls.ACCENT)
            self._toggle.setToolTip("")
            # `session.is_running` rather than `running`: identical today, since
            # a card only exists on the page of the task its window is set to,
            # but this is the half that must not offer to start a second task on
            # a busy window if that ever stops being true.
            self._toggle.setEnabled(
                not session.is_running and self._spec.is_available
            )

    def _refresh_thumbnail(self, session: GameSession, capture: bool) -> None:
        """Show the latest frame.

        While a worker runs this is free — it reads the frame the loop already
        captured. An idle window costs a real GDI grab, so those are throttled
        by the caller and skipped entirely on ticks where ``capture`` is False.
        """
        if not (session.is_running or capture or self._needs_frame):
            return
        pixmap = preview.to_pixmap(session.preview_frame())
        if pixmap is None:
            self._thumbnail.set_text("KHÔNG CHỤP ĐƯỢC")
            return
        self._needs_frame = False
        self._thumbnail.set_pixmap(pixmap)


class ShardPanel(QtWidgets.QWidget):
    """What the run has collected, by name.

    Only Ném đậu fills this in — it is the one task whose end-of-round screen
    lists what was won. Everything else leaves it empty and the panel hides
    itself rather than showing a heading over nothing.
    """

    MAX_ROWS = 12

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        column = vbox(0)

        heading = hbox(12)
        heading.addWidget(section_label("Mảnh đã thu"))
        heading.addStretch()
        self._total = label("0", theme.tabular(11), theme.ACCENT)
        heading.addWidget(self._total)
        column.addLayout(heading)
        column.addSpacing(12)

        self._rows_host = QtWidgets.QWidget()
        self._rows = QtWidgets.QGridLayout(self._rows_host)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setHorizontalSpacing(18)
        self._rows.setVerticalSpacing(7)
        column.addWidget(self._rows_host)

        self._more = label("", theme.body(12), theme.TEXT_FAINT)
        column.addWidget(self._more)
        self.setLayout(column)

    def update_from(self, tally: Dict[str, int]) -> None:
        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.setVisible(bool(tally))
        if not tally:
            return

        ordered = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
        self._total.setText("%d mảnh" % sum(tally.values()))
        for index, (name, count) in enumerate(ordered[:self.MAX_ROWS]):
            # Two columns of pairs: a long list down one side wastes the width
            # and pushes the assign section off the bottom.
            row, side = divmod(index, 2)
            self._rows.addWidget(
                label(name, theme.body(13), theme.TEXT_SECONDARY), row, side * 2
            )
            self._rows.addWidget(
                label(str(count), theme.tabular(13), theme.TEXT), row, side * 2 + 1
            )
        self._rows.setColumnStretch(4, 1)

        left = len(ordered) - self.MAX_ROWS
        self._more.setText("và %d thức thần nữa — xem nhật ký chạy" % left if left > 0 else "")
        self._more.setVisible(left > 0)


class TaskView(QtWidgets.QWidget):
    """Config panel plus the cards for windows with this task queued."""

    startRequested = QtCore.pyqtSignal(int)
    stopRequested = QtCore.pyqtSignal(int)
    captureRequested = QtCore.pyqtSignal(int)
    recordRequested = QtCore.pyqtSignal(int)
    revealRequested = QtCore.pyqtSignal(int)
    selectRequested = QtCore.pyqtSignal(int, str)      # hwnd, task id
    optionChanged = QtCore.pyqtSignal(str, str, object)         # task id, key, value
    windowOptionChanged = QtCore.pyqtSignal(int, str, object)   # hwnd, key, value

    def __init__(self, spec: tasks.TaskSpec, config: Dict[str, object],
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.spec = spec
        self._cards: Dict[int, TaskWindowCard] = {}
        self._order: List[int] = []
        self._columns = MAX_CARD_COLUMNS
        # Kept only so the coordinate picker has a window to photograph. It
        # prefers one already set to this task, because that is the window
        # whose screen the point is being chosen for.
        self._chosen: List[GameSession] = []
        self._others: List[GameSession] = []

        row = hbox(0)

        panel = ConfigPanel(spec, config, frame_source=self._any_frame)
        panel.optionChanged.connect(self.optionChanged)
        row.addWidget(panel)
        row.addWidget(Divider(horizontal=False))
        row.addWidget(self._build_windows(), 1)
        self.setLayout(row)

    def _any_frame(self) -> Optional[Any]:
        """A frame from some open game window, for the coordinate picker.

        Any window will do — every one of them is resized to the same client
        size, so a point picked on one lands in the same place on the rest.
        """
        for session in list(self._chosen) + list(self._others):
            frame = session.preview_frame()
            if frame is not None:
                return frame
        return None

    def _build_windows(self) -> QtWidgets.QWidget:
        scroll = QtWidgets.QScrollArea()
        self._scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        holder = QtWidgets.QWidget()
        column = vbox(0, margins=(30, 24, 30, 30))

        heading = hbox(12)
        heading.addWidget(section_label("Cửa sổ đang gán tác vụ này"))
        heading.addStretch()
        self._count = label("0 cửa sổ", theme.tabular(11), theme.TEXT_FAINT)
        heading.addWidget(self._count)
        column.addLayout(heading)
        column.addSpacing(16)

        self._grid_host = QtWidgets.QWidget()
        self._grid = QtWidgets.QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(16)
        column.addWidget(self._grid_host)

        self._none_assigned = body_text(
            "Chưa cửa sổ nào chạy tác vụ này. Gán thêm ở dưới.", 13.5, theme.TEXT_MUTED
        )
        column.addWidget(self._none_assigned)

        column.addSpacing(26)
        self._shards = ShardPanel()
        self._shards.setVisible(False)
        column.addWidget(self._shards)

        column.addSpacing(26)
        self._assign_label = section_label("Gán thêm cửa sổ")
        column.addWidget(self._assign_label)
        column.addSpacing(12)
        self._free_host = QtWidgets.QWidget()
        self._free = FlowLayout(self._free_host, spacing=9)
        column.addWidget(self._free_host)
        column.addStretch()

        holder.setLayout(column)
        scroll.setWidget(holder)
        return scroll

    # ── refresh ─────────────────────────────────────────────────────────────

    def set_sessions(self, chosen: Sequence[GameSession],
                     others: Sequence[GameSession]) -> None:
        assigned, free = chosen, others
        self._chosen = list(chosen)
        self._others = list(others)
        wanted = {session.hwnd for session in assigned}
        for hwnd in list(self._cards):
            if hwnd not in wanted:
                card = self._cards.pop(hwnd)
                self._grid.removeWidget(card)
                card.deleteLater()

        for session in assigned:
            if session.hwnd in self._cards:
                continue
            card = TaskWindowCard(session, self.spec)
            card.startRequested.connect(self.startRequested)
            card.stopRequested.connect(self.stopRequested)
            card.captureRequested.connect(self.captureRequested)
            card.recordRequested.connect(self.recordRequested)
            card.revealRequested.connect(self.revealRequested)
            card.optionChanged.connect(self.windowOptionChanged)
            self._cards[session.hwnd] = card

        self._order = [session.hwnd for session in assigned]
        self._place_cards()

        self._count.setText("%d cửa sổ" % len(assigned))
        self._grid_host.setVisible(bool(assigned))
        self._none_assigned.setVisible(not assigned)
        self._rebuild_free(free)

    # ── responsive grid ─────────────────────────────────────────────────────

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        columns = self._columns_that_fit()
        if columns != self._columns:
            self._columns = columns
            self._place_cards()

    def _columns_that_fit(self) -> int:
        width = self._scroll.viewport().width() - 60   # the column's own margins
        spacing = self._grid.spacing()
        fits = (width + spacing) // (MIN_CARD_WIDTH + spacing)
        return max(1, min(MAX_CARD_COLUMNS, int(fits)))

    def _place_cards(self) -> None:
        for index, hwnd in enumerate(self._order):
            card = self._cards.get(hwnd)
            if card is not None:
                self._grid.addWidget(
                    card, index // self._columns, index % self._columns
                )
        # Cards are capped, so the spare width goes to a trailing column rather
        # than stretching them unevenly.
        for index in range(MAX_CARD_COLUMNS):
            self._grid.setColumnStretch(index, 0)
        self._grid.setColumnStretch(MAX_CARD_COLUMNS, 1)

    def _rebuild_free(self, free: Sequence[GameSession]) -> None:
        while self._free.count():
            item = self._free.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Unparent before deleting, or the outgoing buttons keep
                # painting at their old positions until the loop runs.
                widget.setParent(None)
                widget.deleteLater()

        for session in free:
            button = controls.OutlineButton("→  " + session.title, padding="9px 15px")
            button.setToolTip("Chuyển cửa sổ này sang tác vụ %s" % self.spec.name)
            button.clicked.connect(
                lambda _checked=False, hwnd=session.hwnd:
                    self.selectRequested.emit(hwnd, self.spec.id)
            )
            self._free.addWidget(button)
        # Hide the heading too — a section label with nothing under it reads as
        # a list that failed to load.
        self._free_host.setVisible(bool(free))
        self._assign_label.setVisible(bool(free))

    def refresh(self, assigned: Sequence[GameSession], capture: bool = True) -> None:
        for session in assigned:
            card = self._cards.get(session.hwnd)
            if card is not None:
                card.update_from(session, capture)
        self._shards.update_from(self._merged_shards(assigned))

    def _merged_shards(self, assigned: Sequence[GameSession]) -> Dict[str, int]:
        """One tally across every window running this task.

        Summed rather than shown per window: several windows farming the same
        parade are still one pile of shards to whoever is reading.
        """
        total: Dict[str, int] = {}
        for session in assigned:
            # shards_for, not shards: a window that ran something else before
            # being assigned here must not show that task's haul under this
            # heading.
            for name, count in session.shards_for(self.spec.id).items():
                total[name] = total.get(name, 0) + count
        return total
