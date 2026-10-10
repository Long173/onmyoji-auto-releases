"""Emulators: found over ADB, photographed and tapped through it.

No adb runs here. :class:`adb.Adb` takes its command runner as a seam, and every
test hands it a fake that answers like the real one did on BlueStacks 5 —
including the screencap header, whose exact bytes are what the parser has to
get right. The machine these were written on had BlueStacks open, which is why
conftest keeps the real scan away from every other test.
"""
from __future__ import annotations

import struct
import time

import cv2
import numpy as np
import pytest

import adb
import adb_control
import geometry
from adb_control import AdbControl
from auto import window_scanner
from auto.window_scanner import GameWindow
# Taken before conftest's autouse fixture stubs it out for every test.
from auto.window_scanner import scan_emulators as real_scan_emulators

SERIAL = "127.0.0.1:5555"


def screencap_bytes(frame_bgr: np.ndarray, header: int = 16) -> bytes:
    """What ``adb exec-out screencap`` returns: header, then RGBA rows."""
    height, width = frame_bgr.shape[:2]
    rgba = np.dstack([frame_bgr[:, :, ::-1], np.full((height, width), 255, np.uint8)])
    head = struct.pack("<III", width, height, 1)
    if header == 16:
        head += struct.pack("<I", 1)        # colour space, Android 9 and later
    return head + rgba.tobytes()


class FakeDevice:
    """Answers adb commands for one or more emulators. Records what it is told."""

    def __init__(self, frame=None, packages=None, online=(SERIAL,), open_ports=(5555,)):
        self.frame = frame if frame is not None else np.zeros((900, 1600, 3), np.uint8)
        self.packages = packages if packages is not None else {SERIAL: "com.netease.onmyoji.gb"}
        self.serials = list(online)
        self.open_ports = set(open_ports)
        self.calls = []
        height, width = self.frame.shape[:2]
        self.wm_size = "Physical size: %dx%d\n" % (width, height)

    def __call__(self, args, timeout):
        self.calls.append(list(args[1:]))
        rest = list(args[1:])
        serial = ""
        if rest[:1] == ["-s"]:
            serial, rest = rest[1], rest[2:]
        if rest == ["devices"]:
            lines = ["List of devices attached"]
            lines += ["%s\tdevice" % s for s in self.serials]
            lines += ["127.0.0.1:62001\toffline"]
            return ("\n".join(lines) + "\n").encode()
        if rest[0] == "connect":
            return b"connected to " + rest[1].encode()
        if rest[:2] == ["exec-out", "screencap"]:
            return screencap_bytes(self.frame)
        if rest[0] == "shell" and rest[1] == "wm size":
            return self.wm_size.encode()
        if rest[0] == "shell" and rest[1].startswith("pm list packages"):
            package = self.packages.get(serial)
            return ("package:%s\n" % package).encode() if package else b""
        if rest[0] == "shell":
            return b""
        raise AssertionError("unexpected adb call %r" % (rest,))

    def shell_calls(self):
        return [call[3] for call in self.calls if call[:1] == ["-s"] and call[2] == "shell"]


# ── the screencap format ────────────────────────────────────────────────────

@pytest.mark.parametrize("header", [12, 16])
def test_a_raw_screencap_becomes_a_bgr_frame(header):
    frame = np.zeros((9, 16, 3), np.uint8)
    frame[2, 3] = (10, 20, 30)          # B, G, R
    parsed = adb.parse_screencap(screencap_bytes(frame, header))
    assert parsed.shape == (9, 16, 3)
    assert tuple(parsed[2, 3]) == (10, 20, 30)


@pytest.mark.parametrize("raw", [b"", b"\x00" * 11,
                                 struct.pack("<III", 16, 9, 1) + b"\x00" * 10])
def test_a_screencap_that_does_not_add_up_is_refused(raw):
    with pytest.raises(adb.AdbError):
        adb.parse_screencap(raw)


def test_a_pixel_format_other_than_rgba_is_refused():
    raw = struct.pack("<IIII", 2, 1, 4, 1) + b"\x00" * 8
    with pytest.raises(adb.AdbError, match="not RGBA"):
        adb.parse_screencap(raw)


# ── finding emulators ───────────────────────────────────────────────────────

