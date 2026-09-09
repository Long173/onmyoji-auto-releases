"""Recording a game window to an .mp4.

The recorder writes real files, so these tests write to ``tmp_path`` and feed it
a fake window rather than a real one — a suite that grabbed the screen would be
slow, would need a game running, and would record whatever happened to be on
screen at the time.

Two properties matter more than the rest, and neither is visible by watching the
app work:

* **The writer is always released.** An .mp4 whose writer was never released does
  not play at all. Losing a recording that way is worse than never starting one,
  because the user believes they have it.
* **A momentary loss of the window is not the end.** A window being resized or
  minimised fails to capture for a fraction of a second; treating the first miss
  as fatal would stop recordings for no reason anybody could see.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

import recorder
from recorder import WindowRecorder

SIZE = (633, 1122, 3)


class FakeControl:
    """A window that hands back frames, and can be told to stop doing so."""

    def __init__(self, frames=None):
        self.client_width, self.client_height = 1122, 633
        self.closed = False
        self.grabs = 0
        # A list of frames or Nones to serve in order; the last repeats.
        self.script = list(frames or [])

    def full_shot(self, gray: bool = False):
        self.grabs += 1
        if not self.script:
            return np.full(SIZE, 40, dtype=np.uint8)
        index = min(self.grabs - 1, len(self.script) - 1)
        return self.script[index]

    def close(self):
        self.closed = True


def a_frame(value=40):
    return np.full(SIZE, value, dtype=np.uint8)


def run_briefly(made: WindowRecorder, seconds: float = 0.6) -> WindowRecorder:
    made.start()
    time.sleep(seconds)
    made.stop()
    made.join(timeout=5)
    assert not made.is_alive(), "the recorder thread did not finish"
    return made


# ── the file ────────────────────────────────────────────────────────────────


def test_it_writes_a_playable_file(tmp_path):
    target = tmp_path / "out.mp4"
    made = WindowRecorder(1, target=target, fps=20, control=FakeControl())

    run_briefly(made)

    assert made.error == "", made.error
    assert target.is_file()
    assert target.stat().st_size > 0
    assert made.frames > 1


def test_the_file_can_be_read_back(tmp_path):
    """Written but unplayable is the failure mode this guards."""
    import cv2

    target = tmp_path / "out.mp4"
    made = WindowRecorder(1, target=target, fps=20, control=FakeControl())
    run_briefly(made)

    cap = cv2.VideoCapture(str(target))
    try:
        read = 0
        while cap.read()[0]:
            read += 1
    finally:
        cap.release()

    assert read > 1, "the file has no frames in it"


def test_the_writer_is_released_even_when_it_crashes(tmp_path, monkeypatch):
    """Whatever happens, the .mp4 must be closed and playable.

    Wrapped rather than patched: ``cv2.VideoWriter.release`` is read-only on the
    instance, so a spy has to stand in front of the whole object.
    """
    released = []
    real = recorder.cv2.VideoWriter

    class Spy:
        def __init__(self, *args, **kwargs):
            self._inner = real(*args, **kwargs)

        def isOpened(self):
            return self._inner.isOpened()

        def write(self, frame):
            return self._inner.write(frame)

        def release(self):
            released.append(True)
            return self._inner.release()

    class Boom(FakeControl):
        def full_shot(self, gray: bool = False):
            if self.grabs > 1:
                raise RuntimeError("window went away")
            return super().full_shot(gray)

    monkeypatch.setattr(recorder.cv2, "VideoWriter", Spy)
    made = WindowRecorder(1, target=tmp_path / "boom.mp4", fps=40,
                          control=Boom())
    run_briefly(made, 0.4)

    assert released == [True]


def test_a_borrowed_control_is_left_open(tmp_path):
    """It belongs to the caller; closing it would break the window's preview."""
    control = FakeControl()
    made = WindowRecorder(1, target=tmp_path / "out.mp4", fps=20, control=control)

    run_briefly(made)

    assert control.closed is False


# ── losing the window ───────────────────────────────────────────────────────


def test_one_missed_frame_does_not_stop_it(tmp_path):
    """A window being resized fails for a moment and comes back."""
    script = [a_frame(), None, a_frame(50), None, a_frame(60), a_frame(70)]
    made = WindowRecorder(1, target=tmp_path / "out.mp4", fps=40,
                          control=FakeControl(script))

    run_briefly(made, 0.5)

    assert made.error == ""
    assert made.frames > 1


