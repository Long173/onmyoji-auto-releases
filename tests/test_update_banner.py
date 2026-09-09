"""The update strip: hidden until there is something to install.

Network and disk are stubbed — what is checked here is the wiring: that a
found release surfaces, that the one button walks check → download → restart,
and that a failure leaves the strip usable rather than stuck.
"""
from __future__ import annotations

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")

import updater  # noqa: E402
from ui.update_banner import UpdateBanner  # noqa: E402

RELEASE = updater.Release(
    version="2.2",
    url="https://example.test/app.exe",
    sha256="abc",
    size=107_000_000,
    published="2026-08-20",
    notes="Sửa nhận diện hết vé",
)


@pytest.fixture
def banner(qt_app):
    made = UpdateBanner()
    yield made
    made.stop()
    made.deleteLater()


def button_text(banner):
    return banner._action.text()


# ── visibility ──────────────────────────────────────────────────────────────


def test_hidden_until_there_is_an_update(banner):
    assert banner.isHidden(), "the strip shows even with nothing to install"


def test_a_found_release_is_announced(banner):
    banner._on_found(RELEASE)

    assert not banner.isHidden()
    assert "2.2" in banner._message.text()
    assert "102 MB" in banner._detail.text(), "the download size is not shown"
    assert "SỬA NHẬN DIỆN" in banner._detail.text()


def test_dismissing_hides_it(banner):
    banner._on_found(RELEASE)
    banner._dismiss.click()
    assert banner.isHidden()


# ── the check ───────────────────────────────────────────────────────────────


def test_no_check_runs_when_updates_are_off(banner, monkeypatch):
    """Running from source, or with no URL configured."""
    monkeypatch.setattr(updater, "can_update", lambda: False)
    started = []
    monkeypatch.setattr(
        "ui.update_banner.CheckWorker",
        lambda version: started.append(version) or pytest.fail("a check was started"),
    )

    banner.check_in_background()

    assert banner.isHidden()


# ── download, then restart ──────────────────────────────────────────────────


def test_the_button_walks_download_to_restart(banner, monkeypatch, tmp_path):
    banner._on_found(RELEASE)
    assert button_text(banner) == "Cập nhật"

    # Replace the worker: the download itself is covered in test_updater.
    class FakeDownload:
        def __init__(self, release, target):
            self.progressed = _Signal()
            self.ready = _Signal()
            self.failed = _Signal()
            self.target = target

        def start(self):
            self.progressed.emit(50, 100)

        def isRunning(self):
            return False

        def cancel(self):
            pass

        def wait(self, _ms):
            pass

    monkeypatch.setattr("ui.update_banner.DownloadWorker", FakeDownload)
    monkeypatch.setattr(updater, "staged_path", lambda: tmp_path / "app.exe.new")

    banner._action.click()
    assert "50%" in button_text(banner), "progress is not shown on the button"

    banner._on_ready(str(tmp_path / "app.exe.new"))
    assert button_text(banner) == "Khởi động lại để cài"
    assert banner._action.isEnabled()

    asked = []
    banner.restartRequested.connect(asked.append)
    banner._action.click()
    assert asked == [str(tmp_path / "app.exe.new")]


def test_a_failed_download_can_be_retried(banner):
    banner._on_found(RELEASE)
    banner._on_failed("Không kết nối được")

    assert button_text(banner) == "Thử lại"
    assert banner._action.isEnabled(), "the strip is stuck after a failure"
    assert banner._dismiss.isEnabled()
    assert "KHÔNG KẾT NỐI" in banner._detail.text()


def test_progress_without_a_known_total_shows_megabytes(banner):
    banner._on_found(RELEASE)
    banner._on_progress(3 * 1024 * 1024, 0)
    assert "3 MB" in button_text(banner)


class _Signal:
    """Minimal stand-in for a pyqtSignal on the fake worker."""

    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *args):
        for slot in self._slots:
            slot(*args)