def test_only_listening_ports_are_connected_to():
    device = FakeDevice()
    tool = adb.Adb("adb", runner=device)
    tool.discover(ports=(5555, 5565, 62001), probe=lambda port: port == 5555)
    connects = [call for call in device.calls if call[0] == "connect"]
    assert connects == [["connect", "127.0.0.1:5555"]]


def test_an_emulator_with_the_game_is_found_at_its_own_resolution():
    device = FakeDevice(frame=np.zeros((900, 1600, 3), np.uint8))
    found = adb.Adb("adb", runner=device).discover(ports=(), probe=lambda p: False)
    assert found == [adb.Device(SERIAL, 1600, 900, "com.netease.onmyoji.gb")]
    assert found[0].port == 5555


def test_an_emulator_without_the_game_is_left_out():
    device = FakeDevice(packages={})
    assert adb.Adb("adb", runner=device).discover(ports=(), probe=lambda p: False) == []


def test_one_emulator_listed_twice_is_one_card():
    """emulator-5554 and 127.0.0.1:5555 are the same BlueStacks."""
    device = FakeDevice(online=("emulator-5554", SERIAL),
                        packages={"emulator-5554": "com.netease.onmyoji.gb",
                                  SERIAL: "com.netease.onmyoji.gb"})
    found = adb.Adb("adb", runner=device).discover(ports=(), probe=lambda p: False)
    assert [d.serial for d in found] == [SERIAL]


def test_offline_devices_are_not_online():
    assert adb.Adb("adb", runner=FakeDevice()).online() == [SERIAL]


def test_probing_is_done_all_at_once():
    """A closed localhost port costs the whole timeout on Windows; one after
    another, the known ports took 3.7 s with BlueStacks open."""
    slow = lambda port: time.sleep(0.05) or False   # noqa: E731
    started = time.monotonic()
    adb.Adb("adb", runner=FakeDevice()).discover(probe=slow)
    assert time.monotonic() - started < 0.05 * len(adb.KNOWN_PORTS) / 2


def test_a_scan_shows_each_emulator_as_a_game_window(monkeypatch):
    device = FakeDevice()
    monkeypatch.setattr(adb, "shared", lambda: adb.Adb("adb", runner=device))
    monkeypatch.setattr(adb, "port_is_open", lambda port, *a, **k: False)
    [window] = real_scan_emulators()
    assert window.is_emulator and window.serial == SERIAL
    assert window.hwnd < 0, "a stand-in handle must never be a real one"
    assert (window.client_width, window.client_height) == (1600, 900)
    assert window.handle_text == "ADB 127.0.0.1:5555"
    assert window.title == "Giả lập · 5555"
    assert window_scanner.is_alive(window.hwnd)


def test_no_adb_means_no_emulators(monkeypatch):
    monkeypatch.setattr(adb, "shared", lambda: None)
    assert real_scan_emulators() == []


# ── the stand-in handle ─────────────────────────────────────────────────────

def test_an_emulator_keeps_its_handle_across_scans():
    first = window_scanner.emulator_key("127.0.0.1:61999")
    assert window_scanner.emulator_key("127.0.0.1:61999") == first < 0
    assert window_scanner.emulator_serial(first) == "127.0.0.1:61999"
    assert window_scanner.emulator_key("127.0.0.1:61998") != first


def test_windows_questions_are_answered_for_an_emulator_without_windows(monkeypatch):
    """None of these may reach win32 with a negative handle."""
    key = window_scanner.emulator_key("127.0.0.1:61997")
    monkeypatch.setattr(window_scanner.win32gui, "IsWindow",
                        lambda h: pytest.fail("asked Windows about an emulator"))
    monkeypatch.setattr(window_scanner.win32gui, "IsIconic",
                        lambda h: pytest.fail("asked Windows about an emulator"))
    assert window_scanner.is_gone(key) is False
    assert window_scanner.is_minimised(key) is False
    assert window_scanner.open_if_minimised(key) is True


def test_open_control_picks_adb_for_an_emulator(monkeypatch):
    key = window_scanner.emulator_key(SERIAL)
    made = []
    monkeypatch.setattr(adb_control, "AdbControl",
                        lambda serial, hwnd: made.append((serial, hwnd)) or "adb")
    assert adb_control.open_control(key, lambda h: "window") == "adb"
    assert made == [(SERIAL, key)]
    assert adb_control.open_control(0x1234, lambda h: "window") == "window"


