"""Interactive controls.

The design uses outline buttons throughout — transparent fill, coloured stroke,
a wash on hover. Three tones carry all the meaning: neutral for secondary
actions, accent (gold) for the primary one, danger for anything that stops work.
"""
from __future__ import annotations

from typing import Callable, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

import theme
from ui import primitives

NEUTRAL = "neutral"
ACCENT = "accent"
DANGER = "danger"

_TONES = {
    # tone: (text, border, hover background, hover border, pressed background)
    NEUTRAL: (theme.TEXT_SECONDARY, theme.CONTROL, "transparent",
              theme.CONTROL_HOVER, theme.HOVER),
    ACCENT: (theme.ACCENT, theme.ACCENT, theme.ACCENT_WASH,
             theme.ACCENT, theme.ACCENT_PRESSED),
    DANGER: (theme.DANGER, theme.DANGER_BORDER, theme.DANGER_WASH,
             theme.DANGER_BORDER_HOVER, theme.DANGER_WASH),
}


class OutlineButton(QtWidgets.QPushButton):
    """The design's signature button."""

    def __init__(
        self,
        text: str,
        tone: str = NEUTRAL,
        size: float = 13,
        padding: str = "10px 18px",
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(text, parent)
        self.setFont(theme.body(size))
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        self._padding = padding
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        fg, border, hover_bg, hover_border, pressed_bg = _TONES[tone]
        self._tone = tone
        self.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent;
                color: {fg};
                border: 1px solid {border};
                border-radius: {theme.RADIUS}px;
                padding: {self._padding};
            }}
            QPushButton:hover {{
                background: {hover_bg};
                border-color: {hover_border};
                color: {theme.TEXT if tone == NEUTRAL else fg};
            }}
            QPushButton:pressed {{ background: {pressed_bg}; }}
            QPushButton:disabled {{ color: {theme.TEXT_FAINT};
                                    border-color: {theme.BORDER}; }}
            """
        )


class Chip(QtWidgets.QPushButton):
    """Filter chip — checkable, gold when selected."""

    def __init__(
        self,
        text: str,
        mono: bool = False,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFont(theme.mono(11, tracking=0.08) if mono else theme.body(12))
        self.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
        self.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent;
                color: {theme.TEXT_DIM};
                border: 1px solid {theme.CONTROL};
                border-radius: {theme.RADIUS_SMALL}px;
                padding: 5px 11px;
            }}
            QPushButton:hover {{ border-color: {theme.ACCENT}; }}
            QPushButton:checked {{
                background: {theme.ACCENT_FILL};
                color: {theme.ACCENT};
                border-color: {theme.ACCENT};
            }}
            """
        )


class CheckMark(QtWidgets.QWidget):
    """The 15px checkbox square.

    The tick is drawn rather than typed: none of the bundled faces carry a
    convincing U+2713, and the fallback glyph reads as a capital V.
    """

    SIZE = 15

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._checked = False
        self.setFixedSize(self.SIZE, self.SIZE)

    def set_checked(self, checked: bool) -> None:
        self._checked = checked
        self.update()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        box = QtCore.QRectF(0.5, 0.5, self.SIZE - 1, self.SIZE - 1)

        painter.setPen(
            QtGui.QPen(QtGui.QColor(theme.ACCENT if self._checked else theme.CONTROL_STRONG), 1)
        )
        painter.setBrush(
            QtGui.QColor(theme.ACCENT) if self._checked else QtCore.Qt.NoBrush
        )
        painter.drawRoundedRect(box, theme.RADIUS_SMALL, theme.RADIUS_SMALL)

        if not self._checked:
            return
        pen = QtGui.QPen(QtGui.QColor(theme.WINDOW), 1.8)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        painter.setPen(pen)
        path = QtGui.QPainterPath()
        path.moveTo(self.SIZE * 0.27, self.SIZE * 0.52)
        path.lineTo(self.SIZE * 0.44, self.SIZE * 0.70)
        path.lineTo(self.SIZE * 0.75, self.SIZE * 0.32)
        painter.drawPath(path)


