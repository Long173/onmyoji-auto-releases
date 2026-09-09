"""Detail views for a single shikigami or soul."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

import paths
import theme
from ui.primitives import (Badge, Card, Divider, FlowLayout, HatchFrame, body_text,
                           hbox, label, section_label, vbox)
from ui import controls
from ui.wiki_views import clear_layout, scrollable
from wiki import submissions
from wiki.images import ImageResolver
from wiki.models import Shikigami, Soul

PORTRAIT_COLUMN = 340
# The portrait column gives width back when the window is narrow rather than
# pushing the text column off-screen.
PORTRAIT_COLUMN_MIN = 240
PORTRAIT_HEIGHT = 300
SOUL_ART = 128
DETAIL_MAX_WIDTH = 860


# ── editing in place ────────────────────────────────────────────────────────
#
# The inputs keep the typography of the text they replace: the name stays 42pt
# display, the subtitle stays italic. That is the point of editing here instead
# of in a form — the page still reads as the page, so it is obvious what each
# box will look like once it is saved.
#
# What marks them as editable is a hairline under the single-line ones and a
# framed inset behind the blocks, going accent-coloured on focus. Boxes drawn
# like form fields would have turned the page back into the form.


def edit_line(value: str, font: QtGui.QFont, colour: str = theme.TEXT,
              placeholder: str = "") -> QtWidgets.QLineEdit:
    """A single line of the page, made editable, at its own size."""
    box = QtWidgets.QLineEdit(value)
    box.setFont(font)
    box.setPlaceholderText(placeholder)
    box.setStyleSheet(
        "QLineEdit { background: transparent; border: none;"
        " border-bottom: 1px solid %s; padding: 2px 0; color: %s; }"
        " QLineEdit:focus { border-bottom: 1px solid %s; }"
        " QLineEdit[readOnly=\"true\"] { color: %s; }"
        % (theme.CONTROL, colour, theme.ACCENT, theme.TEXT_FAINT)
    )
    return box


def edit_area(value: str, height: int, placeholder: str = "",
              font: Optional[QtGui.QFont] = None) -> QtWidgets.QPlainTextEdit:
    """A block of the page, made editable."""
    box = QtWidgets.QPlainTextEdit(value)
    box.setFont(font or theme.body(13.5))
    box.setPlaceholderText(placeholder)
    box.setFixedHeight(height)
    box.setStyleSheet(
        "QPlainTextEdit { background: %s; border: 1px solid %s;"
        " border-radius: %dpx; padding: 6px 8px; color: %s; }"
        " QPlainTextEdit:focus { border: 1px solid %s; }"
        % (theme.INSET, theme.CONTROL, theme.RADIUS, theme.TEXT_BODY, theme.ACCENT)
    )
    return box


def edit_choice(value: str, choices: Sequence[str]) -> QtWidgets.QComboBox:
    """The rarity badge, made editable, without growing to fill the row."""
    box = QtWidgets.QComboBox()
    box.addItems(list(choices))
    index = box.findText(value)
    box.setCurrentIndex(index if index >= 0 else 0)
    box.setFont(theme.mono(11, tracking=0.14))
    box.setFixedWidth(88)
    box.setStyleSheet(
        "QComboBox { background: %s; border: 1px solid %s; border-radius: %dpx;"
        " padding: 3px 8px; color: %s; }"
        " QComboBox QAbstractItemView { background: %s; color: %s;"
        " selection-background-color: %s; }"
        % (theme.INSET, theme.ACCENT, theme.RADIUS_BADGE, theme.ACCENT,
           theme.CARD, theme.TEXT, theme.ACCENT_FILL)
    )
    return box


def demon_fire_pixmap(height: int) -> QtGui.QPixmap:
    """The game's own demon-fire orb, scaled to sit beside text.

    Cut out of a capture of the skill panel: the parchment behind it was removed
    by distance from its own colour, which is what keeps the near-white core —
    an earlier attempt keyed on "bluer than green" and made a hole where the
    core is.

    Cached because a skill list asks for it once per skill and the scaling is
    the expensive half.
    """
    cached = _DEMON_FIRE.get(height)
    if cached is not None:
        return cached
    path = paths.ASSET_DIR / "icons" / "demon_fire.png"
    pixmap = QtGui.QPixmap(str(path))
    if not pixmap.isNull():
        pixmap = pixmap.scaledToHeight(
            height, QtCore.Qt.SmoothTransformation)
    _DEMON_FIRE[height] = pixmap
    return pixmap


_DEMON_FIRE: Dict[int, QtGui.QPixmap] = {}

COST_ICON_HEIGHT = 17


def cost_badge(text: str) -> QtWidgets.QWidget:
    """Orbs of demon fire the skill spends.

    The game's own icon and a number, which is how the game shows it and how the
    Vietnamese source writes it — "(2 🔥)". It was an emoji flame, which was
    orange; demon fire is blue, so the emoji was not a placeholder for the icon
    but a different thing entirely.

    If the icon is missing the badge still draws, with the number alone. A
    missing asset should cost a picture, not the fact.
    """
    holder = QtWidgets.QFrame()
    holder.setObjectName("costBadge")
    # Border only, no fill. A translucent fill on the frame did not paint under
    # the child holding the pixmap — Qt renders a stylesheet background behind
    # styled widgets, and a child left transparent shows the ancestor's colour
    # rather than its parent's — so the icon sat in a visibly darker rectangle.
    # Measured: (28,26,24) inside that rectangle against (30,39,43) beside it.
    holder.setStyleSheet(
        "#costBadge { border: 1px solid %s; border-radius: %dpx;"
        " background: transparent; }"
        % (theme.DEMON_FIRE_BORDER, theme.RADIUS_BADGE))
    row = hbox(4, margins=(6, 2, 8, 2))
    orb = demon_fire_pixmap(COST_ICON_HEIGHT)
    if not orb.isNull():
        art = QtWidgets.QLabel()
        art.setPixmap(orb)
        art.setFixedSize(orb.size())
        row.addWidget(art, 0, QtCore.Qt.AlignVCenter)
    row.addWidget(label(text, theme.mono(11.5, tracking=0.06), theme.DEMON_FIRE),
                  0, QtCore.Qt.AlignVCenter)
    holder.setLayout(row)
    holder.setToolTip("Tốn %s quỷ hỏa" % text)
    return holder


def kept_note(what: str) -> QtWidgets.QLabel:
    """Says a field is carried through untouched rather than lost.

    Skills, stats and slot mains have no sensible text box, so they are not
    offered. Saying so matters: a page that showed them read-only beside
    editable neighbours and said nothing would read as "these will be dropped".
    """
    note = body_text("%s không sửa được ở đây — sẽ được giữ nguyên." % what,
                     11.5, theme.TEXT_FAINT, italic=True)
    return note


def gold_label(text: str) -> QtWidgets.QLabel:
    """Section heading in the accent colour."""
    return section_label(text, theme.ACCENT)


def framed_art(resolver: ImageResolver, image: str, height: int, caption: str,
               hug: bool = False) -> QtWidgets.QWidget:
    """Inset frame with a hairline border, matching the design's plate treatment."""
    frame = QtWidgets.QFrame()
    frame.setObjectName("artFrame")
    frame.setStyleSheet(
        "#artFrame { border: 1px solid %s; background: %s; }"
        % (theme.DIVIDER, theme.INSET)
    )
    layout = QtWidgets.QVBoxLayout(frame)
    layout.setContentsMargins(8, 8, 8, 8)
    art = HatchFrame(caption, hug=hug, hug_min=height if hug else 0)
    if not hug:
        # Without hugging the frame has no opinion of its own, so the height
        # asked for has to be pinned as a floor.
        art.setMinimumHeight(height)
    art.set_pixmap(resolver.pixmap(image))
    layout.addWidget(art)
    return frame