# ── the control ─────────────────────────────────────────────────────────────

def control_on(device):
    return AdbControl(SERIAL, -1, adb=adb.Adb("adb", runner=device))


def test_the_control_takes_the_devices_size_as_its_client():
    control = control_on(FakeDevice(frame=np.zeros((900, 1600, 3), np.uint8)))
    assert (control.client_width, control.client_height) == (1600, 900)
    assert control.client_is_measurable
    assert control.describe() == "adb=127.0.0.1:5555 screen=1600x900"


def test_a_tap_goes_to_the_devices_own_pixels():
    device = FakeDevice()
    assert control_on(device).click((800, 450)) is True
    assert device.shell_calls() == ["input tap 800 450"]


def test_a_drag_is_one_swipe_as_long_as_the_windows_drag():
    device = FakeDevice()
    control_on(device).drag((1000, 400), (300, 400))
    [swipe] = device.shell_calls()
    *points, milliseconds = swipe.split()[2:]
    assert points == ["1000", "400", "300", "400"]
    assert int(milliseconds) >= 700


def test_taps_are_never_held_for_the_cursor():
    """ADB taps do not share the player's mouse, so there is nothing to wait for."""
    assert control_on(FakeDevice()).withholding_clicks() is False


def test_a_template_is_found_at_the_devices_scale():
    """Matching stretches a 1600x900 frame to the reference size and maps back."""
    rng = np.random.default_rng(7)
    template = rng.integers(0, 255, (40, 60), np.uint8)
    ref = np.full((633, 1122), 128, np.uint8)
    ref[300:340, 500:560] = template
    frame = cv2.resize(np.dstack([ref] * 3), (1600, 900),
                       interpolation=cv2.INTER_CUBIC)
    control = control_on(FakeDevice(frame=frame))
    control._template = lambda path, gray: template
    score, (x, y) = control.match("template", delay=0)
    assert score > 0.9
    scale = 1600 / geometry.REFERENCE_CLIENT_SIZE[0]
    assert abs(x - 530 * scale) <= 3 and abs(y - 320 * scale) <= 3


def test_a_resolution_change_is_followed():
    device = FakeDevice(frame=np.zeros((900, 1600, 3), np.uint8))
    control = control_on(device)
    device.frame = np.zeros((720, 1280, 3), np.uint8)
    control.full_shot()
    assert (control.client_width, control.client_height) == (1280, 720)


def test_a_failed_screencap_is_a_capture_error():
    from game_control import CaptureError

    def broken(args, timeout):
        if "screencap" in args:
            raise adb.AdbError("device offline")
        return b""

    control = AdbControl(SERIAL, -1, adb=adb.Adb("adb", runner=broken))
    with pytest.raises(CaptureError):
        control.full_shot()


def test_a_preview_answers_at_once_and_refreshes_behind():
    """Thumbnails are taken on the UI thread; a screencap costs 0.19 s."""
    device = FakeDevice()
    control = control_on(device)
    first = control.preview()
    assert first is not None
    control._preview_at = 0.0                    # make it stale
    before = sum(1 for c in device.calls if "screencap" in c)
    control.preview()
    control._preview_thread.join(timeout=2)
    assert sum(1 for c in device.calls if "screencap" in c) == before + 1


def test_a_session_on_an_emulator_does_not_resize_a_window(monkeypatch):
    import realm_raid
    from auto import session as session_module

    window = GameWindow(window_scanner.emulator_key(SERIAL), "emu", 1600, 900,
                        serial=SERIAL)

    class Control:
        client_width, client_height = 1600, 900
        client_is_measurable = True

        def refresh_metrics(self):
            pass

    class Worker:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(session_module, "open_control", lambda hwnd, cls: Control())
    monkeypatch.setattr(session_module, "is_alive", lambda hwnd: True)
    monkeypatch.setattr(realm_raid, "resize_game_window",
                        lambda hwnd: pytest.fail("resized an emulator"))
    monkeypatch.setattr(realm_raid, "RealmRaidWorker", Worker)
    import tasks

    session = session_module.GameSession(window, task_id="realm_raid")
    session.start(tasks.merge_layers(tasks.coerce_app(None),
                                     tasks.BY_ID["realm_raid"].coerce({})))
    assert session.status == session_module.RUNNING


