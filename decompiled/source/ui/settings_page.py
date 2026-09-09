"""Settings that belong to the app rather than to any one task.

A page in the main window, not a dialog. It began as a modal, and outgrew it: by
the time it carried four switches with an explanation under each, the version
block, the contact details and the release link, it was a tall modal box in front
of a window with plenty of room in it.

Making it a page fixed a second thing that had been quietly inconsistent. A
task's own settings apply the moment they are changed; this one alone had an OK
button, so the same kind of control behaved differently depending on which
screen it was on. There is no OK button here — a change is applied as it is made,
like everywhere else in the app.

The form is generated from ``tasks.APP_FIELDS`` by the same code that builds a
task's config panel, so adding an app-wide setting means declaring a field and
nothing else.

What belongs here is anything true whichever task is running — the reply to a
co-op Wanted Quest invite, for instance: that dialog covers the window and
blocks every task until it is answered.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from PyQt5 import QtCore, QtWidgets

import contact
import paths
import tasks
import theme
import updater
from ui import controls
from ui.fields import FieldForm
from ui.primitives import Divider, body_text, hbox, label, section_label, vbox


class SettingsPage(QtWidgets.QWidget):
    """The app-wide switches, and what this build is."""

    # key, value — emitted as each control is changed, not on the way out.
    changed = QtCore.pyqtSignal(str, object)

    def __init__(self, values: Dict[str, Any],
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._values: Dict[str, Any] = tasks.coerce_app(values)

        # Scrolled, and inset the same 30 px a task page uses. Rendered on its
        # own this content stands about 895 px tall, which is more than the
        # window's content area on a laptop — unscrolled, the version, contact
        # and licence blocks at the bottom simply were not reachable.
        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        holder = QtWidgets.QWidget()
        column = vbox(0, margins=(30, 24, 30, 30))
        column.addWidget(section_label("Áp dụng cho mọi tác vụ"))
        column.addSpacing(16)

        self._form = FieldForm(
            tasks.APP_FIELDS, self._values, notes=tasks.APP_FIELD_NOTES, spacing=20
        )
        self._form.changed.connect(self._on_changed)
        column.addWidget(self._form)

        column.addSpacing(16)
        column.addWidget(Divider())
        column.addSpacing(14)
        column.addWidget(self._build_about())

        # Only when there is something to show — an unfilled build says nothing
        # rather than showing an empty heading.
        for block in (self._build_folders(), self._build_review(),
                      self._build_contact(), self._build_links()):
            if block is None:
                continue
            column.addSpacing(16)
            column.addWidget(Divider())
            column.addSpacing(14)
            column.addWidget(block)

        column.addStretch()
        holder.setLayout(column)
        scroll.setWidget(holder)

        outer = vbox(0)
        outer.addWidget(scroll)
        self.setLayout(outer)

    def show_values(self, values: Dict[str, Any]) -> None:
        """Redraw the controls from the given values.

        Called each time the page is opened. One of these settings — starting
        with Windows — lives in the registry rather than in the app's own store,
        and can be turned off from Task Manager while the app is running, so the
        page has to be able to catch up rather than show what it was built with.
        """
        self._values = tasks.coerce_app(values)
        self._form.show_values(self._values)

    def _on_changed(self, key: str, value: Any) -> None:
        self._values[key] = value
        self.changed.emit(key, value)

    def values(self) -> Dict[str, Any]:
        return dict(self._values)

    def _build_folders(self) -> QtWidgets.QWidget:
        """Where the app puts the things it saves, as links that open them.

        The reliable half of "let me see the folder". A click on the notification
        that appears when a recording ends does the same thing, but Windows makes
        no promise about delivering that click, so there has to be somewhere it
        can always be found.
        """
        import recorder
        from ui import snapshot_dialog

        holder = QtWidgets.QWidget()
        block = vbox(6)
        block.addWidget(section_label("Thư mục"))
        block.addWidget(body_text(
            "Nơi app lưu ảnh chụp và video. Bấm để mở.", 12.5, theme.TEXT_LABEL))
        block.addSpacing(4)
        for name, folder in (("Video", recorder.recording_dir()),
                             ("Ảnh chụp", snapshot_dialog.snapshot_dir())):
            row = hbox(10)
            tag = label(name, theme.mono(11, tracking=0.06), theme.TEXT_FAINT)
            tag.setFixedWidth(84)
            row.addWidget(tag)
            link = label("", theme.tabular(12), theme.TEXT_SECONDARY)
            url = QtCore.QUrl.fromLocalFile(str(folder)).toString()
            link.setText('<a href="%s" style="color: %s; text-decoration: none;">%s</a>'
                         % (url, theme.ACCENT, folder))
            link.setContentsMargins(0, 0, 0, 0)
            link.setIndent(0)
            link.setOpenExternalLinks(True)
            link.setTextInteractionFlags(
                QtCore.Qt.TextBrowserInteraction | QtCore.Qt.TextSelectableByMouse
            )
            link.setCursor(QtCore.Qt.PointingHandCursor)
            row.addWidget(link)
            row.addStretch()
            block.addLayout(row)
        holder.setLayout(block)
        return holder

    def _build_review(self) -> QtWidgets.QWidget:
        """The service_role key, for whoever owns the wiki database.

        Empty for everybody else, and that is the whole design: users propose
        changes, and only a machine holding this key can apply one. The key is
        never part of a build — a released .exe gives up every string in it — so
        the only way it gets here is somebody typing it in.
        """
        from wiki import config as wiki_config
        from wiki import submissions

        holder = QtWidgets.QWidget()
        block = vbox(6)
        block.addWidget(section_label("Duyệt góp ý wiki"))
        block.addWidget(body_text(
            "Chỉ dành cho người quản lý dữ liệu. Dán service_role key để mở "
            "mục duyệt trong trang Bách khoa. Khoá chỉ nằm trên máy này.",
            12.5, theme.TEXT_LABEL))
        block.addSpacing(4)

        row = hbox(8)
        field = QtWidgets.QLineEdit(wiki_config.load_service_key())
        field.setFont(theme.body(12.5))
        field.setMinimumHeight(32)
        field.setEchoMode(QtWidgets.QLineEdit.Password)
        field.setPlaceholderText("service_role key (để trống nếu bạn là người dùng)")
        field.setStyleSheet(
            "QLineEdit { background: %s; border: 1px solid %s; border-radius: %dpx;"
            " padding: 0 9px; color: %s; }"
            % (theme.INSET, theme.CONTROL, theme.RADIUS, theme.TEXT)
        )
        row.addWidget(field, 1)

        # Openable from here, not only from the wiki page. This is where the key
        # is pasted, so it is where somebody who has just pasted one looks for
        # what it unlocked — and until it is pasted the wiki page shows nothing
        # at all, by design.
        open_review = controls.OutlineButton("Mở mục duyệt", controls.ACCENT)
        open_review.clicked.connect(self._open_review)
        row.addWidget(open_review)
        block.addLayout(row)

        note = body_text("", 12, theme.TEXT_MUTED)
        note.setWordWrap(True)
        block.addWidget(note)

        def describe() -> None:
            typed = field.text().strip()
            open_review.setEnabled(submissions.looks_like_service_key(typed))
            if not typed:
                note.setText("Chưa có khoá — mục duyệt sẽ bị ẩn.")
                note.setStyleSheet("color: %s;" % theme.TEXT_MUTED)
            elif submissions.looks_like_service_key(typed):
                note.setText("Đã nhận khoá service_role. Mở lại trang Bách khoa để thấy mục duyệt.")
                note.setStyleSheet("color: %s;" % theme.SUCCESS)
            else:
                # Told apart locally because the alternative is a permission
                # error from the server that reads like a bug in the app.
                note.setText("Khoá này không phải service_role (có thể bạn dán anon key).")
                note.setStyleSheet("color: %s;" % theme.ERROR)

        def store() -> None:
            wiki_config.save_service_key(field.text())
            describe()

        field.editingFinished.connect(store)
        describe()
        self._review_key_field = field
        holder.setLayout(block)
        return holder

    def _open_review(self) -> None:
        """Open the approval window with the key stored on this machine."""
        from ui import wiki_review
        from wiki import config as wiki_config

        wiki_review.review(wiki_config.load_config(),
                           wiki_config.load_service_key(), self)

    def _build_about(self) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        block = vbox(6)
        block.addWidget(section_label("Phiên bản"))
        block.addWidget(
            label("%s %s" % (theme.APP_NAME, theme.APP_VERSION),
                  theme.tabular(13), theme.TEXT_SECONDARY)
        )
        where = (
            "Tự kiểm tra bản mới lúc khởi động."
            if updater.can_update()
            else "Chạy từ mã nguồn — không kiểm tra cập nhật."
        )
        block.addWidget(body_text(where, 12.5, theme.TEXT_LABEL))
        block.addWidget(
            label("Dữ liệu: %s" % paths.DATA_ROOT, theme.mono(9.5, tracking=0.04),
                  theme.TEXT_FAINT)
        )
        holder.setLayout(block)
        return holder

    def _build_links(self) -> Optional[QtWidgets.QWidget]:
        """The public releases page, when this build knows where it is.

        The address comes from :mod:`updater`, which already holds the account
        and repository names because it needs them to find updates. Writing the
        URL out again here would let the two drift, and a link pointing
        somewhere the updater does not is worse than no link.

        Absent — a build with no account filled in — the section is left out
        entirely rather than showing a dead row, the same rule the contact block
        follows.
        """
        if not updater.REPO_URL:
            return None

        holder = QtWidgets.QWidget()
        block = vbox(6)
        block.addWidget(section_label("Trang phát hành"))
        block.addWidget(body_text(
            "%s Bản mới, ghi chú thay đổi và các bản cũ đều ở đây:"
            % contact.FREE_NOTICE,
            12.5, theme.TEXT_LABEL,
        ))
        link = label("", theme.tabular(12.5), theme.TEXT_SECONDARY)
        link.setText('<a href="%s" style="color: %s; text-decoration: none;">%s</a>'
                     % (updater.REPO_URL, theme.ACCENT, updater.REPO_URL))
        # Rich text arrives with a block element's own spacing, which left this
        # row sitting noticeably lower than the tight rows above it.
        link.setContentsMargins(0, 0, 0, 0)
        link.setIndent(0)
        link.setOpenExternalLinks(True)
        # Selectable as well as clickable: a link is no use to somebody reading
        # the app over a screen share, or with no browser on the machine.
        link.setTextInteractionFlags(
            QtCore.Qt.TextBrowserInteraction | QtCore.Qt.TextSelectableByMouse
        )
        link.setCursor(QtCore.Qt.PointingHandCursor)
        block.addWidget(link)
        block.addSpacing(2)
        block.addWidget(label("Giấy phép: %s" % contact.LICENCE_NAME,
                              theme.mono(9.5, tracking=0.04), theme.TEXT_FAINT))
        holder.setLayout(block)
        return holder

    def _build_contact(self) -> Optional[QtWidgets.QWidget]:
        """Who to reach, or nothing at all when none is configured."""
        rows = contact.rows()
        if not rows:
            return None

        holder = QtWidgets.QWidget()
        block = vbox(6)
        block.addWidget(section_label("Liên hệ"))
        block.addWidget(body_text(contact.INTRO, 12.5, theme.TEXT_LABEL))
        block.addSpacing(4)

        # The labels share a column so the values line up under each other.
        width = max(
            QtWidgets.QLabel(name).fontMetrics().width(name) for name, _ in rows
        ) + 24

        for name, value in rows:
            row = hbox(10)
            name_label = label(name, theme.mono(11, tracking=0.06), theme.TEXT_FAINT)
            name_label.setFixedWidth(width)
            row.addWidget(name_label)
            value_label = label(value, theme.tabular(13), theme.TEXT_SECONDARY)
            # Selectable so it can be copied out — a phone number nobody can
            # copy is barely a contact detail.
            value_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            value_label.setCursor(QtCore.Qt.IBeamCursor)
            row.addWidget(value_label)
            row.addStretch()
            block.addLayout(row)

        holder.setLayout(block)
        return holder
