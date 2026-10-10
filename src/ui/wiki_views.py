"""List, table and search views for the wiki."""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Sequence, Tuple

from PyQt5 import QtCore, QtWidgets, sip

import theme
from ui import controls
from ui.primitives import Divider, body_text, hbox, label, section_label, vbox
from ui.wiki_cards import ShikigamiCard, SoulCard
from wiki.images import ImageResolver
from wiki.models import RARITY_CHOICES, Effect, Shikigami, Soul

SHIKI_COLUMNS = 6
SOUL_COLUMNS = 4
GRID_SPACING = 14
CONTENT_MARGINS = (26, 22, 26, 28)

# How long one slice of grid filling may run before handing the event loop back.
#
# Only the first slice is painted, so the ones after it cannot drop a frame and
# the budget is really about input latency. Widening it to 40 ms on that
# reasoning cut the slice count from 69 to 18 and measured *worse* on both
# counts that matter — 858 ms total against 786, and up to 40 ms before a click
# is looked at. Whatever the fill spends is not per-slice overhead, so there is
# nothing to buy back by yielding less often. 8 ms it is.
#
# The first visit of a session has to decode every portrait as it goes, 1.9 ms
# a card on the shipped roster, which is why any of this is needed.
FILL_BUDGET_SECONDS = 0.008

# Rows to place in the first, visible slice, so the tab opens with something
# on it rather than filling in from empty.
#
# Counted in rows and deliberately not cut short by the budget: bounded by time
# it managed two cards before yielding, because the first cards of a run are
# its slowest — 3.8 ms each against the 1.9 ms average, with the font and style
# caches still cold. Four rows on that reading cost 91 ms, which is the freeze
# this was all meant to remove, so it is two.
FIRST_SLICE_ROWS = 2

# How long a fill must already have been running before it says so.
#
# The grid visibly filling is itself the progress report, so the line is only
# worth adding once the wait is long enough to read as a stall. Below this it
# would be a one-frame flash: eight cold portraits already overrun a single
# slice, so without the delay even a filtered handful announced itself.
LOADING_AFTER_SECONDS = 0.15