def test_losing_the_window_for_long_enough_stops_it(tmp_path, monkeypatch):
    """And says so, rather than writing an ever-growing file of nothing."""
    monkeypatch.setattr(recorder, "MAX_MISSES", 3)
    script = [a_frame(), None, None, None, None, None]
    made = WindowRecorder(1, target=tmp_path / "out.mp4", fps=40,
                          control=FakeControl(script))

    made.start()
    made.join(timeout=5)

    assert "Mất hình" in made.error, made.error


def test_a_window_that_never_captures_reports_it(tmp_path):
    made = WindowRecorder(1, target=tmp_path / "out.mp4", fps=20,
                          control=FakeControl([None]))

    made.start()
    made.join(timeout=5)

    assert made.error
    assert made.frames == 0


def test_a_frame_that_changes_size_is_skipped(tmp_path, monkeypatch):
    """A resized window gives frames the open writer cannot accept."""
    monkeypatch.setattr(recorder, "MAX_MISSES", 3)
    odd = np.full((400, 800, 3), 40, dtype=np.uint8)
    made = WindowRecorder(1, target=tmp_path / "out.mp4", fps=40,
                          control=FakeControl([a_frame(), odd, odd, odd, odd]))

    made.start()
    made.join(timeout=5)

    assert made.error, "a differently sized frame was written into the file"


# ── pace ────────────────────────────────────────────────────────────────────


def test_it_records_at_about_the_asked_rate(tmp_path):
    """Paced against a clock, so playback is not slower than real life.

    Sleeping a fixed amount per frame would stretch the interval by however long
    the capture took, and a recording of a 30-second run would play for 40.
    """
    made = WindowRecorder(1, target=tmp_path / "out.mp4", fps=20,
                          control=FakeControl())

    run_briefly(made, 1.0)

    # Generous bounds: this is about the pacing being *applied*, not about
    # timing precision on a busy test runner.
    assert 8 <= made.frames <= 40, made.frames


def test_stopping_is_prompt(tmp_path):
    made = WindowRecorder(1, target=tmp_path / "out.mp4", fps=2,
                          control=FakeControl())
    made.start()
    time.sleep(0.2)

    started = time.monotonic()
    made.stop()
    made.join(timeout=5)

    # Waiting on the stop event rather than sleeping means a slow frame rate
    # does not make the button feel stuck.
    assert time.monotonic() - started < 1.0


# ── names and places ────────────────────────────────────────────────────────


def test_the_name_sorts_by_time_and_says_which_window(tmp_path):
    early = recorder.default_name("Onmyoji", datetime(2026, 8, 27, 9, 0, 0))
    later = recorder.default_name("Onmyoji", datetime(2026, 8, 27, 21, 0, 0))

    assert early < later
    assert early.endswith(".mp4")
    assert "Onmyoji" in early


def test_a_hostile_window_title_cannot_escape_the_filename(tmp_path):
    """Titles come from other people's game windows, not from us."""
    name = recorder.default_name(r"..\..\evil name/with:bits")

    assert "/" not in name and "\\" not in name and ":" not in name
    assert name.endswith(".mp4")


def test_the_size_is_read_from_disk(tmp_path):
    """Counted bytes would drift from what the user actually finds."""
    target = tmp_path / "out.mp4"
    made = WindowRecorder(1, target=target, fps=20, control=FakeControl())
    run_briefly(made)

    assert made.size_bytes() == target.stat().st_size


def test_the_size_of_a_file_that_is_not_there_is_zero(tmp_path):
    made = WindowRecorder(1, target=tmp_path / "never.mp4", control=FakeControl())

    assert made.size_bytes() == 0


# ── the thread itself ───────────────────────────────────────────────────────


def test_the_stop_flag_does_not_shadow_the_thread_s_own(tmp_path):
    """``threading.Thread`` has a private ``_stop`` that ``join()`` calls.

    Naming the event ``_stop`` shadowed it, and joining then failed with
    "'Event' object is not callable" — raised from inside the standard library,
    nowhere near the mistake.
    """
    made = WindowRecorder(1, target=tmp_path / "out.mp4", control=FakeControl())

    assert callable(made._stop)
    assert isinstance(made._stop_event, threading.Event)


# ── the button, and what the window does with it ────────────────────────────
#
# The recorder is stubbed here. Left real it would build a GameControl on a
# window id that does not exist, and the point of these tests is the wiring.


