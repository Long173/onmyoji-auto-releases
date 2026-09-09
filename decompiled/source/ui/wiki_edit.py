"""Proposing that a wiki record be deleted.

Adding and editing happen on the detail page itself — see
:meth:`ui.wiki_detail.ShikigamiDetailView.edit`. That page already lays out every
field those two change, so a separate form was the same information twice, worse
arranged.

A deletion has no fields. It has a target and a reason, and it is the one
proposal worth stopping to think about, so it stays a small dialog that asks for
both. Nothing here writes to the live table: the app carries the anon key, which
the database allows to insert a *proposal* and nothing else, and only the owner's
approval copies one across. :mod:`wiki.submissions` has the why.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from PyQt5 import QtWidgets

import app_settings
import theme
from ui import controls
from ui.background import Busy
from ui.primitives import body_text, hbox, label, section_label, vbox
from wiki import submissions
from wiki.config import AUTHOR_SETTING, SupabaseConfig
from wiki.submissions import ADD, DELETE, EDIT, SubmissionError

logger = logging.getLogger(__name__)

BLURB = (
    "Góp ý được gửi lên server và chờ chủ tool duyệt. Dữ liệu đang dùng không "
    "thay đổi ngay."
)


def _input_css() -> str:
    return (
        "background: %s; border: 1px solid %s; border-radius: %dpx;"
        " padding: 5px 9px; color: %s;"
        % (theme.INSET, theme.CONTROL, theme.RADIUS, theme.TEXT)
    )


class DeleteProposalDialog(QtWidgets.QDialog):
    """Asks which record, and why."""

    def __init__(self, config: SupabaseConfig, target_id: str,
                 target_name: str = "",
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._config = config
        self._target_id = target_id
        self._target_name = target_name or target_id
        self._store = app_settings.open_store(app_settings.WIKI_SCOPE)
        self._busy = Busy(self)

        self.setWindowTitle("Đề xuất xoá thức thần")
        self.setMinimumSize(560, 340)
        self.setStyleSheet("QDialog { background: %s; }" % theme.WINDOW)
        self._build()

    def _build(self) -> None:
        column = QtWidgets.QVBoxLayout(self)
        column.setContentsMargins(24, 22, 24, 20)
        column.setSpacing(10)

        column.addWidget(label("Đề xuất xoá thức thần", theme.display(23)))
        column.addWidget(body_text(BLURB, 12.5, theme.TEXT_MUTED))
        column.addWidget(body_text("Thức thần: %s" % self._target_name, 12.5,
                                   theme.TEXT_SECONDARY))
        column.addSpacing(4)

        column.addWidget(section_label("Lý do xoá"))
        self._reason = QtWidgets.QPlainTextEdit()
        self._reason.setFont(theme.body(12.5))
        self._reason.setStyleSheet("QPlainTextEdit { %s }" % _input_css())
        self._reason.setPlaceholderText("Vì sao nên xoá bản ghi này?")
        self._reason.setFixedHeight(90)
        column.addWidget(self._reason, 1)

        column.addWidget(section_label("Tên bạn (không bắt buộc)"))
        self._author = QtWidgets.QLineEdit(
            str(self._store.value(AUTHOR_SETTING, "") or ""))
        self._author.setFont(theme.body(12.5))
        self._author.setMinimumHeight(32)
        self._author.setStyleSheet("QLineEdit { %s }" % _input_css())
        self._author.setPlaceholderText("Để chủ tool biết ai góp ý")
        column.addWidget(self._author)

        self._status = body_text("", 12, theme.TEXT_MUTED)
        self._status.setWordWrap(True)
        column.addSpacing(6)
        column.addWidget(self._status)

        buttons = hbox(8)
        buttons.addStretch()
        cancel = controls.OutlineButton("Huỷ")
        cancel.clicked.connect(self.reject)
        self._send = controls.OutlineButton("Gửi góp ý", controls.DANGER)
        self._send.clicked.connect(self._on_send)
        buttons.addWidget(cancel)
        buttons.addWidget(self._send)
        column.addLayout(buttons)

    def _on_send(self) -> None:
        author = self._author.text().strip()
        self._store.setValue(AUTHOR_SETTING, author)
        reason = self._reason.toPlainText().strip()
        if not reason:
            self._status.setText("Hãy nói rõ vì sao nên xoá.")
            return
        try:
            # The reason travels in the payload, which the reviewer sees and
            # which approval ignores for a delete. Appending it to `author`
            # would have been shorter and would have truncated it at 80
            # characters, losing the half that explains anything.
            proposal = submissions.build(
                DELETE, {"reason": reason}, target_id=self._target_id,
                author=author, app_version=theme.APP_VERSION,
            )
        except SubmissionError as exc:
            self._status.setText(str(exc))
            return

        self._set_enabled(False)
        self._status.setText("Đang gửi…")
        config = self._config
        self._busy.run(lambda: submissions.submit(config, proposal),
                       self._on_sent, self._on_failed)

    def _on_sent(self, _result: Any) -> None:
        logger.info("Sent a delete proposal for %r", self._target_id)
        QtWidgets.QMessageBox.information(
            self, "Đã gửi góp ý",
            "Góp ý đã lên server và đang chờ duyệt.",
        )
        self.accept()

    def _on_failed(self, message: str) -> None:
        self._status.setText("Gửi không được: %s" % message.strip())
        self._set_enabled(True)

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (self._send, self._reason, self._author):
            widget.setEnabled(enabled)

    def closeEvent(self, event) -> None:
        self._busy.wait()
        super().closeEvent(event)


def propose(config: SupabaseConfig, kind: str, parent: QtWidgets.QWidget,
            target_id: str = "", target_name: str = "",
            on_sent: Optional[Callable[[], None]] = None) -> None:
    """Open the deletion dialog.

    ``kind`` is still in the signature, and still checked, because the caller
    routes all three kinds and a wrong turn here would otherwise open a delete
    dialog for an edit.
    """
    if kind != DELETE:
        raise ValueError(
            "thêm/sửa được làm ngay trên trang chi tiết, không phải ở đây: %r" % kind)
    if not config.is_configured:
        QtWidgets.QMessageBox.warning(
            parent, "Chưa kết nối server",
            "Cần cấu hình Supabase trước khi gửi góp ý. Bấm Đồng bộ để nhập.",
        )
        return
    if not target_id:
        return
    dialog = DeleteProposalDialog(config, target_id, target_name, parent)
    if dialog.exec_() == QtWidgets.QDialog.Accepted and on_sent is not None:
        on_sent()