@pytest.mark.parametrize("path, brand", [
    (r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe", "BlueStacks"),
    (r"C:\LDPlayer\LDPlayer9\adb.exe", "LDPlayer"),
    (r"C:\Program Files\Nox\bin\nox_adb.exe", "Nox"),
    (r"C:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe", "MuMu"),
    (r"C:\Program Files\Microvirt\MEmu\adb.exe", "MEmu"),
    (r"C:\tools\adb.exe", "Giả lập"),
])
def test_a_card_is_named_after_the_emulator_that_brought_adb(path, brand):
    assert adb.brand_of(path) == brand


# ── after the review ────────────────────────────────────────────────────────

@pytest.mark.parametrize("answer, size", [
    ("Physical size: 1600x900\n", (1600, 900)),
    ("Physical size: 1080x1920\n", (1920, 1080)),            # portrait device
    ("Physical size: 1080x1920\nOverride size: 900x1600\n", (1600, 900)),
    ("", (0, 0)),
])
def test_the_screen_size_is_read_landscape(answer, size):
    device = FakeDevice()
    device.wm_size = answer
    assert adb.Adb("adb", runner=device).screen_size(SERIAL) == size


def test_a_scan_does_not_need_a_frame():
    """A scan that photographed each device dropped it whenever one capture
    failed — and a running card then sat at "Mất cửa sổ" for good."""
    device = FakeDevice()

    def no_screencap(args, timeout):
        if "screencap" in args:
            raise adb.AdbError("busy")
        return device(args, timeout)

    found = adb.Adb("adb", runner=no_screencap).discover(ports=(), probe=lambda p: False)
    assert [(d.serial, d.width, d.height) for d in found] == [(SERIAL, 1600, 900)]


def test_an_emulator_that_stops_answering_is_gone(monkeypatch):
    """Closed mid-run, its card used to say "đang chạy" forever."""
    from game_control import CaptureError

    monkeypatch.setattr(adb_control, "LOST_AFTER_SECONDS", 0)
    serial = "127.0.0.1:61990"
    key = window_scanner.emulator_key(serial)
    window_scanner._emulators_seen.add(serial)
    device = FakeDevice()
    answering = [True]

    def runner(args, timeout):
        if "screencap" in args and not answering[0]:
            raise adb.AdbError("device offline")
        return device(args, timeout)

    control = AdbControl(serial, key, adb=adb.Adb("adb", runner=runner))
    assert window_scanner.is_alive(key) and not window_scanner.is_gone(key)
    answering[0] = False
    for _ in range(2):
        with pytest.raises(CaptureError):
            control.full_shot()
    assert window_scanner.is_gone(key) and not window_scanner.is_alive(key)
    answering[0] = True
    control.full_shot()
    assert window_scanner.is_alive(key) and not window_scanner.is_gone(key)


def test_refused_taps_end_the_run_with_a_message(monkeypatch):
    """BlueStacks with ADB off still answers screencaps but closes every tap.
    The run used to see the board, press nothing and report nothing."""
    device = FakeDevice()

    def runner(args, timeout):
        if "input tap" in " ".join(args):
            raise adb.AdbError("-s 127.0.0.1:5555 exited 1: error: closed")
        return device(args, timeout)

    control = AdbControl(SERIAL, -1, adb=adb.Adb("adb", runner=runner))
    for _ in range(adb_control.TAP_FAILURE_LIMIT - 1):
        assert control.click((10, 10)) is False
    with pytest.raises(adb_control.EmulatorRefusesInput, match="bật ADB"):
        control.click((10, 10))


def test_one_refused_tap_is_forgiven():
    device = FakeDevice()
    refuse = [True]

    def runner(args, timeout):
        if "input tap" in " ".join(args) and refuse[0]:
            refuse[0] = False
            raise adb.AdbError("glitch")
        return device(args, timeout)

    control = AdbControl(SERIAL, -1, adb=adb.Adb("adb", runner=runner))
    assert control.click((10, 10)) is False
    assert control.click((10, 10)) is True
    assert control._tap_failures == 0