@pytest.fixture
def fake_recorder(monkeypatch):
    """Stands in for the recorder, and records how it was driven."""
    made = []

    class Fake:
        def __init__(self, hwnd, fps=10, title="", **kwargs):
            self.hwnd, self.fps, self.title = hwnd, fps, title
            self.started = self.stopped = False
            self.frames = 12
            self.error = ""
            self.elapsed_seconds = 65.0
            self.path = Path("somewhere") / "out.mp4"
            made.append(self)

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

        def join(self, timeout=None):
            pass

        def size_bytes(self):
            return 3_000_000

    monkeypatch.setattr(recorder, "WindowRecorder", Fake)
    return made


def hush(window, monkeypatch):
    """Keep the notifier's dialog fallback from opening a modal in a test."""
    said = []
    monkeypatch.setattr(window._notifier, "notify",
                        lambda title, body, *a, **k: said.append(body))
    return said


def test_the_control_panel_row_asks_to_record(qt_app, dashboard, monkeypatch):
    hush(dashboard, monkeypatch)
    asked = []
    row = dashboard._home._rows[101]
    row.recordRequested.connect(asked.append)

    row._record.click()

    assert asked == [101]


def test_a_task_page_card_asks_to_record(qt_app, dashboard, monkeypatch):
    hush(dashboard, monkeypatch)
    dashboard._manager.select(101, "realm_raid")
    dashboard._show_page("realm_raid")
    dashboard._rebuild()
    asked = []
    card = dashboard._views["realm_raid"]._cards[101]
    card.recordRequested.connect(asked.append)

    card._record.click()

    assert asked == [101]


def test_one_button_starts_and_stops(qt_app, dashboard, monkeypatch, fake_recorder):
    """A window is either being recorded or it is not; two buttons would waste a
    slot on one that is always disabled."""
    said = hush(dashboard, monkeypatch)

    dashboard._on_record(101)
    assert len(fake_recorder) == 1 and fake_recorder[0].started
    assert 101 in dashboard._recorders

    dashboard._on_record(101)

    assert fake_recorder[0].stopped
    assert 101 not in dashboard._recorders
    assert said == [], "finishing should be silent"


def test_a_recorder_that_failed_reports_the_reason(qt_app, dashboard, monkeypatch, fake_recorder):
    said = hush(dashboard, monkeypatch)
    dashboard._on_record(101)
    fake_recorder[0].error = "Bản này không ghi được video (thiếu bộ mã hoá)."

    dashboard._on_record(101)

    assert said == [fake_recorder[0].error]


def test_the_fps_setting_is_used(qt_app, dashboard, monkeypatch, fake_recorder):
    hush(dashboard, monkeypatch)
    dashboard._manager.set_app_option("record_fps", "15 fps")

    dashboard._on_record(101)

    assert fake_recorder[0].fps == 15


def test_a_missing_fps_setting_falls_back(qt_app, dashboard, monkeypatch, fake_recorder):
    hush(dashboard, monkeypatch)
    dashboard._manager.set_app_option("record_fps", "")

    dashboard._on_record(101)

    assert fake_recorder[0].fps == recorder.DEFAULT_FPS


def test_two_windows_record_at_once(qt_app, dashboard, monkeypatch, fake_recorder):
    hush(dashboard, monkeypatch)

    dashboard._on_record(101)
    dashboard._on_record(102)

    assert set(dashboard._recorders) == {101, 102}


def test_closing_the_app_stops_every_recording(qt_app, dashboard, monkeypatch, fake_recorder):
    """An unreleased writer leaves an .mp4 that will not play."""
    from PyQt5 import QtGui

    hush(dashboard, monkeypatch)
    monkeypatch.setattr(dashboard._manager, "shutdown", lambda: None)
    monkeypatch.setattr(dashboard._update_banner, "stop", lambda: None)
    monkeypatch.setattr(dashboard, "_unregister_hotkeys", lambda: None)
    monkeypatch.setattr(dashboard, "_hides_to_tray", lambda: False)
    dashboard._on_record(101)

    dashboard.closeEvent(QtGui.QCloseEvent())

    assert fake_recorder[0].stopped
    assert dashboard._recorders == {}


def test_the_button_shows_the_time_and_size_while_recording(qt_app, dashboard, monkeypatch, fake_recorder):
    """26 MB a minute is the one thing here that can quietly fill a disk."""
    hush(dashboard, monkeypatch)
    dashboard._on_record(101)

    dashboard._show_recordings()

    text = dashboard._home._rows[101]._record.text()
    assert "1:05" in text, text
    assert "3 MB" in text, text


