"""No test may touch the real "start with Windows" entry.

The main window repairs that entry on startup, and every UI test builds a main
window. Before conftest redirected it for all tests, running the suite from a
scratch worktree pointed the developer's sign-in at that worktree.
"""
from __future__ import annotations

import pytest

winreg = pytest.importorskip("winreg")

import autostart  # noqa: E402
import conftest  # noqa: E402

REAL_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def real_entry():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REAL_RUN_KEY) as key:
            return winreg.QueryValueEx(key, "OnmyojiTool")[0]
    except OSError:
        return None


def test_every_test_runs_against_the_scratch_key():
    assert autostart.RUN_KEY == conftest.STARTUP_SCRATCH_KEY
    assert autostart.VALUE_NAME != "OnmyojiTool"


def test_a_dashboard_repairing_a_stale_entry_leaves_the_real_one_alone(dashboard):
    before = real_entry()
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, autostart.RUN_KEY) as key:
        winreg.SetValueEx(key, autostart.VALUE_NAME, 0, winreg.REG_SZ,
                          '"C:\\somewhere\\else\\app.py" --tray')

    dashboard._repair_autostart()

    assert autostart.is_current(), "the repair did not run, so this proves nothing"
    assert real_entry() == before
