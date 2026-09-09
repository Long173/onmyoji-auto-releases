"""A system-wide key combination, for taking a screenshot without leaving the game.

The whole point is that it works while something else has the keyboard: whoever
presses it is looking at Onmyoji, not at this app. That rules out Qt's own
``QShortcut``, which only fires while one of our windows is focused, and leaves
Windows' ``RegisterHotKey``.

Two things here were measured rather than assumed, on this machine:

* **Registered against the thread (``hwnd`` of 0), not against a window.** Both
  reach Qt's native event filter, but the window-registered one arrived *twice*
  per press while the thread-registered one arrived once. Two deliveries would
  open two preview windows for one keystroke. Registering against the thread
  also survives the main window being destroyed and rebuilt, which the tray
  makes possible.
* **``MOD_NOREPEAT``**, so holding the combination down photographs the window
  once rather than as fast as the key repeats.

Failure here is reported, never raised. Windows refuses a combination another
application already owns — that is a normal thing for a user to run into, and
the answer is to tell them which combination is taken so they can pick another.
"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

# An id of our own. Only has to be unique within this thread.
HOTKEY_ID = 0xA51

MODIFIER_NAMES: Dict[str, int] = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "meta": MOD_WIN,
}

# The order they are written back out in, so a combination has one spelling
# however it was typed.
MODIFIER_ORDER: Tuple[Tuple[int, str], ...] = (
    (MOD_CONTROL, "Ctrl"),
    (MOD_ALT, "Alt"),
    (MOD_SHIFT, "Shift"),
    (MOD_WIN, "Win"),
)

NAMED_KEYS: Dict[str, int] = {
    "space": 0x20,
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "escape": 0x1B,
    "esc": 0x1B,
    "backspace": 0x08,
    "insert": 0x2D,
    "delete": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "printscreen": 0x2C,
    "prtsc": 0x2C,
    "pause": 0x13,
    "scrolllock": 0x91,
}
NAMED_KEYS.update({"f%d" % n: 0x6F + n for n in range(1, 25)})

KEY_LABELS = {
    0x20: "Space", 0x0D: "Enter", 0x09: "Tab", 0x1B: "Esc", 0x08: "Backspace",
    0x2D: "Insert", 0x2E: "Delete", 0x24: "Home", 0x23: "End",
    0x21: "PageUp", 0x22: "PageDown", 0x25: "Left", 0x26: "Up",
    0x27: "Right", 0x28: "Down", 0x2C: "PrintScreen", 0x13: "Pause",
    0x91: "ScrollLock",
}
KEY_LABELS.update({0x6F + n: "F%d" % n for n in range(1, 25)})

# Keys that mean nothing else on their own, so they may be bound without a
# modifier. Everything else must carry one: a bare letter would take that letter
# away from every other application on the machine, including the game.
ALONE_ALLOWED = frozenset(
    [0x2C, 0x13, 0x91] + [0x6F + n for n in range(13, 25)]
)


@dataclass(frozen=True)
class Combination:
    """A parsed key combination."""

    modifiers: int
    key: int

    @property
    def text(self) -> str:
        """One canonical spelling, whatever was typed."""
        parts = [name for bit, name in MODIFIER_ORDER if self.modifiers & bit]
        parts.append(KEY_LABELS.get(self.key, chr(self.key)))
        return "+".join(parts)


def parse(text: str) -> Optional[Combination]:
    """``"ctrl+shift+s"`` -> a :class:`Combination`, or None if it is not one.

    None rather than an exception: this reads a settings value that a user may
    have typed or an older build may have written, and "no hotkey" is a
    perfectly good outcome for something unreadable.
    """
    tokens = [part.strip().lower() for part in str(text or "").split("+")]
    tokens = [token for token in tokens if token]
    if not tokens:
        return None

    modifiers = 0
    for token in tokens[:-1]:
        bit = MODIFIER_NAMES.get(token)
        if bit is None:
            return None
        modifiers |= bit

    key = _key_code(tokens[-1])
    if key is None:
        return None
    if not modifiers and key not in ALONE_ALLOWED:
        # Binding a bare letter takes it from every other application on the
        # machine — including the game this is meant to photograph.
        return None
    return Combination(modifiers, key)


def _key_code(token: str) -> Optional[int]:
    if token in MODIFIER_NAMES:
        return None  # a modifier on its own is not a combination
    if token in NAMED_KEYS:
        return NAMED_KEYS[token]
    if len(token) == 1 and (token.isalpha() or token.isdigit()):
        return ord(token.upper())
    return None


def describe(text: str) -> str:
    """The canonical spelling of ``text``, or it unchanged if it is not valid."""
    combination = parse(text)
    return combination.text if combination is not None else str(text or "")


class GlobalHotkey:
    """Holds at most one registration, and says whether it took.

    Not a ``QObject``: it owns no Qt state and is easier to test without one.
    The caller supplies the callback and installs the native event filter — see
    :class:`HotkeyFilter`.
    """

    def __init__(self, hotkey_id: int = HOTKEY_ID) -> None:
        self._id = hotkey_id
        self._bound: Optional[Combination] = None
        self.error = ""

    @property
    def bound(self) -> Optional[Combination]:
        return self._bound

    @property
    def id(self) -> int:
        return self._id

    def bind(self, text: str) -> bool:
        """Register ``text``, replacing whatever was registered before.

        An empty or unreadable ``text`` unbinds and counts as success: "no
        hotkey" is a state the user can ask for, not a failure.
        """
        self.unbind()
        combination = parse(text)
        if combination is None:
            if str(text or "").strip():
                self.error = "Tổ hợp phím không hợp lệ: %s" % text
                logger.info("Ignoring unusable hotkey %r", text)
                return False
            return True

        user32 = _user32()
        if user32 is None:
            self.error = "Không đăng ký được phím tắt trên hệ điều hành này."
            return False
        ctypes.set_last_error(0)
        ok = user32.RegisterHotKey(
            None, self._id, combination.modifiers | MOD_NOREPEAT, combination.key)
        if not ok:
            code = ctypes.get_last_error()
            if code == ERROR_HOTKEY_ALREADY_REGISTERED:
                self.error = ("%s đang được ứng dụng khác dùng — chọn tổ hợp khác."
                              % combination.text)
            else:
                self.error = "Không đăng ký được %s (lỗi %s)." % (combination.text, code)
            logger.warning("RegisterHotKey(%s) failed: %s", combination.text, code)
            return False
        self._bound = combination
        self.error = ""
        logger.info("Hotkey registered: %s", combination.text)
        return True

    def unbind(self) -> None:
        self.error = ""
        if self._bound is None:
            return
        user32 = _user32()
        if user32 is not None:
            user32.UnregisterHotKey(None, self._id)
        logger.info("Hotkey released: %s", self._bound.text)
        self._bound = None


def _user32():
    try:
        return ctypes.WinDLL("user32", use_last_error=True)
    except (AttributeError, OSError):  # pragma: no cover - Windows-only app
        return None


def is_our_hotkey(message_address: int, hotkey_id: int) -> bool:
    """Whether a native message is ``WM_HOTKEY`` for ``hotkey_id``.

    Split out from the event filter so the message decoding can be tested
    without a running Qt application.
    """
    try:
        message = ctypes.cast(
            int(message_address), ctypes.POINTER(wintypes.MSG)).contents
    except (ValueError, TypeError, OSError):
        return False
    return message.message == WM_HOTKEY and int(message.wParam) == hotkey_id