def test_the_button_goes_back_to_quay_when_stopped(qt_app, dashboard, monkeypatch, fake_recorder):
    hush(dashboard, monkeypatch)
    dashboard._on_record(101)
    dashboard._show_recordings()
    dashboard._on_record(101)

    dashboard._show_recordings()

    assert dashboard._home._rows[101]._record.text() == "Quay"


def test_recording_an_unknown_window_does_nothing(qt_app, dashboard, monkeypatch, fake_recorder):
    hush(dashboard, monkeypatch)

    dashboard._on_record(999)

    assert dashboard._recorders == {}
    assert fake_recorder == []


# ── getting to the file afterwards ──────────────────────────────────────────


def test_stopping_remembers_the_file(qt_app, dashboard,
                                                          monkeypatch, fake_recorder):
    """So the folder button lands on the folder that has it."""
    hush(dashboard, monkeypatch)
    dashboard._on_record(101)

    dashboard._on_record(101)

    assert dashboard._last_saved is not None
    assert dashboard._last_saved.name == "out.mp4"


def test_finishing_a_recording_says_nothing(qt_app, dashboard, monkeypatch,
                                            fake_recorder):
    """By request, and it is the right call.

    The file is reachable from the folder button on the same row the recording
    was started from — a toast describing what the user had just watched happen
    was noise.
    """
    said = hush(dashboard, monkeypatch)
    dashboard._on_record(101)

    dashboard._on_record(101)

    assert said == []


def test_the_folder_button_opens_the_folder(qt_app, dashboard, monkeypatch,
                                            fake_recorder):
    """On the row, where somebody who just stopped a recording is looking."""
    from PyQt5 import QtGui

    hush(dashboard, monkeypatch)
    opened = []
    monkeypatch.setattr(QtGui.QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url.toLocalFile())))

    dashboard._home._rows[101]._reveal.click()

    assert opened, "the folder button did nothing"


def test_the_folder_button_works_before_anything_is_recorded(qt_app, dashboard,
                                                             monkeypatch):
    """A button that only works after a recording reads as broken before one."""
    from PyQt5 import QtGui

    hush(dashboard, monkeypatch)
    opened = []
    monkeypatch.setattr(QtGui.QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url.toLocalFile())))

    dashboard._on_reveal(101)

    assert opened and "recordings" in opened[0]


def test_clicking_the_notification_opens_the_folder(qt_app, dashboard, monkeypatch,
                                                    fake_recorder):
    from PyQt5 import QtGui

    hush(dashboard, monkeypatch)
    opened = []
    monkeypatch.setattr(QtGui.QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url.toLocalFile())))
    dashboard._on_record(101)
    dashboard._on_record(101)

    dashboard._reveal_last_saved()

    assert opened and opened[0].endswith("somewhere")


def test_clicking_with_nothing_saved_yet_opens_the_recordings_folder(
    qt_app, dashboard, monkeypatch
):
    """Rather than doing nothing, which reads as a broken click."""
    from PyQt5 import QtGui

    hush(dashboard, monkeypatch)
    opened = []
    monkeypatch.setattr(QtGui.QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url.toLocalFile())))

    dashboard._reveal_last_saved()

    assert opened and "recordings" in opened[0]


def test_a_failed_recording_is_not_remembered_as_saved(qt_app, dashboard,
                                                       monkeypatch, fake_recorder):
    """There is no file to open, so the toast must not offer one."""
    hush(dashboard, monkeypatch)
    dashboard._on_record(101)
    fake_recorder[0].error = "Mất hình quá lâu — đã dừng quay."

    dashboard._on_record(101)

    assert dashboard._last_saved is None


def test_the_settings_page_links_to_both_folders(qt_app):
    """The half that always works: Windows makes no promise about toast clicks."""
    from PyQt5 import QtWidgets as W
    from ui.settings_page import SettingsPage

    page = SettingsPage({})
    texts = [c.text() for c in page.findChildren(W.QLabel)]

    assert any("recordings" in t for t in texts), "no link to the video folder"
    assert any("snapshots" in t for t in texts), "no link to the picture folder"
    page.deleteLater()


def test_the_folder_links_open_without_leaving_the_app_to_do_it(qt_app):
    """``file://`` links with external links on need no code behind them."""
    from PyQt5 import QtWidgets as W
    from ui.settings_page import SettingsPage

    page = SettingsPage({})
    links = [c for c in page.findChildren(W.QLabel) if "recordings" in c.text()]

    assert links
    assert links[0].openExternalLinks()
    assert "file:///" in links[0].text()
    page.deleteLater()