class Toggle(QtWidgets.QWidget):
    """Checkbox row from the settings strip: a square mark plus a label."""

    toggled = QtCore.pyqtSignal(bool)

    def __init__(
        self,
        text: str,
        checked: bool = False,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._checked = checked
        self.setCursor(QtCore.Qt.PointingHandCursor)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        self._mark = CheckMark()

        self._label = QtWidgets.QLabel(text)
        self._label.setFont(theme.body(13))

        layout.addWidget(self._mark)
        layout.addWidget(self._label)
        self._restyle()

    def is_checked(self) -> bool:
        return self._checked

    def set_checked(self, checked: bool) -> None:
        if checked == self._checked:
            return
        self._checked = checked
        self._restyle()
        self.toggled.emit(checked)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self.set_checked(not self._checked)
        super().mousePressEvent(event)

    def _restyle(self) -> None:
        self._mark.set_checked(self._checked)
        self._label.setStyleSheet(
            "color: %s; background: transparent;"
            % (theme.TEXT if self._checked else theme.TEXT_DIM)
        )


class SearchField(QtWidgets.QFrame):
    """Bordered search box with a leading glyph and a shortcut hint."""

    textChanged = QtCore.pyqtSignal(str)

    def __init__(
        self,
        placeholder: str,
        hint: str = "CTRL K",
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setFixedHeight(38)
        # Scoped to this widget so the border does not cascade onto the glyph,
        # the line edit and the shortcut hint.
        self.setObjectName("searchField")
        self.setStyleSheet(
            "#searchField { background: %s; border: 1px solid %s; border-radius: %dpx; }"
            % (theme.INSET, theme.CONTROL, theme.RADIUS)
        )

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(10)

        glyph = QtWidgets.QLabel("⌕")
        glyph.setFont(theme.body(15))
        glyph.setStyleSheet("color: %s; border: 0;" % theme.TEXT_FAINT)

        self.input = QtWidgets.QLineEdit()
        self.input.setPlaceholderText(placeholder)
        self.input.setFont(theme.body(13.5))
        self.input.setStyleSheet(
            "QLineEdit { background: transparent; border: 0; color: %s; }"
            "QLineEdit::placeholder { color: %s; }" % (theme.TEXT, theme.TEXT_FAINT)
        )
        self.input.textChanged.connect(self.textChanged)

        self._hint = QtWidgets.QLabel(hint)
        self._hint.setFont(theme.mono(10, tracking=0.1))
        self._hint.setStyleSheet("color: %s; border: 0;" % theme.TEXT_FAINT)

        layout.addWidget(glyph)
        layout.addWidget(self.input, 1)
        layout.addWidget(self._hint)

    def text(self) -> str:
        return self.input.text()

    def set_text(self, value: str) -> None:
        self.input.setText(value)

    def focus(self) -> None:
        self.input.setFocus(QtCore.Qt.ShortcutFocusReason)
        self.input.selectAll()


class NavItem(QtWidgets.QWidget):
    """Sidebar row: label on the left, count on the right, gold rule when active.

    With ``dot=True`` a status light sits between the two, which is how the task
    rows show that a window is mid-run without opening the task.
    """

    clicked = QtCore.pyqtSignal(str)

    def __init__(
        self,
        key: str,
        text: str,
        count: str = "",
        dot: bool = False,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.key = key
        self._active = False
        self._hovered = False
        self._enabled = True
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setAttribute(QtCore.Qt.WA_Hover, True)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(20, 11, 20, 11)
        layout.setSpacing(10)

        self._label = QtWidgets.QLabel(text)
        self._label.setFont(theme.body(14.5))
        self._count = QtWidgets.QLabel(count)
        self._count.setFont(theme.tabular(11))
        self._count.setStyleSheet("color: %s;" % theme.TEXT_FAINT)

        layout.addWidget(self._label)
        layout.addStretch()
        self._dot: Optional[primitives.StatusDot] = None
        if dot:
            self._dot = primitives.StatusDot(theme.CONTROL, diameter=6)
            layout.addWidget(self._dot)
        layout.addWidget(self._count)
        self._restyle()

    def set_count(self, count: str) -> None:
        self._count.setText(count)

    def set_status(self, color: str, pulsing: bool) -> None:
        if self._dot is not None:
            self._dot.set_color(color)
            self._dot.set_pulsing(pulsing)

    def set_available(self, available: bool) -> None:
        """A task with no worker behind it still shows, but reads as inert."""
        self._enabled = available
        self.setCursor(
            QtCore.Qt.PointingHandCursor if available else QtCore.Qt.ArrowCursor
        )
        self._restyle()

    def set_active(self, active: bool) -> None:
        self._active = active
        self._restyle()

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = True
        self._restyle()
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = False
        self._restyle()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit(self.key)
        super().mousePressEvent(event)

    def _restyle(self) -> None:
        if self._active:
            background = theme.HOVER
        elif self._hovered:
            background = theme.CARD
        else:
            background = "transparent"
        self.setStyleSheet(
            "NavItem { background: %s; border-left: 2px solid %s; }"
            % (background, theme.ACCENT if self._active else "transparent")
        )
        if not self._enabled:
            ink = theme.TEXT_FAINT
        elif self._active:
            ink = theme.TEXT
        else:
            ink = theme.TEXT_NAV
        self._label.setStyleSheet(
            "color: %s; background: transparent; border: 0;" % ink
        )
        self._count.setStyleSheet(
            "color: %s; background: transparent; border: 0;" % theme.TEXT_FAINT
        )


def clickable(widget: QtWidgets.QWidget, handler: Callable[[], None]) -> QtWidgets.QWidget:
    """Attach a left-click handler to any widget, hand it back."""

    def on_press(event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            handler()

    widget.setCursor(QtCore.Qt.PointingHandCursor)
    widget.mousePressEvent = on_press  # type: ignore[assignment]
    return widget
