"""The owner's approval step.

Only reachable with a ``service_role`` key, which the owner pastes into the
settings page on their own machine and which is never part of a build. That is
not a preference: the released .exe has already been shown to give up every
string inside it in three lines, so a key shipped in one is a key published.

What this window can do is exactly what the queue needs and nothing more — list
what is waiting, show what it would change, apply it or refuse it. It cannot
edit a proposal. A reviewer who rewrites a submission before approving it is no
longer reviewing anything, and the person who submitted it would never know.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from PyQt5 import QtCore, QtWidgets

import theme
from ui import controls
from ui.background import Busy
from ui.primitives import Divider, body_text, hbox, label, section_label, vbox
from ui.wiki_detail import ShikigamiDetailView
from wiki.images import ImageResolver
from wiki.models import Shikigami
from wiki import submissions
from wiki.config import SupabaseConfig
from wiki.submissions import DELETE, EDIT, Submission

logger = logging.getLogger(__name__)


def _effect_names() -> Dict[str, str]:
    """Effect id -> Vietnamese name, from whatever dataset is on this machine."""
    try:
        from wiki.repository import WikiRepository

        return {effect.id: effect.display_name
                for effect in WikiRepository().load().effects}
    except Exception as exc:  # noqa: BLE001 - a nicety, never a blocker
        logger.debug("No effect names available: %s", exc)
        return {}


class ReviewDialog(QtWidgets.QDialog):
    """What users have proposed, and the two buttons that settle it."""

    # Something was approved, so whoever opened this can offer a re-sync.
    applied = QtCore.pyqtSignal()

    def __init__(self, config: SupabaseConfig, service_key: str,
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._config = config
        self._key = service_key
        self._busy = Busy(self)
        self._pending: List[Submission] = []
        self._approved_any = False
        # What the last batch reported, kept so a reload does not wipe it.
        self._summary = ""
        self._failed_any = False

        self.setWindowTitle("Duyệt góp ý")
        self.setMinimumSize(920, 600)
        self.setStyleSheet("QDialog { background: %s; }" % theme.WINDOW)
        self._build()
        self._reload()

    # ── layout ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        column = QtWidgets.QVBoxLayout(self)
        column.setContentsMargins(24, 22, 24, 20)
        column.setSpacing(10)

        head = hbox(12)
        heading = vbox(2)
        heading.addWidget(label("Duyệt góp ý", theme.display(23)))
        self._count = body_text("", 12.5, theme.TEXT_MUTED)
        heading.addWidget(self._count)
        head.addLayout(heading, 1)
        self._refresh = controls.OutlineButton("Tải lại")
        self._refresh.clicked.connect(self._reload)
        head.addWidget(self._refresh)
        column.addLayout(head)
        column.addWidget(Divider())

        body = hbox(16)
        body.addWidget(self._build_list(), 2)
        body.addWidget(self._build_detail(), 3)
        column.addLayout(body, 1)

        self._status = body_text("", 12, theme.TEXT_MUTED)
        self._status.setWordWrap(True)
        column.addWidget(self._status)

        buttons = hbox(8)
        self._note = QtWidgets.QLineEdit()
        self._note.setFont(theme.body(12.5))
        self._note.setMinimumHeight(32)
        self._note.setPlaceholderText("Ghi chú duyệt (không bắt buộc)")
        self._note.setStyleSheet(
            "QLineEdit { background: %s; border: 1px solid %s; border-radius: %dpx;"
            " padding: 0 9px; color: %s; }"
            % (theme.INSET, theme.CONTROL, theme.RADIUS, theme.TEXT)
        )
        buttons.addWidget(self._note, 1)
        self._reject = controls.OutlineButton("Từ chối", controls.DANGER)
        self._reject.clicked.connect(self._on_reject)
        self._approve = controls.OutlineButton("Chấp nhận", controls.ACCENT)
        self._approve.clicked.connect(self._on_approve)
        close = controls.OutlineButton("Đóng")
        close.clicked.connect(self.accept)
        for button in (self._reject, self._approve, close):
            buttons.addWidget(button)
        column.addLayout(buttons)

    def _build_list(self) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        block = vbox(6)
        block.addWidget(section_label("Đang chờ"))
        self._list = QtWidgets.QListWidget()
        self._list.setFont(theme.body(12.5))
        self._list.setStyleSheet(
            "QListWidget { background: %s; border: 1px solid %s; border-radius: %dpx;"
            " color: %s; padding: 4px; }"
            " QListWidget::item { padding: 7px 8px; border-radius: %dpx; }"
            " QListWidget::item:selected { background: %s; color: %s; }"
            % (theme.INSET, theme.BORDER, theme.RADIUS, theme.TEXT_SECONDARY,
               theme.RADIUS_SMALL, theme.ACCENT_FILL, theme.TEXT)
        )
        # Several at a time, because one confirmation per row is enough
        # friction that people stop reading them — which costs more review than
        # it buys. Choosing the rows is still a deliberate act; there is no
        # "approve everything" button.
        self._list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._list.currentRowChanged.connect(self._show_selected)
        self._list.itemSelectionChanged.connect(self._selection_changed)
        block.addWidget(self._list, 1)
        holder.setLayout(block)
        return holder

    def _build_detail(self) -> QtWidgets.QWidget:
        """The proposal as the page it would become.

        It was a JSON dump. That shows the shape of the data and hides the thing
        being decided: whether the text is right. A reviewer reading
        ``"levels": [{"level": 2, ...}]`` is doing the parser's job.

        So the same view the wiki uses renders it, and the raw form stays behind
        a toggle — some columns have no place on the page (`image`,
        `source_url`, `sort_index`, and a skill's `cost` and `alt_forms`), and
        approving a change means being able to see all of it.
        """
        holder = QtWidgets.QWidget()
        block = vbox(6)

        head = hbox(10)
        head.addWidget(section_label("Nội dung đề xuất"))
        head.addStretch()
        self._as_json = controls.OutlineButton("Xem JSON", padding="5px 12px")
        self._as_json.setCheckable(True)
        self._as_json.toggled.connect(self._on_view_toggled)
        head.addWidget(self._as_json)
        block.addLayout(head)

        # What is about to happen, in words, above whichever view is showing.
        self._banner = body_text("", 12.5, theme.TEXT_SECONDARY)
        self._banner.setWordWrap(True)
        block.addWidget(self._banner)

        self._views = QtWidgets.QStackedWidget()
        self._views.setStyleSheet(
            "QStackedWidget { background: %s; border: 1px solid %s;"
            " border-radius: %dpx; }" % (theme.WINDOW, theme.BORDER, theme.RADIUS))

        self._rendered = ShikigamiDetailView(ImageResolver())
        # Read off the local dataset, not the network: this is the window where
        # somebody has to understand a skill well enough to approve it, and
        # `scorching_fire` is not something to ask them to decode.
        self._rendered.set_effect_names(_effect_names())
        self._views.addWidget(self._rendered)

        self._detail = QtWidgets.QPlainTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setFont(theme.mono(11, tracking=0.0))
        self._detail.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self._detail.setStyleSheet(
            "QPlainTextEdit { background: %s; border: none; padding: 8px;"
            " color: %s; }" % (theme.INSET, theme.TEXT_BODY))
        self._views.addWidget(self._detail)

        block.addWidget(self._views, 1)
        holder.setLayout(block)
        return holder

    def _on_view_toggled(self, as_json: bool) -> None:
        self._views.setCurrentIndex(1 if as_json else 0)
        self._as_json.setText("Xem trang" if as_json else "Xem JSON")

    # ── the queue ───────────────────────────────────────────────────────────

    def _reload(self) -> None:
        self._set_enabled(False)
        self._status.setText("Đang tải danh sách…")
        config, key = self._config, self._key
        self._busy.run(
            lambda: submissions.pending(config, key),
            self._on_loaded,
            self._on_failed,
        )

    def _on_loaded(self, rows: Any) -> None:
        self._pending = list(rows or [])
        self._list.clear()
        for row in self._pending:
            when = row.when
            who = row.author or "ẩn danh"
            self._list.addItem("%s\n%s · %s" % (row.describes, who, when))
        self._count.setText(
            "%d góp ý đang chờ." % len(self._pending) if self._pending
            else "Không có góp ý nào đang chờ."
        )
        self._show_summary()
        self._set_enabled(True)
        if self._pending:
            self._list.setCurrentRow(0)
        else:
            self._detail.setPlainText("")
            self._show_selected(-1)

    def _show_summary(self) -> None:
        """Whatever the last batch reported, or nothing if there was none."""
        self._status.setText(self._summary)
        self._status.setStyleSheet(
            "color: %s;" % (theme.ERROR if self._failed_any else theme.TEXT_MUTED))

    def _on_failed(self, message: str) -> None:
        self._status.setText("Lỗi: %s" % message.strip())
        self._set_enabled(True)
        self._approve.setEnabled(False)
        self._reject.setEnabled(False)

    def _selected(self) -> Optional[Submission]:
        """The one being shown on the right."""
        row = self._list.currentRow()
        if 0 <= row < len(self._pending):
            return self._pending[row]
        return None

    def _chosen(self) -> List[Submission]:
        """Every proposal the buttons will act on, in the order they are listed.

        In list order rather than selection order: approving writes to the live
        table, and two proposals for the same record must land in the order they
        were submitted or the older one wins.
        """
        rows = sorted(index.row() for index in self._list.selectedIndexes())
        return [self._pending[row] for row in rows if 0 <= row < len(self._pending)]

    def _selection_changed(self) -> None:
        chosen = self._chosen()
        self._approve.setEnabled(bool(chosen))
        self._reject.setEnabled(bool(chosen))
        suffix = "" if len(chosen) < 2 else " (%d)" % len(chosen)
        self._approve.setText("Chấp nhận" + suffix)
        self._reject.setText("Từ chối" + suffix)

    def _show_selected(self, _row: int) -> None:
        chosen = self._selected()
        has = chosen is not None
        self._approve.setEnabled(has)
        self._reject.setEnabled(has)
        if chosen is None:
            self._detail.setPlainText("")
            self._banner.setText("")
            self._rendered.render(Shikigami.from_row({"id": "", "rarity": "N"}), (), ())
            return
        self._banner.setText(self._headline(chosen))
        self._detail.setPlainText(self._describe(chosen))
        self._render_payload(chosen)

    def _render_payload(self, chosen: Submission) -> None:
        """Draw the proposal with the wiki's own detail view.

        For a deletion there is nothing proposed to draw, so what is drawn is
        the record that would go — which is the thing actually being decided.
        It is fetched with the anon key, off the UI thread, and a failure leaves
        the JSON view to explain itself rather than blocking the decision.
        """
        if chosen.kind == DELETE:
            self._rendered.render(
                Shikigami.from_row({"id": chosen.target_id, "rarity": "N"}), (), ())
            config, target = self._config, chosen.target_id
            self._busy.run(
                lambda: submissions.fetch_live(config, target),
                lambda row: self._draw(row if isinstance(row, dict) else {}),
                lambda message: None,
            )
            return
        self._draw(dict(chosen.payload or {}))

    def _draw(self, row: Dict[str, Any]) -> None:
        record = Shikigami.from_row(row or {"id": "", "rarity": "N"})
        # The ids as they stand, rather than resolved names: this window has no
        # dataset to resolve them against, and an id a reviewer can read is
        # better than a blank.
        recommended = [(str(sid), "", None)
                       for sid in (row.get("recommended_souls") or [])]
        counters = [(str(cid), None) for cid in (row.get("countered_by") or [])]
        self._rendered.render(record, recommended, counters)

    @staticmethod
    def _headline(chosen: Submission) -> str:
        """One sentence saying what approving this does."""
        who = chosen.author or "ẩn danh"
        when = chosen.when
        if chosen.kind == DELETE:
            reason = str((chosen.payload or {}).get("reason") or "").strip()
            return ("SẼ XOÁ bản ghi %s — %s, %s.%s"
                    % (chosen.target_id, who, when,
                       ("\nLý do: " + reason) if reason else ""))
        if chosen.kind == EDIT:
            return ("SẼ GHI ĐÈ toàn bộ bản ghi %s bằng nội dung dưới đây — %s, %s."
                    % (chosen.target_id, who, when))
        return ("SẼ THÊM bản ghi mới (ghi đè nếu mã đã có) — %s, %s."
                % (who, when))

    @staticmethod
    def _describe(chosen: Submission) -> str:
        head = [
            "loại      : %s" % chosen.kind,
            "id đích   : %s" % (chosen.target_id or "(mới)"),
            "người gửi : %s" % (chosen.author or "ẩn danh"),
            "phiên bản : %s" % (chosen.app_version or "?"),
            "lúc       : %s" % chosen.when,
            "",
        ]
        if chosen.kind == DELETE:
            head.append("Sẽ XOÁ bản ghi %r khỏi bảng shikigami." % chosen.target_id)
            reason = (chosen.payload or {}).get("reason")
            if reason:
                head += ["", "Lý do:", str(reason)]
            return "\n".join(head)
        if chosen.kind == EDIT:
            head.append("Sẽ GHI ĐÈ toàn bộ bản ghi %r bằng nội dung dưới đây."
                        % chosen.target_id)
        else:
            head.append("Sẽ THÊM bản ghi mới (hoặc ghi đè nếu mã đã có).")
        head.append("")
        head.append(json.dumps(chosen.payload, ensure_ascii=False, indent=2,
                               sort_keys=True))
        return "\n".join(head)

    # ── deciding ────────────────────────────────────────────────────────────

    def _on_approve(self) -> None:
        chosen = self._chosen()
        if not chosen:
            return
        warning = ("Ghi vào bảng shikigami và đánh dấu đã duyệt:\n\n%s\n\n"
                   "Không hoàn tác được. Tiếp tục?" % self._listing(chosen))
        if not self._confirm("Chấp nhận %d góp ý" % len(chosen)
                             if len(chosen) > 1 else "Chấp nhận góp ý", warning):
            return
        config, key, note = self._config, self._key, self._note.text().strip()
        self._act(lambda: submissions.apply_many(config, key, chosen, note),
                  approved=True)

    def _on_reject(self) -> None:
        chosen = self._chosen()
        if not chosen:
            return
        config, key, note = self._config, self._key, self._note.text().strip()
        self._act(lambda: submissions.reject_many(config, key, chosen, note))

    @staticmethod
    def _listing(chosen: List[Submission]) -> str:
        """What is about to happen, spelled out.

        Every one of them, up to a point: a confirmation that says "12 góp ý"
        and nothing else is a confirmation nobody can check.
        """
        shown = [row.describes for row in chosen[:10]]
        if len(chosen) > 10:
            shown.append("… và %d góp ý nữa" % (len(chosen) - 10))
        return "\n".join(shown)

    def _act(self, call, approved: bool = False) -> None:
        self._set_enabled(False)
        self._status.setText("Đang xử lý…")

        def finished(result: Any) -> None:
            if approved and getattr(result, "applied", None):
                self._approved_any = True
                self.applied.emit()
            self._note.clear()
            # Both halves, and the failures in colour: a batch that reports only
            # what worked leaves nobody able to say which rows are still waiting.
            # Held rather than only shown: the reload below finishes by
            # clearing the status line, and the first version of this had the
            # summary — including which rows failed — wiped a fraction of a
            # second after it appeared.
            self._summary = getattr(result, "summary", "Đã xử lý.")
            self._failed_any = bool(getattr(result, "failures", None))
            # Not shown here: the reload below ends in `_on_loaded`, which shows
            # it. Showing it twice was dead code — removing this line changed
            # nothing any test could see, which is how it was found.
            # Reload rather than drop the row locally: the queue is the truth,
            # and a list edited by hand would disagree with it the moment two
            # things were reviewed from two places.
            self._reload()

        self._busy.run(call, finished, self._on_failed)

    def _confirm(self, title: str, message: str) -> bool:
        answer = QtWidgets.QMessageBox.question(
            self, title, message,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return answer == QtWidgets.QMessageBox.Yes

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (self._refresh, self._list, self._approve, self._reject,
                       self._note):
            widget.setEnabled(enabled)

    @property
    def approved_anything(self) -> bool:
        return self._approved_any

    def closeEvent(self, event) -> None:
        self._busy.wait()
        super().closeEvent(event)


def review(config: SupabaseConfig, service_key: str,
           parent: QtWidgets.QWidget) -> bool:
    """Open the review window. Returns whether anything was approved."""
    if not config.is_configured:
        QtWidgets.QMessageBox.warning(
            parent, "Chưa kết nối server", "Cần cấu hình Supabase trước.")
        return False
    if not submissions.looks_like_service_key(service_key):
        QtWidgets.QMessageBox.warning(
            parent, "Khoá không đúng",
            "Khoá đã lưu không phải service_role key. Dán lại trong Cài đặt chung.",
        )
        return False
    dialog = ReviewDialog(config, service_key, parent)
    dialog.exec_()
    return dialog.approved_anything
