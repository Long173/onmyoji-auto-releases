"""Shared test setup: import path, and the Qt fixtures the UI tests need."""
from __future__ import annotations

import importlib
import os
import sys
import threading
from pathlib import Path

import pytest

SOURCE_DIR = Path(__file__).resolve().parents[1] / "decompiled" / "source"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

# Must be set before Qt picks a platform plugin, so the UI tests run headless.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtCore  # noqa: E402 - after the platform is chosen


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Give every test its own empty settings store.

    The dashboard remembers each window's task queue in QSettings, which on
    Windows means the registry. Without this a test run rewrites the real
    user's settings — and, because the store outlives a single test, one test's
    saved queue decides what the next one starts with.
    """
    import app_settings

    def open_store(scope=app_settings.theme.SETTINGS_SCOPE):
        return QtCore.QSettings(
            str(tmp_path / ("settings-%s.ini" % scope)), QtCore.QSettings.IniFormat
        )

    monkeypatch.setattr(app_settings, "open_store", open_store)
    # Yielded so a test can reopen it: QSettings hands unsynced writes straight
    # back from its own cache, so reading through the same object proves
    # nothing about what a later launch would actually see.
    yield tmp_path / ("settings-%s.ini" % app_settings.theme.SETTINGS_SCOPE)


@pytest.fixture(scope="session")
def qt_app():
    """One QApplication for the whole run — Qt allows only one."""
    QtWidgets = pytest.importorskip("PyQt5.QtWidgets")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


# One entry per task that has a `build` in the registry, keyed by its task id:
#   task id -> (module, worker class)
# The dashboard fixture swaps each worker for SpyWorker. Keyed by id rather
# than by module so the guard test can compare the two sets exactly.
STUBBED_WORKERS = {
    "realm_raid": ("realm_raid", "RealmRaidWorker"),
    "souls": ("souls_dungeon", "SoulsDungeonWorker"),
    "beans": ("demon_parade", "DemonParadeWorker"),
    "event": ("event_clicker", "EventClickerWorker"),
    "exploration": ("exploration", "ExplorationWorker"),
}


def bare_control(hwnd: int = 1, client=(1136, 640)):
    """A GameControl with no window behind it, for tests that stub the capture.

    One factory rather than a copy per test file. Three files were each
    hand-mirroring the constructor, so adding one field to it broke all three at
    once — for a reason that had nothing to do with what they were testing.
    Anything added to ``GameControl.__init__`` belongs here too.
    """
    from game_control import GameControl

    made = GameControl.__new__(GameControl)
    made.hwnd = hwnd
    made.client_width, made.client_height = client
    made.window_width, made.window_height = client
    made._frame_cache = {}
    made._scaled_cache = {}
    made._templates = {}
    made._caching = False
    made._last_frame = None
    made._dc_ready = False
    made._printwindow_failed = False
    return made


PLACEHOLDER_TASK_ID = "_unbuilt_placeholder"


def unbuilt_task_id() -> str:
    """A task the registry declares but does not build.

    Several tests need one to check that the UI refuses to start it. Taken from
    the registry rather than named outright: it used to be spelled "beans", and
    implementing that task turned seven tests red at once for no reason other
    than the stand-in having grown up.

    Every shipped task is implemented now — "Nhiệm vụ truy nã" was the last
    unbuilt one and has been dropped — so this installs its own. The app still
    renders an unbuilt task's "CHƯA CÀI ĐẶT" page, and that path should be
    watched by something: this used to ``pytest.skip``, which would have quietly
    stood ten UI tests down the moment the placeholder left the registry.
    """
    import tasks

    for spec in tasks.TASKS:
        if spec.build is None:
            return spec.id
    spec = tasks.TaskSpec(
        id=PLACEHOLDER_TASK_ID,
        name="Chưa cài đặt",
        kicker="Tác vụ · chỗ giữ chỗ của test",
        summary="Không có trong bản chạy thật; dựng ở đây để kiểm màn của một "
                "tác vụ chưa cài đặt.",
        # It counts, because two tests use this task to check that removing the
        # raid's counter did not remove the counter machinery.
        progress_label="lần đã chạy",
        todo="Chỗ giữ chỗ do bộ test dựng lên, không phải việc đang chờ làm.",
    )
    tasks.TASKS = tasks.TASKS + (spec,)
    tasks.BY_ID[spec.id] = spec
    return spec.id


class SpyWorker(threading.Thread):
    """Stands in for a task worker: runs until asked to stop, records that."""

    live: list = []

    def __init__(self, **kwargs):
        super().__init__(name="SpyWorker", daemon=True)
        self.kwargs = kwargs
        self.progress = 0
        self.elapsed_seconds = 0.0
        self.is_paused = False
        self.stop_called = False
        self._halt = threading.Event()
        SpyWorker.live.append(self)

    def run(self):
        while not self._halt.is_set():
            self._halt.wait(0.02)

    def stop(self):
        self.stop_called = True
        self._halt.set()

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def latest_frame(self):
        return None


class FakeControl:
    def __init__(self, hwnd):
        self.client_width, self.client_height = 1122, 633
        self.closed = False

    def describe(self):
        return "fake control"

    def refresh_metrics(self):
        pass

    def full_shot(self):
        return None

    def close(self):
        self.closed = True


@pytest.fixture
def dashboard(qt_app, monkeypatch):
    """An AutoWindow wired to fake game windows and fake workers."""
    import realm_raid
    import auto.manager as manager_module
    from auto import session as session_module
    from auto.window_scanner import GameWindow

    SpyWorker.live = []

    # Khong cai hook ban phim toan may trong test. AutoWindow._register_hotkeys
    # goi keyboard.add_hotkey cho F1/F2, va thu vien do dung hook cap thap cua
    # Windows kem may luong nen chay ngam — chung khong chet theo cua so, va sau
    # vai chuc dashboard thi ca tien trinh ngã bang access violation giua chung.
    # Cung ly do ma GameControl va cac worker bi thay bang stub o duoi: mot cu
    # access violation khong phai la test fail, no giet ca lan chay.
    #
    # Code that da chiu duoc truong hop nay san — _register_hotkeys bat Exception
    # va chuyen sang F1/F2 chi-khi-dang-chon — nen day khong phai duong tat.
    import keyboard

    monkeypatch.setattr(keyboard, "add_hotkey",
                        lambda *a, **k: object(), raising=False)
    monkeypatch.setattr(keyboard, "remove_hotkey",
                        lambda *a, **k: None, raising=False)

    monkeypatch.setattr(session_module, "GameControl", FakeControl)
    monkeypatch.setattr(session_module, "is_alive", lambda hwnd: True)
    # The other half of the same claim. These hwnds are invented, so the real
    # IsWindow says every one of them has been destroyed — and the dashboard's
    # tick would drop all of them before a test could look.
    monkeypatch.setattr(manager_module.window_scanner, "is_gone",
                        lambda hwnd: False)
    monkeypatch.setattr(realm_raid, "resize_game_window", lambda hwnd: None)

    # Every implemented task, not just the raid. A real worker here captures a
    # window that is not there, fails, and calls back into Qt from its own
    # thread — which on Windows is an access violation that takes the whole
    # test run down, not a failure with a message. `test_every_implemented_task
    # _is_stubbed_for_the_ui_tests` keeps this list honest.
    for module_name, class_name in STUBBED_WORKERS.values():
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, class_name, SpyWorker)

    monkeypatch.setattr(
        manager_module.window_scanner,
        "scan",
        lambda patterns=None: [
            GameWindow(101, "陰陽師Onmyoji", 1122, 633),
            GameWindow(102, "陰陽師Onmyoji — acc 2", 1122, 633),
        ],
    )

    from ui.auto_window import AutoWindow

    window = AutoWindow()
    # Shown so isVisible() actually reflects whether a close was vetoed.
    window.show()
    # The refresh timer would keep polling the fake windows during the test.
    window._timer.stop()
    # Worker callbacks are marshalled through signals; a direct connection keeps
    # them synchronous so a test does not need to spin the event loop.
    window.sessionFinished.disconnect()
    window.sessionFailed.disconnect()
    window.sessionFinished.connect(
        window._on_session_finished, QtCore.Qt.DirectConnection
    )
    window.sessionFailed.connect(
        window._on_session_failed, QtCore.Qt.DirectConnection
    )
    # Closing with workers running raises a modal; answer it without a display.
    # Individual tests override this to exercise the prompt itself.
    monkeypatch.setattr(window, "_confirm_exit", lambda running: True)
    window._on_scan()
    yield window
    # Dong that. `close_to_tray` mac dinh la True, nen close() thuong chi an cua
    # so xuong khay: closeEvent thoat som va khong thao gi ca. Moi dashboard vi
    # the de lai mot native event filter tren QApplication dung chung, va sau
    # vai chuc test thi Qt duyet danh sach do di vao vung nho da giai phong.
    window._force_close = True
    window.close()


@pytest.fixture
def instant_background(monkeypatch):
    """Answer every :class:`ui.background.Busy` call on the spot.

    A test seam, not a shortcut: the thread is tested where it lives, and a
    widget test that waits on one goes flaky on a slow machine. Requested by
    name rather than autouse, so a test that wants the real thread still gets
    it.
    """
    from ui.background import Busy

    def run(self, call, on_done, on_failed):
        try:
            result = call()
        except Exception as exc:  # noqa: BLE001 - mirrors CallWorker
            on_failed(str(exc))
            return
        on_done(result)

    monkeypatch.setattr(Busy, "run", run)
    monkeypatch.setattr(Busy, "wait", lambda self, ms=3000: None)


@pytest.fixture
def quiet_dialogs(monkeypatch):
    """Answer modal message boxes instead of blocking on them.

    Returns the list of (title, text) pairs that were raised, so a test can
    check that something *was* asked. Questions answer Yes; override in the test
    when refusing is the point.
    """
    from PyQt5 import QtWidgets

    raised = []

    def record(answer):
        def show(parent, title, text, *args, **kwargs):
            raised.append((title, text))
            return answer
        return staticmethod(show)

    monkeypatch.setattr(QtWidgets.QMessageBox, "information",
                        record(QtWidgets.QMessageBox.Ok))
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning",
                        record(QtWidgets.QMessageBox.Ok))
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical",
                        record(QtWidgets.QMessageBox.Ok))
    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        record(QtWidgets.QMessageBox.Yes))
    return raised