def stat_row(caption: str, value: str, numeric: bool = True) -> QtWidgets.QWidget:
    """Label left, value right, hairline under.

    ``numeric`` picks the tabular mono face for figures; words read better in
    the body face.
    """
    holder = QtWidgets.QWidget()
    wrapper = QtWidgets.QVBoxLayout(holder)
    wrapper.setContentsMargins(0, 0, 0, 0)
    wrapper.setSpacing(0)

    row = hbox(margins=(0, 8, 0, 8))
    row.addWidget(label(caption, theme.body(13), theme.TEXT_SECONDARY))
    row.addStretch()
    if numeric:
        row.addWidget(label(value, theme.tabular(13.5)))
    else:
        # Wording like "Tấn công % / Tốc độ / Sinh mệnh %" needs to wrap rather
        # than widen the column.
        wrapped = label(value, theme.body(13), wrap=True)
        wrapped.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignTop)
        row.addWidget(wrapped, 1)

    wrapper.addLayout(row)
    wrapper.addWidget(Divider(color=theme.ROW_RULE))
    return holder


CHIP_MAX_WIDTH = 220
LEVEL_TAG_WIDTH = 54
SKILL_ICON = 40
SKILL_ICON_GAP = 14


def skill_icon(resolver: ImageResolver, image: str) -> QtWidgets.QWidget:
    """The round skill icon, or an empty slot of the same size.

    The slot is kept even when there is no artwork so that every skill's text
    starts on the same edge — 7 of the 836 skills have no file.
    """
    holder = QtWidgets.QLabel()
    holder.setFixedSize(SKILL_ICON, SKILL_ICON)
    holder.setStyleSheet("background: transparent; border: 0;")
    holder.setAlignment(QtCore.Qt.AlignCenter)

    pixmap = resolver.pixmap(image) if image else None
    if pixmap is not None and not pixmap.isNull():
        holder.setPixmap(
            pixmap.scaled(
                SKILL_ICON,
                SKILL_ICON,
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )
        )
    return holder


