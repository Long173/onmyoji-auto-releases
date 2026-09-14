"""The task centre: a sidebar of automations, an overview, and a page per task.

This file owns the shell and the wiring only. What the app can automate lives
in :mod:`tasks`; each page builds itself from that registry.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

import app_settings
import autostart
import paths
import recorder
import game_control
import tasks
import theme
import updater
from auto.manager import SessionManager
from auto.session import GameSession
import hotkeys
from ui import app_icon, notifications, preview, snapshot_dialog
from ui.chrome import FramelessWindow
from ui.home_view import HomeView
from ui.page_header import PageHeader
from ui.primitives import Divider, hbox, vbox
from ui.settings_page import SettingsPage
from ui.task_sidebar import (HOME, SETTINGS, TaskSidebar, wiki_key,
                            wiki_section_of)
from ui.task_view import TaskView
from ui.update_banner import UpdateBanner
from ui.wiki_page import SECTIONS as WIKI_SECTIONS

logger = logging.getLogger(__name__)


def _foreground_window() -> int:
    """The window the user is looking at, or 0 if it cannot be asked."""
    try:
        import ctypes

        return int(ctypes.windll.user32.GetForegroundWindow())
    except (AttributeError, OSError):  # pragma: no cover - Windows-only app
        return 0

# The design's own preview canvas is 1340×900; the frameless shell spends 56px
# of that on the drop-shadow margin, so ask for it back.
WINDOW_WIDTH = 1340
WINDOW_HEIGHT = 900
REFRESH_MS = 1000
# A running window's frame is already in hand, so its thumbnail costs nothing.
# An idle one needs a real GDI grab per card, so those refresh every other tick.
PREVIEW_EVERY_N_TICKS = 2

HOME_SUMMARY = (
    "Mỗi cửa sổ game là một luồng chạy độc lập, chạy đúng một tác vụ do bạn "
    "chọn."
)


def _storable(value):
    """A settings value in a form QSettings will hand back unchanged.

    Tuples are the reason this exists. PyQt has no native QSettings type for
    one, so it falls back to pickling the object into an ``@Variant(...)`` blob.
    That does round-trip — the click point was read back correctly from a real
    registry — but it stores a pickle where a person looking at their own
    settings should see two numbers, and it ties the saved value to the PyQt
    version that wrote it. Written as "1030,549" instead; ``tasks.as_point``
    already reads that shape, because the registry hands strings back for
    plenty of other values too.
    """
    if isinstance(value, tuple):
        return ",".join(str(part) for part in value)
    return value


class AutoWindow(FramelessWindow):
    """Dashboard window. Owns the session manager and the refresh timer."""

    # Worker callbacks arrive on the worker's own thread. Qt widgets may only be
    # touched from the GUI thread, so the callbacks do nothing but emit these;
    # a queued connection hands the work back to the right thread.
    sessionFinished = QtCore.pyqtSignal(str, int)
    sessionFailed = QtCore.pyqtSignal(str, int)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__("%s — %s" % (theme.APP_NAME, theme.APP_SUBTITLE), parent)
        self._settings = app_settings.open_store()
        self._migrate_legacy_settings()
        self._manager = SessionManager(self._load_configs(), self._load_app_config())
        # Read once at startup and then on every change: unlike a task's
        # settings, this one is consulted at click time, so it needs no restart.
        game_control.set_pause_while_hovering(
            tasks.as_bool(self._manager.app_config.get("pause_while_hovering", True))
        )
        self._views: Dict[str, TaskView] = {}
        # Built on first use: loading the dataset costs ~0.3s and most launches
        # never open the wiki.
        self._wiki: Optional[QtWidgets.QWidget] = None
        self._wiki_source = ""
        self._notifier = notifications.Notifier(self)
        self._page = HOME
        self._tick = 0
        self._force_close = False
        # Set only while the tray's own Thoát is running, so closeEvent knows
        # this close is meant to be a close. Declared here rather than reached
        # for with getattr, which hides a typo as "False".
        self._quitting_from_tray = False
        # Open snapshot previews. They outlive the click that made them.
        self._snapshots: List[QtWidgets.QDialog] = []
        # The system-wide screenshot key, and the last window it photographed.
        # The second is the tie-breaker when the key is pressed while something
        # that is not a game window has the foreground.
        self._hotkey = hotkeys.GlobalHotkey()
        self._hotkey_filter: Optional[HotkeyFilter] = None
        self._last_captured: int = 0
        # hwnd -> the recorder writing that window, while it is writing.
        self._recorders: Dict[int, object] = {}
        # The last file this app wrote on purpose, so the notification about it
        # has something to open when it is clicked.
        self._last_saved: Optional[Path] = None
        self._notifier.showRequested.connect(self._show_from_tray)
        self._notifier.stopRequested.connect(self._stop_all_from_tray)
        self._notifier.quitRequested.connect(self._quit_from_tray)
        self._notifier.messageClicked.connect(self._reveal_last_saved)
        self._install_hotkey()
        self._notifier.watch_running(lambda: self._manager.running_count)
        self.setWindowIcon(app_icon.build_icon())

        self.setMinimumSize(1120, 700)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self._build()
        self._register_hotkeys()
        self._repair_autostart()

        self.sessionFinished.connect(self._on_session_finished)
        self.sessionFailed.connect(self._on_session_failed)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

        QtCore.QTimer.singleShot(0, self._on_scan)
        # After the window is up, so a slow network never delays the first paint.
        QtCore.QTimer.singleShot(1500, self._update_banner.check_in_background)

    # ── settings ────────────────────────────────────────────────────────────

    def _migrate_legacy_settings(self) -> None:
        """Carry v2 settings into the task registry, once.

        v2 kept the invite reply as a bare bool, which means nothing to v3, so
        without this the user silently loses it on upgrade.

        It also kept one raid target per window title under ``slots/``, and that
        one is deliberately *not* carried over any more: the option it fed was
        removed once measuring showed a tap there could not do what it claimed,
        so migrating the value would restore a ghost setting nothing reads. The
        dead keys are still cleared out at the end.
        """
        raid = tasks.DEFAULT_TASK_ID

        # The invite reply has moved twice: a v2 bool, then briefly a Realm Raid
        # field, and now an app-wide setting — it blocks every task, not just
        # that one. Take whichever is present, newest first.
        if self._settings.value("wanted_invite") is None:
            per_task = self._settings.value("tasks/%s/wanted_invite" % raid)
            if per_task is not None:
                self._settings.setValue("wanted_invite", per_task)
                logger.info("Moved the Wanted Quest reply to the app settings")
            else:
                legacy = self._settings.value("accept_wanted_quest")
                if legacy is not None:
                    self._settings.setValue(
                        "wanted_invite",
                        tasks.ACCEPT if tasks.as_bool(legacy) else tasks.REFUSE,
                    )
                    logger.info("Migrated the v2 Wanted Quest reply")

        self._settings.remove("tasks/%s/wanted_invite" % raid)
        for dead in ("vitri", "refresh", "slot", "window_title", "accept_wanted_quest"):
            self._settings.remove(dead)
        self._settings.remove("slots")

    def _read_field(self, path: str, field: tasks.Field):  # noqa: D401
        """One saved value, with the type QSettings would otherwise lose."""
        if self._settings.value(path) is None:
            return None
        if field.kind == tasks.TOGGLE:
            return self._settings.value(path, type=bool)
        return self._settings.value(path)

    def _load_app_config(self) -> Dict[str, object]:
        """The app-wide settings, stored as flat keys."""
        values: Dict[str, object] = {}
        for field in tasks.APP_FIELDS:
            if not field.holds_value:
                continue
            saved = self._read_field(field.key, field)
            if saved is not None:
                values[field.key] = saved
        return values

    def _load_configs(self) -> Dict[str, Dict[str, object]]:
        """Read every task's saved settings. Coercion happens in the manager."""
        stored: Dict[str, Dict[str, object]] = {}
        for spec in tasks.TASKS:
            values: Dict[str, object] = {}
            for field in spec.fields:
                if not field.holds_value:
                    continue
                saved = self._read_field(
                    "tasks/%s/%s" % (spec.id, field.key), field
                )
                if saved is not None:
                    values[field.key] = saved
            if values:
                stored[spec.id] = values
        return stored

    def _remembered_task(self, title: str) -> Optional[str]:
        """The task a window was last set to. Remembered per title, because a
        window handle changes every launch.

        Reads the key an older version wrote a whole queue into, and takes the
        first task from it — see :func:`tasks.clean_task`. A user who set their
        windows up under that version keeps their choice.
        """
        return tasks.clean_task(self._settings.value("queues/" + title))

    def _remember_task(self, session: GameSession) -> None:
        self._settings.setValue("queues/" + session.title, session.selected)

    # ── layout ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        outer = QtWidgets.QVBoxLayout(self.body)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Hidden unless a newer build has been published. Full width, above
        # everything, because it is about the app rather than any one page.
        self._update_banner = UpdateBanner()
        self._update_banner.restartRequested.connect(self._on_update_restart)
        outer.addWidget(self._update_banner)

        split = hbox(0)
        self._sidebar = TaskSidebar()
        self._sidebar.pageSelected.connect(self._show_page)
        self._sidebar.scanRequested.connect(self._on_scan)
        self._sidebar.logsRequested.connect(self._open_logs)
        split.addWidget(self._sidebar)
        split.addWidget(Divider(horizontal=False))

        content = vbox(0)
        self._header = PageHeader()
        self._header.startRequested.connect(self._on_start_all)
        self._header.stopRequested.connect(self._on_stop_all)
        content.addWidget(self._header)
        content.addWidget(Divider())

        self._stack = QtWidgets.QStackedWidget()
        self._home = HomeView()
        self._home.startRequested.connect(self._on_start)
        self._home.stopRequested.connect(self._on_stop)
        self._home.captureRequested.connect(self._on_capture)
        self._home.recordRequested.connect(self._on_record)
        self._home.revealRequested.connect(self._on_reveal)
        self._stack.addWidget(self._home)

        # Built once with the window rather than on first use: it is small, and
        # its values are re-read every time the page is opened anyway.
        self._settings_page = SettingsPage(self._app_values())
        self._settings_page.changed.connect(self._on_app_setting)
        self._stack.addWidget(self._settings_page)
        content.addWidget(self._stack, 1)

        split.addLayout(content, 1)
        outer.addLayout(split, 1)
        self._show_page(HOME)

    def _task_view(self, task_id: str) -> Optional[TaskView]:
        """Build a task's page the first time it is opened."""
        if task_id in self._views:
            return self._views[task_id]
        spec = tasks.get(task_id)
        if spec is None:
            return None
        view = TaskView(spec, self._manager.config_for(task_id))
        view.startRequested.connect(self._on_start)
        view.stopRequested.connect(self._on_stop)
        view.captureRequested.connect(self._on_capture)
        view.recordRequested.connect(self._on_record)
        view.revealRequested.connect(self._on_reveal)
        view.selectRequested.connect(self._on_select)
        view.optionChanged.connect(self._on_option_changed)
        view.windowOptionChanged.connect(self._on_window_option_changed)
        self._views[task_id] = view
        self._stack.addWidget(view)
        return view

    def _wiki_page(self) -> QtWidgets.QWidget:
        """Build the wiki page the first time it is opened."""
        if self._wiki is None:
            from ui.wiki_page import WikiPage

            page = WikiPage()
            page.sectionChanged.connect(self._on_wiki_section)
            page.countsChanged.connect(self._sidebar.set_wiki_counts)
            page.sourceChanged.connect(self._on_wiki_source)
            self._wiki = page
            # Once the page is on screen, not before: the sync repaints the
            # grid when it lands, and the tab should appear first.
            QtCore.QTimer.singleShot(0, page.sync_in_background)
            self._stack.addWidget(page)
            # The page loaded its dataset in the constructor and emitted both
            # signals before anything was connected; ask for them again.
            page._publish_counts()
        return self._wiki

    def _show_page(self, key: str) -> None:
        section = wiki_section_of(key)
        if key == SETTINGS:
            # Re-read on the way in. One of these settings lives in the registry
            # rather than in the app's own store and can be turned off from Task
            # Manager while this is open, so the page has to catch up.
            self._settings_page.show_values(self._app_values())
            self._stack.setCurrentWidget(self._settings_page)
        elif section is not None:
            page = self._wiki_page()
            page.show_section(section)
            self._stack.setCurrentWidget(page)
        elif key != HOME:
            view = self._task_view(key)
            if view is None:
                return
            self._stack.setCurrentWidget(view)
        else:
            self._stack.setCurrentWidget(self._home)
        self._page = key
        self._sidebar.set_current(key)
        # Thumbnails only exist on task pages, so leaving one lets the device
        # contexts those grabs opened go. Idle windows only; release is a no-op
        # while a worker owns the handles.
        for session in self._manager.sessions:
            session.release()
        self._sync_header()
        # _rebuild, not _refresh: a page opened for the first time has no cards
        # yet, and only _rebuild creates them. With a plain refresh the window
        # list stayed empty until something else triggered a rebuild — a scan,
        # or assigning a task.
        self._rebuild()

    def _sync_header(self) -> None:
        if self._page == HOME:
            self._header.set_page(
                "Tổng quan", "Bảng điều khiển", HOME_SUMMARY, "Bắt đầu tất cả",
                True, self._everything_is_running(),
            )
            return

        section = wiki_section_of(self._page)
        if section is not None:
            name = dict(WIKI_SECTIONS).get(section, "")
            self._header.set_plain_page(
                "Bách khoa · Âm Dương Sư", name,
                "Tra cứu offline. %s" % (
                    "Nguồn: %s." % self._wiki_source.lower()
                    if self._wiki_source else
                    "Bấm Đồng bộ để lấy nội dung mới từ Supabase."
                ),
            )
            return

        spec = tasks.get(self._page)
        if spec is None:
            return
        self._header.set_page(
            spec.kicker, spec.name, spec.summary,
            "Bắt đầu tác vụ này", spec.is_available,
            self._everything_is_running(self._page),
        )

    def _everything_is_running(self, task_id: str = "") -> bool:
        """Nothing left to start — on this task's page, or across every window.

        Deliberately not "anything is running": with one window still to go the
        header keeps offering to start, because start skips what is already
        going while a stop would end it.
        """
        sessions = (self._manager.sessions_for(task_id) if task_id
                    else self._manager.sessions)
        startable = [s for s in sessions
                     if not s.is_running and tasks.is_available(s.task_id or "")]
        return bool(sessions) and not startable and any(
            s.is_running for s in sessions
        )

    def _on_wiki_section(self, section: str) -> None:
        """Follow the wiki's own navigation in the sidebar and the header."""
        key = wiki_key(section) if section else ""
        if not key:
            # A search spans every section, so nothing is highlighted.
            self._sidebar.set_current("")
            return
        self._page = key
        self._sidebar.set_current(key)
        self._sync_header()

    def _on_wiki_source(self, described: str) -> None:
        self._wiki_source = described
        if wiki_section_of(self._page) is not None:
            self._sync_header()

    # ── actions ─────────────────────────────────────────────────────────────

    def _on_option_changed(self, task_id: str, key: str, value: object) -> None:
        self._manager.set_option(task_id, key, value)
        self._settings.setValue(
            "tasks/%s/%s" % (task_id, key), _storable(value)
        )
        logger.info("Option %s.%s -> %r", task_id, key, value)
        # A worker reads its settings once, when it is built, so a change made
        # while it runs looks applied and is not — which is how somebody comes
        # to believe "Tự dừng khi hết vé" was on for a run that never had it.
        # The app-wide settings already say this; task options were silent.
        #
        # A dialog rather than a tray notification, unlike everywhere else here:
        # this fires only in answer to the person's own click, so they are at
        # the keyboard. The reason notifications.py gives for avoiding modals —
        # a bot running unattended for hours — is the one case this is not.
        if self._manager.running_count_for(task_id):
            spec = tasks.get(task_id)
            QtWidgets.QMessageBox.information(
                self,
                "%s — %s" % (theme.APP_NAME, spec.name if spec else "tác vụ"),
                "Đã lưu. Tác vụ đang chạy vẫn dùng thiết lập cũ — dừng rồi "
                "bật lại để áp dụng.",
            )

    def _on_window_option_changed(self, hwnd: int, key: str, value: object) -> None:
        """A setting that belongs to one window, not to the task."""
        session = self._manager.get(hwnd)
        if session is None:
            return
        session.set_option(self._page, key, value)
        self._remember_options(session)
        logger.info("Window 0x%08x %s.%s -> %r", hwnd, self._page, key, value)

    def _options_key(self, title: str, task_id: str, key: str) -> str:
        return "windows/%s/%s/%s" % (title, task_id, key)

    def _remembered_options(self, title: str) -> Dict[str, Dict[str, object]]:
        """Per-window settings saved for this window title."""
        stored: Dict[str, Dict[str, object]] = {}
        for spec in tasks.TASKS:
            values: Dict[str, object] = {}
            for field in spec.window_fields:
                saved = self._read_field(
                    self._options_key(title, spec.id, field.key), field
                )
                if saved is not None:
                    values[field.key] = saved
            if values:
                stored[spec.id] = values
        return stored

    def _remember_options(self, session: GameSession) -> None:
        for task_id, values in session.window_options.items():
            for key, value in values.items():
                self._settings.setValue(
                    self._options_key(session.title, task_id, key), value
                )

    def _on_scan(self) -> None:
        sessions = self._manager.scan()
        for session in sessions:
            remembered = self._remembered_task(session.title)
            if remembered and not session.is_running:
                session.select(remembered)
            session.load_options(self._remembered_options(session.title))
        self._rebuild()

    def _on_start(self, hwnd: int) -> None:
        # On a task's own page, start that task — the same rule the header's
        # "start all" already followed. The two buttons sit inches apart and
        # used to disagree.
        task_id = None if self._page == HOME else self._page
        try:
            self._manager.start(
                hwnd, self._finished_from_worker, self._failed_from_worker, task_id
            )
        except Exception as exc:  # noqa: BLE001 - shown to the user
            logger.exception("Could not start window 0x%08x", hwnd)
            QtWidgets.QMessageBox.warning(self, "Không khởi động được", str(exc))
        self._refresh()

    def _on_stop(self, hwnd: int) -> None:
        self._manager.stop(hwnd)
        self._refresh()

    def _on_start_all(self) -> None:
        task_id = None if self._page == HOME else self._page
        errors = self._manager.start_all(
            self._finished_from_worker, self._failed_from_worker, task_id
        )
        if errors:
            QtWidgets.QMessageBox.warning(
                self, "Có cửa sổ không khởi động được", "\n".join(errors)
            )
        self._refresh()

    def _on_capture(self, hwnd: int) -> None:
        """Photograph one game window: clipboard first, then a preview to mark up.

        The clipboard copy happens before the dialog opens and does not wait for
        it. Pasting is what a screenshot is usually for and it should cost one
        click; the dialog is for the times a circle round the interesting part is
        worth drawing.

        The frame comes from the session rather than a capture of our own. While
        a worker is running it owns the window's device contexts, and grabbing
        from here as well would use the same GDI handles from a second thread —
        the session already knows to hand over the worker's latest frame instead,
        and to capture on demand when nothing is running.
        """
        session = self._manager.get(hwnd)
        if session is None:
            return
        pixmap = preview.to_pixmap(session.preview_frame())
        if pixmap is None or pixmap.isNull():
            logger.warning("Nothing to capture for window 0x%08x", hwnd)
            self._notifier.notify(
                theme.APP_NAME,
                "Chưa chụp được cửa sổ này — cửa sổ game có thể đang thu nhỏ.",
                notifications.WARNING,
            )
            return

        self._last_captured = hwnd
        snapshot_dialog.copy_to_clipboard(pixmap)
        logger.info("Captured 0x%08x (%dx%d) and copied it to the clipboard",
                    hwnd, pixmap.width(), pixmap.height())
        dialog = snapshot_dialog.SnapshotDialog(pixmap, session.title, self)
        # Held in a list rather than a local. The dialog is deliberately
        # non-modal so the app keeps running behind it, and a local reference
        # would be collected the moment this method returns.
        self._snapshots.append(dialog)
        dialog.finished.connect(lambda _result, d=dialog: self._forget_snapshot(d))
        dialog.show()

    # ── recording ───────────────────────────────────────────────────────────

    def _show_recordings(self) -> None:
        """Put the live elapsed time and size on every recording window's button.

        Pushed on the refresh tick rather than from the recorder's own thread:
        the recorder must never touch a widget, and this is already ticking.
        """
        cards = dict(getattr(self._home, "_rows", {}))
        view = self._views.get(self._page)
        if view is not None:
            cards.update(getattr(view, "_cards", {}))
        for hwnd, card in cards.items():
            if not hasattr(card, "set_recording"):
                continue
            made = self._recorders.get(hwnd)
            if made is None:
                card.set_recording(on=False)
            else:
                card.set_recording(made.elapsed_seconds,
                                   made.size_bytes() / 1e6, on=True)

    def _record_fps(self) -> int:
        """The frames-a-second setting, as a number."""
        chosen = str(self._manager.app_config.get("record_fps") or "")
        digits = "".join(ch for ch in chosen if ch.isdigit())
        return int(digits) if digits else recorder.DEFAULT_FPS

    def _on_record(self, hwnd: int) -> None:
        """One button: start recording this window, or stop it.

        A toggle rather than two buttons because there is only ever one answer
        available — a window is either being recorded or it is not — and a
        disabled second button would take space from the row for nothing.
        """
        live = self._recorders.get(hwnd)
        if live is not None:
            self._stop_recording(hwnd)
            return
        session = self._manager.get(hwnd)
        if session is None:
            return
        made = recorder.WindowRecorder(
            hwnd, fps=self._record_fps(), title=session.title
        )
        made.start()
        self._recorders[hwnd] = made
        logger.info("Recording 0x%08x at %d fps", hwnd, self._record_fps())
        self._refresh()

    def _stop_recording(self, hwnd: int) -> None:
        """Stop one recording and note the file, quietly.

        Nothing is announced on success, by request. The file is reachable from
        the folder button on the same row the recording was started from, which
        is where somebody who just stopped one is already looking — a toast
        telling them what they had just watched happen was noise.

        A *failure* still speaks. "Nothing was saved" is not something to leave
        somebody to discover for themselves in an empty folder.
        """
        made = self._recorders.pop(hwnd, None)
        if made is None:
            return
        made.stop()
        made.join(timeout=5.0)
        if made.error:
            self._notifier.notify(
                "%s — quay video" % theme.APP_NAME, made.error,
                notifications.WARNING,
            )
        elif made.frames:
            self._last_saved = Path(made.path)
            logger.info("Saved %.0fs (%.1f MB) to %s", made.elapsed_seconds,
                        made.size_bytes() / 1e6, made.path)
        self._refresh()

    def _on_reveal(self, _hwnd: int) -> None:
        """The folder button on a window's row.

        Always the same folder whichever row it was pressed on: recordings are
        named by time and window, and one folder that can be opened from
        anywhere beats one folder per window that has to be hunted for.
        """
        self._reveal_last_saved()

    def _reveal_last_saved(self) -> None:
        """Open the folder holding the last thing this app saved.

        Wired to a click on the notification, which is where somebody is looking
        the moment a recording ends. Windows does not promise to deliver that
        click — the balloon signal is unreliable across versions — so the
        settings page carries the same folders as plain links, and that is the
        path that always works.
        """
        target = self._last_saved
        folder = target.parent if target is not None else recorder.recording_dir()
        logger.info("Opening %s", folder)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(folder)))

    def _release_hotkey(self) -> None:
        """Hand the combination back to the system.

        Windows releases a process's hotkeys when it exits anyway, but not
        before — and during a restart the new copy would be refused its own
        combination by the old one.

        The native event filter goes back too. It is installed on the
        QApplication rather than on this window, so it outlives the window
        unless it is taken off — and it holds a bound method of the very window
        being torn down. A running app builds exactly one of these and then
        exits, so nothing was ever seen. A test run builds one per test against
        a shared QApplication, and Qt walks that list on the next native event:
        straight into freed memory. The result is an access violation, not a
        test failure, so it takes the whole run down with it and names an
        innocent test on the way out.
        """
        self._hotkey.unbind()
        if self._hotkey_filter is not None:
            app = QtWidgets.QApplication.instance()
            if app is not None:
                app.removeNativeEventFilter(self._hotkey_filter)
            self._hotkey_filter = None

    def _stop_all_recordings(self) -> None:
        for hwnd in list(self._recorders):
            self._stop_recording(hwnd)

    # ── the system-wide screenshot key ──────────────────────────────────────

    def _install_hotkey(self, announce: bool = False) -> None:
        """Register whatever the settings ask for, and say so if it is refused.

        ``announce`` only when the user has just changed it. At startup a
        combination another application already owns is written to the log and
        left alone — a warning box in front of somebody who has just turned the
        machine on, about a key they set up weeks ago, helps nobody.
        """
        if self._hotkey_filter is None:
            self._hotkey_filter = HotkeyFilter(self._hotkey.id, self._on_hotkey)
            QtWidgets.QApplication.instance().installNativeEventFilter(
                self._hotkey_filter)

        wanted = str(self._manager.app_config.get("snapshot_hotkey") or "")
        if self._hotkey.bind(wanted) or not announce:
            return
        QtWidgets.QMessageBox.warning(self, "Phím tắt", self._hotkey.error)

    def _on_hotkey(self) -> None:
        """The key was pressed, somewhere on the machine."""
        hwnd = self._window_to_photograph()
        if hwnd is None:
            # Look again before complaining. The session list is only as fresh
            # as the last scan, and it goes stale in both directions: a game
            # opened since then is missing, and one that has *closed* is still
            # there. The second is the one that gets reported, because a dead
            # handle counts towards "which of the several did you mean" — a
            # user with one game open and one shut was told there was no window
            # at all, and told to press Scan by a program well able to press it
            # itself. A rescan drops the dead entry and the question answers
            # itself.
            self._on_scan()
            hwnd = self._window_to_photograph()
        if hwnd is None:
            self._notifier.notify(
                theme.APP_NAME,
                self._nothing_to_photograph(),
                notifications.WARNING,
            )
            return
        logger.info("Hotkey capture of 0x%08x", hwnd)
        self._on_capture(hwnd)

    def _say_goodbye_to_closed_windows(self) -> None:
        """Drop cards whose game has been closed, announcing the ones at work.

        A closed window used to stay on the list until the next scan, and one
        running a task stayed indefinitely — so that a failing run would be
        visible rather than vanishing. In practice nothing was visible: the
        worker simply logged "Invalid window handle" once a second, on a live
        instance for half an hour, and the dead entry went on counting as a
        game window for anything asking how many there were.

        So it is announced instead. A run cut short is worth a word; an idle
        card going away is not — the user closed that game themselves a moment
        ago and does not need telling.
        """
        for session in self._manager.drop_closed_windows():
            logger.info("Window 0x%08x closed; dropping its card (running=%s)",
                        session.hwnd, session.was_running)
            if session.was_running:
                self._notifier.notify(
                    theme.APP_NAME,
                    "Cửa sổ game đã đóng — đã dừng tác vụ đang chạy trên %s."
                    % session.title,
                    notifications.WARNING,
                )

    def _nothing_to_photograph(self) -> str:
        """Why the key could not pick a window, having just scanned.

        Two different problems wearing one message before this: nothing open,
        and too much open. Only the second has anything the user can do about
        it, and "press Scan" was the wrong advice for both.
        """
        count = len(self._manager.sessions)
        if count == 0:
            return "Chưa thấy cửa sổ game nào để chụp — mở game rồi thử lại."
        return ("Đang mở %d cửa sổ game — bấm vào cửa sổ muốn chụp rồi bấm lại "
                "phím tắt." % count)

    def _window_to_photograph(self) -> Optional[int]:
        """Which game window the hotkey means.

        Whatever is in front, when that is a window we know about — pressing it
        while looking at a game is the whole point. Otherwise the last one
        photographed, then the only one there is. Anything cleverer would be
        guessing, and a screenshot of the wrong window is worse than being told
        to pick one.
        """
        known = {session.hwnd for session in self._manager.sessions}
        if not known:
            return None
        front = _foreground_window()
        if front in known:
            return front
        if self._last_captured in known:
            return self._last_captured
        if len(known) == 1:
            return next(iter(known))
        return None

    def _forget_snapshot(self, dialog) -> None:
        if dialog in self._snapshots:
            self._snapshots.remove(dialog)
        dialog.deleteLater()

    def _on_stop_all(self) -> None:
        self._manager.stop_all(None if self._page == HOME else self._page)
        self._refresh()

    def _on_select(self, hwnd: int, task_id: str) -> None:
        self._manager.select(hwnd, task_id)
        self._remember(hwnd)
        self._rebuild()

    def _remember(self, hwnd: int) -> None:
        session = self._manager.get(hwnd)
        if session is not None:
            self._remember_task(session)

    def _notifies(self) -> bool:
        """Whether a finished run should raise a Windows notification."""
        return tasks.as_bool(self._manager.app_config.get("notify_on_finish"))

    def _hides_to_tray(self) -> bool:
        """Whether pressing X should hide the window instead of quitting.

        Both halves matter. The setting is the user's wish; the tray actually
        existing is what makes the wish safe to grant — hidden with no icon to
        click, the app would be unreachable and unclosable except through Task
        Manager.
        """
        return (
            tasks.as_bool(self._manager.app_config.get("close_to_tray"))
            and self._notifier.has_tray
        )

    # ── the tray ────────────────────────────────────────────────────────────

    def show_from_launch(self) -> None:
        """Somebody launched the app again. Show this window instead.

        Public because it is called from outside the UI — by the single-instance
        guard in ``app`` — and it is the same request as the tray's "Mở", so it
        is the same code.
        """
        logger.info("A second launch was folded into this window")
        self._show_from_tray()

    def _show_from_tray(self) -> None:
        """Bring the window back from the tray."""
        # showNormal rather than show: a window hidden while minimised comes
        # back still minimised otherwise, which looks like nothing happened.
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def _stop_all_from_tray(self) -> None:
        """Stop every window, whatever page the hidden window is sitting on.

        Not :meth:`_on_stop_all`, which stops only the task whose page is open.
        That is the right rule for a button *on* that page and a surprising one
        for a menu item read from the tray, where there is no page in sight.

        Silent, by request. It is not feedback-free: the refresh that follows
        puts "đang nghỉ" on the tray tooltip, so hovering the icon says what
        happened without a toast interrupting anything.
        """
        self._manager.stop_all(None)
        self._refresh()

    def _quit_from_tray(self) -> None:
        """Quit for real from the tray menu.

        Goes through ``close`` rather than quitting outright so the running-task
        confirmation and the orderly shutdown both still happen. The window is
        shown first: a confirmation dialog belonging to a hidden window can end
        up behind everything with nothing to click.
        """
        self._quitting_from_tray = True
        try:
            if not self.isVisible():
                self._show_from_tray()
            self.close()
        finally:
            self._quitting_from_tray = False

    def _repair_autostart(self) -> None:
        """Rewrite a startup entry that no longer points at this build.

        The entry survives the build being moved, and survives a change to the
        command this app would write — and in both cases it goes on starting
        nothing at every sign-in, silently. Since the app is running, it knows
        the right answer, so it just fixes it rather than waiting for somebody to
        notice and toggle the switch twice.
        """
        if not autostart.is_enabled() or autostart.is_current():
            return
        was = autostart.stored_command()
        if autostart.set_enabled(True):
            logger.info("Repaired the startup entry (was %r)", was)

    def _apply_autostart(self, wanted: bool) -> None:
        """Write the Windows startup entry, and say so if it would not take.

        Not stored in the app's own settings at all: the registry is the only
        place this lives, so there is nothing that can disagree with it. A write
        under HKCU normally cannot fail, but a policy-managed machine can refuse
        and a toggle that claimed success anyway would be a lie.
        """
        if wanted == autostart.is_enabled() and (not wanted or autostart.is_current()):
            return
        if autostart.set_enabled(wanted):
            logger.info("Start with Windows: %s", "on" if wanted else "off")
            return
        logger.warning("Start with Windows could not be changed")
        self._notifier.notify(
            "%s — cài đặt" % theme.APP_NAME,
            "Không đổi được mục khởi động cùng Windows. Máy có thể đang bị "
            "chính sách hệ thống chặn ghi vào Startup.",
            notifications.WARNING,
        )

    # ── worker callbacks ────────────────────────────────────────────────────
    # These two run on the worker's thread; they only emit.

    def _finished_from_worker(self, message: str, hwnd: int) -> None:
        self.sessionFinished.emit(message, hwnd)

    def _failed_from_worker(self, message: str, hwnd: int) -> None:
        self.sessionFailed.emit(message, hwnd)

    def _on_session_finished(self, message: str, hwnd: int) -> None:
        session = self._manager.get(hwnd)
        if session is None:
            return
        session.mark_finished(message)
        if self._notifies():
            self._notifier.notify("%s — hoàn thành" % theme.APP_NAME, message)
        self._rebuild()

    def _on_session_failed(self, message: str, hwnd: int) -> None:
        session = self._manager.get(hwnd)
        if session is not None:
            session.mark_failed(message)
        # A toast rather than a dialog: the row already shows the error state,
        # and a modal would sit in front of the windows still running.
        self._notifier.notify(
            "%s — lỗi" % theme.APP_NAME,
            "Một cửa sổ đã dừng: %s" % message,
            notifications.CRITICAL,
        )
        self._refresh()

    def _on_update_restart(self, staged: str) -> None:
        """Hand over to the swap helper, then close so it can replace the file."""
        running = self._manager.running_count
        if running and not self._confirm_exit(running):
            return
        try:
            updater.apply_and_restart(Path(staged))
        except updater.UpdateError as exc:
            logger.warning("Could not apply the update: %s", exc)
            self._notifier.notify(
                "%s — cập nhật" % theme.APP_NAME,
                "Không cài được bản mới: %s" % exc,
                notifications.CRITICAL,
            )
            return
        # The helper waits for this process to exit before swapping the file.
        self._force_close = True
        self.close()

    def open_wiki(self) -> None:
        """Jump to the wiki. Used by ``--wiki`` on the command line."""
        self._show_page(wiki_key(WIKI_SECTIONS[0][0]))

    def _open_logs(self) -> None:
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(paths.LOG_DIR))
        )

    def _app_values(self) -> Dict[str, object]:
        """What the settings page should show.

        The app's own store for everything except starting with Windows, which
        is read from the registry because that is where it lives — see
        :mod:`autostart`.
        """
        values = dict(self._manager.app_config)
        values["start_with_windows"] = autostart.is_enabled()
        return values

    def _on_app_setting(self, key: str, value: object) -> None:
        """Apply one app-wide setting, the moment it is changed.

        No OK button: a task's own settings already apply on change, and this
        page was the only place in the app where the same kind of control waited
        for confirmation.
        """
        if key == "start_with_windows":
            self._apply_autostart(tasks.as_bool(value))
            return
        self._settings.setValue(key, value)
        self._manager.set_app_option(key, value)
        if key == "snapshot_hotkey":
            self._install_hotkey(announce=True)
        if key == "pause_while_hovering":
            game_control.set_pause_while_hovering(tasks.as_bool(value))
        logger.info("App setting %s = %r", key, value)
        # A worker already running keeps the value it started with; the setting
        # is read when a worker is built. Say so rather than let it look applied.
        if self._manager.running_count and key == "wanted_invite":
            self._notifier.notify(
                "%s — cài đặt" % theme.APP_NAME,
                "Đã lưu. Cửa sổ đang chạy vẫn dùng thiết lập cũ tới khi khởi "
                "động lại tác vụ.",
            )

    def _open_settings(self) -> None:
        """F9, and the sidebar row. Both just go to the page."""
        self._show_page(SETTINGS)
    def _rebuild(self) -> None:
        """Reconcile which rows and cards exist, then repaint them."""
        sessions = self._manager.sessions
        self._home.set_sessions(sessions)
        for task_id, view in self._views.items():
            chosen = [s for s in sessions if s.task_id == task_id]
            others = [s for s in sessions if s.task_id != task_id]
            view.set_sessions(chosen, others)
        self._refresh()

    def _refresh(self) -> None:
        self._tick += 1
        self._manager.sync()
        self._say_goodbye_to_closed_windows()
        # The header carries one button whose meaning follows the running state,
        # so it has to be repainted on the tick as well as on a page change.
        self._sync_header()
        sessions = self._manager.sessions
        running = self._manager.running_count
        # The tray tooltip answers "is it still going" without opening anything,
        # which is the question somebody who hid the window will have.
        self._notifier.set_running(running)
        self._show_recordings()

        self._sidebar.update_counts(
            len(sessions), running,
            {
                spec.id: (
                    len(self._manager.sessions_for(spec.id)),
                    self._manager.running_count_for(spec.id),
                )
                for spec in tasks.TASKS
            },
        )

        if self._page == HOME:
            self._home.refresh(sessions, self._stats(sessions, running))
        else:
            view = self._views.get(self._page)
            if view is not None:
                # Only the page on screen captures. A task page nobody is
                # looking at costs nothing, and the overview shows no
                # thumbnails, so idle windows are not grabbed at all there.
                view.refresh(
                    [s for s in sessions if s.task_id == self._page],
                    self._tick % PREVIEW_EVERY_N_TICKS == 0,
                )

    @staticmethod
    def _stats(sessions, running: int) -> List[str]:
        # Only tasks that report a trustworthy count contribute to the total;
        # with none of them doing so the tile reads "—" rather than a hard zero
        # that looks like the app failed to count something.
        counted = [
            session.progress for session in sessions
            if session.task is not None and session.task.counts_progress
        ]
        return [
            "%d / %d" % (running, len(sessions)),
            str(sum(counted)) if counted else "—",
            str(len(tasks.available())),
            GameSession.format_elapsed(
                sum(session.elapsed_seconds for session in sessions)
            ),
        ]

    # ── hotkeys ─────────────────────────────────────────────────────────────

    def _register_hotkeys(self) -> None:
        """F1, F2 and F9, live only while one of our windows has the keyboard.

        These used to be registered system-wide as well, through the
        ``keyboard`` package, so they worked while the game had focus. That is
        gone on purpose. The package works by installing a low-level Windows
        keyboard hook, and a low-level hook receives *every* keystroke on the
        machine and filters afterwards — this app only ever wanted two of them.
        Nothing was done with the rest, but the capability is there in the
        binary, it is the shape of a keylogger, and it is one of the things an
        antivirus weighs when it decides an unsigned PyInstaller build looks
        like a trojan. The hook also outlived the window it belonged to, which
        left listener threads running behind a closed dashboard.

        The screenshot key kept its system-wide reach and did not need any of
        that: ``hotkeys.GlobalHotkey`` asks Windows for one specific
        combination via ``RegisterHotKey``, and Windows tells us when that
        combination is pressed. It cannot see another key even in principle.
        """
        QtWidgets.QShortcut(QtGui.QKeySequence("F1"), self, self._toggle_pause_all)
        QtWidgets.QShortcut(QtGui.QKeySequence("F2"), self, self._on_stop_all)
        QtWidgets.QShortcut(QtGui.QKeySequence("F9"), self, self._open_settings)

    def _toggle_pause_all(self) -> None:
        self._manager.pause_all()
        self._refresh()

    # ── shutdown ────────────────────────────────────────────────────────────

    def _confirm_exit(self, running: int) -> bool:
        """Ask before throwing away work in progress. True means go ahead.

        Only reached when a worker is actually running, so a routine close
        never costs a click.
        """
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Thoát %s" % theme.APP_NAME)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setText("Đang chạy %d cửa sổ." % running)
        box.setInformativeText(
            "Thoát sẽ dừng toàn bộ auto đang chạy. Muốn tiếp tục chạy thì chọn "
            "“Ở lại” rồi thu nhỏ cửa sổ."
        )
        leave = box.addButton("Thoát", QtWidgets.QMessageBox.AcceptRole)
        stay = box.addButton("Ở lại", QtWidgets.QMessageBox.RejectRole)
        # Defaulting to the harmless answer: a stray Enter should not end a run.
        box.setDefaultButton(stay)
        box.exec_()
        return box.clickedButton() is leave

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        # Hiding comes first, and asks nothing: there is nothing to confirm
        # because nothing stops. This is the whole point of the setting — the
        # app is meant to be left running for hours, and a window that has to
        # stay on the taskbar to do that is in the way.
        #
        # Skipped for the two closes that really are closes: the tray's own
        # Thoát, and the update handler's, which has a helper waiting on this
        # process to exit.
        if (self._hides_to_tray()
                and not self._force_close
                and not self._quitting_from_tray):
            event.ignore()
            self.hide()
            return

        running = self._manager.running_count
        # _force_close is set when the update handler already asked and the
        # swap helper is waiting on this process; asking twice would strand it.
        if running and not self._force_close and not self._confirm_exit(running):
            event.ignore()
            return

        # Before anything else is torn down: an unreleased writer leaves an
        # .mp4 that will not play, and the writer lives on the recorder's thread.
        self._stop_all_recordings()
        self._timer.stop()
        self._release_hotkey()
        self._update_banner.stop()
        self._notifier.close()
        self._manager.shutdown()
        if self._wiki is not None:
            self._wiki.shutdown()
        super().closeEvent(event)
        # Reached only when the close is a real close: hiding to the tray and a
        # refused confirmation both return above. The application does not quit
        # on its own any more — it must not, or closing a screenshot preview
        # while the dashboard is hidden would end the whole app — so the one
        # place that knows a close was genuine says so.
        QtWidgets.QApplication.quit()


class HotkeyFilter(QtCore.QAbstractNativeEventFilter):
    """Turns ``WM_HOTKEY`` into a plain callback.

    Registered on the application rather than a window: the hotkey is registered
    against the thread (see :mod:`hotkeys` for why), so the message arrives with
    no window to route it through.
    """

    def __init__(self, hotkey_id: int, on_pressed) -> None:
        super().__init__()
        self._id = hotkey_id
        self._on_pressed = on_pressed

    def nativeEventFilter(self, kind, message):
        if kind == b"windows_generic_MSG" and hotkeys.is_our_hotkey(
                int(message), self._id):
            self._on_pressed()
        # Never swallow it. Returning True would stop Qt delivering the message
        # to anything else that wants it, and this filter sees every message the
        # application pumps.
        return False, 0
