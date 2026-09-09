"""Choose a click position by clicking it on a picture of the game window.

Typing two numbers into a pair of spin boxes would have been a tenth of the
code, and would have been the wrong control: nobody knows that the button they
want is at (1030, 549). They know it is *that button, there*. So the picker
shows the window and takes a click.

Clicking a picture is only as precise as the picture is big, which is the whole
difficulty here. Three things make a single pixel selectable:

* a **loupe** that magnifies the pixels under the cursor, so the choice is made
  on what is actually there rather than on a smudge a mouse-width wide;
* **arrow keys** that nudge the chosen point one pixel at a time (ten with
  Shift), because past a certain precision a mouse is the wrong instrument;
* the frame drawn **1:1 whenever it fits**, so most of the time no scaling sits
  between the cursor and the pixel at all.

The frame is resized to the reference client size if it arrives at some other
size, so the number that gets saved means the same thing whatever window it was
picked on — the same convention every other coordinate in `geometry` follows.
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

import geometry
import theme
from geometry import Region
from ui import controls, preview
from ui.primitives import Divider, body_text, hbox, label, section_label, vbox

# Game pixels the loupe samples, square, and how much bigger it draws them.
# Fifteen is enough context to recognise what you are pointing at; nine times
# is enough that one pixel is a comfortable target.
LOUPE_SOURCE = 15
LOUPE_ZOOM = 9

NUDGE = 1
NUDGE_FAST = 10

# The picture is never drawn bigger than the frame itself — magnifying the whole
# thing would only blur it, and the loupe already covers close work.
MAX_CANVAS = (1122, 633)
# Room the dialog needs around the picture: margins, the heading, the readout
# row and the buttons. Subtracted from the screen before the picture is sized,
# so the dialog fits on a laptop instead of running off the bottom with its
# buttons out of reach.
FURNITURE = (72, 280)
# Below this the picture is too small to aim on at all; better a dialog that
# needs scrolling than one nobody can use.
MIN_CANVAS = (480, 270)


def canvas_cap() -> Tuple[int, int]:
    """How big the picture may be drawn, given the screen it has to fit on."""
    screen = QtWidgets.QApplication.primaryScreen()
    if screen is None:
        return MAX_CANVAS
    area = screen.availableGeometry()
    return (max(MIN_CANVAS[0], min(MAX_CANVAS[0], area.width() - FURNITURE[0])),
            max(MIN_CANVAS[1], min(MAX_CANVAS[1], area.height() - FURNITURE[1])))


def loupe_origin(point: Tuple[int, int],
                 frame_size: Tuple[int, int]) -> Tuple[int, int]:
    """Top-left game pixel of the magnified box, kept inside the frame.

    Clamped rather than shrunk, so the loupe is always the same size — which
    means that near an edge the pixel being pointed at is *not* the middle of
    the loupe. Whoever draws the highlight has to position it from this origin
    rather than assume the centre; getting that wrong points the highlight at
    the wrong pixel exactly where the picture runs out, which is where the
    interesting buttons tend to be.
    """
    half = LOUPE_SOURCE // 2
    width, height = frame_size
    return (max(0, min(width - LOUPE_SOURCE, point[0] - half)),
            max(0, min(height - LOUPE_SOURCE, point[1] - half)))


def loupe_corner(anchor: Tuple[float, float], canvas_size: Tuple[int, int],
                 size: int) -> Tuple[int, int]:
    """Which corner of the picture to park the loupe in, as a top-left.

    Pinned to a corner rather than trailing the cursor, and to the corner
    *furthest* from it. A loupe that follows the mouse sits on top of what is
    being aimed at, and the thing being aimed at here is a button in the bottom
    right of the game screen — so the standard eyedropper behaviour covered the
    target every time it mattered. Parking it opposite means it is never in the
    way, and always in the same few places, which is easier to read than
    something that moves with every twitch.
    """
    width, height = canvas_size
    left = 0 if anchor[0] > width / 2 else max(0, width - size)
    top = 0 if anchor[1] > height / 2 else max(0, height - size)
    return (left, top)


def _inside(point: Tuple[int, int], region) -> bool:
    (x1, y1), (x2, y2) = region
    return x1 <= point[0] <= x2 and y1 <= point[1] <= y2


class _Canvas(QtWidgets.QWidget):
    """The frame, a crosshair, the chosen point, and a loupe."""

    hovered = QtCore.pyqtSignal(int, int)
    picked = QtCore.pyqtSignal(int, int)
    left = QtCore.pyqtSignal()

    def __init__(self, pixmap: QtGui.QPixmap, point: Tuple[int, int],
                 max_size: Optional[Tuple[int, int]] = None,
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._pixmap = pixmap
        self._point = point
        self._hover: Optional[Tuple[int, int]] = None
        self.setMouseTracking(True)
        self.setCursor(QtCore.Qt.CrossCursor)
        # Focusable so the arrow-key nudge reaches here rather than being eaten
        # by a button moving focus.
        self.setFocusPolicy(QtCore.Qt.StrongFocus)

        source = pixmap.size()
        cap = max_size if max_size is not None else canvas_cap()
        scale = min(1.0,
                    cap[0] / max(1, source.width()),
                    cap[1] / max(1, source.height()))
        self._scale = scale
        self.setFixedSize(max(1, round(source.width() * scale)),
                          max(1, round(source.height() * scale)))

    # ── coordinates ─────────────────────────────────────────────────────────

    def _to_game(self, position: QtCore.QPoint) -> Tuple[int, int]:
        x = int(position.x() / self._scale)
        y = int(position.y() / self._scale)
        return (max(0, min(self._pixmap.width() - 1, x)),
                max(0, min(self._pixmap.height() - 1, y)))

    def _to_widget(self, point: Tuple[int, int]) -> QtCore.QPointF:
        """Centre of that game pixel, in widget coordinates."""
        return QtCore.QPointF((point[0] + 0.5) * self._scale,
                              (point[1] + 0.5) * self._scale)

    @property
    def point(self) -> Tuple[int, int]:
        return self._point

    def set_point(self, point: Tuple[int, int]) -> None:
        self._point = (max(0, min(self._pixmap.width() - 1, point[0])),
                       max(0, min(self._pixmap.height() - 1, point[1])))
        self.update()

    def nudge(self, dx: int, dy: int) -> None:
        self.set_point((self._point[0] + dx, self._point[1] + dy))
        self.picked.emit(*self._point)

    # ── events ──────────────────────────────────────────────────────────────

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        self._hover = self._to_game(event.pos())
        self.hovered.emit(*self._hover)
        self.update()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() != QtCore.Qt.LeftButton:
            return
        self.setFocus()
        self.set_point(self._to_game(event.pos()))
        self.picked.emit(*self._point)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hover = None
        self.left.emit()
        self.update()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        step = NUDGE_FAST if event.modifiers() & QtCore.Qt.ShiftModifier else NUDGE
        moves = {
            QtCore.Qt.Key_Left: (-step, 0),
            QtCore.Qt.Key_Right: (step, 0),
            QtCore.Qt.Key_Up: (0, -step),
            QtCore.Qt.Key_Down: (0, step),
        }
        move = moves.get(event.key())
        if move is None:
            super().keyPressEvent(event)
            return
        self.nudge(*move)

    # ── painting ────────────────────────────────────────────────────────────

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.drawPixmap(self.rect(), self._pixmap)
        if self._hover is not None:
            self._draw_crosshair(painter, self._hover)
        self._draw_marker(painter, self._point)
        if self._hover is not None:
            self._draw_loupe(painter, self._hover)
        painter.end()

    def _draw_crosshair(self, painter: QtGui.QPainter, point: Tuple[int, int]) -> None:
        centre = self._to_widget(point)
        pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 110), 1)
        painter.setPen(pen)
        painter.drawLine(QtCore.QPointF(0, centre.y()),
                         QtCore.QPointF(self.width(), centre.y()))
        painter.drawLine(QtCore.QPointF(centre.x(), 0),
                         QtCore.QPointF(centre.x(), self.height()))

    def _draw_marker(self, painter: QtGui.QPainter, point: Tuple[int, int]) -> None:
        centre = self._to_widget(point)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        # Black under white, not the app's gold. The game's own furniture is
        # gold and the start button is cream parchment, so a gold marker
        # vanishes precisely where this point is meant to go — and a marker you
        # cannot see is a coordinate you cannot check. Two tones means one of
        # them always shows, whatever it lands on.
        for colour, width in ((QtGui.QColor(0, 0, 0, 200), 3.0),
                              (QtGui.QColor(255, 255, 255), 1.4)):
            painter.setPen(QtGui.QPen(colour, width))
            painter.drawEllipse(centre, 9, 9)
            for a, b in ((-15, -5), (5, 15)):
                painter.drawLine(centre + QtCore.QPointF(a, 0),
                                 centre + QtCore.QPointF(b, 0))
                painter.drawLine(centre + QtCore.QPointF(0, a),
                                 centre + QtCore.QPointF(0, b))
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)

    def _draw_loupe(self, painter: QtGui.QPainter, point: Tuple[int, int]) -> None:
        x0, y0 = loupe_origin(point, (self._pixmap.width(), self._pixmap.height()))
        source = QtCore.QRect(x0, y0, LOUPE_SOURCE, LOUPE_SOURCE)
        size = LOUPE_SOURCE * LOUPE_ZOOM

        anchor = self._to_widget(point)
        left, top = loupe_corner((anchor.x(), anchor.y()),
                                 (self.width(), self.height()), size)
        target = QtCore.QRect(left, top, size, size)

        painter.fillRect(target.adjusted(-1, -1, 1, 1), QtGui.QColor(0, 0, 0, 220))
        # FastTransformation: nearest-neighbour, so a magnified pixel is a
        # crisp square. Smoothing here would defeat the point of magnifying.
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, False)
        painter.drawPixmap(target, self._pixmap, source)
        painter.setPen(QtGui.QPen(QtGui.QColor(theme.BORDER_HOVER), 1))
        painter.drawRect(target)

        cell = QtCore.QRect(
            target.left() + (point[0] - x0) * LOUPE_ZOOM,
            target.top() + (point[1] - y0) * LOUPE_ZOOM,
            LOUPE_ZOOM, LOUPE_ZOOM,
        )
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 200), 3))
        painter.drawRect(cell)
        painter.setPen(QtGui.QPen(QtGui.QColor(theme.ACCENT_HOVER), 1))
        painter.drawRect(cell)


class PointPicker(QtWidgets.QDialog):
    """Modal that returns a click position, or nothing if it was cancelled."""

    def __init__(self, point: Tuple[int, int],
                 frame_source: Callable[[], Optional[Any]],
                 default: Tuple[int, int],
                 parent: Optional[QtWidgets.QWidget] = None,
                 danger: Optional[Region] = None,
                 danger_note: str = "",
                 title: str = "Chọn chỗ tự nhấn") -> None:
        super().__init__(parent)
        # The danger zone travels with the field that asked for the point, not
        # with the dialog: what a stray click costs depends on which screen the
        # point is for. Nothing passed means nothing to warn about.
        self._danger = danger
        self._danger_note = danger_note
        self.setWindowTitle(title)
        self.setModal(True)
        self.setStyleSheet("QDialog { background: %s; }" % theme.WINDOW)

        self._frame_source = frame_source
        self._default = default
        self._point = point
        self._canvas: Optional[_Canvas] = None

        self._column = vbox(0, margins=(22, 20, 22, 18))
        self._column.addWidget(section_label("Chọn chỗ tự nhấn"))
        self._column.addSpacing(10)
        self._column.addWidget(body_text(
            "Bấm vào đúng chỗ muốn auto nhấn — thường là nút bắt đầu của event. "
            "Kính lúp phóng to chỗ con trỏ đang chỉ; mũi tên trên bàn phím dịch "
            "từng điểm một, giữ Shift để dịch mười điểm. Nếu màn hình nhỏ, ảnh "
            "bị thu lại nên chuột không trỏ tới được từng điểm — dùng mũi tên "
            "để chỉnh nốt.",
            13, theme.TEXT_BODY, justify=True,
        ))
        self._column.addSpacing(14)

        self._holder = QtWidgets.QWidget()
        self._holder_box = vbox(0)
        self._holder.setLayout(self._holder_box)
        self._column.addWidget(self._holder)

        self._column.addSpacing(14)
        self._column.addWidget(self._build_readout())
        self._column.addSpacing(16)
        self._column.addWidget(Divider())
        self._column.addSpacing(14)
        self._column.addLayout(self._build_buttons())
        self.setLayout(self._column)

        self._load_frame()
        self._show_point(*self._point)

    # ── construction ────────────────────────────────────────────────────────

    def _build_readout(self) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        block = vbox(6)

        row = hbox(18)
        self._chosen = label("", theme.tabular(15), theme.TEXT)
        row.addWidget(label("ĐÃ CHỌN", theme.mono(10, tracking=0.18), theme.TEXT_LABEL))
        row.addWidget(self._chosen)
        row.addSpacing(10)
        self._under = label("", theme.tabular(12), theme.TEXT_FAINT)
        row.addWidget(self._under)
        row.addStretch()
        block.addLayout(row)

        # Hidden until it applies. A caution that is always on screen stops
        # being read as a caution.
        self._warning = body_text("", 12.5, theme.DANGER, justify=True)
        self._warning.setVisible(False)
        block.addWidget(self._warning)

        holder.setLayout(block)
        return holder

    def _build_buttons(self) -> QtWidgets.QHBoxLayout:
        row = hbox(9)
        again = controls.OutlineButton("Chụp lại", padding="9px 14px")
        again.setToolTip("Chụp lại cửa sổ game — dùng khi đã chuyển sang màn hình khác")
        again.clicked.connect(self._recapture)
        row.addWidget(again)

        restore = controls.OutlineButton("Về mặc định", padding="9px 14px")
        restore.setToolTip("Quay lại điểm %d, %d" % self._default)
        restore.clicked.connect(lambda: self._set_point(self._default))
        row.addWidget(restore)

        row.addStretch()
        cancel = controls.OutlineButton("Huỷ", padding="9px 16px")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        use = controls.OutlineButton("Dùng điểm này", controls.ACCENT, padding="9px 16px")
        use.clicked.connect(self.accept)
        row.addWidget(use)
        return row

    # ── frame ───────────────────────────────────────────────────────────────

    def _load_frame(self) -> None:
        while self._holder_box.count():
            item = self._holder_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._canvas = None

        pixmap = self._grab()
        if pixmap is None:
            self._holder_box.addWidget(body_text(
                "Chưa chụp được cửa sổ game. Mở game lên rồi bấm “Chụp lại” — "
                "hoặc bấm Huỷ và giữ nguyên điểm đang có.",
                13, theme.TEXT_MUTED, justify=True,
            ))
            return

        canvas = _Canvas(pixmap, self._point)
        canvas.hovered.connect(self._on_hover)
        canvas.picked.connect(self._show_point)
        canvas.left.connect(lambda: self._under.setText(""))
        self._canvas = canvas

        frame = QtWidgets.QFrame()
        frame.setObjectName("pickFrame")
        frame.setStyleSheet(
            "#pickFrame { background: %s; border: 1px solid %s; border-radius: %dpx; }"
            % (theme.INSET, theme.BORDER, theme.RADIUS_SMALL)
        )
        box = vbox(0, margins=(1, 1, 1, 1))
        box.addWidget(canvas, 0, QtCore.Qt.AlignCenter)
        frame.setLayout(box)
        self._holder_box.addWidget(frame, 0, QtCore.Qt.AlignCenter)
        canvas.setFocus()

    def _grab(self) -> Optional[QtGui.QPixmap]:
        """The game window, normalised to the reference client size.

        Resized rather than refused when it comes back some other size: the
        saved number has to mean the same thing on every window, and every task
        resizes the window to the reference size before it runs anyway.
        """
        try:
            frame = self._frame_source()
        except Exception:
            frame = None
        pixmap = preview.to_pixmap(frame)
        if pixmap is None:
            return None
        want = QtCore.QSize(*geometry.REFERENCE_CLIENT_SIZE)
        if pixmap.size() != want:
            pixmap = pixmap.scaled(want, QtCore.Qt.IgnoreAspectRatio,
                                   QtCore.Qt.SmoothTransformation)
        return pixmap

    def _recapture(self) -> None:
        if self._canvas is not None:
            self._point = self._canvas.point
        self._load_frame()
        self._show_point(*self._point)

    # ── readout ─────────────────────────────────────────────────────────────

    def _set_point(self, point: Tuple[int, int]) -> None:
        self._point = point
        if self._canvas is not None:
            self._canvas.set_point(point)
        self._show_point(*point)

    def _on_hover(self, x: int, y: int) -> None:
        self._under.setText("con trỏ  %d, %d" % (x, y))

    def _show_point(self, x: int, y: int) -> None:
        self._point = (x, y)
        self._chosen.setText("%d , %d" % (x, y))
        risky = self._danger is not None and _inside(self._point, self._danger)
        self._warning.setVisible(risky)
        if risky:
            self._warning.setText(self._danger_note)

    # ── result ──────────────────────────────────────────────────────────────

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self.accept()
            return
        super().keyPressEvent(event)

    def point(self) -> Tuple[int, int]:
        if self._canvas is not None:
            return self._canvas.point
        return self._point


def choose_point(point: Tuple[int, int],
                 frame_source: Callable[[], Optional[Any]],
                 default: Tuple[int, int],
                 parent: Optional[QtWidgets.QWidget] = None,
                 danger: Optional[Region] = None,
                 danger_note: str = "",
                 title: str = "Chọn chỗ tự nhấn"
                 ) -> Optional[Tuple[int, int]]:
    """Run the picker. Returns the chosen point, or None if cancelled."""
    dialog = PointPicker(point, frame_source, default, parent,
                         danger, danger_note, title)
    if dialog.exec_() != QtWidgets.QDialog.Accepted:
        return None
    return dialog.point()
