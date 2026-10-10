"""Grid cards for the wiki lists."""
from __future__ import annotations

from typing import Callable, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

import theme
from ui.primitives import Badge, Card, HatchFrame, elide_to_lines, label, vbox
from wiki.images import ImageResolver
from wiki.models import Shikigami, Soul

SHIKI_IMAGE_HEIGHT = 118
NAME_LINES = 2
SHIKI_NAME_HEIGHT = 44
SOUL_THUMB = 62
GOLD_RARITIES = {"SSR", "SP"}


def rarity_colors(rarity: str):
    """Gold for the top two tiers, muted for the rest — as in the design."""
    if rarity in GOLD_RARITIES:
        return theme.ACCENT, theme.BORDER_HOVER
    return theme.TEXT_DIM, theme.CONTROL


class _HoverCard(Card):
    """Card that warms its outline on hover and reports clicks."""

    def __init__(self, on_click: Optional[Callable[[], None]] = None) -> None:
        super().__init__()
        self._on_click = on_click
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setAttribute(QtCore.Qt.WA_Hover, True)

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self.set_border(theme.BORDER_HOVER)
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self.set_border(theme.BORDER)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton and self._on_click is not None:
            self._on_click()
        super().mouseReleaseEvent(event)


class ShikigamiCard(_HoverCard):
    """Portrait, rarity badge, Vietnamese name, other-language name."""

    def __init__(
        self,
        record: Shikigami,
        resolver: ImageResolver,
        on_click: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(on_click)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # The badge floats over the portrait's top-right corner.
        image_area = QtWidgets.QWidget()
        image_area.setFixedHeight(SHIKI_IMAGE_HEIGHT)
        art = HatchFrame("image", cover=True, parent=image_area)
        art.setGeometry(0, 0, 10_000, SHIKI_IMAGE_HEIGHT)
        art.set_pixmap(resolver.pixmap(record.image))

        colour, border = rarity_colors(record.rarity)
        badge = Badge(record.rarity, colour, border, parent=image_area)
        badge.setFont(theme.mono(9.5, tracking=0.1))
        badge.setStyleSheet(
            "color: %s; border: 1px solid %s; border-radius: %dpx;"
            " padding: 2px 5px; background: rgba(16, 15, 14, 0.8);"
            % (colour, border, theme.RADIUS_BADGE)
        )
        self._art = art
        self._badge = badge
        image_area.installEventFilter(self)
        self._image_area = image_area

        body = QtWidgets.QWidget()
        body_layout = QtWidgets.QVBoxLayout(body)
        body_layout.setContentsMargins(11, 10, 11, 12)
        body_layout.setSpacing(4)

        # Names run to three or four words; two lines keeps every card the same
        # height, so the name is elided to fit rather than clipped by the card.
        self._full_name = record.display_name
        name = label(record.display_name, theme.display(17))
        name.setWordWrap(True)
        name.setFixedHeight(SHIKI_NAME_HEIGHT)
        name.setAlignment(QtCore.Qt.AlignTop)
        self._name = name

        # Second line carries the other-language name when there is one. It is
        # hidden rather than left blank so cards do not reserve an empty row.
        self._full_secondary = record.secondary_name
        secondary = label(record.secondary_name, theme.body(11.5), theme.TEXT_LABEL)
        secondary.setToolTip(record.secondary_name)
        # Names like "Shinjou Hoshiguma Douji" are wider than a grid cell; without
        # a zero minimum the label pushes every column out past the viewport.
        secondary.setMinimumWidth(0)
        secondary.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed
        )
        self._secondary = secondary

        body_layout.addWidget(name)
        body_layout.addWidget(secondary)
        # Only now that it has a parent. A parentless QWidget is a window, so
        # setVisible() before this point maps a real one on screen — 85 cards
        # doing that is 85 popups flashing when the list re-renders.
        secondary.setVisible(bool(record.secondary_name))

        layout.addWidget(image_area)
        layout.addWidget(body)
        self.setToolTip(record.display_name)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched is self._image_area and event.type() == QtCore.QEvent.Resize:
            width = self._image_area.width()
            self._art.setGeometry(0, 0, width, SHIKI_IMAGE_HEIGHT)
            self._badge.adjustSize()
            self._badge.move(width - self._badge.width() - 7, 7)
            self._badge.raise_()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._name.setText(
            elide_to_lines(
                self._full_name, self._name.font(), self._name.width(), NAME_LINES
            )
        )
        if self._full_secondary:
            metrics = QtGui.QFontMetrics(self._secondary.font())
            self._secondary.setText(
                metrics.elidedText(
                    self._full_secondary, QtCore.Qt.ElideRight, self._secondary.width()
                )
            )


class SoulCard(_HoverCard):
    """Square thumbnail beside the name, kind and first set bonus."""

    def __init__(
        self,
        record: Soul,
        resolver: ImageResolver,
        on_click: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(on_click)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(13)

        frame = QtWidgets.QFrame()
        frame.setObjectName("soulThumb")
        frame.setFixedSize(SOUL_THUMB, SOUL_THUMB)
        frame.setStyleSheet(
            "#soulThumb { border: 1px solid %s; background: %s; }"
            % (theme.DIVIDER, theme.INSET)
        )
        frame_layout = QtWidgets.QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        art = HatchFrame("img", cover=True)
        art.set_pixmap(resolver.pixmap(record.image))
        frame_layout.addWidget(art)

        text = vbox(3)
        text.addWidget(label(record.display_name, theme.display(19)))
        text.addWidget(
            label(record.kind_label.upper(), theme.mono(10, tracking=0.12), theme.TEXT_LABEL)
        )
        summary = label(record.summary, theme.body(12.5), theme.TEXT_SECONDARY)
        summary.setWordWrap(True)
        text.addSpacing(4)
        text.addWidget(summary)

        layout.addWidget(frame, 0, QtCore.Qt.AlignTop)
        layout.addLayout(text, 1)
        text.addStretch()
