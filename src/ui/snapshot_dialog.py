"""A captured game window, shown so it can be cropped and marked up before it is
sent.

Every screenshot in this project so far has been taken to *show somebody
something* — a badge the loop misread, a counter reading 1/30, a menu missing an
entry. That is what shapes this: the picture arrives already on the clipboard,
because pasting is the common case and it should cost nothing, and the dialog is
for the times cutting away the other nine tenths of the screen says more than a
paragraph would.

Cropping is by dragging the frame, the way a phone's screenshot editor does it,
not by choosing a percentage. Percentages were the first attempt and they answer
the wrong question: a smaller copy of the whole screen is not what somebody wants
when they say "just show me this bit".

Four rules it follows, all of them about not losing anything:

* **Closing writes no file.** Nothing on disk unless Lưu was pressed, so a
  capture taken by mistake leaves nothing to clean up.
* **The clipboard keeps whatever was last put there.** The whole picture goes on
  at capture; a crop or a drawing reaches the clipboard only when Sao chép is
  pressed. Closing does not put the original back — a paste is a paste, and
  silently reverting one would be worse than either behaviour.
* **Cropping never throws pixels away.** The frame is a rectangle held beside
  the picture, so dragging it back out brings the rest of the screen with it.
  Only Sao chép and Lưu apply it.
* **Drawing is undoable and never touches the original.** Strokes go onto a copy
  and the copy can be thrown away, so a slip of the hand cannot spoil a capture.

The picture is drawn on at **full resolution** while being *displayed* scaled to
fit the dialog, so a mark made on a shrunken view lands where it looked like it
would and stays sharp in the saved file.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

import paths
import theme
from ui import controls
from ui.primitives import Divider, body_text, hbox, label, section_label, vbox

logger = logging.getLogger(__name__)

# How large the picture may be drawn in the dialog. A capture is about 1136x640,
# which is wider than comfortable on a laptop screen.
MAX_VIEW = QtCore.QSize(900, 520)

PEN_WIDTH = 3
# Red first: it is what a person reaches for to point at something, and it is
# legible on the game's mostly dark art. The others are for marking a second
# thing in a different colour, which is the only reason to change.
PEN_COLOURS = (
    ("Đỏ", "#e5484d"),
    ("Vàng", "#f5c451"),
    ("Trắng", "#f5f5f5"),
    ("Đen", "#101010"),
)

CROP = "Cắt"
DRAW = "Vẽ"
TEXT = "Chữ"
TOOLS = (CROP, DRAW, TEXT)

# Typed labels are drawn in a plain bold sans, not the app's own serif: the
# picture leaves the app and is read at a glance beside a game screenshot.
#
# A list rather than one name, and checked at use rather than assumed. Asking for
# a family that cannot be resolved does not raise and does not fall back to
# something legible — it hands back a font with *metrics but no glyphs*, so the
# text lays out at the right size and draws absolutely nothing. That is what
# happened here: `QFontInfo(...).family()` came back empty while the metrics
# cheerfully reported an ascent of 31 and a width of 93, and the label silently
# never appeared. Anything that picks a font by name has to check it resolved.
TEXT_FAMILIES = ("Segoe UI", "Tahoma", "Arial", "Verdana")
# As a share of the picture's height, so a label looks the same size whatever
# the capture's resolution is, with a floor for very small pictures.
TEXT_HEIGHT_SHARE = 0.035
TEXT_MIN_SIZE = 14
# Laid down behind the letters in near-black before the colour goes on top.
# Game art is busy and any single colour is illegible somewhere on it.
TEXT_OUTLINE = 2

# How close to an edge a press counts as grabbing it, in the *view's* pixels so
# the target is the same size on screen whatever the picture's resolution is.
GRAB_SLACK = 10
# The smallest crop allowed, in the picture's own pixels. Small enough to isolate
# one button in the game; large enough that the frame cannot be collapsed into
# nothing by a careless drag.
MIN_CROP = 40

# Undo depth. Each entry is a whole copy of the picture — about 2.9 MB at capture
# size — so this is a memory budget as much as a usability one, and twenty
# strokes is far more than anybody draws on a screenshot.
UNDO_LIMIT = 20

# The eight edges and corners, as (grows left, grows top, grows right, grows
# bottom). Dragging 'nw' moves the left and top edges and leaves the others.
EDGES = {
    "nw": (1, 1, 0, 0), "n": (0, 1, 0, 0), "ne": (0, 1, 1, 0),
    "w": (1, 0, 0, 0), "e": (0, 0, 1, 0),
    "sw": (1, 0, 0, 1), "s": (0, 0, 0, 1), "se": (0, 0, 1, 1),
}
CURSORS = {
    "nw": QtCore.Qt.SizeFDiagCursor, "se": QtCore.Qt.SizeFDiagCursor,
    "ne": QtCore.Qt.SizeBDiagCursor, "sw": QtCore.Qt.SizeBDiagCursor,
    "n": QtCore.Qt.SizeVerCursor, "s": QtCore.Qt.SizeVerCursor,
    "w": QtCore.Qt.SizeHorCursor, "e": QtCore.Qt.SizeHorCursor,
    "move": QtCore.Qt.SizeAllCursor,
}


def snapshot_dir() -> Path:
    """Where Lưu offers to put things, created on first use."""
    folder = paths.DATA_ROOT / "snapshots"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def default_name(now: Optional[datetime] = None) -> str:
    """A filename nobody has to think about, and that sorts by time."""
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return "onmyoji-%s.png" % stamp


def chip_row(options, on_pick, chosen: str = "") -> QtWidgets.QWidget:
    """A row of mutually exclusive chips.

    Built here rather than reached for: ``controls`` has the chip but not the
    group, and ``fields`` only assembles one from a task's declared options.
    """
    holder = QtWidgets.QWidget()
    row = hbox(6)
    row.setContentsMargins(0, 0, 0, 0)
    group = QtWidgets.QButtonGroup(holder)
    group.setExclusive(True)
    for index, name in enumerate(options):
        chip = controls.Chip(name)
        chip.setChecked(name == (chosen or options[0]))
        group.addButton(chip, index)
        row.addWidget(chip)
    group.idClicked.connect(lambda index: on_pick(options[index]))
    holder.setLayout(row)
    # Held so the group is not collected while the chips still need it.
    holder._group = group
    return holder


class Canvas(QtWidgets.QWidget):
    """The picture, a crop frame that can be dragged, and freehand strokes.

    Painted rather than pushed into a ``QLabel``: the crop frame has to be drawn
    over the picture and the area outside it dimmed, which a label cannot do.
    """

    strokeStarted = QtCore.pyqtSignal()
    cropChanged = QtCore.pyqtSignal()

    def __init__(self, pixmap: QtGui.QPixmap, parent=None) -> None:
        super().__init__(parent)
        self._picture = pixmap
        self._crop = QtCore.QRect(QtCore.QPoint(0, 0), pixmap.size())
        self._tool = CROP
        self._colour = QtGui.QColor(PEN_COLOURS[0][1])
        self._grabbed: Optional[str] = None
        self._press_crop = QtCore.QRect()
        self._press_at = QtCore.QPoint()
        self._last: Optional[QtCore.QPoint] = None
        self._typing_at: Optional[QtCore.QPoint] = None
        self._editor = self._build_editor()
        self.setMouseTracking(True)
        self.setFixedSize(self._view_size())

    # ── what it holds ───────────────────────────────────────────────────────

    def picture(self) -> QtGui.QPixmap:
        return self._picture

    def set_picture(self, pixmap: QtGui.QPixmap) -> None:
        self._picture = pixmap
        self.update()

    def tool(self) -> str:
        return self._tool

    def crop(self) -> QtCore.QRect:
        return QtCore.QRect(self._crop)

    def cropped(self) -> QtGui.QPixmap:
        """The picture as it would leave: marks on, crop applied."""
        return self._picture.copy(self._crop)

    def reset_crop(self) -> None:
        self._crop = QtCore.QRect(QtCore.QPoint(0, 0), self._picture.size())
        self.cropChanged.emit()
        self.update()

    def is_cropped(self) -> bool:
        return self._crop.size() != self._picture.size()

    def set_tool(self, tool: str) -> None:
        # Anything half-typed is committed rather than dropped: switching tools
        # is not the same gesture as pressing Escape.
        if self._typing_at is not None:
            self._commit_text()
        self._tool = tool
        self.setCursor({DRAW: QtCore.Qt.CrossCursor,
                        TEXT: QtCore.Qt.IBeamCursor}.get(tool,
                                                         QtCore.Qt.ArrowCursor))

    def set_colour(self, colour: str) -> None:
        self._colour = QtGui.QColor(colour)

    # ── the two coordinate spaces ───────────────────────────────────────────

    def _view_size(self) -> QtCore.QSize:
        return self._picture.size().scaled(MAX_VIEW, QtCore.Qt.KeepAspectRatio)

    def _scale(self) -> float:
        view = self._view_size()
        if not self._picture.width():
            return 1.0
        return view.width() / self._picture.width()

    def _to_picture(self, point: QtCore.QPoint) -> QtCore.QPoint:
        """Where a click on the shrunken view lands on the real picture."""
        factor = self._scale() or 1.0
        return QtCore.QPoint(round(point.x() / factor), round(point.y() / factor))

    def _to_view(self, rect: QtCore.QRect) -> QtCore.QRect:
        factor = self._scale()
        return QtCore.QRect(
            round(rect.x() * factor), round(rect.y() * factor),
            round(rect.width() * factor), round(rect.height() * factor),
        )

    # ── painting ────────────────────────────────────────────────────────────

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(self.rect(), self._picture)

        frame = self._to_view(self._crop)
        if self.is_cropped():
            # Dimmed rather than hidden: what is being cut away is still worth
            # seeing while deciding where to cut.
            shade = QtGui.QPainterPath()
            shade.addRect(QtCore.QRectF(self.rect()))
            keep = QtGui.QPainterPath()
            keep.addRect(QtCore.QRectF(frame))
            painter.fillPath(shade.subtracted(keep), QtGui.QColor(0, 0, 0, 140))

        painter.setPen(QtGui.QPen(QtGui.QColor(theme.ACCENT), 1))
        painter.drawRect(frame.adjusted(0, 0, -1, -1))
        if self._tool == CROP:
            self._paint_handles(painter, frame)
        painter.end()

    def _paint_handles(self, painter: QtGui.QPainter, frame: QtCore.QRect) -> None:
        painter.setBrush(QtGui.QColor(theme.ACCENT))
        painter.setPen(QtGui.QPen(QtGui.QColor("#101010"), 1))
        for point in self._handle_points(frame).values():
            painter.drawRect(QtCore.QRect(point.x() - 4, point.y() - 4, 8, 8))

    @staticmethod
    def _handle_points(frame: QtCore.QRect) -> dict:
        mid_x = frame.center().x()
        mid_y = frame.center().y()
        return {
            "nw": QtCore.QPoint(frame.left(), frame.top()),
            "n": QtCore.QPoint(mid_x, frame.top()),
            "ne": QtCore.QPoint(frame.right(), frame.top()),
            "w": QtCore.QPoint(frame.left(), mid_y),
            "e": QtCore.QPoint(frame.right(), mid_y),
            "sw": QtCore.QPoint(frame.left(), frame.bottom()),
            "s": QtCore.QPoint(mid_x, frame.bottom()),
            "se": QtCore.QPoint(frame.right(), frame.bottom()),
        }

    # ── deciding what a press grabbed ───────────────────────────────────────

    def grab_at(self, pos: QtCore.QPoint) -> Optional[str]:
        """Which handle is under a view position — or "move", or nothing."""
        frame = self._to_view(self._crop)
        for name, point in self._handle_points(frame).items():
            if (abs(pos.x() - point.x()) <= GRAB_SLACK
                    and abs(pos.y() - point.y()) <= GRAB_SLACK):
                return name
        return "move" if frame.contains(pos) else None

    # ── mouse ───────────────────────────────────────────────────────────────

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._tool == CROP and self._grabbed is None:
            grab = self.grab_at(event.pos())
            self.setCursor(CURSORS.get(grab, QtCore.Qt.ArrowCursor))
        if self._grabbed is not None:
            self._drag_crop(event.pos())
        elif self._last is not None:
            self._draw_to(event.pos())

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() != QtCore.Qt.LeftButton:
            return
        if self._tool == CROP:
            self._grabbed = self.grab_at(event.pos())
            self._press_crop = QtCore.QRect(self._crop)
            self._press_at = event.pos()
            return
        if self._tool == TEXT:
            # A second click while typing finishes the first label and starts
            # another, which is how one gets two captions without visiting the
            # chips in between.
            if self._typing_at is not None:
                self._commit_text()
            self._start_typing(event.pos())
            return
        # Announced before the first pixel changes, so the undo stack keeps the
        # picture as it was rather than as it is halfway through a stroke.
        self.strokeStarted.emit()
        self._last = self._to_picture(event.pos())

    def mouseReleaseEvent(self, _event: QtGui.QMouseEvent) -> None:
        self._grabbed = None
        self._last = None

    # ── the two things a drag can do ────────────────────────────────────────

    def _drag_crop(self, pos: QtCore.QPoint) -> None:
        factor = self._scale() or 1.0
        dx = round((pos.x() - self._press_at.x()) / factor)
        dy = round((pos.y() - self._press_at.y()) / factor)
        started = self._press_crop
        bounds = QtCore.QRect(QtCore.QPoint(0, 0), self._picture.size())

        if self._grabbed == "move":
            moved = QtCore.QRect(started)
            moved.translate(dx, dy)
            # Pushed back inside rather than clamped edge by edge, so a box
            # dragged off the side keeps its size instead of being squashed.
            moved.moveLeft(max(0, min(moved.left(), bounds.width() - moved.width())))
            moved.moveTop(max(0, min(moved.top(), bounds.height() - moved.height())))
            self._crop = moved
        else:
            left, top, right, bottom = EDGES.get(self._grabbed, (0, 0, 0, 0))
            box = QtCore.QRect(
                started.left() + dx * left,
                started.top() + dy * top,
                0, 0,
            )
            box.setRight(started.right() + dx * right)
            box.setBottom(started.bottom() + dy * bottom)
            self._crop = self._sane(box, started, bounds)
        self.cropChanged.emit()
        self.update()

    @staticmethod
    def _sane(box: QtCore.QRect, started: QtCore.QRect,
              bounds: QtCore.QRect) -> QtCore.QRect:
        """Keep a dragged frame inside the picture and above the minimum size.

        Each edge is held separately. Clamping the rectangle as a whole would let
        a corner dragged past the opposite one flip the frame inside out, which
        looks like the crop jumping to the other side of the picture.
        """
        left = max(0, min(box.left(), started.right() - MIN_CROP))
        top = max(0, min(box.top(), started.bottom() - MIN_CROP))
        right = min(bounds.width() - 1, max(box.right(), started.left() + MIN_CROP))
        bottom = min(bounds.height() - 1, max(box.bottom(), started.top() + MIN_CROP))
        sane = QtCore.QRect()
        sane.setCoords(left, top, right, bottom)
        return sane

    # ── typing on the picture ───────────────────────────────────────────────

    def _build_editor(self) -> QtWidgets.QLineEdit:
        """The box that appears where the picture was clicked.

        A real editor rather than keystrokes painted as they arrive: it gives
        backspace, selection and a caret for free, and nothing touches the
        picture until the text is finished, so a typo costs nothing.
        """
        editor = QtWidgets.QLineEdit(self)
        editor.hide()
        editor.setFrame(False)
        editor.returnPressed.connect(self._commit_text)
        editor.installEventFilter(self)
        return editor

    def text_size(self) -> int:
        """Point size for typed labels, in the picture's own scale."""
        return max(TEXT_MIN_SIZE, round(self._picture.height() * TEXT_HEIGHT_SHARE))

    def _picture_font(self) -> QtGui.QFont:
        return self._font_at(self.text_size())

    @staticmethod
    def _font_at(size: int) -> QtGui.QFont:
        """A bold sans that this machine can really draw.

        Falls through the preferred families and settles for Qt's own default
        rather than a named font that resolved to nothing. See TEXT_FAMILIES.
        """
        for family in TEXT_FAMILIES:
            font = QtGui.QFont(family, size, QtGui.QFont.Bold)
            # By resolved family name, not ``exactMatch()``. That is far
            # stricter than it sounds — it wants the size and style to match
            # too, so it answers False for fonts that are perfectly available,
            # and using it meant this loop never chose anything.
            if QtGui.QFontInfo(font).family().lower() == family.lower():
                return font
        fallback = QtGui.QFont()
        fallback.setPointSize(size)
        fallback.setBold(True)
        return fallback

    def _start_typing(self, pos: QtCore.QPoint) -> None:
        self._typing_at = self._to_picture(pos)
        # Shown at the size it will end up, so what is typed is what appears.
        view_size = max(9, round(self.text_size() * self._scale()))
        self._editor.setFont(self._font_at(view_size))
        self._editor.setStyleSheet(
            "QLineEdit { background: rgba(0,0,0,150); color: %s;"
            " selection-background-color: %s; padding: 0 2px; }"
            % (self._colour.name(), theme.ACCENT)
        )
        self._editor.clear()
        self._editor.setFixedWidth(max(140, self.width() - pos.x() - 8))
        self._editor.move(pos)
        self._editor.show()
        self._editor.setFocus()

    def _commit_text(self) -> None:
        """Put what was typed onto the picture, if anything was."""
        where, self._typing_at = self._typing_at, None
        typed = self._editor.text().strip()
        self._editor.hide()
        self._editor.clear()
        if where is None or not typed:
            return
        self.strokeStarted.emit()
        self._paint_text(where, typed)
        self.update()

    def _cancel_text(self) -> None:
        self._typing_at = None
        self._editor.hide()
        self._editor.clear()

    def _paint_text(self, where: QtCore.QPoint, typed: str) -> None:
        painter = QtGui.QPainter(self._picture)
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
        font = self._picture_font()
        painter.setFont(font)
        # The click marks the top-left of the text, which is what it looks like
        # it should; drawText takes a baseline, hence the ascent.
        baseline = QtCore.QPoint(
            where.x(), where.y() + QtGui.QFontMetrics(font).ascent()
        )
        painter.setPen(QtGui.QColor("#101010"))
        for dx in range(-TEXT_OUTLINE, TEXT_OUTLINE + 1):
            for dy in range(-TEXT_OUTLINE, TEXT_OUTLINE + 1):
                if dx or dy:
                    painter.drawText(baseline + QtCore.QPoint(dx, dy), typed)
        painter.setPen(self._colour)
        painter.drawText(baseline, typed)
        painter.end()

    def eventFilter(self, watched, event) -> bool:
        """Escape throws the text away; losing focus keeps it."""
        if watched is self._editor:
            if (event.type() == QtCore.QEvent.KeyPress
                    and event.key() == QtCore.Qt.Key_Escape):
                self._cancel_text()
                return True
            if event.type() == QtCore.QEvent.FocusOut and self._typing_at is not None:
                self._commit_text()
        return super().eventFilter(watched, event)

    def _draw_to(self, pos: QtCore.QPoint) -> None:
        here = self._to_picture(pos)
        painter = QtGui.QPainter(self._picture)
        pen = QtGui.QPen(self._colour, PEN_WIDTH)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        painter.setPen(pen)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.drawLine(self._last, here)
        painter.end()
        self._last = here
        self.update()


