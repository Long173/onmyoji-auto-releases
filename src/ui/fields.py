"""Turn declared :class:`~tasks.Field` tuples into controls.

Both settings surfaces read from here — a task's config panel and the app-wide
settings dialog — so declaring a field is the whole of adding a setting,
whichever layer it belongs to. One implementation also means the two cannot
drift into looking like different products.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

import geometry
import tasks
import theme
from ui import controls
from ui.primitives import (Divider, FlowLayout, body_text, hbox, label,
                          section_label, vbox)


class FieldForm(QtWidgets.QWidget):
    """A column of controls built from ``fields``, seeded from ``values``."""

    changed = QtCore.pyqtSignal(str, object)   # key, new value

    def __init__(
        self,
        fields: Tuple[tasks.Field, ...],
        values: Mapping[str, Any],
        notes: Optional[Mapping[str, str]] = None,
        spacing: int = 18,
        frame_source: Optional[Callable[[], Optional[Any]]] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._notes = dict(notes or {})
        # Only a POINT field uses this: it needs a picture of the game window to
        # pick a position off. Left None the picker still opens and says it
        # could not capture, which is a better answer than a disabled button
        # with no explanation.
        self._frame_source = frame_source
        self._values = dict(values)
        # key -> the widget to grey out, for fields that depend on another.
        self._controls: Dict[str, QtWidgets.QWidget] = {}
        self._fields = tuple(fields)

        column = vbox(0)
        for field in self._fields:
            widget = self._build(field, values)
            if widget is None:
                continue
            column.addWidget(widget)
            column.addSpacing(spacing)
        self.setLayout(column)

        self.changed.connect(self._remember)
        self._apply_dependencies()

    def _remember(self, key: str, value: Any) -> None:
        self._values[key] = value
        self._apply_dependencies()

    def _apply_dependencies(self) -> None:
        """Grey out any control whose ``disabled_when`` condition is met."""
        for field in self._fields:
            if not field.disabled_when:
                continue
            widget = self._controls.get(field.key)
            if widget is None:
                continue
            other, expected = field.disabled_when
            widget.setEnabled(self._values.get(other) != expected)

    # ── construction ────────────────────────────────────────────────────────

    def _build(self, field: tasks.Field, values: Mapping[str, Any]):
        if field.kind == tasks.NOTE:
            return self._note_block(field.label)
        if field.kind == tasks.TOGGLE:
            return self._toggle(field, values)
        if field.kind == tasks.SEGMENTED:
            return self._segmented(field, values)
        if field.kind == tasks.NUMBER:
            return self._number(field, values)
        if field.kind == tasks.HOTKEY:
            return self._hotkey(field, values)
        if field.kind == tasks.POINT:
            return self._point(field, values)
        return None

    def _hotkey(self, field: tasks.Field, values: Mapping[str, Any]) -> QtWidgets.QWidget:
        """A button that listens for the next combination pressed.

        Typing the combination as text was the other option and is worse: it
        makes somebody spell "PrintScreen" correctly to use a key they are
        looking at. Pressing it is the thing they already know how to do.
        """
        import hotkeys

        holder = QtWidgets.QWidget()
        block = vbox(6)
        block.addWidget(section_label(field.label))
        hint = self._explanation(field.key)
        if hint is not None:
            block.addWidget(hint)

        row = hbox(8)
        catcher = HotkeyButton(str(values.get(field.key) or ""))
        catcher.captured.connect(
            lambda text, key=field.key: self.changed.emit(key, text))
        row.addWidget(catcher, 1)

        clear = controls.OutlineButton("Tắt", padding="8px 14px")
        clear.setToolTip("Bỏ phím tắt")
        clear.clicked.connect(catcher.clear)
        row.addWidget(clear)
        block.addLayout(row)

        self._controls[field.key] = catcher
        holder.setLayout(block)
        return holder

    def _point(self, field: tasks.Field, values: Mapping[str, Any]) -> QtWidgets.QWidget:
        """A coordinate, shown as a number and changed by clicking a screenshot.

        The number is displayed rather than typed. Two spin boxes would let
        someone enter (1030, 549) without ever knowing whether that is the
        button they meant, and a coordinate nobody can check is a coordinate
        that silently clicks the wrong thing.
        """
        default = tasks.as_point(field.default, geometry.EVENT_CLICK_POINT)
        current = tasks.as_point(values.get(field.key, default), default)

        holder = QtWidgets.QWidget()
        block = vbox(8)
        block.addWidget(label(field.label, theme.body(13), theme.TEXT_MUTED))

        row = hbox(9)
        readout = label("", theme.tabular(13), theme.TEXT)
        readout.setAlignment(QtCore.Qt.AlignCenter)
        readout.setFixedHeight(34)
        readout.setMinimumWidth(96)
        readout.setStyleSheet(
            "background: %s; border: 1px solid %s; border-radius: %dpx;"
            " color: %s; padding: 0 10px;"
            % (theme.INSET, theme.CONTROL, theme.RADIUS, theme.TEXT)
        )
        row.addWidget(readout)

        button = controls.OutlineButton("Chọn trên màn hình", padding="9px 14px")
        row.addWidget(button, 1)
        block.addLayout(row)

        state = {"point": current}

        def show(point):
            readout.setText("%d , %d" % point)

        def pick():
            from ui.point_picker import choose_point

            chosen = choose_point(
                state["point"], self._capture, default, self,
                danger=field.danger_zone,
                danger_note=field.danger_note,
                title=field.label or "Chọn chỗ tự nhấn",
            )
            if chosen is None or chosen == state["point"]:
                return
            state["point"] = chosen
            show(chosen)
            self.changed.emit(field.key, chosen)

        show(current)
        button.clicked.connect(pick)
        self._controls[field.key] = button

        hint = self._explanation(field.key)
        if hint is not None:
            block.addWidget(hint)
        holder.setLayout(block)
        return holder

    def _capture(self) -> Optional[Any]:
        if self._frame_source is None:
            return None
        return self._frame_source()

    def _number(self, field: tasks.Field, values: Mapping[str, Any]) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        block = vbox(8)
        block.addWidget(label(field.label, theme.body(13), theme.TEXT_MUTED))

        box = QtWidgets.QSpinBox()
        box.setRange(field.minimum, field.maximum)
        if field.suffix:
            box.setSuffix(field.suffix)
        if field.special:
            # Qt shows this instead of the minimum value, so "0" never appears
            # on screen meaning something other than zero.
            box.setSpecialValueText(field.special)
        try:
            box.setValue(int(values.get(field.key, field.default) or 0))
        except (TypeError, ValueError):
            box.setValue(field.minimum)
        box.setFont(theme.body(13))
        box.setFixedHeight(34)
        box.setButtonSymbols(QtWidgets.QAbstractSpinBox.UpDownArrows)
        box.setStyleSheet(
            "QSpinBox { background: %s; border: 1px solid %s; border-radius: %dpx;"
            " padding: 0 8px; color: %s; }"
            "QSpinBox:focus { border-color: %s; }"
            % (theme.INSET, theme.CONTROL, theme.RADIUS, theme.TEXT, theme.ACCENT)
        )
        box.valueChanged.connect(
            lambda value, key=field.key: self.changed.emit(key, value)
        )
        block.addWidget(box)
        self._controls[field.key] = box

        hint = self._explanation(field.key)
        if hint is not None:
            block.addWidget(hint)
        holder.setLayout(block)
        return holder

    @staticmethod
    def _note_block(text: str) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        block = vbox(14)
        block.addWidget(Divider())
        block.addWidget(body_text(text, 12.5, theme.TEXT_LABEL, justify=True))
        holder.setLayout(block)
        return holder

    def _explanation(self, key: str) -> Optional[QtWidgets.QWidget]:
        text = self._notes.get(key)
        if not text:
            return None
        hint = body_text(text, 12.5, theme.TEXT_LABEL)
        # Indented to sit under the control it describes rather than beside it.
        hint.setContentsMargins(24, 4, 0, 0)
        return hint

    def show_values(self, values: Mapping[str, Any]) -> None:
        """Re-seed the controls from ``values`` without reporting a change.

        Only toggles are refreshed, because a toggle is the only control here
        that can change behind the app's back: "start with Windows" lives in the
        Windows registry and can be switched off from Task Manager while the app
        is running.

        Signals are blocked while it happens. Without that, re-seeding a switch
        looks exactly like the user flicking it, and the app would write back
        the value it had just finished reading.
        """
        self._values.update(values)
        for key, widget in self._controls.items():
            if not isinstance(widget, controls.Toggle):
                continue
            wanted = tasks.as_bool(self._values.get(key))
            if widget.is_checked() == wanted:
                continue
            blocked = widget.blockSignals(True)
            widget.set_checked(wanted)
            widget.blockSignals(blocked)

    def _toggle(self, field: tasks.Field, values: Mapping[str, Any]) -> QtWidgets.QWidget:
        toggle = controls.Toggle(field.label, tasks.as_bool(values.get(field.key)))
        toggle.toggled.connect(
            lambda checked, key=field.key: self.changed.emit(key, checked)
        )
        self._controls[field.key] = toggle
        hint = self._explanation(field.key)
        if hint is None:
            return toggle

        holder = QtWidgets.QWidget()
        block = vbox(0)
        block.addWidget(toggle)
        block.addWidget(hint)
        holder.setLayout(block)
        return holder

    def _segmented(self, field: tasks.Field, values: Mapping[str, Any]) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        block = vbox(8)
        block.addWidget(label(field.label, theme.body(13), theme.TEXT_MUTED))

        chips = QtWidgets.QWidget()
        flow = FlowLayout(chips, spacing=6)
        group = QtWidgets.QButtonGroup(holder)
        group.setExclusive(True)
        current = values.get(field.key)
        for index, option in enumerate(field.options):
            chip = controls.Chip(option)
            chip.setChecked(option == current)
            group.addButton(chip, index)
            flow.addWidget(chip)
        group.idClicked.connect(
            lambda index, key=field.key, options=field.options:
                self.changed.emit(key, options[index])
        )
        block.addWidget(chips)
        self._controls[field.key] = chips

        hint = self._explanation(field.key)
        if hint is not None:
            block.addWidget(hint)
        holder.setLayout(block)
        return holder


def heading(text: str) -> QtWidgets.QWidget:
    """The mono section label both surfaces put above their form."""
    return section_label(text)


def values_of(fields: Tuple[tasks.Field, ...], config: Dict[str, Any]) -> Dict[str, Any]:
    """Only the keys ``fields`` declares — used to seed a form from a merged dict."""
    return {f.key: config.get(f.key) for f in fields if f.holds_value}


class HotkeyButton(QtWidgets.QPushButton):
    """Press me, then press the combination you want.

    Only whole combinations are accepted, and only once a non-modifier key
    arrives — otherwise the first press of Ctrl would end the capture with
    "Ctrl", which is not a hotkey and never will be.
    """

    captured = QtCore.pyqtSignal(str)

    PROMPT = "Nhấn tổ hợp phím…"
    EMPTY = "Chưa đặt"

    def __init__(self, text: str = "", parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        import hotkeys

        self._hotkeys = hotkeys
        self._value = hotkeys.describe(text)
        self._listening = False
        self.setCheckable(True)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setMinimumHeight(34)
        self.clicked.connect(self._start_listening)
        self._restyle()

    def value(self) -> str:
        return self._value

    def set_value(self, text: str) -> None:
        self._value = self._hotkeys.describe(text)
        self._listening = False
        self.setChecked(False)
        self._restyle()

    def clear(self) -> None:
        if self._value == "":
            return
        self.set_value("")
        self.captured.emit("")

    def _start_listening(self) -> None:
        self._listening = True
        self.setChecked(True)
        self._restyle()
        self.grabKeyboard()

    def _stop_listening(self) -> None:
        if self._listening:
            self.releaseKeyboard()
        self._listening = False
        self.setChecked(False)
        self._restyle()

    def keyPressEvent(self, event) -> None:
        if not self._listening:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key in (QtCore.Qt.Key_Control, QtCore.Qt.Key_Shift, QtCore.Qt.Key_Alt,
                   QtCore.Qt.Key_Meta, QtCore.Qt.Key_unknown):
            return  # still waiting for the key the modifiers go with
        if key == QtCore.Qt.Key_Escape:
            self._stop_listening()
            return

        text = describe_key_event(event)
        if self._hotkeys.parse(text) is None:
            # Shown rather than accepted: a bare letter is refused on purpose,
            # and silently doing nothing would look like a broken button.
            self.setText("%s — không dùng được" % text)
            self._stop_listening()
            return
        self._value = self._hotkeys.describe(text)
        self._stop_listening()
        self.captured.emit(self._value)

    def focusOutEvent(self, event) -> None:
        self._stop_listening()
        super().focusOutEvent(event)

    def _restyle(self) -> None:
        self.setText(self.PROMPT if self._listening
                     else (self._value or self.EMPTY))
        self.setFont(theme.mono(11.5, tracking=0.08))
        colour = theme.ACCENT if self._listening else (
            theme.TEXT if self._value else theme.TEXT_FAINT)
        border = theme.ACCENT if self._listening else theme.CONTROL
        self.setStyleSheet(
            "QPushButton { background: %s; border: 1px solid %s;"
            " border-radius: %dpx; padding: 7px 12px; color: %s; text-align: left; }"
            " QPushButton:hover { border: 1px solid %s; }"
            % (theme.INSET, border, theme.RADIUS, colour, theme.ACCENT)
        )


# Qt names the modifiers; `hotkeys` names them the same way, so the two meet
# here rather than each knowing about the other.
_QT_MODIFIERS = (
    (QtCore.Qt.ControlModifier, "Ctrl"),
    (QtCore.Qt.AltModifier, "Alt"),
    (QtCore.Qt.ShiftModifier, "Shift"),
    (QtCore.Qt.MetaModifier, "Win"),
)


def describe_key_event(event) -> str:
    """``"Ctrl+Shift+S"`` from a Qt key event."""
    parts = [name for bit, name in _QT_MODIFIERS if event.modifiers() & bit]
    parts.append(QtGui.QKeySequence(event.key()).toString() or "?")
    return "+".join(parts)