def level_row(caption: str, text: str) -> QtWidgets.QWidget:
    """One rung of a skill's upgrade ladder: mono tag, then the change.

    Both columns line up with the skill description above: the tag is
    left-aligned so its glyphs start on the same edge, and it is nudged down by
    the difference in ascent so the two type sizes share a baseline.
    """
    holder = QtWidgets.QWidget()
    row = QtWidgets.QHBoxLayout(holder)
    row.setContentsMargins(0, 5, 0, 0)
    row.setSpacing(12)

    tag_font = theme.mono(10, tracking=0.1)
    body_font = theme.body(13)
    baseline_offset = max(
        0,
        QtGui.QFontMetrics(body_font).ascent()
        - QtGui.QFontMetrics(tag_font).ascent(),
    )

    tag = label(caption.upper(), tag_font, theme.TEXT_LABEL)
    tag.setFixedWidth(LEVEL_TAG_WIDTH)
    tag.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
    tag.setContentsMargins(0, baseline_offset, 0, 0)

    # Top-aligned as an item so the tag stays on the first line of wrapped text.
    row.addWidget(tag, 0, QtCore.Qt.AlignTop)
    row.addWidget(body_text(text, 13, theme.TEXT_MUTED), 1)
    return holder


def outlined_chip(text: str, color: str = theme.TEXT_SECONDARY,
                  border: str = theme.CONTROL) -> QtWidgets.QLabel:
    chip = QtWidgets.QLabel(text)
    chip.setFont(theme.body(12))
    chip.setStyleSheet(
        "color: %s; border: 1px solid %s; border-radius: %dpx;"
        " padding: 4px 10px; background: transparent;" % (color, border, theme.RADIUS_SMALL)
    )
    # Only chips too long to fit the cap wrap. Wrapping every chip made short
    # ones like "tên gọi: Dơi SP" break across two lines, because a wrapped
    # QLabel prefers a balanced width over its single-line width.
    padding = 22  # the 10px each side above, plus the border
    single_line = QtGui.QFontMetrics(chip.font()).horizontalAdvance(text) + padding
    if single_line > CHIP_MAX_WIDTH:
        chip.setWordWrap(True)
        chip.setMaximumWidth(CHIP_MAX_WIDTH)
        chip.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Minimum)
    else:
        chip.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
    return chip


def flow(widgets: Sequence[QtWidgets.QWidget], spacing: int = 7) -> QtWidgets.QWidget:
    """Lay widgets left to right, wrapping onto new lines as the width allows."""
    holder = QtWidgets.QWidget()
    layout = FlowLayout(holder, spacing=spacing)
    for widget in widgets:
        layout.addWidget(widget)
    return holder


class LinkRow(Card):
    """A bordered, clickable row — used for recommended souls."""

    def __init__(self, title: str, note: str, on_click: Callable[[], None]) -> None:
        super().__init__(background="transparent")
        self._on_click = on_click
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setAttribute(QtCore.Qt.WA_Hover, True)

        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)
        row.addWidget(label(title, theme.body(13.5)))
        row.addStretch()
        if note:
            row.addWidget(label(note, theme.mono(10.5, tracking=0.08), theme.TEXT_LABEL))

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self.set_border(theme.BORDER_HOVER)
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self.set_border(theme.BORDER)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self._on_click()
        super().mouseReleaseEvent(event)


