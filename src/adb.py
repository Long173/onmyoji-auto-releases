"""Talking to Android emulators over ADB: find them, photograph them, tap them.

An emulator (BlueStacks, LDPlayer, Nox, MuMu, MEmu) runs the same game as the
PC client, on the same servers and with the same screens — measured on
BlueStacks 5 at 1600x900, shrunk to the reference size, the PC templates match
it as they are: the world map's Realm Raid button 0.942, the chapter panel's
Exploration button 0.982, the ticket counter's digits 0.93-0.99. What does not
carry over is how the window is reached. An emulator draws the game with
OpenGL into a child window wrapped in its own toolbars; PrintWindow sees black
or the wrong thing, and many emulators drop posted mouse messages. So for an
emulator the frame and the taps go through ADB, which every one of them runs
and which does not care whether the window is covered, minimised or focused.

Every emulator serves ADB on localhost, on ports of its own choosing; see
:data:`KNOWN_PORTS`. A port is only handed to ``adb connect`` once a plain
socket has found something listening there, so a scan with no emulator open
costs a dozen refused connections and no adb at all.

``adb`` itself is not shipped. Every emulator brings its own — BlueStacks'
is ``HD-Adb.exe`` — and two different adb versions on one machine kill each
other's server, so the one the emulator already uses is the one to use.

Nothing here imports Qt or win32; :mod:`adb_control` puts it behind the same
interface as :class:`game_control.GameControl`.
"""
from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"

# Where each emulator listens, first instance first. Multi-instance managers
# step the port: BlueStacks by 10, LDPlayer by 2, MuMu 12 by 32.
KNOWN_PORTS: Tuple[int, ...] = (
    5555, 5557, 5559, 5561, 5563, 5565, 5575, 5585, 5595,   # BlueStacks, LDPlayer
    62001, 62025, 62026, 62027, 62028, 62029,               # Nox
    16384, 16416, 16448, 16480,                             # MuMu 12
    7555,                                                   # MuMu 6
    21503, 21513, 21523,                                    # MEmu
)
PROBE_TIMEOUT_SECONDS = 0.15
COMMAND_TIMEOUT_SECONDS = 10.0
SCREENCAP_TIMEOUT_SECONDS = 5.0
# A window scan runs on the UI thread, so everything it asks adb is kept short.
SCAN_TIMEOUT_SECONDS = 3.0

# The game's Android packages: the global build is com.netease.onmyoji.gb.
GAME_PACKAGE_PREFIX = "com.netease.onmyoji"

# The bundled adb of each emulator, relative to its install folder, and the
# folders those usually are. Searched in order; PATH last.
ADB_NAMES = ("HD-Adb.exe", "adb.exe", "nox_adb.exe")
INSTALL_DIRS = (
    r"C:\Program Files\BlueStacks_nxt",
    r"C:\Program Files\BlueStacks",
    r"C:\LDPlayer\LDPlayer9",
    r"C:\LDPlayer\LDPlayer4.0",
    r"C:\Program Files\Nox\bin",
    r"C:\Program Files (x86)\Nox\bin",
    r"C:\Program Files\Netease\MuMuPlayer-12.0\shell",
    r"C:\Program Files\Netease\MuMu Player 12\shell",
    r"C:\Program Files\Microvirt\MEmu",
)

# A console window would flash up for every adb call from the windowless app.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class AdbError(RuntimeError):
    """An adb command failed or produced something unusable."""


def _registry_install_dirs() -> List[str]:
    """Install folders the emulators recorded in the registry, where readable."""
    found: List[str] = []
    try:
        import winreg
    except ImportError:          # not Windows: nothing to read
        return found
    keys = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\BlueStacks_nxt", "InstallDir"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\BlueStacks", "InstallDir"),
        (winreg.HKEY_CURRENT_USER, r"Software\leidian\ldplayer9", "InstallDir"),
    )
    for root, path, name in keys:
        try:
            with winreg.OpenKey(root, path) as key:
                value, _ = winreg.QueryValueEx(key, name)
        except OSError:
            continue
        if value:
            found.append(str(value))
    return found


def find_adb(extra_dirs: Iterable[str] = ()) -> Optional[str]:
    """Path of an adb executable an installed emulator brought, or None."""
    for folder in [*extra_dirs, *_registry_install_dirs(), *INSTALL_DIRS]:
        for name in ADB_NAMES:
            candidate = os.path.join(folder, name)
            if os.path.isfile(candidate):
                return candidate
    return shutil.which("adb")