class ProgressiveGrid:
    """Fills a QGridLayout with cards a slice at a time.

    Mixed into the two card grids. Subclasses provide ``_grid``, ``_columns``,
    ``_loading`` and ``_build_card``; this owns the cache, the slicing and the
    abandoning of a fill whose list is no longer wanted.
    """

    def _init_fill(self) -> None:
        # Built cards, keyed by record id, reused across renders and thrown
        # away by forget_cards() when the dataset is replaced.
        self._cards: Dict[str, QtWidgets.QWidget] = {}
        self._queue: List[object] = []
        self._filled = 0
        self._fill_started = 0.0
        # Bumped by anything that invalidates a fill in flight. A slice that
        # wakes with a stale token does nothing: without it, a fill started
        # before a filter change would carry on placing records the user has
        # just excluded, and one interrupted by a sync would place cards that
        # have been destroyed.
        self._token = 0

    @property
    def is_filling(self) -> bool:
        """Whether cards are still being placed."""
        return self._filled < len(self._queue)

    def _start_fill(self, records: Sequence[object]) -> None:
        self._token += 1
        self._queue = list(records)
        self._filled = 0
        self._fill_started = time.perf_counter()
        detach_layout(self._grid)
        self._grid_host.setUpdatesEnabled(True)
        self._fill_slice(self._token, visible=True)

    def _abandon_fill(self) -> None:
        self._token += 1
        self._queue = []
        self._filled = 0
        # Never leave the host frozen: nothing else would ever thaw it, and the
        # grid would sit there showing whatever was last painted.
        self._grid_host.setUpdatesEnabled(True)

    def _is_gone(self) -> bool:
        """Whether the widgets this fill writes into have been destroyed.

        The token is not enough. It cancels a fill that a *newer* fill has
        superseded, and says nothing about whether the view is still there —
        but slicing guarantees there is always a moment with the next slice
        queued in the event loop and nothing having run it yet. A view closed
        in that moment leaves a queued call holding a live Python wrapper
        around a deleted C++ layout, and every line below touches that layout.

        It matters more than a stray traceback would suggest: PyQt turns an
        exception raised inside a slot into an abort, so this did not fail, it
        killed the interpreter with 0xC0000409 — taking every test queued
        behind it down too, and holding CI red for seven runs.

        Both are asked about. The host and the grid are children of the view,
        so destroying the view destroys them; checking only the view would
        still be right today, and would stop being right the moment anything
        rebuilt the grid on its own.
        """
        return sip.isdeleted(self) or sip.isdeleted(self._grid)

    def _fill_slice(self, token: int, visible: bool = False) -> None:
        """Place cards for up to one budget, then hand the loop back.

        The first slice paints: it puts a screenful up so the tab has content
        the moment it opens. Every slice after it runs with updates switched
        off on the host, because what reaches the screen otherwise is a grid
        re-laying-out once per slice — 48 reflows on the shipped roster, 56% of
        them overrunning a frame. One repaint happens when the fill ends.
        """
        if token != self._token:
            return
        if self._is_gone():
            return
        if not visible:
            # Disabled here, at the top of the second and later slices, rather
            # than at the foot of the one before. Disabling on the way out of
            # the first slice meant the event loop never got to paint it: the
            # cards were placed, the host was frozen, and the grid stayed blank
            # until the whole fill finished and thawed it — the freeze this was
            # meant to remove, wearing a different hat.
            self._grid_host.setUpdatesEnabled(False)
        limit = FIRST_SLICE_ROWS * self._columns if visible else None
        started = time.perf_counter()
        while self._filled < len(self._queue):
            record = self._queue[self._filled]
            card = self._cards.get(record.id)
            if card is None:
                card = self._build_card(record)
                card._record_id = record.id
                self._cards[record.id] = card
            # addWidget before show, in that order: a card is built with no
            # parent, and show() on an unparented widget makes it a top-level
            # window that flashes on screen. addWidget parents it first.
            self._grid.addWidget(card, self._filled // self._columns,
                                 self._filled % self._columns)
            card.show()
            self._filled += 1
            if limit is not None:
                # The visible slice runs to a full screen, however long that
                # takes: this is the content the tab opens with.
                if self._filled >= limit:
                    break
            elif time.perf_counter() - started >= FILL_BUDGET_SECONDS:
                break
        if self.is_filling:
            waited = time.perf_counter() - self._fill_started
            self._loading.setVisible(waited >= LOADING_AFTER_SECONDS)
            QtCore.QTimer.singleShot(0, lambda: self._fill_slice(token))
        else:
            self._loading.setVisible(False)
            self._grid_host.setUpdatesEnabled(True)

    def forget_cards(self) -> None:
        """Destroy every cached card. Called when the dataset is replaced.

        A sync brings new names, artwork and rarities, and a card kept from
        before would quietly go on showing the old ones.
        """
        self._abandon_fill()
        detach_layout(self._grid)
        for card in self._cards.values():
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()
        self._loading.setVisible(False)