class ShikigamiDetailView(QtWidgets.QWidget):
    """Portrait and stats on the left, everything else on the right."""

    openSoul = QtCore.pyqtSignal(str)
    openShikigami = QtCore.pyqtSignal(str)
    # Edit mode only. The page owns what happens next; this view owns the boxes.
    saveRequested = QtCore.pyqtSignal()
    cancelRequested = QtCore.pyqtSignal()

    def __init__(self, resolver: ImageResolver, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._resolver = resolver
        # Set while editing: field key -> the widget holding it. Rebuilt on every
        # render, because render() throws the previous widgets away.
        self._inputs: Dict[str, QtWidgets.QWidget] = {}
        self._editing = False
        self._adding = False
        self._save: Optional[QtWidgets.QPushButton] = None
        self._status: Optional[QtWidgets.QLabel] = None
        self._author = ""
        self._author_box: Optional[QtWidgets.QLineEdit] = None
        self._skills: List[Dict[str, Any]] = []
        # One entry per skill on screen: the widgets holding its text, so the
        # typing can be read back before the page is rebuilt.
        self._skill_boxes: List[Dict[str, Any]] = []
        # effect id -> Vietnamese name. All 20 ids that appear on skills resolve
        # in the `effects` table, so the tags can be words instead of slugs.
        # Empty until somebody supplies it, and then the slug is shown — a
        # reader who sees `scorching_fire` at least has something to search for.
        self._effect_names: Dict[str, str] = {}

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        area, inner = scrollable()
        self._root = QtWidgets.QHBoxLayout(inner)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)
        layout.addWidget(area)

    def set_effect_names(self, names: Dict[str, str]) -> None:
        """Supply the id → name mapping for skill tags."""
        self._effect_names = dict(names or {})

    def render(
        self,
        record: Shikigami,
        recommended: Sequence[Tuple[str, str, Optional[str]]],
        counters: Sequence[Tuple[str, Optional[str]]],
    ) -> None:
        """``recommended`` and ``counters`` carry resolved ids for the links."""
        self._editing = False
        self._adding = False
        self._inputs = {}
        self._save = None
        self._status = None
        self._author = ""
        self._author_box = None
        self._skills: List[Dict[str, Any]] = []
        self._skill_boxes: List[Dict[str, Any]] = []
        self._values: Dict[str, str] = {}
        clear_layout(self._root)
        self._root.addWidget(self._build_left(record))
        self._root.addWidget(Divider(horizontal=False))
        self._root.addWidget(self._build_right(record, recommended, counters), 1)

    def edit(self, row: Dict[str, Any], adding: bool = False,
             author: str = "") -> None:
        """The same page, with its text made editable.

        Driven by the raw server row rather than by a :class:`Shikigami`. The
        model drops what it has no field for, and approval upserts the whole
        row — so an edit built from the model would delete every column the
        model does not carry.
        """
        self._editing = True
        self._adding = adding
        self._inputs = {}
        self._skill_boxes = []
        self._author = author
        self._values = submissions.read_values(row)
        # A working copy, because the skills editor grows and shrinks: adding or
        # removing one rebuilds the page, and the boxes cannot survive that.
        # Harvested back into this list before every rebuild.
        self._skills = submissions.read_skills(row)
        # Not a form field any more, but the label above still shows it.
        self._values["id"] = str(row.get("id") or "")
        record = Shikigami.from_row(dict(row) or {"id": "", "rarity": "N"})
        clear_layout(self._root)
        self._root.addWidget(self._build_left(record))
        self._root.addWidget(Divider(horizontal=False))
        self._root.addWidget(self._build_right(record, (), ()), 1)

    # ── what the boxes hold ─────────────────────────────────────────────────

    def edit_values(self) -> Dict[str, str]:
        """One string per editable field, as typed."""
        values: Dict[str, str] = {}
        for key, box in self._inputs.items():
            if isinstance(box, QtWidgets.QComboBox):
                values[key] = box.currentText()
            elif isinstance(box, QtWidgets.QPlainTextEdit):
                values[key] = box.toPlainText()
            else:
                values[key] = box.text()
        return values

    def set_busy(self, busy: bool) -> None:
        if self._save is not None:
            self._save.setEnabled(not busy)
        if self._author_box is not None:
            self._author_box.setEnabled(not busy)
        for box in self._inputs.values():
            if isinstance(box, QtWidgets.QLineEdit) and box.isReadOnly():
                continue
            box.setEnabled(not busy)

    def set_status(self, message: str, colour: str = "") -> None:
        if self._status is not None:
            self._status.setText(message)
            self._status.setStyleSheet("color: %s;" % (colour or theme.TEXT_MUTED))

    def _remember(self, key: str, box: QtWidgets.QWidget) -> QtWidgets.QWidget:
        self._inputs[key] = box
        return box

    def _field(self, key: str) -> str:
        return self._values.get(key, "")

    def _build_left(self, record: Shikigami) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        holder.setMinimumWidth(PORTRAIT_COLUMN_MIN)
        holder.setMaximumWidth(PORTRAIT_COLUMN)
        holder.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred
        )
        column = QtWidgets.QVBoxLayout(holder)
        column.setContentsMargins(26, 26, 26, 26)
        column.setSpacing(0)

        column.addWidget(
            framed_art(self._resolver, record.image, PORTRAIT_HEIGHT,
                       "shikigami.image", hug=True)
        )

        rows = record.stat_rows
        if rows:
            column.addSpacing(20)
            column.addWidget(section_label("Chỉ số"))
            column.addSpacing(10)
            for caption, value in rows:
                column.addWidget(stat_row(caption, value))
        if self._editing:
            column.addSpacing(20 if not rows else 10)
            column.addWidget(kept_note("Chỉ số"))

        if self._editing:
            column.addSpacing(20)
            column.addWidget(section_label("Nguồn"))
            column.addSpacing(8)
            column.addWidget(self._remember("obtain", edit_area(
                self._field("obtain"), 92, "Mỗi cách nhận một dòng")))
        elif record.obtain:
            column.addSpacing(20)
            column.addWidget(section_label("Nguồn"))
            column.addSpacing(8)
            column.addWidget(
                body_text(" · ".join(record.obtain), 13, theme.TEXT_SECONDARY)
            )

        column.addStretch()
        return holder

    def _build_right(
        self,
        record: Shikigami,
        recommended: Sequence[Tuple[str, str, Optional[str]]],
        counters: Sequence[Tuple[str, Optional[str]]],
    ) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(holder)
        column.setContentsMargins(30, 26, 30, 34)
        column.setSpacing(0)

        if self._editing:
            column.addWidget(self._build_edit_bar())
            column.addSpacing(18)

        # Names run long ("Linh Ngạn Cơ (Suzuhiko Hime)/Linda"), so the heading
        # wraps and the badge sits on its own line under it. Keeping them on one
        # unwrapped row made the page 1400px wide at the title alone.
        if self._editing:
            column.addWidget(self._remember("name_vi", edit_line(
                self._field("name_vi"), theme.display(42), theme.TEXT,
                "Tên tiếng Việt")))
        else:
            column.addWidget(label(record.display_name, theme.display(42), wrap=True))

        if self._editing:
            subtitle_row = hbox(10)
            subtitle_row.addWidget(
                self._remember("rarity", edit_choice(
                    self._field("rarity") or "N", submissions.RARITIES)),
                0, QtCore.Qt.AlignTop)
            english = self._remember("name_en", edit_line(
                self._field("name_en"), theme.body(15, italic=True),
                theme.TEXT_LABEL, "Tên tiếng Anh / romaji"))
            subtitle_row.addWidget(english, 1)
            column.addSpacing(8)
            column.addLayout(subtitle_row)
            column.addSpacing(4)
            # Under the English name, because that is what it is made from.
            column.addWidget(self._build_generated_id(english))
        else:
            subtitle = [Badge(record.rarity, theme.ACCENT)]
            if record.secondary_name:
                subtitle.append(
                    label(record.secondary_name, theme.body(15, italic=True),
                          theme.TEXT_LABEL, wrap=True)
                )
            column.addSpacing(8)
            column.addWidget(flow(subtitle, spacing=10))

        if self._editing:
            column.addSpacing(14)
            column.addWidget(section_label("Tên gọi khác"))
            column.addSpacing(6)
            column.addWidget(self._remember("friendly_name", edit_area(
                self._field("friendly_name"), 84, "Mỗi tên một dòng")))
        else:
            chips = [outlined_chip("tên gọi: " + name)
                     for name in record.friendly_name]
            if chips:
                column.addSpacing(12)
                column.addWidget(flow(chips))

        column.addSpacing(20)
        column.addWidget(Divider())
        column.addSpacing(20)

        if self._editing:
            column.addWidget(section_label("Mô tả"))
            column.addSpacing(6)
            column.addWidget(self._remember("description", edit_area(
                self._field("description"), 104, "Mô tả ngắn về thức thần",
                theme.body(14))))
        elif record.description:
            column.addWidget(body_text(record.description, 14.5, justify=True))

        if self._editing:
            column.addSpacing(26)
            column.addWidget(gold_label("Kỹ năng"))
            column.addSpacing(6)
            for index in range(len(self._skills)):
                column.addWidget(self._build_skill_editor(index))
            column.addSpacing(10)
            add_skill = controls.OutlineButton(
                "+  Thêm kỹ năng", controls.ACCENT, padding="8px 16px")
            add_skill.clicked.connect(self._add_skill)
            column.addWidget(add_skill, 0, QtCore.Qt.AlignLeft)
        elif record.skills:
            column.addSpacing(26)
            column.addWidget(gold_label("Kỹ năng"))
            column.addSpacing(6)
            for skill in record.skills:
                column.addWidget(self._build_skill(skill))

        bottom = hbox(26)
        bottom.addWidget(
            self._build_souls_column(record, recommended), 1, QtCore.Qt.AlignTop
        )
        bottom.addWidget(
            self._build_counters_column(record, counters), 1, QtCore.Qt.AlignTop
        )
        column.addSpacing(26)
        column.addLayout(bottom)
        column.addStretch()
        return holder

    def _build_generated_id(self, name_box: QtWidgets.QLineEdit) -> QtWidgets.QWidget:
        """Shows the id this record will have, as the English name is typed.

        Shown but not editable. The id is the primary key: approving an
        addition upserts on it, so one typed by hand either makes a duplicate
        record or overwrites somebody else's. It is still *shown*, because a key
        that appears from nowhere is a key nobody can search for or report.

        Absent while editing, where the id is fixed and cannot be changed by
        anything on this page.
        """
        label_widget = body_text("", 11.5, theme.TEXT_FAINT)
        label_widget.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        def restate() -> None:
            generated = (submissions.slugify(name_box.text()) if self._adding
                         else self._field_id())
            label_widget.setText(
                "mã: %s" % generated if generated
                else "mã: (nhập tên tiếng Anh để sinh mã)")

        name_box.textChanged.connect(lambda _text: restate())
        restate()
        self._generated_id = label_widget
        return label_widget

    def _field_id(self) -> str:
        return str(self._values.get("id") or "")

    def _build_edit_bar(self) -> QtWidgets.QWidget:
        """Save and cancel, at the top of the page being edited.

        At the top rather than the bottom: the page is long and scrolls, and
        buttons at the end of a scrolling page are buttons somebody has to go
        looking for.
        """
        holder = QtWidgets.QWidget()
        block = vbox(8)

        row = hbox(10)
        row.addWidget(label(
            "Đang đề xuất thêm thức thần mới" if self._adding
            else "Đang đề xuất sửa", theme.mono(10.5, tracking=0.14),
            theme.ACCENT))
        row.addStretch()
        cancel = controls.OutlineButton("Huỷ", padding="7px 14px")
        cancel.clicked.connect(self.cancelRequested.emit)
        self._save = controls.OutlineButton(
            "Gửi góp ý", controls.ACCENT, padding="7px 16px")
        self._save.clicked.connect(self.saveRequested.emit)
        row.addWidget(cancel)
        row.addWidget(self._save)
        block.addLayout(row)

        credit = hbox(8)
        credit.addWidget(label("Tên bạn", theme.mono(10, tracking=0.14),
                               theme.TEXT_FAINT))
        self._author_box = QtWidgets.QLineEdit(self._author)
        self._author_box.setFont(theme.body(12))
        self._author_box.setFixedWidth(220)
        self._author_box.setPlaceholderText("không bắt buộc")
        self._author_box.setStyleSheet(
            "QLineEdit { background: transparent; border: none;"
            " border-bottom: 1px solid %s; padding: 1px 0; color: %s; }"
            " QLineEdit:focus { border-bottom: 1px solid %s; }"
            % (theme.CONTROL, theme.TEXT_SECONDARY, theme.ACCENT)
        )
        credit.addWidget(self._author_box)
        credit.addStretch()
        block.addLayout(credit)

        self._status = body_text("", 12, theme.TEXT_MUTED)
        self._status.setWordWrap(True)
        block.addWidget(self._status)
        holder.setLayout(block)
        return holder

    def author(self) -> str:
        return self._author_box.text().strip() if self._author_box is not None else ""

    def _build_skill(self, skill) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        wrapper = QtWidgets.QVBoxLayout(holder)
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.setSpacing(0)
        wrapper.addWidget(Divider())

        # Icon in its own column; name, description and levels share the single
        # left edge beside it.
        row = hbox(SKILL_ICON_GAP, margins=(0, 14, 0, 14))
        # Alignment belongs on the item, not the layout: QLayout.setAlignment
        # positions the layout inside its parent and leaves items centred, which
        # floated the icon into the middle of the block.
        row.addWidget(skill_icon(self._resolver, skill.image), 0, QtCore.Qt.AlignTop)

        body = vbox(6)
        # Skill names are long and uppercase; wrapping keeps them from setting
        # the page width. The cost sits beside the name rather than under it,
        # which is where the game puts it and the first thing anybody asks about
        # an active skill.
        heading = hbox(10)
        heading.addWidget(label(skill.name, theme.display(20), wrap=True), 1)
        if skill.cost_label:
            heading.addWidget(cost_badge(skill.cost_label), 0, QtCore.Qt.AlignTop)
        body.addLayout(heading)

        tags = self._effect_chips(skill.effects)
        if tags is not None:
            body.addWidget(tags)

        if skill.description:
            body.addWidget(
                body_text(skill.description, 13.5, theme.TEXT_SECONDARY, justify=True)
            )
        for caption, text in skill.level_rows:
            body.addWidget(level_row(caption, text))

        for form in skill.alt_forms:
            body.addSpacing(10)
            body.addWidget(self._build_alt_form(form))

        row.addLayout(body, 1)
        wrapper.addLayout(row)
        return holder

    def _effect_chips(self, effects) -> Optional[QtWidgets.QWidget]:
        """The skill's tags, as words where they can be resolved."""
        if not effects:
            return None
        chips = [outlined_chip(self._effect_names.get(str(tag), str(tag)))
                 for tag in effects]
        return flow(chips)

    def _build_alt_form(self, form) -> QtWidgets.QWidget:
        """The form a skill permanently turns into.

        Indented under its parent and labelled, because that is what it is: not
        a fourth skill in the list, but what the third one becomes. Three skills
        in the dataset have one and none of them showed it before.
        """
        holder = QtWidgets.QFrame()
        holder.setObjectName("altForm")
        holder.setStyleSheet(
            "#altForm { border-left: 2px solid %s; background: %s; }"
            % (theme.ACCENT, theme.HATCH_DARK))
        block = vbox(6, margins=(14, 12, 12, 12))
        block.addWidget(section_label("CHUYỂN THÀNH", theme.ACCENT))

        heading = hbox(10)
        heading.addWidget(label(form.name, theme.display(17), wrap=True), 1)
        if form.cost_label:
            heading.addWidget(cost_badge(form.cost_label), 0, QtCore.Qt.AlignTop)
        block.addLayout(heading)

        tags = self._effect_chips(form.effects)
        if tags is not None:
            block.addWidget(tags)
        if form.description:
            block.addWidget(body_text(form.description, 13, theme.TEXT_SECONDARY,
                                      justify=True))
        # Its own ladder, because the game gives it one.
        for caption, text in form.level_rows:
            block.addWidget(level_row(caption, text))
        holder.setLayout(block)
        return holder

    def _build_skill_editor(self, index: int) -> QtWidgets.QWidget:
        """One skill, editable, in the shape the read-only block has.

        The icon stays where it is and is not editable: it is a storage key for
        artwork that has to exist, and a text box inviting somebody to invent one
        would only ever produce a broken image.

        Level rows keep their "CẤP n" captions and the numbers are positional —
        leave a level blank and it is dropped, which is how a five-row template
        serves a three-level skill without asking anyone to count.
        """
        skill = self._skills[index]
        boxes: Dict[str, Any] = {"levels": []}
        self._skill_boxes.append(boxes)

        holder = QtWidgets.QWidget()
        wrapper = vbox(0)
        wrapper.addWidget(Divider())

        row = hbox(SKILL_ICON_GAP, margins=(0, 14, 0, 14))
        row.addWidget(skill_icon(self._resolver, str(skill.get("image") or "")),
                      0, QtCore.Qt.AlignTop)

        body = vbox(6)

        head = hbox(8)
        boxes["name"] = edit_line(str(skill.get("name") or ""),
                                  theme.display(20), theme.TEXT, "Tên kỹ năng")
        head.addWidget(boxes["name"], 1)
        # Shown, not editable. It is carried through untouched, and a skill that
        # displayed its cost on the page and then hid it here would look as
        # though editing had dropped it.
        if isinstance(skill.get("cost"), int):
            head.addWidget(cost_badge(str(skill["cost"])), 0, QtCore.Qt.AlignTop)
        remove = controls.OutlineButton("✕", controls.DANGER, padding="4px 10px")
        remove.setToolTip("Bỏ kỹ năng này")
        remove.clicked.connect(lambda _checked=False, i=index: self._remove_skill(i))
        head.addWidget(remove, 0, QtCore.Qt.AlignTop)
        body.addLayout(head)

        boxes["description"] = edit_area(
            str(skill.get("description") or ""), 72, "Mô tả kỹ năng")
        body.addWidget(boxes["description"])

        # Level 1 is the description and has no box of its own — see
        # `submissions.editable_levels`. The caption shows the level's *stored*
        # number rather than its position, because the numbers are not always a
        # plain run: ten skills on the server carry two forms and are numbered
        # 1,2,3,4,5,2,3,4,5.
        for entry in submissions.editable_levels(skill):
            level_row_widget = hbox(10)
            caption = label("CẤP %s" % (entry.get("level") or "?"),
                            theme.mono(10, tracking=0.14), theme.TEXT_FAINT)
            caption.setFixedWidth(58)
            level_row_widget.addWidget(caption, 0, QtCore.Qt.AlignTop)
            # Two lines, not one. Measured across all 1501 levels on the
            # server: half are under 40 characters, but 26% pass 80 and the
            # longest is 1176. A single-line box also scrolls to its *end* when
            # filled in, so a long level opened showing the middle of a
            # sentence — which reads as truncated data rather than a small box.
            box = edit_area(str((entry or {}).get("description") or ""), 48,
                            "để trống nếu kỹ năng không có cấp này",
                            theme.body(12.5))
            boxes["levels"].append(box)
            level_row_widget.addWidget(box, 1)
            body.addLayout(level_row_widget)

        for form in (skill.get("alt_forms") or []):
            if isinstance(form, dict) and str(form.get("name") or "").strip():
                body.addSpacing(8)
                body.addWidget(kept_note(
                    "Dạng chuyển đổi \"%s\"" % form["name"]))

        levels = hbox(8)
        add_level = controls.OutlineButton("+ cấp", padding="4px 12px")
        add_level.clicked.connect(lambda _checked=False, i=index: self._add_level(i))
        levels.addWidget(add_level)
        levels.addStretch()
        body.addSpacing(4)
        body.addLayout(levels)

        row.addLayout(body, 1)
        wrapper.addLayout(row)
        holder.setLayout(wrapper)
        return holder

    # ── growing and shrinking the skills list ───────────────────────────────

    def _harvest_skills(self) -> None:
        """Read the boxes back into the working copy.

        Called before anything that rebuilds the page. Without it, adding a
        second skill would throw away everything typed into the first.
        """
        for skill, boxes in zip(self._skills, self._skill_boxes):
            skill["name"] = boxes["name"].text()
            skill["description"] = boxes["description"].toPlainText()
            # Zipped against the same list the boxes were built from, so a
            # skill with no level 1 and one with a level 1 both line up. Reading
            # by position into `skill["levels"]` would have written level 2's
            # text into level 1 for every standard skill.
            for entry, box in zip(submissions.editable_levels(skill),
                                  boxes["levels"]):
                entry["description"] = box.toPlainText()

    def _rebuild(self) -> None:
        """Redraw the page around a changed skills list.

        Reads the boxes back first, and is the only place that does. Every path
        that grows or shrinks the list comes through here, so putting the harvest
        anywhere else means remembering it again next time — and forgetting it
        loses whatever was typed, silently.
        """
        self._harvest_skills()
        kept = dict(self._values)
        kept.update(self.edit_values())
        row = submissions.apply_edits({"id": self._field_id()}, kept)
        row["skills"] = self._skills
        row["id"] = self._field_id()
        self.edit(row, adding=self._adding, author=self.author())

    def _add_skill(self) -> None:
        self._skills.append(submissions.blank_skill())
        self._rebuild()

    def _remove_skill(self, index: int) -> None:
        if 0 <= index < len(self._skills):
            del self._skills[index]
        self._rebuild()

    def _add_level(self, index: int) -> None:
        if 0 <= index < len(self._skills):
            levels = self._skills[index].setdefault("levels", [])
            # After the highest number already there, never below 2: level 1 is
            # the description and is not a row anybody adds.
            highest = max([lv.get("level") for lv in levels
                           if isinstance(lv, dict)
                           and isinstance(lv.get("level"), int)] or [1])
            levels.append({"level": max(highest + 1, 2), "description": ""})
        self._rebuild()

    def edit_skills(self) -> List[Dict[str, Any]]:
        """The skills as typed, ready to send."""
        self._harvest_skills()
        return submissions.clean_skills(self._skills)

    def _build_souls_column(
        self, record: Shikigami, recommended: Sequence[Tuple[str, str, Optional[str]]]
    ) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        column.addWidget(gold_label("Ngự hồn gợi ý"))
        if self._editing:
            column.addWidget(self._remember("recommended_souls", edit_area(
                self._field("recommended_souls"), 104, "Mã ngự hồn, mỗi mã một dòng")))
            column.addStretch()
            return holder
        if recommended:
            for name, note, soul_id in recommended:
                if soul_id:
                    column.addWidget(
                        LinkRow(name, note, lambda i=soul_id: self.openSoul.emit(i))
                    )
                else:
                    column.addWidget(outlined_chip(name))
        else:
            column.addWidget(label("Chưa có dữ liệu", theme.body(13), theme.TEXT_FAINT))

        slot_rows = record.slot_main_rows
        if slot_rows:
            column.addSpacing(10)
            column.addWidget(section_label("Chỉ số chính"))
            for caption, value in slot_rows:
                column.addWidget(stat_row(caption, value, numeric=False))
        column.addStretch()
        return holder

    def _build_counters_column(
        self, record: Shikigami, counters: Sequence[Tuple[str, Optional[str]]]
    ) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        column.addWidget(gold_label("Bị khắc chế bởi"))
        if self._editing:
            column.addWidget(self._remember("countered_by", edit_area(
                self._field("countered_by"), 92, "Mã thức thần, mỗi mã một dòng")))
            column.addSpacing(12)
            column.addWidget(section_label("Truyền thuyết"))
            column.addSpacing(6)
            column.addWidget(self._remember("lore", edit_area(
                self._field("lore"), 112, "Cốt truyện",
                theme.body(13.5, italic=True))))
            column.addStretch()
            return holder
        if counters:
            chips: List[QtWidgets.QWidget] = []
            for name, target_id in counters:
                chip = outlined_chip(name, theme.DANGER, theme.DANGER_BORDER)
                if target_id:
                    chip.setCursor(QtCore.Qt.PointingHandCursor)
                    chip.mousePressEvent = (  # type: ignore[assignment]
                        lambda _event, i=target_id: self.openShikigami.emit(i)
                    )
                chips.append(chip)
            column.addWidget(flow(chips))
        else:
            column.addWidget(label("Chưa có dữ liệu", theme.body(13), theme.TEXT_FAINT))

        if record.lore:
            column.addSpacing(10)
            column.addWidget(section_label("Truyền thuyết"))
            column.addWidget(
                body_text(record.lore, 13.5, theme.TEXT_MUTED, justify=True, italic=True)
            )
        column.addStretch()
        return holder


