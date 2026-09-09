"""The strip that appears when a newer build has been published.

Hidden unless there is something to say, so the dashboard is unchanged for
anyone already up to date. The check and the download both run on worker
threads — a 100 MB fetch must never touch the UI thread.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt5 import QtCore, QtWidgets

import theme
import updater
from ui import controls
from ui.primitives import hbox, label

logger = logging.getLogger(__name__)


class CheckWorker(QtCore.QThread):
    """Asks the manifest whether anything newer exists."""

    found = QtCore.pyqtSignal(object)   # Release
    upToDate = QtCore.pyqtSignal()
    failed = QtCore.pyqtSignal(str)

    def __init__(self, current_version: str) -> None:
        super().__init__()
        self._current = current_version

    def run(self) -> None:
        try:
            release = updater.check(self._current)
        except updater.UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - shown to the user
            logger.exception("Update check crashed")
            self.failed.emit(str(exc))
        else:
            if release is None:
                self.upToDate.emit()
            else:
                self.found.emit(release)


class DownloadWorker(QtCore.QThread):
    """Fetches and verifies the new build."""

    progressed = QtCore.pyqtSignal(int, int)   # received, total
    ready = QtCore.pyqtSignal(str)             # staged path
    failed = QtCore.pyqtSignal(str)

    def __init__(self, release, target: Path) -> None:
        super().__init__()
        self._release = release
        self._target = target
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            staged = updater.download(
                self._release,
                self._target,
                progress=lambda got, total: self.progressed.emit(got, total),
                cancelled=lambda: self._cancelled,
            )
        except updater.UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - shown to the user
            logger.exception("Update download crashed")
            self.failed.emit(str(exc))
        else:
            self.ready.emit(str(staged))


class UpdateBanner(QtWidgets.QWidget):
    """One strip: what is available, and the single action that applies it."""

    restartRequested = QtCore.pyqtSignal(str)   # staged path

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._release = None
        self._staged: Optional[str] = None
        self._check: Optional[CheckWorker] = None
        self._download: Optional[DownloadWorker] = None

        self.setObjectName("updateBanner")
        self.setStyleSheet(
            "#updateBanner { background: %s; border-bottom: 1px solid %s; }"
            % (theme.ACCENT_WASH, theme.BORDER_HOVER)
        )

        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(32, 11, 32, 11)
        row.setSpacing(14)

        self._message = label("", theme.body(13), theme.TEXT)
        self._detail = label("", theme.mono(10.5, tracking=0.1), theme.TEXT_LABEL)

        self._action = controls.OutlineButton(
            "Cập nhật", controls.ACCENT, padding="7px 16px"
        )
        self._action.clicked.connect(self._on_action)
        self._dismiss = controls.OutlineButton("Để sau", padding="7px 14px")
        self._dismiss.clicked.connect(self.hide)

        row.addWidget(self._message, 0, QtCore.Qt.AlignVCenter)
        row.addWidget(self._detail, 0, QtCore.Qt.AlignVCenter)
        row.addStretch()
        row.addWidget(self._action, 0, QtCore.Qt.AlignVCenter)
        row.addWidget(self._dismiss, 0, QtCore.Qt.AlignVCenter)

        self.hide()

    # ── checking ────────────────────────────────────────────────────────────

    def check_in_background(self) -> None:
        """Ask once, quietly. Nothing is shown unless an update exists."""
        if not updater.can_update():
            logger.info("Updates are off (frozen=%s, url set=%s)",
                        __import__("paths").FROZEN, bool(updater.manifest_url()))
            return
        if self._check is not None and self._check.isRunning():
            return
        self._check = CheckWorker(theme.APP_VERSION)
        self._check.found.connect(self._on_found)
        self._check.failed.connect(
            lambda message: logger.info("Update check failed: %s", message)
        )
        self._check.start()

    def _on_found(self, release) -> None:
        self._release = release
        size = " · %.0f MB" % release.size_mb if release.size else ""
        self._message.setText("Có bản mới %s" % release.version)
        self._detail.setText(
            (release.notes or release.published or "").strip()[:80].upper() + size.upper()
        )
        self._action.setText("Cập nhật")
        self._action.setEnabled(True)
        self.show()

    # ── downloading ─────────────────────────────────────────────────────────

    def _on_action(self) -> None:
        if self._staged:
            self.restartRequested.emit(self._staged)
            return
        if self._release is None:
            return
        self._action.setEnabled(False)
        self._action.setText("Đang tải 0%")
        self._dismiss.setEnabled(False)

        self._download = DownloadWorker(self._release, updater.staged_path())
        self._download.progressed.connect(self._on_progress)
        self._download.ready.connect(self._on_ready)
        self._download.failed.connect(self._on_failed)
        self._download.start()

    def _on_progress(self, received: int, total: int) -> None:
        if total:
            self._action.setText("Đang tải %d%%" % int(received * 100 / total))
        else:
            self._action.setText("Đang tải %.0f MB" % (received / (1024 * 1024)))

    def _on_ready(self, staged: str) -> None:
        self._staged = staged
        self._action.setText("Khởi động lại để cài")
        self._action.setEnabled(True)
        self._dismiss.setEnabled(True)
        self._message.setText("Đã tải xong bản %s" % self._release.version)
        self._detail.setText("SẼ THAY THẾ KHI KHỞI ĐỘNG LẠI")

    def _on_failed(self, message: str) -> None:
        logger.warning("Update download failed: %s", message)
        self._action.setEnabled(True)
        self._action.setText("Thử lại")
        self._dismiss.setEnabled(True)
        self._message.setText("Không tải được bản mới")
        self._detail.setText(message[:90].upper())

    # ── shutdown ────────────────────────────────────────────────────────────

    def stop(self) -> None:
        for worker in (self._check, self._download):
            if worker is not None and worker.isRunning():
                if isinstance(worker, DownloadWorker):
                    worker.cancel()
                worker.wait(3000)
