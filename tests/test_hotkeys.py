"""The system-wide screenshot key.

Most of this is parsing, which is pure and cheap to pin. The registration tests
do talk to Windows, but only with combinations nothing sane would want — F24 and
friends — and every one of them is released again.

Two rules carry the weight:

* **A bare letter is not a hotkey.** Registering one takes that letter from
  every other application on the machine, the game included. Only keys that mean
  nothing on their own — PrintScreen, Pause, F13 and up — may be bound alone.
* **A refused registration is reported, not swallowed.** Windows says no when
  another application already owns the combination; a toggle that then claimed
  the hotkey was working would send somebody hunting for a bug in the capture
  code.
"""
from __future__ import annotations

import ctypes

import pytest

import hotkeys
from hotkeys import Combination, GlobalHotkey, parse

WINDOWS = hasattr(ctypes, "WinDLL")
needs_windows = pytest.mark.skipif(not WINDOWS, reason="Windows-only")


# ── reading a combination ───────────────────────────────────────────────────


def test_a_plain_combination():
    got = parse("Ctrl+Shift+S")

    assert got == Combination(hotkeys.MOD_CONTROL | hotkeys.MOD_SHIFT, ord("S"))


def test_case_and_spacing_do_not_matter():
    assert parse("  ctrl + SHIFT + s ") == parse("Ctrl+Shift+S")


def test_control_is_a_synonym_for_ctrl():
    assert parse("control+s") == parse("ctrl+s")


def test_win_and_meta_are_the_same_key():
    assert parse("win+f9") == parse("meta+f9")


def test_function_keys():
    assert parse("Alt+F5").key == 0x74


def test_named_keys():
    assert parse("Ctrl+PrintScreen").key == 0x2C
    assert parse("Ctrl+Space").key == 0x20


def test_digits():
    assert parse("Ctrl+Alt+1").key == ord("1")


def test_the_spelling_is_canonical():
    """So the settings file and the label agree however it was typed."""
    assert parse("shift+ctrl+s").text == "Ctrl+Shift+S"
    assert parse("alt+ctrl+f12").text == "Ctrl+Alt+F12"


def test_describe_leaves_nonsense_alone():
    assert hotkeys.describe("wat+++") == "wat+++"


# ── what is not a combination ───────────────────────────────────────────────


def test_a_bare_letter_is_refused():
    """It would take that letter from every application on the machine."""
    assert parse("S") is None


def test_a_bare_modifier_is_refused():
    assert parse("Ctrl") is None
    assert parse("Ctrl+") is None


def test_an_unknown_name_is_refused():
    assert parse("Ctrl+Banana") is None


def test_nothing_is_refused():
    assert parse("") is None
    assert parse(None) is None
    assert parse("   ") is None


def test_printscreen_may_stand_alone():
    """It means nothing else, and it is the key people reach for."""
    assert parse("PrintScreen") == Combination(0, 0x2C)


def test_f13_and_up_may_stand_alone():
    """No keyboard sends them by accident and nothing else claims them."""
    assert parse("F13") is not None
    assert parse("F24") is not None


def test_f12_may_not():
    assert parse("F12") is None


# ── registering ─────────────────────────────────────────────────────────────


@pytest.fixture
def hotkey():
    key = GlobalHotkey(hotkey_id=0xA5F1)
    yield key
    key.unbind()


@needs_windows
def test_binding_an_obscure_combination_works(hotkey):
    assert hotkey.bind("Ctrl+Alt+Shift+F24") is True

    assert hotkey.bound is not None
    assert hotkey.bound.text == "Ctrl+Alt+Shift+F24"
    assert hotkey.error == ""


@needs_windows
def test_binding_again_replaces_the_first(hotkey):
    hotkey.bind("Ctrl+Alt+Shift+F24")

    assert hotkey.bind("Ctrl+Alt+Shift+F23") is True

    assert hotkey.bound.text == "Ctrl+Alt+Shift+F23"


@needs_windows
def test_a_combination_someone_else_owns_is_reported(hotkey):
    """Not swallowed: otherwise the setting claims to work and nothing happens."""
    other = GlobalHotkey(hotkey_id=0xA5F2)
    assert other.bind("Ctrl+Alt+Shift+F22") is True
    try:
        assert hotkey.bind("Ctrl+Alt+Shift+F22") is False
        assert "ứng dụng khác" in hotkey.error
        assert hotkey.bound is None
    finally:
        other.unbind()


@needs_windows
def test_releasing_frees_it_for_someone_else(hotkey):
    hotkey.bind("Ctrl+Alt+Shift+F21")
    hotkey.unbind()

    other = GlobalHotkey(hotkey_id=0xA5F3)
    try:
        assert other.bind("Ctrl+Alt+Shift+F21") is True
    finally:
        other.unbind()


def test_binding_nothing_unbinds_and_is_not_a_failure(hotkey):
    """"No hotkey" is a state a user can ask for."""
    assert hotkey.bind("") is True

    assert hotkey.bound is None
    assert hotkey.error == ""


def test_binding_nonsense_is_a_failure_and_says_so(hotkey):
    assert hotkey.bind("Ctrl+Banana") is False

    assert hotkey.bound is None
    assert "không hợp lệ" in hotkey.error


def test_a_failed_bind_leaves_nothing_registered(hotkey):
    """Otherwise the old combination keeps firing after being replaced."""
    hotkey.bind("Ctrl+Alt+Shift+F20")

    hotkey.bind("Ctrl+Banana")

    assert hotkey.bound is None


def test_unbinding_twice_is_fine(hotkey):
    hotkey.bind("Ctrl+Alt+Shift+F19")
    hotkey.unbind()
    hotkey.unbind()

    assert hotkey.bound is None


# ── recognising the message ─────────────────────────────────────────────────


@needs_windows
def test_a_hotkey_message_is_recognised():
    from ctypes import wintypes

    message = wintypes.MSG()
    message.message = hotkeys.WM_HOTKEY
    message.wParam = 0xA5F1

    assert hotkeys.is_our_hotkey(ctypes.addressof(message), 0xA5F1)


@needs_windows
def test_another_hotkey_id_is_not_ours():
    from ctypes import wintypes

    message = wintypes.MSG()
    message.message = hotkeys.WM_HOTKEY
    message.wParam = 0x1234

    assert not hotkeys.is_our_hotkey(ctypes.addressof(message), 0xA5F1)


@needs_windows
def test_an_ordinary_message_is_not_ours():
    from ctypes import wintypes

    message = wintypes.MSG()
    message.message = 0x0100  # WM_KEYDOWN
    message.wParam = 0xA5F1

    assert not hotkeys.is_our_hotkey(ctypes.addressof(message), 0xA5F1)


def test_a_nonsense_address_is_not_ours():
    """The filter is handed a pointer by Qt; it must not crash on a surprise."""
    assert not hotkeys.is_our_hotkey(0, 0xA5F1)
