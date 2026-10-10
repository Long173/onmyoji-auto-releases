"""Non-interactive building blocks: labels, rules, frames, indicators."""
from __future__ import annotations

from typing import List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

import theme

HATCH_STRIPE = 8  # px, matches the design's repeating-linear-gradient


def vbox(spacing: int = 0, margins=(0, 0, 0, 0)) -> QtWidgets.QVBoxLayout:
    """Vertical layout with no implicit padding.

    Qt gives every layout a 9px margin by default, which silently inflates a
    design specified in exact pixels — a nested column ends up 18px taller than
    its content. Always build nested layouts through these helpers.
    """
    layout = QtWidgets.QVBoxLayout()
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


def hbox(spacing: int = 0, margins=(0, 0, 0, 0)) -> QtWidgets.QHBoxLayout:
    """Horizontal layout with no implicit padding. See :func:`vbox`."""
    layout = QtWidgets.QHBoxLayout()
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


def label(
    text: str,
    font: QtGui.QFont,
    color: str = theme.TEXT,
    parent: Optional[QtWidgets.QWidget] = None,
    wrap: bool = False,
) -> QtWidgets.QLabel:
    """A plain text label. Every label in the app goes through here.

    ``wrap`` matters for more than looks: an unwrapped QLabel reports its full
    single-line width as its minimum, so one long title can push a whole page
    wider than the window and force horizontal scrolling.
    """
    widget = QtWidgets.QLabel(text, parent)
    widget.setFont(font)
    widget.setStyleSheet("color: %s; background: transparent;" % color)
    if wrap:
        widget.setWordWrap(True)
        widget.setMinimumWidth(0)
        policy = QtWidgets.QSizePolicy(
            QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Minimum
        )
        policy.setHeightForWidth(True)
        widget.setSizePolicy(policy)
    return widget


def section_label(text: str, color: str = theme.TEXT_LABEL) -> QtWidgets.QLabel:
    """Mono, uppercase, widely tracked — the design's section heading."""
    return label(text.upper(), theme.mono(10, tracking=0.2), color)


def eyebrow(text: str) -> QtWidgets.QLabel:
    """Gold mono kicker above a page title."""
    return label(text.upper(), theme.mono(10, tracking=0.28), theme.ACCENT)


def body_text(
    text: str,
    size: float = 14.5,
    color: str = theme.TEXT_BODY,
    justify: bool = False,
    italic: bool = False,
) -> QtWidgets.QLabel:
    """Wrapped prose with the design's generous line height."""
    widget = QtWidgets.QLabel(text)
    widget.setFont(theme.body(size, italic=italic))
    widget.setWordWrap(True)
    widget.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
    if justify:
        widget.setAlignment(QtCore.Qt.AlignJustify | QtCore.Qt.AlignTop)
    else:
        widget.setAlignment(QtCore.Qt.AlignTop)
    # Without an explicit height-for-width policy, a wrapped QLabel in a
    # horizontal layout reserves height for its unwrapped size hint and leaves
    # a large gap under short text.
    policy = QtWidgets.QSizePolicy(
        QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum
    )
    policy.setHeightForWidth(True)
    widget.setSizePolicy(policy)
    widget.setStyleSheet("color: %s; background: transparent;" % color)
    return widget


class ElidedLabel(QtWidgets.QLabel):
    """Single-line label that shortens itself rather than widening its parent.

    A plain QLabel reports the full width of its text as its minimum, so one
    long window title stretches the whole column — and, in a grid of cards,
    pushes the last column off the edge of the window. This one asks for
    nothing and truncates to whatever width it is given.
    """

    def __init__(
        self,
        font: QtGui.QFont,
        color: str = theme.TEXT,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._full = ""
        self.setFont(font)
        self.setStyleSheet("color: %s; background: transparent;" % color)
        self.setTextFormat(QtCore.Qt.PlainText)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed
        )

    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        self._full = text or ""
        self.setToolTip(self._full)
        self._apply()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        self._apply()
        super().resizeEvent(event)

    def _apply(self) -> None:
        metrics = QtGui.QFontMetrics(self.font())
        super().setText(
            metrics.elidedText(self._full, QtCore.Qt.ElideRight, max(self.width(), 0))
        )


def elide_to_lines(text: str, font: QtGui.QFont, width: int, max_lines: int) -> str:
    """Shorten ``text`` with an ellipsis until it wraps into ``max_lines``.

    ``QLabel`` only elides single-line text, and grid cards need a predictable
    height, so the truncation point is found here by bisection.
    """
    if width <= 0 or not text:
        return text
    metrics = QtGui.QFontMetrics(font)
    limit = metrics.lineSpacing() * max_lines + 2

    def height_of(value: str) -> int:
        return metrics.boundingRect(
            QtCore.QRect(0, 0, width, 0), QtCore.Qt.TextWordWrap, value
        ).height()

    if height_of(text) <= limit:
        return text

    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if height_of(text[:middle].rstrip() + "…") <= limit:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + "…"


