"""The navigation column: overview, one row per task, then tools.

Every task row is built from the :mod:`tasks` registry, so adding an
automation puts it in the sidebar without this file changing.
"""
from __future__ import annotations

from typing import Dict, Optional

from PyQt5 import QtCore, QtWidgets

import tasks
import theme
from ui import controls
from ui.primitives import Divider, label, section_label, vbox
from ui.wiki_page import SECTIONS as WIKI_SECTIONS

WIDTH = 244
HOME = "__home__"
# A page like any other, reached from the sidebar. It used to be a modal opened
# from the "Công cụ" list, and outgrew that: four switches with an explanation
# under each, plus the version, contact and release blocks, is a tall box to put
# in front of a window with room to spare.
SETTINGS = "__settings__"
# Wiki sections are pages too, keyed so one router can tell them from task ids.
WIKI_PREFIX = "wiki:"


def wiki_key(section: str) -> str:
    return WIKI_PREFIX + section


def wiki_section_of(key: str) -> Optional[str]:
    """The wiki section a page key names, or ``None`` if it names something else."""
    return key[len(WIKI_PREFIX):] if key.startswith(WIKI_PREFIX) else None


class TaskSidebar(QtWidgets.QWidget):
    """Left column. Emits the key of whatever the user picked."""

    pageSelected = QtCore.pyqtSignal(str)
    scanRequested = QtCore.pyqtSignal()
    logsRequested = QtCore.pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(WIDTH)
        self.setObjectName("taskSidebar")
        self.setStyleSheet("#taskSidebar { background: %s; }" % theme.SIDEBAR)

        self._rows: Dict[str, controls.NavItem] = {}
        self._current = HOME

        column = QtWidgets.QVBoxLayout(self)
        column.setContentsMargins(0, 22, 0, 16)
        column.setSpacing(0)

        column.addWidget(self._build_brand())
        column.addWidget(Divider())
        # The nav scrolls and the footer does not: the list grows with every
        # task added, and it already outgrew a 900px window once — which cut the
        # "Quét cửa sổ" button in half rather than scrolling to it.
        column.addWidget(self._build_nav(), 1)
        column.addWidget(self._build_footer())
        self.set_current(HOME)

    def _build_nav(self) -> QtWidgets.QWidget:
        content = QtWidgets.QWidget()
        column = vbox(0)

        column.addWidget(self._pad(section_label("Tổng quan"), top=0))
        column.addWidget(self._add_row(HOME, "Bảng điều khiển"))

        column.addWidget(self._pad(section_label("Tác vụ auto"), top=18))
        for spec in tasks.TASKS:
            row = self._add_row(spec.id, spec.name, dot=True)
            row.set_available(spec.is_available)
            if not spec.is_available:
                row.setToolTip("Chưa cài đặt — %s" % spec.todo)
            column.addWidget(row)

        column.addWidget(self._pad(section_label("Bách khoa Âm Dương Sư"), top=18))
        for section, name in WIKI_SECTIONS:
            column.addWidget(self._add_row(wiki_key(section), name))

        column.addWidget(self._pad(section_label("Công cụ"), top=18))
        column.addWidget(self._add_row(SETTINGS, "Cài đặt chung", hint="F9"))
        column.addWidget(self._build_tool("Nhật ký chạy", "LOG", self.logsRequested))
        column.addStretch()
        content.setLayout(column)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    # ── construction ────────────────────────────────────────────────────────

    def _build_brand(self) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        block = vbox(6, margins=(20, 0, 20, 18))
        block.addWidget(
            label("%s V%s" % (theme.APP_NAME.upper(), theme.APP_VERSION),
                  theme.mono(10, tracking=0.26), theme.ACCENT)
        )
        block.addWidget(label(theme.APP_SUBTITLE, theme.display(25)))
        holder.setLayout(block)
        return holder

    def _pad(self, widget: QtWidgets.QWidget, top: int = 14) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        box = vbox(0, margins=(20, top, 20, 8))
        box.addWidget(widget)
        holder.setLayout(box)
        return holder

    def _add_row(self, key: str, text: str, dot: bool = False,
                 hint: str = "") -> controls.NavItem:
        row = controls.NavItem(key, text, hint, dot=dot)
        row.clicked.connect(self._on_row_clicked)
        self._rows[key] = row
        return row

    def _build_tool(self, text: str, hint: str, signal) -> QtWidgets.QWidget:
        row = controls.NavItem(text, text, hint)
        row.clicked.connect(lambda _key: signal.emit())
        return row

    def _build_footer(self) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        block = vbox(0, margins=(20, 0, 20, 0))
        block.addSpacing(8)
        block.addWidget(Divider())

        self._hint = label(
            "F1 TẠM DỪNG · F2 DỪNG HẾT", theme.mono(10, tracking=0.1), theme.TEXT_FAINT
        )
        self._hint.setContentsMargins(0, 13, 0, 0)
        self._found = label(
            "0 CỬA SỔ NHẬN DIỆN", theme.mono(10, tracking=0.1), theme.TEXT_FAINT
        )
        block.addWidget(self._hint)
        block.addWidget(self._found)

        scan = controls.OutlineButton("Quét cửa sổ", size=12.5, padding="9px 0")
        scan.clicked.connect(self.scanRequested)
        scan.setContentsMargins(0, 12, 0, 0)
        block.addSpacing(12)
        block.addWidget(scan)

        holder.setLayout(block)
        return holder

    # ── state ───────────────────────────────────────────────────────────────

    def set_current(self, key: str) -> None:
        self._current = key
        for row_key, row in self._rows.items():
            row.set_active(row_key == key)

    def set_hint(self, text: str) -> None:
        self._hint.setText(text.upper())

    def update_counts(
        self, window_count: int, running_count: int, per_task: Dict[str, tuple]
    ) -> None:
        """``per_task`` maps a task id to ``(assigned, running)``."""
        self._found.setText("%d CỬA SỔ NHẬN DIỆN" % window_count)
        self._rows[HOME].set_count("%d/%d" % (running_count, window_count))
        for spec in tasks.TASKS:
            row = self._rows.get(spec.id)
            if row is None:
                continue
            assigned, running = per_task.get(spec.id, (0, 0))
            row.set_count("—" if not spec.is_available else str(assigned))
            row.set_status(theme.ACCENT if running else theme.CONTROL, bool(running))

    def set_wiki_counts(self, counts: Dict[str, int]) -> None:
        for section, _name in WIKI_SECTIONS:
            row = self._rows.get(wiki_key(section))
            if row is not None:
                row.set_count(str(counts.get(section, 0)))

    def _on_row_clicked(self, key: str) -> None:
        self.pageSelected.emit(key)
