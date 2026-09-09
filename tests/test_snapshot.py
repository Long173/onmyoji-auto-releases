"""Quick capture: clipboard straight away, a preview to mark up, nothing saved
unless asked.

The rules worth pinning are the ones about not losing and not leaving things
behind, because those are the ones a user cannot check by looking:

* **Closing writes no file.** A capture taken by mistake leaves nothing to
  clean up.
* **The clipboard is written once, at capture.** Drawing does not silently
  change what is already pasteable; pressing Sao chép does.
* **Drawing never touches the original.** Xoá vẽ has to bring back the capture
  exactly, and it has to be undoable itself.
* **A mark made on the shrunken view lands where it looked like it would.** The
  picture is displayed scaled and drawn on at full size, which is the whole
  reason the coordinate maths exists.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")
from PyQt5 import QtCore, QtGui  # noqa: E402

from ui import snapshot_dialog  # noqa: E402
from ui.snapshot_dialog import CROP, DRAW, TEXT, SnapshotDialog  # noqa: E402

CAPTURE = QtCore.QSize(1122, 633)


def a_capture(colour="#203040", size=CAPTURE) -> QtGui.QPixmap:
    pixmap = QtGui.QPixmap(size)
    pixmap.fill(QtGui.QColor(colour))
    return pixmap


@pytest.fixture
def dialog(qt_app):
    made = []

    def build(pixmap=None):
        d = SnapshotDialog(pixmap or a_capture())
        made.append(d)
        return d

    yield build
    for d in made:
        d.deleteLater()


def stroke(dialog, start=(20, 20), end=(200, 120)):
    """Draw a line on the canvas, the way a mouse would.

    Switches to the pen first: the dialog opens on the crop tool, because
    cropping is what most captures need and a stray drag should move the frame
    rather than leave a mark.
    """
    canvas = dialog._canvas
    canvas.set_tool(DRAW)
    press = QtGui.QMouseEvent(
        QtCore.QEvent.MouseButtonPress, QtCore.QPointF(*start),
        QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier,
    )
    move = QtGui.QMouseEvent(
        QtCore.QEvent.MouseMove, QtCore.QPointF(*end),
        QtCore.Qt.NoButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier,
    )
    release = QtGui.QMouseEvent(
        QtCore.QEvent.MouseButtonRelease, QtCore.QPointF(*end),
        QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier,
    )
    canvas.mousePressEvent(press)
    canvas.mouseMoveEvent(move)
    canvas.mouseReleaseEvent(release)


def looks_changed(before: QtGui.QPixmap, after: QtGui.QPixmap) -> bool:
    return before.toImage() != after.toImage()


# ── the file, or the absence of one ─────────────────────────────────────────


def test_closing_writes_no_file(dialog):
    """Nothing on disk unless Lưu was pressed."""
    d = dialog()

    d.close()

    assert d.saved_to() is None


def test_saving_writes_the_file_it_says_it_did(dialog, tmp_path, monkeypatch):
    d = dialog()
    target = tmp_path / "shot.png"
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(target), "PNG (*.png)")),
    )

    d._on_save()

    assert d.saved_to() == target
    assert target.is_file() and target.stat().st_size > 0


def test_cancelling_the_save_dialog_writes_nothing(dialog, monkeypatch):
    d = dialog()
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: ("", "")),
    )

    d._on_save()

    assert d.saved_to() is None


def test_the_suggested_name_sorts_by_time(qt_app):
    early = snapshot_dialog.default_name(datetime(2026, 8, 26, 9, 5, 1))
    later = snapshot_dialog.default_name(datetime(2026, 8, 26, 21, 5, 1))

    assert early < later
    assert early.endswith(".png")


# ── the clipboard ───────────────────────────────────────────────────────────


def test_copy_puts_the_edited_picture_on_the_clipboard(dialog, qt_app):
    d = dialog()
    stroke(d)

    d._on_copy()

    pasted = QtWidgets.QApplication.clipboard().pixmap()
    assert not pasted.isNull()
    assert pasted.size() == d.output().size()


def test_drawing_alone_does_not_touch_the_clipboard(dialog, qt_app):
    """What is already pasteable must not change under the user's feet."""
    QtWidgets.QApplication.clipboard().setPixmap(a_capture("#ffffff"))
    before = QtWidgets.QApplication.clipboard().pixmap().toImage()
    d = dialog()

    stroke(d)

    assert QtWidgets.QApplication.clipboard().pixmap().toImage() == before


# ── drawing ─────────────────────────────────────────────────────────────────


def test_a_stroke_changes_the_picture(dialog):
    d = dialog()
    before = QtGui.QPixmap(d._canvas.picture())

    stroke(d)

    assert looks_changed(before, d._canvas.picture())