class FlowLayout(QtWidgets.QLayout):
    """Left-to-right layout that wraps onto a new line when it runs out of room.

    Qt ships no wrapping layout. A plain QHBoxLayout of chips reports the sum of
    their widths as its minimum, so a shikigami with several tags pushed the
    detail page wider than the window instead of wrapping.
    """

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
        spacing: int = 7,
    ) -> None:
        super().__init__(parent)
        self._items: List[QtWidgets.QLayoutItem] = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    # QLayout plumbing
    def addItem(self, item: QtWidgets.QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return QtCore.Qt.Orientations(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QtCore.QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QtCore.QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QtCore.QSize:
        return self.minimumSize()

    def minimumSize(self) -> QtCore.QSize:
        size = QtCore.QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QtCore.QSize(
            margins.left() + margins.right(), margins.top() + margins.bottom()
        )

    def _arrange(self, rect: QtCore.QRect, apply: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        x, y, line_height = area.x(), area.y(), 0

        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self.spacing()
            if next_x - self.spacing() > area.right() and line_height > 0:
                x = area.x()
                y += line_height + self.spacing()
                next_x = x + hint.width() + self.spacing()
                line_height = 0
            if apply:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())

        return y + line_height - rect.y() + margins.bottom()


class Divider(QtWidgets.QFrame):
    """A one-pixel rule."""

    def __init__(
        self,
        horizontal: bool = True,
        color: str = theme.DIVIDER,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        if horizontal:
            self.setFixedHeight(1)
        else:
            self.setFixedWidth(1)
        self.setStyleSheet("background: %s; border: 0;" % color)


class Card(QtWidgets.QFrame):
    """Bordered surface used for every panel in the app.

    The stylesheet is scoped to this widget's own object name. A bare
    ``QFrame { border: ... }`` rule cascades into every child, drawing a box
    around each nested label.
    """

    _next_id = 0

    def __init__(
        self,
        background: str = theme.CARD,
        border: str = theme.BORDER,
        radius: int = theme.RADIUS,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        Card._next_id += 1
        self.setObjectName("card%d" % Card._next_id)
        self._background = background
        self._radius = radius
        self.set_border(border)

    def set_border(self, color: str) -> None:
        """Cards change outline colour to signal state (running, hovered)."""
        self.setStyleSheet(
            "#%s { background: %s; border: 1px solid %s; border-radius: %dpx; }"
            % (self.objectName(), self._background, color, self._radius)
        )


class HatchFrame(QtWidgets.QWidget):
    """Diagonal-stripe placeholder shown until an image is available.

    Also renders the image once one is set, letterboxed inside the frame.
    """

    # Ceiling for hug mode. Without one, a portrait-shaped picture would make
    # the frame taller than the column is wide and push everything under it —
    # the stats, the souls, the counters — off the visible page.
    HUG_MAX_HEIGHT = 420

    def __init__(
        self,
        text: str = "",
        cover: bool = False,
        hug: bool = False,
        hug_min: int = 0,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._text = text.upper()
        self._pixmap: Optional[QtGui.QPixmap] = None
        # cover: fill the frame and crop the overflow, the way a CSS
        # ``object-fit: cover`` thumbnail behaves. Otherwise letterbox.
        self._cover = cover
        # hug: take exactly the height this picture needs at whatever width the
        # layout gives, instead of keeping the height it was built with. For
        # the detail page, where a fixed 300 left 107px of empty inset under an
        # avatar that only needed 194. Off by default: the card grids set an
        # exact height deliberately and must keep it.
        self._hug = hug
        # What to ask for while there is no picture: the hatched placeholder is
        # all there is to see then, and it needs room to be seen.
        self._hug_min = hug_min
        if hug:
            policy = self.sizePolicy()
            policy.setHeightForWidth(True)
            self.setSizePolicy(policy)
        self.setAttribute(QtCore.Qt.WA_StyledBackground, False)

    def set_text(self, text: str) -> None:
        self._text = text.upper()
        self.update()

    def set_pixmap(self, pixmap: Optional[QtGui.QPixmap]) -> None:
        self._pixmap = pixmap
        if self._hug:
            # The shape changed, so whatever height the layout worked out from
            # the previous picture is stale.
            self.updateGeometry()
        self.update()

    def hasHeightForWidth(self) -> bool:
        return self._hug

    def heightForWidth(self, width: int) -> int:
        """The height this picture needs at that width.

        -1 outside hug mode: Qt's "no opinion", leaving the frame sized by its
        layout the way every other HatchFrame in the app is.
        """
        if not self._hug:
            return -1
        if (self._pixmap is None or self._pixmap.isNull()
                or self._pixmap.height() <= 0 or width <= 0):
            return max(self._hug_min, 1)
        aspect = self._pixmap.width() / self._pixmap.height()
        return min(self.HUG_MAX_HEIGHT, max(1, round(width / aspect)))

    def sizeHint(self) -> QtCore.QSize:
        hint = super().sizeHint()
        if not self._hug:
            return hint
        width = self.width() or hint.width()
        return QtCore.QSize(width, self.heightForWidth(width))

    def clear(self) -> None:
        self._pixmap = None
        self.update()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect()

        if self._pixmap is not None and not self._pixmap.isNull():
            painter.fillRect(rect, QtGui.QColor(theme.INSET))
            mode = (
                QtCore.Qt.KeepAspectRatioByExpanding
                if self._cover
                else QtCore.Qt.KeepAspectRatio
            )
            scaled = self._pixmap.scaled(
                rect.size(), mode, QtCore.Qt.SmoothTransformation
            )
            # Centre it; in cover mode this is what crops the overflow evenly.
            origin = QtCore.QPoint(
                rect.x() + (rect.width() - scaled.width()) // 2,
                rect.y() + (rect.height() - scaled.height()) // 2,
            )
            painter.setClipRect(rect)
            painter.drawPixmap(origin, scaled)
            return

        self._paint_hatch(painter, rect)
        if self._text:
            painter.setFont(theme.mono(9.5, tracking=0.18))
            painter.setPen(QtGui.QColor(theme.TEXT_FAINT))
            painter.drawText(rect, QtCore.Qt.AlignCenter, self._text)

    def _paint_hatch(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        painter.fillRect(rect, QtGui.QColor(theme.HATCH_DARK))
        painter.save()
        painter.setClipRect(rect)
        pen = QtGui.QPen(QtGui.QColor(theme.HATCH_LIGHT), HATCH_STRIPE)
        painter.setPen(pen)
        # 45° stripes: step twice the stripe width so light and dark alternate.
        step = HATCH_STRIPE * 2
        span = rect.width() + rect.height()
        for offset in range(-rect.height(), span, step):
            painter.drawLine(
                rect.x() + offset,
                rect.y() + rect.height(),
                rect.x() + offset + rect.height(),
                rect.y(),
            )
        painter.restore()


class StatusDot(QtWidgets.QWidget):
    """Small filled circle. Pulses while the worker is running."""

    PULSE_MS = 1600
    MIN_OPACITY = 0.35

    def __init__(
        self,
        color: str = theme.TEXT_DIM,
        diameter: int = 8,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._color = QtGui.QColor(color)
        self._diameter = diameter
        self._opacity = 1.0
        self.setFixedSize(diameter, diameter)

        self._animation = QtCore.QPropertyAnimation(self, b"pulseOpacity", self)
        self._animation.setDuration(self.PULSE_MS)
        self._animation.setStartValue(1.0)
        self._animation.setKeyValueAt(0.5, self.MIN_OPACITY)
        self._animation.setEndValue(1.0)
        self._animation.setLoopCount(-1)
        self._animation.setEasingCurve(QtCore.QEasingCurve.InOutSine)

    def get_pulse_opacity(self) -> float:
        return self._opacity

    def set_pulse_opacity(self, value: float) -> None:
        self._opacity = value
        self.update()

    pulseOpacity = QtCore.pyqtProperty(float, get_pulse_opacity, set_pulse_opacity)

    def set_color(self, color: str) -> None:
        self._color = QtGui.QColor(color)
        self.update()

    def set_pulsing(self, pulsing: bool) -> None:
        if pulsing and self._animation.state() != QtCore.QAbstractAnimation.Running:
            self._animation.start()
        elif not pulsing and self._animation.state() == QtCore.QAbstractAnimation.Running:
            self._animation.stop()
            self.set_pulse_opacity(1.0)

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setOpacity(self._opacity)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(0, 0, self._diameter, self._diameter)


class Diamond(QtWidgets.QWidget):
    """The small rotated square that marks the app in title bars."""

    def __init__(
        self,
        size: int = 7,
        color: str = theme.ACCENT,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._color = QtGui.QColor(color)
        self.setFixedSize(size + 4, size + 4)
        self._size = size

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(45)
        painter.setPen(QtGui.QPen(self._color, 1))
        painter.setBrush(QtCore.Qt.NoBrush)
        half = self._size / 2
        painter.drawRect(QtCore.QRectF(-half, -half, self._size, self._size))


class Badge(QtWidgets.QLabel):
    """Outlined pill for rarity, kind and similar short tags."""

    def __init__(
        self,
        text: str,
        color: str = theme.ACCENT,
        border: Optional[str] = None,
        uppercase: bool = False,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(text.upper() if uppercase else text, parent)
        self.setFont(theme.mono(10.5, tracking=0.14))
        self.setStyleSheet(
            "color: %s; border: 1px solid %s; border-radius: %dpx;"
            " padding: 3px 7px; background: transparent;"
            % (color, border or color, theme.RADIUS_BADGE)
        )
        self.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
