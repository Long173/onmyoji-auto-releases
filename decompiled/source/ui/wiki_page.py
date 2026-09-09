"""The wiki, as a page inside the main window.

It used to be a window of its own with its own navigation column. Two sidebars
side by side wasted 460px on nothing but nav, so the three sections now live in
the app's one sidebar and this widget is just the search strip plus the content
stack. It reports its sections and counts upward through signals rather than
drawing its own nav.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

import app_settings
import theme
from ui import controls
from ui.background import Busy
from ui.primitives import Divider, hbox, label, section_label, vbox
from ui.wiki_detail import ShikigamiDetailView, SoulDetailView
from ui.wiki_views import (EffectsView, SearchResultsView, ShikigamiListView,
                           SoulListView)
from wiki import config as wiki_config
from wiki.config import AUTHOR_SETTING
from wiki import submissions
from wiki.config import SupabaseConfig, resolve
from wiki.images import ImageResolver, collect_image_fields, download_missing
from wiki.repository import WikiRepository
from wiki.supabase_client import SupabaseClient, SupabaseError

logger = logging.getLogger(__name__)

TAB_SHIKIGAMI = "shikigami"
TAB_SOULS = "souls"
TAB_EFFECTS = "effects"

SECTIONS: Tuple[Tuple[str, str], ...] = (
    (TAB_SHIKIGAMI, "Thức thần"),
    (TAB_SOULS, "Ngự hồn"),
    (TAB_EFFECTS, "Hiệu ứng"),
)

VIEW_SHIKI_LIST = 0
VIEW_SHIKI_DETAIL = 1
VIEW_SOUL_LIST = 2
VIEW_SOUL_DETAIL = 3
VIEW_EFFECTS = 4
VIEW_SEARCH = 5


class SyncWorker(QtCore.QThread):
    """Runs a Supabase pull, then back-fills missing images, off the UI thread."""

    progressed = QtCore.pyqtSignal(str)
    succeeded = QtCore.pyqtSignal()
    failed = QtCore.pyqtSignal(str)

    def __init__(
        self,
        repository: WikiRepository,
        config: SupabaseConfig,
        resolver: ImageResolver,
    ) -> None:
        super().__init__()
        self._repository = repository
        self._config = config
        self._resolver = resolver

    def run(self) -> None:
        try:
            dataset = self._repository.sync(self._config, self.progressed.emit)
            self._fetch_missing_images(dataset)
        except SupabaseError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - shown to the user
            logger.exception("Wiki sync crashed")
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit()

    def _fetch_missing_images(self, dataset) -> None:
        """Pull artwork the local checkout does not have.

        Only matters when the wiki data lives on the server rather than beside
        the app; with the Flutter checkout present there is nothing to fetch.
        A failure here is not worth failing the sync over.
        """
        fields = (
            collect_image_fields(dataset.shikigami)
            + collect_image_fields(dataset.souls)
            + collect_image_fields(dataset.effects)
        )
        missing = [f for f in fields if self._resolver.local_path(f) is None]
        if not missing:
            return
        self.progressed.emit("Đang tải %d ảnh…" % len(missing))
        try:
            written = download_missing(
                self._resolver, SupabaseClient(self._config), missing
            )
            logger.info("Downloaded %d of %d missing images", written, len(missing))
        except Exception:
            logger.warning("Image back-fill failed", exc_info=True)


class CredentialsDialog(QtWidgets.QDialog):
    """Collects the Supabase URL and anon key."""

    def __init__(self, config: SupabaseConfig,
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kết nối Supabase")
        self.setMinimumWidth(520)
        self.setStyleSheet("QDialog { background: %s; }" % theme.WINDOW)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        layout.addWidget(label("Kết nối Supabase", theme.display(24)))
        layout.addWidget(
            label(
                "Khoá anon chỉ có quyền đọc (RLS), an toàn để lưu trên máy.",
                theme.body(12.5),
                theme.TEXT_MUTED,
            )
        )
        layout.addSpacing(6)

        self.url = QtWidgets.QLineEdit(config.url)
        self.url.setPlaceholderText("https://xxxx.supabase.co")
        self.key = QtWidgets.QLineEdit(config.anon_key)
        self.key.setPlaceholderText("anon key")
        for field, caption in ((self.url, "Project URL"), (self.key, "Anon key")):
            field.setFont(theme.body(13))
            field.setMinimumHeight(34)
            field.setStyleSheet(
                "QLineEdit { background: %s; border: 1px solid %s;"
                " border-radius: %dpx; padding: 0 10px; color: %s; }"
                % (theme.INSET, theme.CONTROL, theme.RADIUS, theme.TEXT)
            )
            layout.addWidget(section_label(caption))
            layout.addWidget(field)

        buttons = hbox()
        buttons.addStretch()
        cancel = controls.OutlineButton("Huỷ")
        cancel.clicked.connect(self.reject)
        save = controls.OutlineButton("Lưu và đồng bộ", controls.ACCENT)
        save.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addSpacing(8)
        layout.addLayout(buttons)

    def config(self) -> SupabaseConfig:
        return SupabaseConfig(self.url.text().strip(), self.key.text().strip())


class WikiPage(QtWidgets.QWidget):
    """Browse shikigami, souls and status effects."""

    # Which section is on screen, so the app's sidebar can follow along. Empty
    # while a search is showing, because no section is then current.
    sectionChanged = QtCore.pyqtSignal(str)
    countsChanged = QtCore.pyqtSignal(dict)
    sourceChanged = QtCore.pyqtSignal(str)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._settings = app_settings.open_store(app_settings.WIKI_SCOPE)
        self._repository = WikiRepository()
        self._resolver = ImageResolver()
        self._sync_worker: Optional[SyncWorker] = None
        # Whether the running sync is one nobody asked for. It has to be
        # quieter than the button: no credentials prompt, and no complaint when
        # there is no connection — see sync_in_background.
        self._sync_is_automatic = False
        self._synced_automatically = False

        self._tab = TAB_SHIKIGAMI
        self._selected: Optional[str] = None
        self._query = ""
        # While a proposal is being written: the kind, and the live row it is
        # built on ({} for an addition). Both None/absent the rest of the time.
        self._edit_kind = ""
        self._edit_row: Optional[Dict[str, object]] = None
        self._busy = Busy(self)

        self._build()
        self._repository.load()
        # After the load, not inside _build: the mapping comes out of the
        # dataset, and at build time there is not one yet.
        self._shiki_detail.set_effect_names(self._effect_names())
        self._publish_counts()
        self._render()

    # ── layout ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        column = QtWidgets.QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        column.addWidget(self._build_search_bar())
        column.addWidget(Divider())

        self._stack = QtWidgets.QStackedWidget()
        self._shiki_list = ShikigamiListView(self._resolver)
        self._shiki_detail = ShikigamiDetailView(self._resolver)
        self._soul_list = SoulListView(self._resolver)
        self._soul_detail = SoulDetailView(self._resolver)
        self._effects = EffectsView(self._resolver)
        self._search = SearchResultsView()

        for view in (self._shiki_list, self._shiki_detail, self._soul_list,
                     self._soul_detail, self._effects, self._search):
            self._stack.addWidget(view)

        self._shiki_list.opened.connect(self._open_shikigami)
        self._shiki_list.filtersChanged.connect(self._render)
        self._shiki_detail.openSoul.connect(self._open_soul)
        self._shiki_detail.openShikigami.connect(self._open_shikigami)
        self._shiki_detail.saveRequested.connect(self._on_edit_saved)
        self._shiki_detail.cancelRequested.connect(self._on_edit_cancelled)
        self._soul_list.opened.connect(self._open_soul)
        self._soul_detail.openShikigami.connect(self._open_shikigami)
        self._search.opened.connect(self._open_result)

        column.addWidget(self._stack, 1)

    def _build_search_bar(self) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        holder.setObjectName("searchBar")
        holder.setStyleSheet("#searchBar { background: %s; }" % theme.BAR)
        row = QtWidgets.QHBoxLayout(holder)
        row.setContentsMargins(26, 14, 26, 14)
        row.setSpacing(14)

        self._search_field = controls.SearchField(
            "Tìm thức thần, ngự hồn, hiệu ứng… (tiếng Việt không dấu cũng được)"
        )
        self._search_field.textChanged.connect(self._on_search)
        row.addWidget(self._search_field, 1)

        self._back = controls.OutlineButton("←  Quay lại", controls.ACCENT, padding="9px 16px")
        self._back.clicked.connect(self._on_back)
        row.addWidget(self._back)

        # Where the data came from, and how to refresh it. This lived in the old
        # window's own footer; the page carries it now.
        source = vbox(1)
        self._source_label = label("", theme.mono(9.5, tracking=0.1), theme.SUCCESS)
        source.addWidget(
            label("NGUỒN DỮ LIỆU", theme.mono(9, tracking=0.2), theme.TEXT_FAINT)
        )
        source.addWidget(self._source_label)
        row.addLayout(source)

        # One button with a menu rather than four buttons. Add, edit, delete and
        # review are all the same errand — proposing or settling a change — and
        # four of them would have crowded out the search field they sit beside.
        self._contribute = controls.OutlineButton("Góp ý ▾", padding="9px 16px")
        self._contribute.clicked.connect(self._show_contribute_menu)
        row.addWidget(self._contribute)

        self._sync_button = controls.OutlineButton("Đồng bộ", padding="9px 16px")
        self._sync_button.clicked.connect(self._on_sync)
        row.addWidget(self._sync_button)

        # After addWidget: a parentless widget is a window of its own.
        self._back.setVisible(False)

        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+K"), self, self._search_field.focus)
        QtWidgets.QShortcut(QtGui.QKeySequence("Escape"), self, self._on_back)
        return holder

    # ── the app's sidebar drives this ───────────────────────────────────────

    def show_section(self, key: str) -> None:
        """Open one of :data:`SECTIONS`, clearing any search or open record."""
        if key not in dict(SECTIONS):
            return
        self._on_nav(key)

    @property
    def section(self) -> str:
        return self._tab

    def shutdown(self) -> None:
        """Let a running sync finish before the window goes away."""
        if self._sync_worker is not None and self._sync_worker.isRunning():
            self._sync_worker.wait(3000)

    # ── navigation ──────────────────────────────────────────────────────────

    def _may_leave_edit(self) -> bool:
        """Whether it is alright to navigate away from a proposal in progress.

        Every entry point below can reach it — the sidebar, the back button, a
        link inside a record. Without this they would silently do nothing,
        because :meth:`_render` refuses to repaint over the boxes; with it they
        ask once and then work normally.
        """
        if not self._edit_kind:
            return True
        if not self._confirm_discard():
            return False
        self._edit_kind = ""
        self._edit_row = None
        return True

    def _set_chrome_enabled(self, enabled: bool) -> None:
        """Search, sync and the contribute menu, while a proposal is open.

        Sync is the one that matters: it rebuilds the repository and re-renders,
        which would have thrown away whatever was typed.
        """
        self._search_field.setEnabled(enabled)
        self._sync_button.setEnabled(enabled)
        self._contribute.setEnabled(enabled)

    def _on_nav(self, key: str) -> None:
        if not self._may_leave_edit():
            return
        self._tab = key
        self._selected = None
        self._query = ""
        self._search_field.set_text("")
        self._render()

    def _on_search(self, text: str) -> None:
        self._query = text
        self._render()

    def _on_back(self) -> None:
        if not self._may_leave_edit():
            return
        if self._query:
            self._query = ""
            self._search_field.set_text("")
        else:
            self._selected = None
        self._render()

    def _open_shikigami(self, record_id: str) -> None:
        if not self._may_leave_edit():
            return
        self._tab = TAB_SHIKIGAMI
        self._selected = record_id
        self._clear_query()
        self._render()

    def _open_soul(self, record_id: str) -> None:
        if not self._may_leave_edit():
            return
        self._tab = TAB_SOULS
        self._selected = record_id
        self._clear_query()
        self._render()

    def _open_result(self, kind: str, record_id: str) -> None:
        if not self._may_leave_edit():
            return
        if kind == "shikigami":
            self._open_shikigami(record_id)
        elif kind == "soul":
            self._open_soul(record_id)
        else:
            self._tab = TAB_EFFECTS
            self._selected = None
            self._clear_query()
            self._render()

    def _clear_query(self) -> None:
        if not self._query:
            return
        self._query = ""
        self._search_field.input.blockSignals(True)
        self._search_field.set_text("")
        self._search_field.input.blockSignals(False)

    # ── rendering ───────────────────────────────────────────────────────────

    def _render(self) -> None:
        if self._edit_kind:
            # Nothing else may repaint the detail view while it holds somebody's
            # half-written proposal — a re-render would throw the boxes away.
            self._render_editor()
            return
        self._set_chrome_enabled(True)
        searching = bool(self._query.strip())
        self._back.setVisible(searching or self._selected is not None)
        # Empty while searching: results span every section, so highlighting one
        # in the sidebar would be a lie.
        self.sectionChanged.emit("" if searching else self._tab)

        if searching:
            results = self._repository.search_everything(self._query)
            self._search.render(self._query, results)
            self._stack.setCurrentIndex(VIEW_SEARCH)
            return

        if self._tab == TAB_SHIKIGAMI:
            self._render_shikigami()
        elif self._tab == TAB_SOULS:
            self._render_souls()
        else:
            self._effects.render(self._repository.effects())
            self._stack.setCurrentIndex(VIEW_EFFECTS)

    def _render_editor(self) -> None:
        self._set_chrome_enabled(False)
        self._back.setVisible(True)
        self.sectionChanged.emit(TAB_SHIKIGAMI)
        self._shiki_detail.edit(
            dict(self._edit_row or {}),
            adding=self._edit_kind == "add",
            author=str(self._settings.value(AUTHOR_SETTING, "") or ""),
        )
        self._stack.setCurrentIndex(VIEW_SHIKI_DETAIL)

    def _render_shikigami(self) -> None:
        if self._selected:
            record = self._repository.shikigami_by_id(self._selected)
            if record is not None:
                self._shiki_detail.render(
                    record,
                    self._recommended_souls(record),
                    self._counters(record),
                )
                self._stack.setCurrentIndex(VIEW_SHIKI_DETAIL)
                return
            self._selected = None

        self._shiki_list.render(
            self._repository.shikigami(rarity=self._shiki_list.rarity)
        )
        self._stack.setCurrentIndex(VIEW_SHIKI_LIST)

    def _render_souls(self) -> None:
        if self._selected:
            record = self._repository.soul_by_id(self._selected)
            if record is not None:
                users = [
                    (user.display_name, user.id)
                    for user in self._repository.shikigami_using(record)
                ]
                self._soul_detail.render(record, users)
                self._stack.setCurrentIndex(VIEW_SOUL_DETAIL)
                return
            self._selected = None

        self._soul_list.render(self._repository.souls())
        self._stack.setCurrentIndex(VIEW_SOUL_LIST)

    def _recommended_souls(self, record) -> List[Tuple[str, str, Optional[str]]]:
        rows: List[Tuple[str, str, Optional[str]]] = []
        for reference in record.recommended_souls:
            soul = self._repository.resolve_soul(reference)
            if soul is not None:
                rows.append((soul.display_name, soul.kind_label, soul.id))
            else:
                rows.append((reference, "", None))
        return rows

    def _counters(self, record) -> List[Tuple[str, Optional[str]]]:
        rows: List[Tuple[str, Optional[str]]] = []
        for reference in record.countered_by:
            other = self._repository.resolve_shikigami(reference)
            rows.append((other.display_name if other else reference,
                         other.id if other else None))
        return rows

    def _publish_counts(self) -> None:
        counts: Dict[str, int] = dict(self._repository.dataset.counts)
        self.countsChanged.emit(counts)
        described = self._repository.dataset.describe_source().upper()
        self._source_label.setText(described)
        self.sourceChanged.emit(described)

    # ── syncing ─────────────────────────────────────────────────────────────

    # ── proposing changes ───────────────────────────────────────────────────

    def _show_contribute_menu(self) -> None:
        """What can be proposed from where the user currently is.

        Edit and delete are offered only with a shikigami open, because they
        need something to point at. They are shown greyed rather than hidden so
        it is clear they exist and what to do to reach them.
        """
        from ui import wiki_edit
        from wiki import submissions

        record = self._open_record()
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: %s; border: 1px solid %s; padding: 5px;"
            " color: %s; } QMenu::item { padding: 7px 16px; border-radius: %dpx; }"
            " QMenu::item:selected { background: %s; color: %s; }"
            " QMenu::item:disabled { color: %s; }"
            % (theme.CARD, theme.BORDER, theme.TEXT_SECONDARY, theme.RADIUS_SMALL,
               theme.ACCENT_FILL, theme.TEXT, theme.TEXT_FAINT)
        )
        menu.setFont(theme.body(12.5))

        add = menu.addAction("Đề xuất thêm thức thần…")
        add.triggered.connect(lambda: self._propose(wiki_edit.ADD))

        name = record.display_name if record is not None else ""
        edit = menu.addAction(
            "Đề xuất sửa: %s…" % name if record is not None
            else "Đề xuất sửa… (mở một thức thần trước)")
        edit.setEnabled(record is not None)
        edit.triggered.connect(lambda: self._propose(wiki_edit.EDIT))

        remove = menu.addAction(
            "Đề xuất xoá: %s…" % name if record is not None
            else "Đề xuất xoá… (mở một thức thần trước)")
        remove.setEnabled(record is not None)
        remove.triggered.connect(lambda: self._propose(wiki_edit.DELETE))

        # Only where the key is. Everybody else never learns the option exists,
        # which is the point: the shipped app cannot reach the live table.
        key = wiki_config.load_service_key()
        if submissions.looks_like_service_key(key):
            menu.addSeparator()
            menu.addAction("Duyệt góp ý…").triggered.connect(self._open_review)

        menu.exec_(self._contribute.mapToGlobal(
            QtCore.QPoint(0, self._contribute.height() + 4)))

    def _effect_names(self) -> Dict[str, str]:
        """id -> Vietnamese name, for the tags on a skill."""
        return {effect.id: effect.display_name
                for effect in self._repository.effects()}

    def _open_record(self):
        """The shikigami currently on screen, if one is."""
        if self._tab != TAB_SHIKIGAMI or not self._selected or self._query.strip():
            return None
        return self._repository.shikigami_by_id(self._selected)

    def _propose(self, kind: str) -> None:
        """Start a proposal.

        Add and edit happen on the detail page itself — the layout there already
        shows every field they change, so a separate form would have been the
        same information twice, worse arranged. Delete has no fields, only a
        reason, so it stays a small confirm.
        """
        from ui import wiki_edit

        config = resolve(self._stored_config())
        if not config.is_configured:
            QtWidgets.QMessageBox.warning(
                self, "Chưa kết nối server",
                "Cần cấu hình Supabase trước khi gửi góp ý. Bấm Đồng bộ để nhập.",
            )
            return

        record = self._open_record()
        if kind == wiki_edit.DELETE:
            if record is not None:
                wiki_edit.propose(config, kind, self, target_id=record.id,
                                  target_name=record.display_name)
            return

        if kind == wiki_edit.ADD:
            self._enter_edit_mode("add", {})
            return
        if record is None:
            return

        # The live row, not the cached model: approval upserts the whole row, so
        # an edit built on a stale or lossy copy would revert what it never saw.
        # Re-enabled by _on_edit_row/_on_edit_row_failed, or by the next
        # non-editing render, whichever comes first.
        self._contribute.setEnabled(False)
        self._source_label.setText("ĐANG TẢI BẢN GHI…")
        target = record.id
        self._busy.run(
            lambda: submissions.fetch_live(config, target),
            lambda row: self._on_edit_row(target, row),
            self._on_edit_row_failed,
        )

    def _on_edit_row(self, target: str, row: object) -> None:
        self._contribute.setEnabled(True)
        self._publish_counts()
        self._selected = target
        self._enter_edit_mode("edit", dict(row) if isinstance(row, dict) else {})

    def _on_edit_row_failed(self, message: str) -> None:
        self._contribute.setEnabled(True)
        self._publish_counts()
        QtWidgets.QMessageBox.warning(
            self, "Không tải được bản ghi",
            "Không đọc được dữ liệu hiện tại nên chưa sửa được.\n\n%s" % message.strip(),
        )

    def _enter_edit_mode(self, kind: str, row: Dict[str, object]) -> None:
        self._edit_kind = kind
        self._edit_row = row
        self._query = ""
        self._search_field.set_text("")
        self._render()

    def _leave_edit_mode(self) -> None:
        self._edit_kind = ""
        self._edit_row = None
        self._render()

    def _on_edit_cancelled(self) -> None:
        if self._edit_kind and not self._confirm_discard():
            return
        self._leave_edit_mode()

    def _confirm_discard(self) -> bool:
        return QtWidgets.QMessageBox.question(
            self, "Bỏ góp ý?", "Bỏ những gì bạn vừa nhập?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        ) == QtWidgets.QMessageBox.Yes

    def _on_edit_saved(self) -> None:
        view = self._shiki_detail
        author = view.author()
        self._settings.setValue(AUTHOR_SETTING, author)
        payload = submissions.apply_edits(self._edit_row or {}, view.edit_values())
        # Skills are not a form field — they are a list of rows with their own
        # rows inside — so they come across separately. Overwriting rather than
        # merging: the editor was handed the whole list and is holding it.
        payload["skills"] = view.edit_skills()
        if self._edit_kind == "edit":
            # Never regenerated. The id decides which row an approval
            # overwrites; deriving a new one from an edited name would write a
            # second record and leave the first behind.
            payload["id"] = target = str((self._edit_row or {}).get("id") or "")
        else:
            target = self._new_id(payload, view)
            if not target:
                return
            payload["id"] = target
        try:
            proposal = submissions.build(
                self._edit_kind, payload, target_id=target, author=author,
                app_version=theme.APP_VERSION,
            )
        except submissions.SubmissionError as exc:
            view.set_status(str(exc), theme.ERROR)
            return

        config = resolve(self._stored_config())
        view.set_busy(True)
        view.set_status("Đang gửi…")
        self._busy.run(
            lambda: submissions.submit(config, proposal),
            self._on_edit_sent,
            self._on_edit_send_failed,
        )

    def _new_id(self, payload: Dict[str, object], view) -> str:
        """The id for a proposed addition, generated from its name.

        Refuses on a clash rather than suffixing. Approving an addition upserts
        on the id, so a second "Đại Thiên Cẩu" would overwrite the first — and a
        ``dai_thien_cau_2`` sitting beside it would be worse still: two records
        for one shikigami, and no way to tell which one anything links to.
        """
        # From the English name: that is what ids are standardised on, and
        # generating from the Vietnamese one would recreate the mixture that
        # migration 0011 cleaned up.
        generated = submissions.slugify(str(payload.get("name_en") or ""))
        if not generated:
            view.set_status(
                "Cần tên tiếng Anh (hoặc romaji) để sinh mã.", theme.ERROR)
            return ""
        existing = self._repository.shikigami_by_id(generated)
        if existing is not None:
            view.set_status(
                "Đã có thức thần với mã %s (%s). Hãy sửa bản đó thay vì thêm mới."
                % (generated, existing.display_name), theme.ERROR)
            return ""
        return generated

    def _on_edit_sent(self, _result: object) -> None:
        logger.info("Sent a %s proposal from the detail page", self._edit_kind)
        self._leave_edit_mode()
        QtWidgets.QMessageBox.information(
            self, "Đã gửi góp ý",
            "Góp ý đã lên server và đang chờ duyệt.\n"
            "Dữ liệu trong tool sẽ đổi sau khi được chấp nhận và bạn đồng bộ lại.",
        )

    def _on_edit_send_failed(self, message: str) -> None:
        view = self._shiki_detail
        view.set_busy(False)
        view.set_status("Gửi không được: %s" % message.strip(), theme.ERROR)

    def _open_review(self) -> None:
        from ui import wiki_review

        applied = wiki_review.review(
            resolve(self._stored_config()), wiki_config.load_service_key(), self)
        if applied and QtWidgets.QMessageBox.question(
            self, "Đồng bộ lại?",
            "Đã ghi vào database. Đồng bộ lại để thấy thay đổi trong tool?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        ) == QtWidgets.QMessageBox.Yes:
            self._on_sync()

    def _stored_config(self) -> SupabaseConfig:
        return SupabaseConfig(
            self._settings.value(wiki_config.URL_SETTING, "", type=str),
            self._settings.value(wiki_config.ANON_SETTING, "", type=str),
        )

    def sync_in_background(self) -> None:
        """Refresh from Supabase without being asked, once per session.

        Called when the tab is first opened, so somebody who never presses
        Đồng bộ still sees current data. Deliberately narrower than the button:

        * unconfigured means do nothing. The button may put a credentials
          dialog up because the user pressed it; a tab opening may not.
        * a failure is swallowed. No connection is the ordinary state of a
          laptop that has just woken up, and a warning box on every start
          would be worse than never syncing.

        Once, not per visit: the page is built the first time the tab is
        opened and kept, so every later visit would otherwise be another
        request per click.
        """
        if self._synced_automatically:
            return
        if self._sync_worker is not None and self._sync_worker.isRunning():
            return
        if not resolve(self._stored_config()).is_configured:
            return
        self._synced_automatically = True
        self._sync_is_automatic = True
        self._on_sync()

    def _on_sync(self) -> None:
        if self._sync_worker is not None and self._sync_worker.isRunning():
            return
        config = resolve(self._stored_config())
        if not config.is_configured:
            if self._sync_is_automatic:
                self._sync_is_automatic = False
                return
            dialog = CredentialsDialog(config, self)
            if dialog.exec_() != QtWidgets.QDialog.Accepted:
                return
            config = dialog.config()
            if not config.is_configured:
                QtWidgets.QMessageBox.warning(
                    self, "Thiếu thông tin", "Cần cả URL và anon key."
                )
                return
            self._settings.setValue("supabase_url", config.url)
            self._settings.setValue("supabase_anon_key", config.anon_key)

        self._sync_button.setEnabled(False)
        self._source_label.setText("ĐANG ĐỒNG BỘ…")
        self._sync_worker = SyncWorker(self._repository, config, self._resolver)
        self._sync_worker.progressed.connect(
            lambda text: self._source_label.setText(text.upper())
        )
        self._sync_worker.succeeded.connect(self._on_sync_done)
        self._sync_worker.failed.connect(self._on_sync_failed)
        self._sync_worker.start()

    def _on_sync_done(self) -> None:
        self._sync_is_automatic = False
        self._sync_button.setEnabled(True)
        self._resolver.clear()
        # And the cards built from the old rows, which would otherwise go on
        # showing pre-sync names, artwork and rarities.
        self._shiki_list.forget_cards()
        self._soul_list.forget_cards()
        self._effects.forget_cards()
        # A sync can bring new effects with it.
        self._shiki_detail.set_effect_names(self._effect_names())
        self._selected = None
        self._publish_counts()
        self._render()

    def _on_sync_failed(self, message: str) -> None:
        self._sync_button.setEnabled(True)
        self._publish_counts()
        if self._sync_is_automatic:
            self._sync_is_automatic = False
            logger.info("Background wiki sync did not complete: %s", message)
            return
        QtWidgets.QMessageBox.warning(self, "Không đồng bộ được", message)