def port_is_open(port: int, host: str = HOST,
                 timeout: float = PROBE_TIMEOUT_SECONDS) -> bool:
    """Whether anything is listening there. Refused ports answer at once."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


Runner = Callable[[Sequence[str], float], bytes]


def _run_process(args: Sequence[str], timeout: float) -> bytes:
    try:
        done = subprocess.run(list(args), capture_output=True, timeout=timeout,
                              creationflags=_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AdbError("%s: %s" % (" ".join(args[1:3]), exc)) from exc
    if done.returncode != 0:
        raise AdbError("%s exited %d: %s" % (" ".join(args[1:3]), done.returncode,
                                            done.stderr.decode(errors="replace").strip()))
    return done.stdout


def parse_screencap(raw: bytes) -> np.ndarray:
    """``screencap`` with no ``-p``: a small header, then RGBA rows. Returns BGR.

    The header is width, height and pixel format, little-endian 32-bit each,
    and from Android 9 a colour space after them; its length is whatever is left
    over once the pixels are accounted for. Raw rather than PNG because the
    phone does not have to compress it: 0.19 s against 0.51 s for a 1600x900
    frame on BlueStacks.
    """
    if len(raw) < 12:
        raise AdbError("screencap returned %d bytes" % len(raw))
    width, height, pixel_format = np.frombuffer(raw[:12], dtype="<u4")
    width, height = int(width), int(height)
    pixels = width * height * 4
    header = len(raw) - pixels
    if width <= 0 or height <= 0 or header not in (12, 16):
        raise AdbError("screencap header does not fit: %dx%d, %d bytes"
                       % (width, height, len(raw)))
    if int(pixel_format) != 1:       # 1 is RGBA_8888, the only one emulators use
        raise AdbError("screencap pixel format %d is not RGBA" % pixel_format)
    rgba = np.frombuffer(raw, dtype=np.uint8, count=pixels, offset=header)
    rgba = rgba.reshape(height, width, 4)
    return np.ascontiguousarray(rgba[:, :, 2::-1])     # RGB -> BGR, alpha dropped


@dataclass(frozen=True)
class Device:
    """An emulator with the game on it."""

    serial: str          # "127.0.0.1:5555"
    width: int
    height: int
    package: str

    @property
    def port(self) -> int:
        try:
            return int(self.serial.rsplit(":", 1)[1])
        except (IndexError, ValueError):
            return 0


# Which emulator brought the adb, told by its path, for naming the cards.
BRANDS = (
    ("bluestacks", "BlueStacks"), ("ldplayer", "LDPlayer"), ("nox", "Nox"),
    ("mumu", "MuMu"), ("microvirt", "MEmu"), ("memu", "MEmu"),
)


def brand_of(path: str) -> str:
    lowered = (path or "").lower()
    for needle, name in BRANDS:
        if needle in lowered:
            return name
    return "Giả lập"


class Adb:
    """One adb executable. ``runner`` is the seam the tests replace."""

    def __init__(self, path: str, runner: Optional[Runner] = None) -> None:
        self.path = path
        self.brand = brand_of(path)
        self._run = runner or _run_process
        self._server_started = False

    def run(self, *args: str, serial: str = "",
            timeout: float = COMMAND_TIMEOUT_SECONDS) -> bytes:
        prefix = [self.path] + (["-s", serial] if serial else [])
        return self._run(prefix + list(args), timeout)

    def shell(self, serial: str, command: str,
              timeout: float = COMMAND_TIMEOUT_SECONDS) -> str:
        return self.run("shell", command, serial=serial,
                        timeout=timeout).decode(errors="replace")

    # ── finding devices ─────────────────────────────────────────────────────

    def start_server(self) -> None:
        """Start adb's background server with nothing attached to it.

        Started by any other command, the server inherits that command's output
        pipes and keeps them open, and on Windows reading the output then waits
        for the server to exit — which it never does. Started here first, with
        its output going nowhere, every later command returns normally.
        """
        if self._server_started:
            return
        self._server_started = True
        if self._run is not _run_process:
            return                      # a test's fake has no server to start
        try:
            subprocess.run([self.path, "start-server"], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=SCAN_TIMEOUT_SECONDS * 3, creationflags=_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired):
            logger.warning("adb start-server did not finish", exc_info=True)

    def online(self) -> List[str]:
        """Serials adb already knows and can talk to."""
        listing = self.run("devices", timeout=SCAN_TIMEOUT_SECONDS).decode(
            errors="replace")
        serials = []
        for line in listing.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                serials.append(parts[0])
        return serials

    def connect(self, port: int) -> bool:
        answer = self.run("connect", "%s:%d" % (HOST, port),
                          timeout=SCAN_TIMEOUT_SECONDS).decode(errors="replace").lower()
        return "connected" in answer and "cannot" not in answer

    def game_package(self, serial: str) -> str:
        """The installed Onmyoji package, or "" if the game is not there."""
        listing = self.shell(serial, "pm list packages %s" % GAME_PACKAGE_PREFIX,
                             timeout=SCAN_TIMEOUT_SECONDS)
        for line in listing.splitlines():
            name = line.strip().replace("package:", "", 1)
            if name.startswith(GAME_PACKAGE_PREFIX):
                return name
        return ""

    def screen_size(self, serial: str) -> Tuple[int, int]:
        """(width, height) of the screen, landscape, or (0, 0) if unknown.

        Asked of ``wm size`` rather than measured from a screencap: it is a few
        bytes instead of six megabytes, and a scan that needed a frame dropped
        the emulator whenever one capture failed — a running card then went to
        "Mất cửa sổ" and stayed there. The game is landscape whatever way round
        the device reports itself; an override, when set, is what is drawn.
        """
        try:
            answer = self.shell(serial, "wm size", timeout=SCAN_TIMEOUT_SECONDS)
        except AdbError:
            return (0, 0)
        size = (0, 0)
        for line in answer.splitlines():
            if ":" not in line:
                continue
            label, _, value = line.partition(":")
            try:
                a, b = (int(n) for n in value.strip().split("x"))
            except ValueError:
                continue
            if "override" in label.lower() or size == (0, 0):
                size = (max(a, b), min(a, b))
        return size

    def discover(self, ports: Iterable[int] = KNOWN_PORTS,
                 probe: Callable[[int], bool] = port_is_open) -> List[Device]:
        """Every emulator, already known or listening on a known port, with
        the game installed. Ordered by serial so cards keep their places."""
        self.start_server()
        # All at once. A closed port on localhost does not refuse instantly on
        # Windows - it retries and costs the whole timeout - so probing the
        # list one after another took 3.7 s with BlueStacks open.
        ports = list(ports)
        with ThreadPoolExecutor(max_workers=max(1, len(ports))) as pool:
            open_ports = [p for p, is_open in zip(ports, pool.map(probe, ports))
                          if is_open]
        for port in open_ports:
            try:
                self.connect(port)
            except AdbError:
                logger.debug("adb connect %d failed", port, exc_info=True)
        found: List[Device] = []
        serials = sorted(set(self.online()))
        has_tcp = any(s.startswith(HOST) for s in serials)
        for serial in serials:
            # One emulator can show up twice, as emulator-5554 and as
            # 127.0.0.1:5555; the TCP name is the one a later connect restores.
            if serial.startswith("emulator-") and has_tcp:
                continue
            try:
                package = self.game_package(serial)
            except AdbError:
                logger.debug("Skipping %s", serial, exc_info=True)
                continue
            if not package:
                continue
            width, height = self.screen_size(serial)
            found.append(Device(serial, width, height, package))
        return found

    # ── the screen ──────────────────────────────────────────────────────────

    def screencap(self, serial: str) -> np.ndarray:
        raw = self.run("exec-out", "screencap", serial=serial,
                       timeout=SCREENCAP_TIMEOUT_SECONDS)
        return parse_screencap(raw)

    def tap(self, serial: str, x: int, y: int) -> None:
        self.shell(serial, "input tap %d %d" % (x, y))

    def swipe(self, serial: str, start: Tuple[int, int], end: Tuple[int, int],
              milliseconds: int) -> None:
        self.shell(serial, "input swipe %d %d %d %d %d"
                   % (start[0], start[1], end[0], end[1], milliseconds))

    def is_online(self, serial: str) -> bool:
        try:
            return serial in self.online()
        except AdbError:
            return False


_shared: Optional[Adb] = None


def shared() -> Optional[Adb]:
    """The adb this app uses. None when no emulator has brought one.

    Looked for again on every call until found, so an emulator installed while
    the app is open is picked up by the next scan; the search is a handful of
    file checks.
    """
    global _shared
    if _shared is None:
        path = find_adb()
        if path:
            logger.info("Using adb at %s", path)
            _shared = Adb(path)
    return _shared
