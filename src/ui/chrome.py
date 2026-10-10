"""Frameless window shell with the design's custom title bar.

The design draws its own chrome — a 38px bar with a diamond, a tracked mono
caption and three hit areas — so the window is created frameless and the bar
takes over dragging, maximising and closing.
"""
from __future__ import annotations

from typing import Optional

import ctypes
import ctypes.wintypes

import win32con
from PyQt5 import QtCore, QtGui, QtWidgets

import theme
from ui.primitives import Diamond

TITLE_BAR_HEIGHT = 38
BUTTON_WIDTH = 44
# There is no margin around the frame any more. One existed to hold a drop
# shadow, and then stayed on as the only place the window itself could catch a
# mouse move for resizing. Both reasons are gone: the shadow was removed, and
# resizing is answered through WM_NCHITTEST, which does not care which child
# widget is painted where. See `nativeEvent`.
RESIZE_MARGIN = 6


class _ChromeButton(QtWidgets.QLabel):
    """One of the minimise / maximise / close hit areas."""

    clicked = QtCore.pyqtSignal()

    def __init__(
        self,
        glyph: str,
        size: float = 13,
        hover_background: str = theme.HOVER,
        hover_color: str = theme.TEXT,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(glyph, parent)
        self._hover_background = hover_background
        self._hover_color = hover_color
        self.setFixedWidth(BUTTON_WIDTH)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setFont(theme.body(size))
        self.setCursor(QtCore.Qt.ArrowCursor)
        self._restyle(False)

    def _restyle(self, hovered: bool) -> None:
        self.setStyleSheet(
            "background: %s; color: %s;"
            % (
                self._hover_background if hovered else "transparent",
                self._hover_color if hovered else theme.TEXT_DIM,
            )
        )

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._restyle(True)
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._restyle(False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class TitleBar(QtWidgets.QFrame):
    """Draggable caption bar."""

    def __init__(self, title: str, window: QtWidgets.QWidget) -> None:
        super().__init__()
        self._window = window
        self._drag_offset: Optional[QtCore.QPoint] = None
        self.setFixedHeight(TITLE_BAR_HEIGHT)
        self.setStyleSheet(
            "TitleBar { background: %s; border-bottom: 1px solid %s; }"
            % (theme.CHROME, theme.DIVIDER)
        )

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 0, 0)
        layout.setSpacing(10)

        caption = QtWidgets.QLabel(title.upper())
        caption.setFont(theme.mono(11, tracking=0.14))
        caption.setStyleSheet("color: %s; border: 0;" % theme.TEXT_LABEL)

        layout.addWidget(Diamond())
        layout.addWidget(caption)
        layout.addStretch()

        minimise = _ChromeButton("—")
        minimise.clicked.connect(window.showMinimized)
        maximise = _ChromeButton("▢", size=12)
        maximise.clicked.connect(self._toggle_maximised)
        close = _ChromeButton(
            "✕", hover_background=theme.CLOSE_HOVER, hover_color="#ffffff"
        )
        close.clicked.connect(window.close)

        for button in (minimise, maximise, close):
            button.setFixedHeight(TITLE_BAR_HEIGHT)
            layout.addWidget(button)

    def _toggle_maximised(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_offset = (
                event.globalPos() - self._window.frameGeometry().topLeft()
            )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._drag_offset is None or not event.buttons() & QtCore.Qt.LeftButton:
            return
        if self._window.isMaximized():
            # Restore first, then keep the cursor over the bar.
            self._window.showNormal()
            self._drag_offset = QtCore.QPoint(
                self._window.width() // 2, TITLE_BAR_HEIGHT // 2
            )
        self._window.move(event.globalPos() - self._drag_offset)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self._toggle_maximised()
        super().mouseDoubleClickEvent(event)


class FramelessWindow(QtWidgets.QWidget):
    """Root window: translucent backdrop, rounded body, drop shadow, title bar.

    Subclasses fill :attr:`body` — a plain QWidget below the title bar.
    """

    def __init__(self, title: str, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._frame = QtWidgets.QFrame()
        self._frame.setObjectName("windowFrame")
        self._frame.setStyleSheet(
            "#windowFrame { background: %s; border: 1px solid %s; border-radius: %dpx; }"
            % (theme.WINDOW, theme.BORDER, theme.RADIUS)
        )
        outer.addWidget(self._frame)

        frame_layout = QtWidgets.QVBoxLayout(self._frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        self.title_bar = TitleBar(title, self)
        frame_layout.addWidget(self.title_bar)

        self.body = QtWidgets.QWidget()
        self.body.setStyleSheet("background: transparent;")
        frame_layout.addWidget(self.body, 1)

    # ── edge resizing ───────────────────────────────────────────────────────
    # A frameless window loses the system resize grips, so it has to say where
    # its own edges are. That answer goes to Windows through WM_NCHITTEST rather
    # than being acted on here, and the reason is Qt's own structure: every child
    # is painted into the one top-level HWND, so a hit test covers the whole
    # surface. Handling Qt mouse events instead only ever worked outside the
    # children — the title bar swallowed the top edge, and the rest needed a
    # transparent margin to be caught in, which is no longer there.
    #
    # Windows then draws the cursors, drags the edge and snaps to other windows.

    HIT_CODES = {
        QtCore.Qt.LeftEdge: win32con.HTLEFT,
        QtCore.Qt.RightEdge: win32con.HTRIGHT,
        QtCore.Qt.TopEdge: win32con.HTTOP,
        QtCore.Qt.BottomEdge: win32con.HTBOTTOM,
        QtCore.Qt.LeftEdge | QtCore.Qt.TopEdge: win32con.HTTOPLEFT,
        QtCore.Qt.RightEdge | QtCore.Qt.TopEdge: win32con.HTTOPRIGHT,
        QtCore.Qt.LeftEdge | QtCore.Qt.BottomEdge: win32con.HTBOTTOMLEFT,
        QtCore.Qt.RightEdge | QtCore.Qt.BottomEdge: win32con.HTBOTTOMRIGHT,
    }

    def _edge_at(self, position: QtCore.QPoint) -> int:
        rect = self.rect()
        edge = 0
        if abs(position.x() - rect.left()) <= RESIZE_MARGIN:
            edge |= QtCore.Qt.LeftEdge
        elif abs(position.x() - rect.right()) <= RESIZE_MARGIN:
            edge |= QtCore.Qt.RightEdge
        if abs(position.y() - rect.top()) <= RESIZE_MARGIN:
            edge |= QtCore.Qt.TopEdge
        elif abs(position.y() - rect.bottom()) <= RESIZE_MARGIN:
            edge |= QtCore.Qt.BottomEdge
        return edge

    @classmethod
    def _hit_code(cls, edge: int) -> Optional[int]:
        """What to tell Windows this point is. None means "not an edge"."""
        return cls.HIT_CODES.get(edge)

    def nativeEvent(self, event_type, message):
        """Claim the edges so Windows resizes the window for us.

        The cursor position comes from Qt rather than from the message's lParam:
        lParam carries physical pixels, and mapping those onto widget
        coordinates goes wrong the moment display scaling is not 100%.

        Maximised windows are left alone — there is no edge to drag there, and
        claiming one would let a stray press unmaximise into a resize.
        """
        if event_type == b"windows_generic_MSG" and message is not None:
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == win32con.WM_NCHITTEST and not self.isMaximized():
                local = self.mapFromGlobal(QtGui.QCursor.pos())
                code = self._hit_code(self._edge_at(local))
                if code is not None:
                    return True, code
        return super().nativeEvent(event_type, message)