def clear_layout(layout: QtWidgets.QLayout) -> None:
    """Remove and destroy every item in a layout."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def detach_layout(layout: QtWidgets.QLayout) -> None:
    """Empty a layout, leaving its widgets alive and hidden.

    The counterpart to :func:`clear_layout`, for grids whose contents are worth
    keeping. A card taken out of a layout is still parented to the host widget
    and would otherwise carry on painting where it sat, so each one is hidden on
    the way out and shown again by whoever puts it back.
    """
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()


def scrollable() -> Tuple[QtWidgets.QScrollArea, QtWidgets.QWidget]:
    """A vertical scroll area and the widget to fill."""
    area = QtWidgets.QScrollArea()
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    inner = QtWidgets.QWidget()
    area.setWidget(inner)
    return area, inner


def chip_row(
    caption: str, choices: Sequence[str], mono: bool, on_pick
) -> Tuple[QtWidgets.QLayout, QtWidgets.QButtonGroup]:
    """Caption plus a set of mutually exclusive filter chips."""
    row = hbox(8)
    row.addWidget(section_label(caption))
    group = QtWidgets.QButtonGroup()
    group.setExclusive(True)
    for index, name in enumerate(choices):
        chip = controls.Chip(name, mono=mono)
        chip.setChecked(index == 0)
        group.addButton(chip, index)
        row.addWidget(chip)
    group.idClicked.connect(lambda index: on_pick(choices[index]))
    return row, group


class ShikigamiListView(ProgressiveGrid, QtWidgets.QWidget):
    """Filter strip over a portrait grid."""

    opened = QtCore.pyqtSignal(str)
    filtersChanged = QtCore.pyqtSignal()

    def __init__(self, resolver: ImageResolver, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._resolver = resolver
        self._init_fill()
        self.rarity = RARITY_CHOICES[0]

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_filters())
        layout.addWidget(Divider())

        area, inner = scrollable()
        outer = QtWidgets.QVBoxLayout(inner)
        outer.setContentsMargins(*CONTENT_MARGINS)
        outer.setSpacing(0)
        self._grid_host = QtWidgets.QWidget()
        self._grid = QtWidgets.QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(GRID_SPACING)
        self._grid.setAlignment(QtCore.Qt.AlignTop)
        # Above the grid, not below it. Under the grid it moved down a step
        # every slice as the rows arrived, which was half of what the stutter
        # looked like.
        self._loading = body_text("Đang tải…", 13, theme.TEXT_FAINT)
        self._loading.setAlignment(QtCore.Qt.AlignCenter)
        self._loading.setVisible(False)
        outer.addWidget(self._loading)
        outer.addWidget(self._grid_host)
        self._empty = body_text("Không có kết quả nào.", 14, theme.TEXT_MUTED)
        self._empty.setAlignment(QtCore.Qt.AlignCenter)
        outer.addWidget(self._empty)
        outer.addStretch()
        layout.addWidget(area, 1)

    _columns = SHIKI_COLUMNS

    def _build_card(self, record) -> QtWidgets.QWidget:
        return ShikigamiCard(
            record,
            self._resolver,
            on_click=lambda record_id=record.id: self.opened.emit(record_id),
        )

    def _build_filters(self) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(holder)
        row.setContentsMargins(26, 14, 26, 14)
        row.setSpacing(26)

        rarity_row, self._rarity_group = chip_row(
            "Hạng", RARITY_CHOICES, True, self._on_rarity
        )
        row.addLayout(rarity_row)
        row.addStretch()

        self._count = label("", theme.tabular(11), theme.TEXT_FAINT)
        row.addWidget(self._count)
        return holder

    def _on_rarity(self, value: str) -> None:
        self.rarity = value
        self.filtersChanged.emit()

    def render(self, records: Sequence[Shikigami]) -> None:
        """Begin placing a card per record; returns before they are all up.

        Rebuilding every card cost 225 ms on the shipped roster of 270, paid
        again on every visit; building them for the first time cost 515 ms with
        the event loop blocked, so the tab did not appear until it was done.
        Cards are now kept between renders and placed a slice at a time. See
        tests/test_wiki_card_reuse.py and tests/test_wiki_progressive_fill.py.
        """
        self._count.setText("%d kết quả" % len(records))
        for column in range(SHIKI_COLUMNS):
            self._grid.setColumnStretch(column, 1)
        self._empty.setVisible(not records)
        self._grid_host.setVisible(bool(records))
        self._start_fill(records)


class SoulListView(ProgressiveGrid, QtWidgets.QWidget):
    """Grid of soul-set cards."""

    opened = QtCore.pyqtSignal(str)

    def __init__(self, resolver: ImageResolver, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._resolver = resolver
        self._init_fill()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        area, inner = scrollable()
        outer = QtWidgets.QVBoxLayout(inner)
        outer.setContentsMargins(*CONTENT_MARGINS)
        outer.setSpacing(0)
        self._grid_host = QtWidgets.QWidget()
        self._grid = QtWidgets.QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(GRID_SPACING)
        self._grid.setAlignment(QtCore.Qt.AlignTop)
        # Above the grid, not below it. Under the grid it moved down a step
        # every slice as the rows arrived, which was half of what the stutter
        # looked like.
        self._loading = body_text("Đang tải…", 13, theme.TEXT_FAINT)
        self._loading.setAlignment(QtCore.Qt.AlignCenter)
        self._loading.setVisible(False)
        outer.addWidget(self._loading)
        outer.addWidget(self._grid_host)
        self._empty = body_text("Không có kết quả nào.", 14, theme.TEXT_MUTED)
        self._empty.setAlignment(QtCore.Qt.AlignCenter)
        outer.addWidget(self._empty)
        outer.addStretch()
        layout.addWidget(area, 1)

    _columns = SOUL_COLUMNS

    def _build_card(self, record) -> QtWidgets.QWidget:
        return SoulCard(
            record,
            self._resolver,
            on_click=lambda record_id=record.id: self.opened.emit(record_id),
        )

    def render(self, records: Sequence[Soul]) -> None:
        """As ShikigamiListView.render: reused cards, placed a slice at a time."""
        for column in range(SOUL_COLUMNS):
            self._grid.setColumnStretch(column, 1)
        self._empty.setVisible(not records)
        self._grid_host.setVisible(bool(records))
        self._start_fill(records)


class EffectsView(QtWidgets.QWidget):
    """Reference table: icon, name, category, description.

    Every Effect record carries an ``image`` and this table used to ignore it.
    Only 59 of the shipped 109 have a file, though — the other 50 name one that
    exists neither locally nor in the Supabase bucket — so the icon column
    holds its width whether or not there is anything to put in it. Letting it
    collapse would shift the names and categories of half the rows out of line
    with the other half.
    """

    # icon, name, category. The description takes what is left.
    ICON_COLUMN = 46
    ICON_SIZE = 32
    COLUMNS = (190, 130)

    def __init__(self, resolver: ImageResolver,
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        # Passed in rather than built here so the icons share one pixmap cache
        # with the shikigami and soul grids — see wiki/images.py on what a
        # cache smaller than its working set is worth.
        self._resolver = resolver
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        area, inner = scrollable()
        outer = QtWidgets.QVBoxLayout(inner)
        outer.setContentsMargins(26, 22, 26, 30)
        outer.setSpacing(0)

        header = hbox(0, margins=(0, 0, 0, 9))
        # The icon column carries no caption — there is nothing useful to call
        # it — but it must still take up its width in the header or every
        # caption sits one column left of the data beneath it.
        for caption, width in (("", self.ICON_COLUMN),
                               ("Hiệu ứng", self.COLUMNS[0]),
                               ("Phân loại", self.COLUMNS[1])):
            item = section_label(caption)
            item.setFixedWidth(width)
            header.addWidget(item)
        header.addWidget(section_label("Mô tả"), 1)
        header_host = QtWidgets.QWidget()
        header_host.setLayout(header)
        self._header = header_host
        outer.addWidget(header_host)
        outer.addWidget(Divider(color=theme.CONTROL))

        self._rows = vbox(0, margins=(0, 0, 0, 0))
        # Built rows, keyed by record id, reused across renders.
        self._cards: Dict[str, QtWidgets.QWidget] = {}
        rows_host = QtWidgets.QWidget()
        rows_host.setLayout(self._rows)
        outer.addWidget(rows_host)
        outer.addStretch()
        layout.addWidget(area, 1)

    def render(self, records: Sequence[Effect]) -> None:
        """Place a row per record, building only the ones not built yet.

        A table rather than a card grid, so there is no artwork to decode and
        no reason to fill it in slices — but tearing down all 109 rows and
        rebuilding them made this the slowest tab once the two grids had been
        fixed, at 124 ms a visit. Rows live until forget_cards().
        """
        detach_layout(self._rows)
        for record in records:
            row = self._cards.get(record.id)
            if row is None:
                row = self._build_row(record)
                row._record_id = record.id
                self._cards[record.id] = row
            self._rows.addWidget(row)
            row.show()

    def forget_cards(self) -> None:
        """Destroy every cached row. Called when the dataset is replaced."""
        detach_layout(self._rows)
        for row in self._cards.values():
            row.setParent(None)
            row.deleteLater()
        self._cards.clear()

    def _icon(self, record: Effect) -> QtWidgets.QWidget:
        """The effect's icon, or an empty slot of the same width.

        The icons ship at 44x44 and 30x30, so they are scaled down to a single
        size and never up: a 30px icon blown up to 44 is mush next to a real
        44px one beside it.
        """
        slot = QtWidgets.QLabel()
        slot.setFixedWidth(self.ICON_COLUMN)
        slot.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        if not record.image:
            return slot
        pixmap = self._resolver.pixmap(record.image)
        if pixmap is None or pixmap.isNull():
            return slot
        if max(pixmap.width(), pixmap.height()) > self.ICON_SIZE:
            pixmap = pixmap.scaled(
                self.ICON_SIZE, self.ICON_SIZE,
                QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        slot.setPixmap(pixmap)
        return slot

    def _build_row(self, record: Effect) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        wrapper = QtWidgets.QVBoxLayout(holder)
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.setSpacing(0)

        row = hbox(0, margins=(0, 13, 0, 13))

        row.addWidget(self._icon(record), 0, QtCore.Qt.AlignTop)

        names = vbox(1)
        names.addWidget(label(record.display_name, theme.display(18), wrap=True))
        if record.en_name:
            names.addWidget(
                label(record.en_name, theme.body(11.5, italic=True),
                      theme.TEXT_FAINT, wrap=True)
            )
        names_host = QtWidgets.QWidget()
        names_host.setLayout(names)
        names_host.setFixedWidth(self.COLUMNS[0])

        kind = label(
            record.kind_label.upper(),
            theme.mono(10.5, tracking=0.1),
            theme.EFFECT_KIND_COLOR.get(record.kind, theme.TEXT_DIM),
        )
        kind.setFixedWidth(self.COLUMNS[1])
        kind.setAlignment(QtCore.Qt.AlignTop)

        description = body_text(record.description, 13.5, theme.TEXT_SECONDARY, justify=True)
        description.setContentsMargins(0, 0, 20, 0)

        # Alignment goes on each item: QLayout.setAlignment would place the
        # layout, leaving the short columns vertically centred against the
        # wrapped description.
        row.addWidget(names_host, 0, QtCore.Qt.AlignTop)
        row.addWidget(kind, 0, QtCore.Qt.AlignTop)
        row.addWidget(description, 1, QtCore.Qt.AlignTop)

        wrapper.addLayout(row)
        wrapper.addWidget(Divider(color=theme.ROW_RULE))
        return holder


class SearchResultsView(QtWidgets.QWidget):
    """Flat, mixed-type result list."""

    opened = QtCore.pyqtSignal(str, str)  # kind, id

    COLUMNS = (118, 220)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        area, inner = scrollable()
        outer = QtWidgets.QVBoxLayout(inner)
        outer.setContentsMargins(26, 22, 26, 30)
        outer.setSpacing(0)

        self._caption = section_label("")
        outer.addWidget(self._caption)
        outer.addSpacing(14)

        self._rows = vbox(0, margins=(0, 0, 0, 0))
        rows_host = QtWidgets.QWidget()
        rows_host.setLayout(self._rows)
        outer.addWidget(rows_host)
        outer.addStretch()
        layout.addWidget(area, 1)

    def render(self, query: str, results: Sequence[dict]) -> None:
        clear_layout(self._rows)
        self._caption.setText(
            ("%d KẾT QUẢ CHO “%s”" % (len(results), query)).upper()
        )
        for result in results:
            self._rows.addWidget(self._build_row(result))

    def _build_row(self, result: dict) -> QtWidgets.QWidget:
        holder = _ResultRow(result, self.opened)
        wrapper = QtWidgets.QVBoxLayout(holder)
        wrapper.setContentsMargins(0, 13, 0, 13)
        wrapper.setSpacing(0)

        row = hbox(16, margins=(0, 0, 0, 0))

        kind = label(result["type"].upper(), theme.mono(10, tracking=0.16), theme.ACCENT)
        kind.setFixedWidth(self.COLUMNS[0])
        title = label(result["title"], theme.display(19), wrap=True)
        title.setFixedWidth(self.COLUMNS[1])
        # Subtitles are whole sentences for effects; wrapping keeps the row from
        # setting the page width.
        subtitle = label(result["subtitle"], theme.body(13), theme.TEXT_MUTED, wrap=True)
        subtitle.setTextFormat(QtCore.Qt.PlainText)

        row.addWidget(kind)
        row.addWidget(title)
        row.addWidget(subtitle, 1)
        wrapper.addLayout(row)
        return holder


class _ResultRow(QtWidgets.QWidget):
    """One clickable search hit."""

    def __init__(self, result: dict, signal: QtCore.pyqtSignal) -> None:
        super().__init__()
        self._result = result
        self._signal = signal
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setAttribute(QtCore.Qt.WA_Hover, True)
        self.setStyleSheet(
            "_ResultRow { border-bottom: 1px solid %s; }" % theme.ROW_RULE
        )

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self.setStyleSheet(
            "_ResultRow { background: %s; border-bottom: 1px solid %s; }"
            % (theme.ROW_HOVER, theme.ROW_RULE)
        )
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self.setStyleSheet(
            "_ResultRow { border-bottom: 1px solid %s; }" % theme.ROW_RULE
        )
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self._signal.emit(self._result["kind"], self._result["id"])
        super().mouseReleaseEvent(event)