def test_the_original_is_never_drawn_on(dialog):
    """Xoá vẽ has to have something clean to go back to."""
    d = dialog()
    original = QtGui.QPixmap(d._original)

    stroke(d)

    assert not looks_changed(original, d._original)


def test_undo_puts_back_what_was_there(dialog):
    d = dialog()
    before = QtGui.QPixmap(d._canvas.picture())
    stroke(d)
    assert looks_changed(before, d._canvas.picture())

    d._on_undo()

    assert not looks_changed(before, d._canvas.picture())


def test_undo_with_nothing_drawn_does_nothing(dialog):
    d = dialog()
    before = QtGui.QPixmap(d._canvas.picture())

    d._on_undo()

    assert not looks_changed(before, d._canvas.picture())


def test_clearing_brings_back_the_capture(dialog):
    d = dialog()
    stroke(d)

    d._on_clear()

    assert not looks_changed(d._original, d._canvas.picture())


def test_clearing_is_itself_undoable(dialog):
    """Pressing Xoá vẽ by accident must not end a careful annotation."""
    d = dialog()
    stroke(d)
    annotated = QtGui.QPixmap(d._canvas.picture())
    d._on_clear()

    d._on_undo()

    assert not looks_changed(annotated, d._canvas.picture())


def test_the_undo_stack_is_bounded(dialog):
    """Each entry is a full copy of the picture — megabytes each."""
    d = dialog()
    for index in range(snapshot_dialog.UNDO_LIMIT + 8):
        stroke(d, (10 + index, 10), (60 + index, 60))

    assert len(d._undo) <= snapshot_dialog.UNDO_LIMIT


# ── drawing on a shrunken view ──────────────────────────────────────────────


def test_the_picture_is_shown_smaller_than_it_is(dialog):
    """Otherwise the coordinate maths below would never be exercised."""
    d = dialog()

    assert d._canvas.size().width() < CAPTURE.width()