class SnapshotDialog(QtWidgets.QDialog):
    """Preview a capture, crop it, mark it up, copy or save it."""

    def __init__(self, pixmap: QtGui.QPixmap, title: str = "",
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ảnh vừa chụp")
        self.setModal(False)
        self.setStyleSheet("QDialog { background: %s; }" % theme.WINDOW)

        self._original = QtGui.QPixmap(pixmap)
        self._undo: List[QtGui.QPixmap] = []
        self._saved_to: Optional[Path] = None

        column = vbox(0, margins=(22, 20, 22, 18))
        column.addWidget(section_label("Ảnh vừa chụp"))
        column.addWidget(body_text(
            "Đã copy vào clipboard, dán được ngay. Kéo khung để giữ lại phần "
            "cần, đổi sang Vẽ để khoanh hoặc Chữ rồi bấm vào ảnh để ghi chú, "
            "sau đó copy lại hoặc lưu ra file. Đóng thì không lưu gì.",
            12.5, theme.TEXT_LABEL,
        ))
        column.addSpacing(12)

        self._canvas = Canvas(QtGui.QPixmap(pixmap))
        self._canvas.strokeStarted.connect(self._remember)
        self._canvas.cropChanged.connect(self._show_size)
        holder = hbox(0)
        holder.addStretch()
        holder.addWidget(self._canvas)
        holder.addStretch()
        column.addLayout(holder)

        column.addSpacing(14)
        column.addWidget(Divider())
        column.addSpacing(12)
        column.addLayout(self._build_tools())
        column.addSpacing(14)
        column.addLayout(self._build_buttons())
        self.setLayout(column)
        self._show_size()

    # ── the controls ────────────────────────────────────────────────────────

    def _build_tools(self) -> QtWidgets.QHBoxLayout:
        row = hbox(10)
        row.addWidget(label("CÔNG CỤ", theme.mono(10, tracking=0.08),
                            theme.TEXT_FAINT))
        row.addWidget(chip_row(list(TOOLS), self._on_tool))
        row.addSpacing(12)
        row.addWidget(label("BÚT", theme.mono(10, tracking=0.08), theme.TEXT_FAINT))
        row.addWidget(chip_row([name for name, _ in PEN_COLOURS], self._on_pen))
        row.addStretch()
        self._size_label = label("", theme.tabular(11), theme.TEXT_FAINT)
        row.addWidget(self._size_label)
        return row

    def _build_buttons(self) -> QtWidgets.QHBoxLayout:
        row = hbox(10)
        full = controls.OutlineButton("Cắt lại", controls.NEUTRAL)
        full.setToolTip("Bỏ cắt, lấy lại cả ảnh")
        full.clicked.connect(self._canvas.reset_crop)
        undo = controls.OutlineButton("Hoàn tác", controls.NEUTRAL)
        undo.clicked.connect(self._on_undo)
        clear = controls.OutlineButton("Xoá vẽ", controls.NEUTRAL)
        clear.clicked.connect(self._on_clear)
        row.addWidget(full)
        row.addWidget(undo)
        row.addWidget(clear)
        row.addStretch()
        copy = controls.OutlineButton("Sao chép", controls.ACCENT)
        copy.clicked.connect(self._on_copy)
        save = controls.OutlineButton("Lưu…", controls.ACCENT)
        save.clicked.connect(self._on_save)
        close = controls.OutlineButton("Đóng", controls.NEUTRAL)
        close.clicked.connect(self.close)
        row.addWidget(copy)
        row.addWidget(save)
        row.addWidget(close)
        return row

    # ── state ───────────────────────────────────────────────────────────────

    def _on_tool(self, name: str) -> None:
        self._canvas.set_tool(name)
        self._canvas.update()

    def _on_pen(self, name: str) -> None:
        for text, colour in PEN_COLOURS:
            if text == name:
                self._canvas.set_colour(colour)
                # Choosing a colour is asking to mark the picture. Making the
                # user press two chips to do one thing is the sort of small
                # friction nobody reports and everybody feels. The text tool is
                # left alone: a colour picked mid-caption is for the caption.
                if self._canvas.tool() != TEXT:
                    self._canvas.set_tool(DRAW)
                self._canvas.update()
                return

    def _show_size(self) -> None:
        crop = self._canvas.crop()
        text = "%d × %d" % (crop.width(), crop.height())
        if self._canvas.is_cropped():
            text += "  (cắt từ %d × %d)" % (
                self._original.width(), self._original.height()
            )
        self._size_label.setText(text)

    def _remember(self) -> None:
        self._undo.append(QtGui.QPixmap(self._canvas.picture()))
        del self._undo[:-UNDO_LIMIT]

    def _on_undo(self) -> None:
        if not self._undo:
            return
        self._canvas.set_picture(self._undo.pop())

    def _on_clear(self) -> None:
        """Back to the capture, with the marks gone but the crop kept.

        Pushed onto the undo stack rather than replacing it: pressing Xoá vẽ by
        accident after a careful annotation should not be the end of it. The crop
        is left alone because it is not a mark — Cắt lại is what undoes that.
        """
        self._remember()
        self._canvas.set_picture(QtGui.QPixmap(self._original))

    # ── what comes out ──────────────────────────────────────────────────────

    def output(self) -> QtGui.QPixmap:
        """The picture as it would be copied or saved."""
        return self._canvas.cropped()

    def _on_copy(self) -> None:
        copy_to_clipboard(self.output())
        logger.info("Snapshot copied to the clipboard")

    def saved_to(self) -> Optional[Path]:
        """The file Lưu wrote, or None. For tests and for the caller's log."""
        return self._saved_to

    def _on_save(self) -> None:
        suggested = str(snapshot_dir() / default_name())
        chosen, _filter = QtWidgets.QFileDialog.getSaveFileName(
            self, "Lưu ảnh", suggested, "PNG (*.png);;JPEG (*.jpg)"
        )
        if not chosen:
            return
        target = Path(chosen)
        if self.output().save(str(target)):
            self._saved_to = target
            logger.info("Snapshot saved to %s", target)
            return
        logger.warning("Could not save the snapshot to %s", target)
        QtWidgets.QMessageBox.warning(
            self, "Không lưu được", "Không ghi được file:\n%s" % target
        )


def copy_to_clipboard(pixmap: QtGui.QPixmap) -> None:
    """Put a picture on the clipboard."""
    QtWidgets.QApplication.clipboard().setPixmap(pixmap)