class SoulDetailView(QtWidgets.QWidget):
    """Set bonuses and the shikigami that use them."""

    openShikigami = QtCore.pyqtSignal(str)

    def __init__(self, resolver: ImageResolver, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._resolver = resolver

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        area, inner = scrollable()
        outer = QtWidgets.QHBoxLayout(inner)
        outer.setContentsMargins(30, 28, 30, 34)
        self._column = vbox(0)
        host = QtWidgets.QWidget()
        host.setMaximumWidth(DETAIL_MAX_WIDTH)
        host.setLayout(self._column)
        outer.addWidget(host)
        outer.addStretch()
        layout.addWidget(area)

    def render(self, record: Soul, users: Sequence[Tuple[str, str]]) -> None:
        clear_layout(self._column)

        header = hbox(22)

        art = framed_art(self._resolver, record.image, SOUL_ART, "soul")
        art.setFixedWidth(SOUL_ART + 18)
        header.addWidget(art, 0, QtCore.Qt.AlignTop)

        titles = vbox(6)
        titles.addWidget(label(record.display_name, theme.display(40), wrap=True))
        if record.secondary_name:
            titles.addWidget(
                label(record.secondary_name, theme.body(15, italic=True),
                      theme.TEXT_LABEL, wrap=True)
            )
        titles.addSpacing(6)
        titles.addWidget(flow([Badge(record.kind_label, theme.ACCENT, uppercase=True)]))
        titles.addStretch()
        header.addLayout(titles, 1)
        self._column.addLayout(header)

        self._column.addSpacing(24)
        self._column.addWidget(Divider())

        for effect in record.effects:
            self._column.addWidget(self._build_effect(effect))

        self._column.addSpacing(26)
        self._column.addWidget(section_label("Thức thần hay dùng"))
        self._column.addSpacing(12)
        if users:
            chips = []
            for name, record_id in users:
                chip = outlined_chip(name)
                chip.setCursor(QtCore.Qt.PointingHandCursor)
                chip.mousePressEvent = (  # type: ignore[assignment]
                    lambda _event, i=record_id: self.openShikigami.emit(i)
                )
                chips.append(chip)
            self._column.addWidget(flow(chips))
        else:
            self._column.addWidget(
                label("Chưa có dữ liệu", theme.body(13), theme.TEXT_FAINT)
            )
        self._column.addStretch()

    def _build_effect(self, effect) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        wrapper = QtWidgets.QVBoxLayout(holder)
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.setSpacing(0)

        row = hbox(18, margins=(0, 16, 0, 16))

        tier = label(
            effect.tier_label.upper(), theme.mono(12, tracking=0.14), theme.ACCENT
        )
        tier.setFixedWidth(96)
        row.addWidget(tier, 0, QtCore.Qt.AlignTop)
        row.addWidget(body_text(effect.description, 14.5, justify=True), 1)

        wrapper.addLayout(row)
        wrapper.addWidget(Divider())
        return holder