def test_a_mark_lands_where_it_looked_like_it_would(dialog):
    """Drawn at full size, displayed scaled: the two have to agree.

    A click in the middle of the view has to reach the middle of the picture,
    not the middle of the *view's* coordinates applied to a larger image — which
    would put every mark up and to the left of where it was made.
    """
    d = dialog()
    canvas = d._canvas
    view = canvas.size()

    middle = canvas._to_picture(QtCore.QPoint(view.width() // 2, view.height() // 2))

    assert abs(middle.x() - CAPTURE.width() // 2) <= 2, middle.x()
    assert abs(middle.y() - CAPTURE.height() // 2) <= 2, middle.y()


def test_the_corner_maps_to_the_corner(dialog):
    d = dialog()
    view = d._canvas.size()

    corner = d._canvas._to_picture(QtCore.QPoint(view.width(), view.height()))

    assert abs(corner.x() - CAPTURE.width()) <= 2
    assert abs(corner.y() - CAPTURE.height()) <= 2


# ── cropping by dragging the frame ──────────────────────────────────────────


def corner(dialog, name="se"):
    """Where a handle sits, in the view's coordinates."""
    canvas = dialog._canvas
    frame = canvas._to_view(canvas.crop())
    return canvas._handle_points(frame)[name]


def drag(dialog, frm, to):
    """Press, move, release — the way a mouse crops."""
    canvas = dialog._canvas
    canvas.mousePressEvent(QtGui.QMouseEvent(
        QtCore.QEvent.MouseButtonPress, QtCore.QPointF(frm),
        QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier))
    canvas.mouseMoveEvent(QtGui.QMouseEvent(
        QtCore.QEvent.MouseMove, QtCore.QPointF(to),
        QtCore.Qt.NoButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier))
    canvas.mouseReleaseEvent(QtGui.QMouseEvent(
        QtCore.QEvent.MouseButtonRelease, QtCore.QPointF(to),
        QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier))


def test_the_whole_picture_comes_out_until_it_is_cropped(dialog):
    d = dialog()

    assert not d._canvas.is_cropped()
    assert d.output().size() == CAPTURE


def test_dragging_a_corner_crops(dialog):
    d = dialog()
    at = corner(d, "se")

    drag(d, at, QtCore.QPoint(at.x() - 200, at.y() - 120))

    assert d._canvas.is_cropped()
    assert d.output().width() < CAPTURE.width()
    assert d.output().height() < CAPTURE.height()


def test_the_crop_is_what_comes_out(dialog):
    d = dialog()
    at = corner(d, "se")
    drag(d, at, QtCore.QPoint(at.x() - 200, at.y() - 120))

    assert d.output().size() == d._canvas.crop().size()


def test_cropping_throws_no_pixels_away(dialog):
    """The frame is a rectangle beside the picture, not a knife.

    Dragging it back out has to bring the rest of the screen with it, or a crop
    made while deciding would quietly become permanent.
    """
    d = dialog()
    at = corner(d, "se")
    drag(d, at, QtCore.QPoint(at.x() - 300, at.y() - 200))

    d._canvas.reset_crop()

    assert not d._canvas.is_cropped()
    assert d.output().size() == CAPTURE


def test_dragging_an_edge_moves_only_that_edge(dialog):
    d = dialog()
    at = corner(d, "w")

    drag(d, at, QtCore.QPoint(at.x() + 120, at.y()))

    crop = d._canvas.crop()
    assert crop.left() > 0, "the left edge did not move"
    assert crop.top() == 0 and crop.bottom() == CAPTURE.height() - 1


def test_the_frame_can_be_moved_without_resizing(dialog):
    """Grabbing the middle slides the frame; its size has to survive."""
    d = dialog()
    at = corner(d, "se")
    drag(d, at, QtCore.QPoint(at.x() - 240, at.y() - 140))
    size = d._canvas.crop().size()
    canvas = d._canvas
    inside = canvas._to_view(canvas.crop()).center()

    drag(d, inside, QtCore.QPoint(inside.x() + 60, inside.y() + 40))

    assert d._canvas.crop().size() == size
    assert d._canvas.crop().topLeft() != QtCore.QPoint(0, 0)


def test_the_frame_cannot_be_dragged_out_of_the_picture(dialog):
    d = dialog()
    at = corner(d, "se")
    drag(d, at, QtCore.QPoint(at.x() - 200, at.y() - 120))
    canvas = d._canvas
    inside = canvas._to_view(canvas.crop()).center()

    drag(d, inside, QtCore.QPoint(inside.x() + 5000, inside.y() + 5000))

    crop = d._canvas.crop()
    assert crop.left() >= 0 and crop.top() >= 0
    assert crop.right() <= CAPTURE.width() and crop.bottom() <= CAPTURE.height()


def test_the_frame_cannot_be_collapsed_to_nothing(dialog):
    """A careless drag past the opposite edge must not leave an empty crop."""
    d = dialog()
    at = corner(d, "se")

    drag(d, at, QtCore.QPoint(0, 0))

    crop = d._canvas.crop()
    assert crop.width() >= snapshot_dialog.MIN_CROP
    assert crop.height() >= snapshot_dialog.MIN_CROP
    assert not d.output().isNull()


def test_a_corner_dragged_past_the_far_side_does_not_flip_the_frame(dialog):
    """Held edge by edge for this reason; clamping the whole rectangle flips it."""
    d = dialog()
    at = corner(d, "nw")

    drag(d, at, QtCore.QPoint(at.x() + 5000, at.y() + 5000))

    crop = d._canvas.crop()
    assert crop.width() > 0 and crop.height() > 0
    assert crop.left() < crop.right() and crop.top() < crop.bottom()


def test_the_middle_of_the_frame_grabs_move_and_a_corner_grabs_that_corner(dialog):
    d = dialog()
    canvas = d._canvas
    frame = canvas._to_view(canvas.crop())

    assert canvas.grab_at(frame.center()) == "move"
    assert canvas.grab_at(QtCore.QPoint(frame.left(), frame.top())) == "nw"
    assert canvas.grab_at(QtCore.QPoint(frame.right(), frame.bottom())) == "se"


def test_cropping_and_drawing_compose(dialog):
    d = dialog()
    stroke(d, (60, 50), (200, 160))
    at = corner(d, "se")
    d._canvas.set_tool(CROP)

    drag(d, at, QtCore.QPoint(at.x() - 150, at.y() - 90))

    assert d.output().size() == d._canvas.crop().size()
    assert not d.output().isNull()


def test_clearing_the_marks_keeps_the_crop(dialog):
    """Xoá vẽ removes marks. Cắt lại is what undoes a crop."""
    d = dialog()
    at = corner(d, "se")
    drag(d, at, QtCore.QPoint(at.x() - 200, at.y() - 120))
    cropped = d._canvas.crop()
    stroke(d)

    d._on_clear()

    assert d._canvas.crop() == cropped


def test_picking_a_pen_colour_switches_to_the_pen(dialog):
    """Choosing a colour is asking to draw; two chips for one intent is friction."""
    d = dialog()
    assert d._canvas._tool == CROP

    d._on_pen("Vàng")

    assert d._canvas._tool == DRAW


def test_the_readout_says_what_will_come_out(dialog):
    d = dialog()
    at = corner(d, "se")

    drag(d, at, QtCore.QPoint(at.x() - 200, at.y() - 120))

    crop = d._canvas.crop()
    assert "%d × %d" % (crop.width(), crop.height()) in d._size_label.text()


# ── typing on the picture ───────────────────────────────────────────────────


def type_at(dialog, text, where=(120, 90)):
    """Click with the text tool, type, and finish — the way a person would."""
    canvas = dialog._canvas
    canvas.set_tool(TEXT)
    canvas.mousePressEvent(QtGui.QMouseEvent(
        QtCore.QEvent.MouseButtonPress, QtCore.QPointF(*where),
        QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier))
    canvas._editor.setText(text)
    canvas._commit_text()


def painted(canvas, monkeypatch) -> list:
    """Record what would be drawn, instead of looking for it in the pixels.

    This process cannot draw text at all: ``QFontInfo(...).family()`` comes back
    empty for every family including Qt's own default, so ``drawText`` lays the
    glyphs out at the right size and renders nothing. Checked against a plain
    Python process, where the same code changes 3915 pixels — so asserting on
    pixels here would be asserting something about the machine's font database
    rather than about this dialog.

    What the dialog is answerable for is *what* it paints and *where*. That is
    what this records.
    """
    calls: list = []
    real = canvas._paint_text

    def spy(where, typed):
        calls.append((where, typed))
        real(where, typed)

    monkeypatch.setattr(canvas, "_paint_text", spy)
    return calls


def test_typing_puts_the_words_on_the_picture(dialog, monkeypatch):
    d = dialog()
    marks = painted(d._canvas, monkeypatch)

    type_at(d, "ổ quái ở đây")

    assert len(marks) == 1
    where, typed = marks[0]
    assert typed == "ổ quái ở đây"
    # In the picture's own pixels, not the shrunken view's: a label typed on the
    # scaled preview has to land where it looked like it would.
    assert where.x() > 120 and where.y() > 90


def test_a_click_opens_an_editor_where_it_was_clicked(dialog):
    """Typed into a real editor, so backspace and the caret come for free."""
    d = dialog()
    canvas = d._canvas
    canvas.set_tool(TEXT)

    canvas.mousePressEvent(QtGui.QMouseEvent(
        QtCore.QEvent.MouseButtonPress, QtCore.QPointF(240, 180),
        QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier))

    assert canvas._typing_at is not None
    # The point recorded is in the picture's own pixels, not the shrunken view's.
    assert canvas._typing_at.x() > 240


def test_typing_is_undoable(dialog):
    """A label goes on the undo stack the same way a stroke does."""
    d = dialog()

    type_at(d, "sai rồi")

    assert len(d._undo) == 1
    d._on_undo()
    assert d._undo == []


def test_typing_nothing_marks_nothing(dialog, monkeypatch):
    """An empty box closed by accident should leave no trace and no undo step."""
    d = dialog()
    marks = painted(d._canvas, monkeypatch)

    type_at(d, "   ")

    assert marks == []
    assert d._undo == []


def test_escape_throws_the_words_away(dialog, monkeypatch):
    d = dialog()
    canvas = d._canvas
    marks = painted(canvas, monkeypatch)
    canvas.set_tool(TEXT)
    canvas.mousePressEvent(QtGui.QMouseEvent(
        QtCore.QEvent.MouseButtonPress, QtCore.QPointF(120, 90),
        QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier))
    canvas._editor.setText("bỏ đi")

    canvas.eventFilter(canvas._editor, QtGui.QKeyEvent(
        QtCore.QEvent.KeyPress, QtCore.Qt.Key_Escape, QtCore.Qt.NoModifier))

    assert marks == []
    assert canvas._typing_at is None


def test_switching_tools_keeps_what_was_typed(dialog, monkeypatch):
    """Changing tool is not the same gesture as pressing Escape."""
    d = dialog()
    canvas = d._canvas
    marks = painted(canvas, monkeypatch)
    canvas.set_tool(TEXT)
    canvas.mousePressEvent(QtGui.QMouseEvent(
        QtCore.QEvent.MouseButtonPress, QtCore.QPointF(120, 90),
        QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier))
    canvas._editor.setText("giữ lại")

    canvas.set_tool(CROP)

    assert [typed for _where, typed in marks] == ["giữ lại"]


def test_a_second_click_finishes_the_first_label(dialog, monkeypatch):
    """Two captions without a trip back to the chips in between."""
    d = dialog()
    marks = painted(d._canvas, monkeypatch)

    type_at(d, "một", (100, 80))
    type_at(d, "hai", (300, 240))

    assert [typed for _where, typed in marks] == ["một", "hai"]
    assert len(d._undo) == 2


def test_a_colour_picked_while_typing_stays_on_the_text_tool(dialog):
    """It is for the caption being written, not a request to switch to the pen."""
    d = dialog()
    d._canvas.set_tool(TEXT)

    d._on_pen("Vàng")

    assert d._canvas.tool() == TEXT


def test_the_font_is_picked_by_what_it_resolved_to(dialog):
    """A named font that cannot be resolved draws nothing at all — silently.

    It does not raise and it does not fall back: the metrics come out right and
    ``drawText`` renders empty. Worse, ``exactMatch()`` is no help — it wants
    the size and style to agree too, so it answers False for fonts that are
    perfectly available and using it meant the preferred families were never
    chosen. The family is checked by the name it resolved *to*.
    """
    d = dialog()

    font = d._canvas._picture_font()

    assert font.bold()
    assert font.pointSize() == d._canvas.text_size()


def test_the_text_scales_with_the_picture(dialog):
    """A label should look the same size on any capture's resolution."""
    big = dialog(a_capture(size=QtCore.QSize(2272, 1280)))
    small = dialog(a_capture(size=QtCore.QSize(568, 320)))

    assert big._canvas.text_size() > small._canvas.text_size()
    assert small._canvas.text_size() >= snapshot_dialog.TEXT_MIN_SIZE


def test_a_label_is_placed_inside_the_kept_area(dialog, monkeypatch):
    """Typed where it was clicked, so a crop drawn round it keeps it."""
    d = dialog()
    marks = painted(d._canvas, monkeypatch)
    type_at(d, "ở đây", (120, 90))
    where, _typed = marks[0]

    at = corner(d, "se")
    d._canvas.set_tool(CROP)
    drag(d, at, QtCore.QPoint(at.x() - 100, at.y() - 60))

    assert d._canvas.crop().contains(where)


# ── the button, and what the window does with it ────────────────────────────
#
# The capture lives on every window card, on the control panel and on each
# task's page — a screenshot is about one game window, so it belongs beside
# that window's own Start and Stop rather than on a page of its own.


def a_frame():
    """A colour frame shaped like a real capture."""
    import numpy as np

    return np.full((633, 1122, 3), 40, dtype=np.uint8)


def hush(window, monkeypatch) -> list:
    """Stop the notifier reaching for a modal dialog, and record what it says.

    Not optional. With no system tray — which the test runner has none of —
    ``Notifier.notify`` falls back to ``QMessageBox``, and a modal box opened
    inside a test took the whole interpreter down with an access violation
    rather than failing. This is the second time that has happened in this
    suite; see ``test_tray.FakeNotifier`` for the first.
    """
    said: list = []
    monkeypatch.setattr(window._notifier, "notify",
                        lambda title, body, *a, **k: said.append(body))
    return said


def only_dialog(window):
    assert len(window._snapshots) == 1, window._snapshots
    return window._snapshots[0]


def test_the_control_panel_row_asks_for_a_capture(dashboard, monkeypatch):
    hush(dashboard, monkeypatch)
    asked = []
    row = dashboard._home._rows[101]
    row.captureRequested.connect(asked.append)

    row._capture.click()

    assert asked == [101]


def test_a_task_page_card_asks_for_a_capture(dashboard, monkeypatch):
    hush(dashboard, monkeypatch)
    dashboard._show_page("realm_raid")
    dashboard._manager.select(101, "realm_raid")
    dashboard._rebuild()
    asked = []
    card = dashboard._views["realm_raid"]._cards[101]
    card.captureRequested.connect(asked.append)

    card._capture.click()

    assert asked == [101]


def test_the_capture_button_works_while_nothing_is_running(dashboard):
    """Never disabled: the moment something looks wrong is the moment for one."""
    row = dashboard._home._rows[101]

    assert row._capture.isEnabled()


def test_capturing_copies_and_opens_a_preview(dashboard, monkeypatch, qt_app):
    hush(dashboard, monkeypatch)
    session = dashboard._manager.get(101)
    monkeypatch.setattr(session, "preview_frame", a_frame)
    QtWidgets.QApplication.clipboard().clear()

    dashboard._on_capture(101)

    assert not QtWidgets.QApplication.clipboard().pixmap().isNull(), "clipboard empty"
    assert only_dialog(dashboard).isVisible()
    only_dialog(dashboard).close()


def test_the_preview_holds_the_captured_size(dashboard, monkeypatch):
    hush(dashboard, monkeypatch)
    session = dashboard._manager.get(101)
    monkeypatch.setattr(session, "preview_frame", a_frame)

    dashboard._on_capture(101)

    assert only_dialog(dashboard).output().size() == QtCore.QSize(1122, 633)
    only_dialog(dashboard).close()


def test_a_window_with_no_frame_opens_nothing(dashboard, monkeypatch):
    """A minimised game gives back nothing; an empty dialog would be worse."""
    session = dashboard._manager.get(101)
    monkeypatch.setattr(session, "preview_frame", lambda: None)
    said = hush(dashboard, monkeypatch)

    dashboard._on_capture(101)

    assert dashboard._snapshots == []
    assert said and "thu nhỏ" in said[0]


def test_the_preview_is_kept_alive_and_let_go_of(dashboard, monkeypatch):
    """Non-modal on purpose, so a local reference would be collected at once."""
    hush(dashboard, monkeypatch)
    session = dashboard._manager.get(101)
    monkeypatch.setattr(session, "preview_frame", a_frame)
    dashboard._on_capture(101)
    dialog = only_dialog(dashboard)

    dialog.close()

    assert dashboard._snapshots == [], "the dialog was never let go of"


def test_two_captures_can_be_open_at_once(dashboard, monkeypatch):
    """One per window, compared side by side — the reason they are not modal."""
    hush(dashboard, monkeypatch)
    for hwnd in (101, 102):
        monkeypatch.setattr(dashboard._manager.get(hwnd), "preview_frame", a_frame)
        dashboard._on_capture(hwnd)

    assert len(dashboard._snapshots) == 2
    for dialog in list(dashboard._snapshots):
        dialog.close()


def test_capturing_an_unknown_window_does_nothing(dashboard, monkeypatch):
    hush(dashboard, monkeypatch)
    dashboard._on_capture(999)

    assert dashboard._snapshots == []


# ── the system-wide screenshot key ──────────────────────────────────────────
#
# The registration itself is tested in test_hotkeys.py. What matters here is
# what happens when it fires: which of several game windows gets photographed,
# and that pressing it with nothing to photograph says so instead of doing
# nothing.


@pytest.fixture
def hotkey(dashboard, monkeypatch):
    """The window's hotkey, with the foreground under the test's control."""
    import ui.auto_window as auto_window

    state = {"front": 0, "captured": [], "said": hush(dashboard, monkeypatch)}
    monkeypatch.setattr(auto_window, "_foreground_window", lambda: state["front"])
    monkeypatch.setattr(dashboard, "_on_capture",
                        lambda hwnd: state["captured"].append(hwnd))
    dashboard._on_scan()
    QtWidgets.QApplication.processEvents()
    state["window"] = dashboard
    return state


def test_the_window_in_front_is_the_one_photographed(hotkey):
    """Pressing it while looking at a game is the whole point."""
    hotkey["front"] = 102

    hotkey["window"]._on_hotkey()

    assert hotkey["captured"] == [102]


def test_the_other_window_in_front_is_photographed_instead(hotkey):
    hotkey["front"] = 101

    hotkey["window"]._on_hotkey()

    assert hotkey["captured"] == [101]


def test_a_foreground_we_do_not_know_falls_back_to_the_last_one(hotkey):
    """Pressed from the preview window, or from a browser, it still means
    "the one I was just working with"."""
    window = hotkey["window"]
    window._last_captured = 102
    hotkey["front"] = 999999

    window._on_hotkey()

    assert hotkey["captured"] == [102]


def test_with_nothing_to_go_on_it_says_so_rather_than_guessing(hotkey):
    """A screenshot of the wrong window is worse than being asked to pick."""
    window = hotkey["window"]
    hotkey["front"] = 999999
    window._last_captured = 0
    window._on_hotkey()

    assert hotkey["captured"] == []
    assert hotkey["said"], "it did nothing at all"


def test_one_window_needs_no_tie_break(hotkey):
    window = hotkey["window"]
    window._manager.forget(102)
    hotkey["front"] = 999999
    window._last_captured = 0

    window._on_hotkey()

    assert hotkey["captured"] == [101]


def test_no_windows_at_all_warns(hotkey):
    window = hotkey["window"]
    window._manager.forget(101)
    window._manager.forget(102)
    window._on_hotkey()

    assert hotkey["captured"] == []
    assert hotkey["said"]


def test_capturing_remembers_which_window_it_was(dashboard, monkeypatch):
    """Which is what makes the fallback above work.

    Only on a capture that produced a picture. A window that could not be
    photographed — minimised, usually — must not become the one the hotkey
    falls back to, or the key would keep aiming at the one window that cannot
    answer.
    """
    from ui import auto_window as auto_window_module

    hush(dashboard, monkeypatch)
    monkeypatch.setattr(auto_window_module.preview, "to_pixmap",
                        lambda frame: a_capture())
    dashboard._on_scan()
    QtWidgets.QApplication.processEvents()

    dashboard._on_capture(101)

    assert dashboard._last_captured == 101
    for dialog in list(dashboard._snapshots):
        dialog.close()


def test_a_window_that_could_not_be_photographed_is_not_remembered(dashboard,
                                                                   monkeypatch):
    hush(dashboard, monkeypatch)
    dashboard._on_scan()
    QtWidgets.QApplication.processEvents()

    dashboard._on_capture(101)

    assert dashboard._last_captured == 0


# ── the setting ─────────────────────────────────────────────────────────────


def test_the_hotkey_is_registered_at_startup(dashboard):
    import hotkeys

    wanted = str(dashboard._manager.app_config.get("snapshot_hotkey") or "")
    if not wanted:
        pytest.skip("no default hotkey configured")

    assert dashboard._hotkey.bound is not None or dashboard._hotkey.error
    if dashboard._hotkey.bound is not None:
        assert dashboard._hotkey.bound == hotkeys.parse(wanted)


def test_changing_the_setting_rebinds(dashboard, monkeypatch):
    asked = []
    monkeypatch.setattr(dashboard._hotkey, "bind",
                        lambda text: asked.append(text) or True)

    dashboard._on_app_setting("snapshot_hotkey", "Ctrl+Alt+Shift+F17")

    assert asked == ["Ctrl+Alt+Shift+F17"]


def test_changing_something_else_does_not_rebind(dashboard, monkeypatch):
    asked = []
    monkeypatch.setattr(dashboard._hotkey, "bind",
                        lambda text: asked.append(text) or True)

    dashboard._on_app_setting("notify_on_finish", True)

    assert asked == []


def test_a_refused_combination_is_shown_when_the_user_just_chose_it(
        dashboard, monkeypatch):
    """Silently failing would send somebody hunting the capture code."""
    monkeypatch.setattr(dashboard._hotkey, "bind", lambda text: False)
    dashboard._hotkey.error = "đang được ứng dụng khác dùng"
    shown = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning",
                        staticmethod(lambda *args, **kwargs: shown.append(args[2])
                                     or QtWidgets.QMessageBox.Ok))

    dashboard._on_app_setting("snapshot_hotkey", "Ctrl+C")

    assert shown == ["đang được ứng dụng khác dùng"]


def test_a_refused_combination_at_startup_is_not_a_popup(dashboard, monkeypatch):
    """Nobody wants a warning about a key they set up weeks ago while the
    machine is still starting."""
    monkeypatch.setattr(dashboard._hotkey, "bind", lambda text: False)
    shown = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning",
                        staticmethod(lambda *args, **kwargs: shown.append(args)
                                     or QtWidgets.QMessageBox.Ok))

    dashboard._install_hotkey()

    assert shown == []


def test_closing_hands_the_combination_back(dashboard, monkeypatch):
    """A restart would otherwise be refused its own hotkey by the old copy."""
    released = []
    monkeypatch.setattr(dashboard._hotkey, "unbind",
                        lambda: released.append(True))

    dashboard._release_hotkey()

    assert released == [True]


# ── what counts as quitting ─────────────────────────────────────────────────
#
# Reported: taking a screenshot with the hotkey while the dashboard was hidden,
# then closing the preview, ended the whole app — tray icon and all.
#
# Qt quits when the last *window* closes, and a hidden dashboard is not a
# window. So the preview was the last one, and closing it was the last close.
# The application no longer quits on its own; the close handler says when a
# close was real. These tests pin both halves, because getting the second one
# wrong leaves a process nobody can see and nobody can stop.


@pytest.fixture
def quits(monkeypatch):
    """Records whether the application was asked to quit."""
    asked = []
    monkeypatch.setattr(QtWidgets.QApplication, "quit",
                        staticmethod(lambda: asked.append(True)))
    return asked


def test_the_application_does_not_quit_on_its_own(qt_app):
    """The one line that caused it. A tray app outlives its windows."""
    import app as app_module

    was = qt_app.quitOnLastWindowClosed()
    try:
        app_module.apply_window_policy(qt_app)
        assert qt_app.quitOnLastWindowClosed() is False
    finally:
        qt_app.setQuitOnLastWindowClosed(was)


def test_closing_a_preview_while_hidden_does_not_quit(dashboard, monkeypatch, quits):
    """The reported bug, in the shape it was reported."""
    from ui import auto_window as auto_window_module

    hush(dashboard, monkeypatch)
    monkeypatch.setattr(auto_window_module.preview, "to_pixmap",
                        lambda frame: a_capture())
    dashboard._on_scan()
    QtWidgets.QApplication.processEvents()
    dashboard.hide()

    dashboard._on_capture(101)
    QtWidgets.QApplication.processEvents()
    assert dashboard._snapshots, "no preview opened"
    for dialog in list(dashboard._snapshots):
        dialog.close()
    QtWidgets.QApplication.processEvents()

    assert quits == [], "closing the preview ended the app"


def test_hiding_to_the_tray_does_not_quit(dashboard, monkeypatch, quits):
    monkeypatch.setattr(dashboard, "_hides_to_tray", lambda: True)

    dashboard.close()
    QtWidgets.QApplication.processEvents()

    assert quits == [], "hiding is not quitting"


def test_a_real_close_does_quit(dashboard, monkeypatch, quits):
    """Otherwise the process lingers with no window and no tray icon."""
    monkeypatch.setattr(dashboard, "_hides_to_tray", lambda: False)

    dashboard.close()
    QtWidgets.QApplication.processEvents()

    assert quits == [True]


def test_quitting_from_the_tray_quits(dashboard, monkeypatch, quits):
    monkeypatch.setattr(dashboard, "_confirm_exit", lambda running: True)

    dashboard._quit_from_tray()
    QtWidgets.QApplication.processEvents()

    assert quits == [True]


def test_a_refused_confirmation_does_not_quit(dashboard, monkeypatch, quits):
    """Somebody who says "no, keep running" must keep running."""
    monkeypatch.setattr(dashboard, "_hides_to_tray", lambda: False)
    monkeypatch.setattr(type(dashboard._manager), "running_count",
                        property(lambda self: 1))
    monkeypatch.setattr(dashboard, "_confirm_exit", lambda running: False)

    dashboard.close()
    QtWidgets.QApplication.processEvents()

    assert quits == []


# ── looking again before giving up ──────────────────────────────────────────
#
# The session list is only as fresh as the last scan, and the hotkey used to
# take it at face value. Two ways that goes wrong, and the second is the one
# that got reported:
#
#   * a game opened since the scan is not in the list, so the key says there is
#     no window while the user is looking straight at one;
#   * a game *closed* since the scan is still in it, and a dead handle counts
#     towards "which of the several did you mean". One live game plus one stale
#     entry is an ambiguity with no way out — the user is told to press Scan by
#     a program perfectly able to press it itself.
#
# Live instance, 2026-09-02: windows 0x4054A and 0x407D2 scanned at startup,
# 0x407D2 shut some time after. GetWindowDC on it had been failing every pass
# for half an hour, and the hotkey answered "Chưa thấy cửa sổ game nào".


def rescans_as(monkeypatch, windows):
    """What the next window scan will find."""
    import auto.manager as manager_module
    from auto.window_scanner import GameWindow

    monkeypatch.setattr(
        manager_module.window_scanner, "scan",
        lambda patterns=None: [GameWindow(h, t, 1122, 633) for h, t in windows],
    )


def test_a_window_that_has_closed_stops_getting_in_the_way(hotkey, monkeypatch):
    """The reported case: one game open, and the key insisting there is none."""
    window = hotkey["window"]
    rescans_as(monkeypatch, [(101, "陰陽師Onmyoji")])   # 102 has been shut
    hotkey["front"] = 999999
    window._last_captured = 0

    window._on_hotkey()

    assert hotkey["captured"] == [101]
    assert hotkey["said"] == [], "complained about a window it could have found"


def test_a_game_opened_since_the_last_scan_is_found(hotkey, monkeypatch):
    """The other direction: nothing known, and a game on screen."""
    window = hotkey["window"]
    window._manager.forget(101)
    window._manager.forget(102)
    rescans_as(monkeypatch, [(103, "陰陽師Onmyoji")])
    hotkey["front"] = 999999
    window._last_captured = 0

    window._on_hotkey()

    assert hotkey["captured"] == [103]


def test_it_still_says_so_when_a_fresh_scan_finds_nothing(hotkey, monkeypatch):
    """Looking again is not the same as pretending."""
    window = hotkey["window"]
    rescans_as(monkeypatch, [])
    hotkey["front"] = 999999
    window._last_captured = 0

    window._on_hotkey()

    assert hotkey["captured"] == []
    assert len(hotkey["said"]) == 1
    assert "Quét" not in hotkey["said"][0], (
        "told the user to scan, having just scanned for them"
    )


def test_several_open_games_ask_which_rather_than_blaming_the_scan(hotkey,
                                                                  monkeypatch):
    """With two genuinely open, the key cannot know which is meant — but the
    remedy is to click one, not to press Scan."""
    window = hotkey["window"]
    rescans_as(monkeypatch, [(101, "陰陽師Onmyoji"), (102, "陰陽師Onmyoji — acc 2")])
    hotkey["front"] = 999999
    window._last_captured = 0

    window._on_hotkey()

    assert hotkey["captured"] == []
    said = hotkey["said"][0]
    assert "2" in said and "Quét" not in said, said


# ── closed windows leave on their own ───────────────────────────────────────


def dies(monkeypatch, hwnds):
    """Which window handles Windows has destroyed."""
    import auto.manager as manager_module

    monkeypatch.setattr(manager_module.window_scanner, "is_gone",
                        lambda hwnd: hwnd in hwnds)


def test_the_tick_drops_a_window_that_has_been_closed(dashboard, monkeypatch):
    hush(dashboard, monkeypatch)
    dies(monkeypatch, {102})

    dashboard._refresh()

    assert [s.hwnd for s in dashboard._manager.sessions] == [101]


def test_a_card_working_when_its_window_closed_is_not_taken_away_in_silence(
        dashboard, monkeypatch):
    """The reason a running card used to be kept: a run that ends because the
    game shut should say so, not just vanish from the list."""
    said = hush(dashboard, monkeypatch)
    dashboard._manager.start(101)
    dies(monkeypatch, {101})

    dashboard._refresh()

    assert [s.hwnd for s in dashboard._manager.sessions] == [102]
    assert len(said) == 1, said


def test_closing_an_idle_window_is_not_announced(dashboard, monkeypatch):
    """Shutting a game nobody was using is not news — the user just did it."""
    said = hush(dashboard, monkeypatch)
    dies(monkeypatch, {102})

    dashboard._refresh()

    assert said == []
