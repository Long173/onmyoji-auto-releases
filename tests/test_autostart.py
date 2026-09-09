"""Starting with Windows, into the tray.

These tests write to the real registry, so they write to a scratch key of their
own under HKCU and clean it up, and they redirect the Startup folder into
``tmp_path``. Both redirections are **autouse**: they started as an opt-in
fixture, and one test that forgot to ask for it — it only meant to check that a
refused write is reported — ran the real thing against the real Run key and
deleted the developer's own startup entry. Safety that has to be remembered is
safety that eventually is not.

The property worth the most care is the one that makes the toggle honest: the
registry is the only place this setting lives. Remembering it in ``QSettings`` as
well would let the app go on claiming "on" after somebody removed the entry
through Task Manager, and a setting that misreports the state of the machine is
worse than no setting at all.
"""
from __future__ import annotations

from pathlib import Path

import pytest

winreg = pytest.importorskip("winreg")

import autostart  # noqa: E402

SCRATCH = r"Software\OnmyojiToolTests\Run"


@pytest.fixture(autouse=True)
def machine(monkeypatch, tmp_path):
    """A scratch Run key and a scratch Startup folder, taken away afterwards."""
    folder = tmp_path / "Startup"
    folder.mkdir()
    monkeypatch.setattr(autostart, "startup_dir", lambda: folder)
    monkeypatch.setattr(autostart, "RUN_KEY", SCRATCH)
    monkeypatch.setattr(autostart, "VALUE_NAME", "OnmyojiToolTest")
    yield folder
    for key in (SCRATCH, r"Software\OnmyojiToolTests"):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except OSError:
            pass


# ── the command Windows will run ────────────────────────────────────────────


def test_the_command_carries_the_tray_flag():
    """Started at sign-in means started *without a window*.

    Somebody who asked for this did not ask for a window in their face every
    time they turn the machine on.
    """
    assert autostart.TRAY_FLAG in autostart.command()


def test_the_command_is_quoted():
    """Both the packaged path and the checkout sit under paths with spaces.

    Not cosmetic. An unquoted command runs the wrong thing, and Task Manager
    also reads it wrong: a neighbouring entry pointing at an unquoted
    ``E:\\Level Up\\Level Up.exe`` is listed as "Level".
    """
    assert autostart.command().startswith('"')


def test_the_command_points_at_something_that_exists():
    """A registered command that starts nothing is the failure with no symptom."""
    import shlex

    parts = shlex.split(autostart.command(), posix=False)
    target = parts[-2] if len(parts) > 2 else parts[0]

    assert Path(target.strip('"')).exists(), target


def test_the_command_does_not_come_from_argv(monkeypatch):
    """``sys.argv[0]`` is not a path under ``python -c`` — it is "-c".

    Reading it there produced a command pointing at a file called "-c", which
    would have registered silently and started nothing at every sign-in.
    """
    monkeypatch.setattr(autostart.sys, "argv", ["-c"])

    assert '-c"' not in autostart.command()
    assert "app.py" in autostart.command()


# ── on and off ──────────────────────────────────────────────────────────────


def test_it_starts_off():
    assert autostart.is_enabled() is False
    assert autostart.stored_command() == ""


def test_turning_it_on_registers_the_command():
    assert autostart.set_enabled(True) is True

    assert autostart.is_enabled() is True
    assert autostart.stored_command() == autostart.command()


def test_turning_it_off_removes_the_entry():
    autostart.set_enabled(True)

    assert autostart.set_enabled(False) is True

    assert autostart.is_enabled() is False
    assert autostart.stored_command() == ""


def test_turning_it_off_when_it_is_already_off_is_fine():
    """Deleting a value that is not there must not be an error."""
    assert autostart.set_enabled(False) is True
    assert autostart.is_enabled() is False


def test_turning_it_on_twice_leaves_one_entry():
    autostart.set_enabled(True)
    autostart.set_enabled(True)

    assert autostart.stored_command() == autostart.command()


# ── the shortcut an interim build wrote ─────────────────────────────────────


def a_leftover_shortcut(folder: Path) -> Path:
    path = folder / autostart.SHORTCUT_NAME
    path.write_bytes(b"not really a shortcut")
    return path


def test_turning_it_on_clears_a_leftover_shortcut(machine):
    """Keeping both would start the app twice at sign-in.

    A build in between registered a Startup-folder shortcut instead, on a theory
    about Task Manager's Name column that turned out to be wrong. Machines that
    ran it still have the file.
    """
    leftover = a_leftover_shortcut(machine)

    autostart.set_enabled(True)

    assert not leftover.exists()
    assert autostart.is_enabled() is True


def test_turning_it_off_clears_a_leftover_shortcut_too(machine):
    leftover = a_leftover_shortcut(machine)

    assert autostart.set_enabled(False) is True

    assert not leftover.exists()
    assert autostart.is_enabled() is False


def test_a_missing_startup_folder_is_not_an_error(monkeypatch):
    monkeypatch.setattr(autostart, "startup_dir", lambda: None)

    assert autostart.set_enabled(True) is True


# ── a stale entry ───────────────────────────────────────────────────────────


def test_a_moved_build_is_noticed():
    """The entry survives the build being moved, and then starts nothing."""
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, SCRATCH) as key:
        winreg.SetValueEx(key, "OnmyojiToolTest", 0, winreg.REG_SZ,
                          r'"C:\somewhere\else\Onmyoji Tool.exe" --tray')

    assert autostart.is_enabled() is True, "it is still registered"
    assert autostart.is_current() is False, "and it points somewhere else"


def test_turning_it_on_again_repairs_a_stale_entry():
    """Which is why the toggle is not driven off ``is_current``.

    Flipping itself off because a folder moved would look like the app forgetting
    the setting. Rewriting on every "on" is the repair, and it costs nothing.
    """
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, SCRATCH) as key:
        winreg.SetValueEx(key, "OnmyojiToolTest", 0, winreg.REG_SZ, "stale")

    autostart.set_enabled(True)

    assert autostart.is_current() is True


# ── nothing to write to ─────────────────────────────────────────────────────


def test_a_refused_write_is_reported_not_raised(monkeypatch):
    """A policy-managed machine can say no; the caller has to be able to tell."""
    def refuse(*_args, **_kwargs):
        raise OSError("access denied")

    monkeypatch.setattr(winreg, "CreateKey", refuse)

    assert autostart.set_enabled(True) is False


def test_no_registry_at_all_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(autostart, "_winreg", lambda: None)

    assert autostart.set_enabled(True) is False
    assert autostart.is_enabled() is False


# ── the setting is not remembered anywhere else ─────────────────────────────


def test_the_setting_is_declared_for_the_dialog():
    import tasks

    keys = [f.key for f in tasks.APP_FIELDS]
    assert "start_with_windows" in keys
    assert "start_with_windows" in tasks.APP_FIELD_NOTES


# ── no console window at sign-in ────────────────────────────────────────────


def test_the_source_command_uses_pythonw(monkeypatch):
    """``python.exe`` flashes a console window every time the machine starts.

    Which is precisely what ``--tray`` promises will not happen, and in the most
    visible way possible. Found by looking at the entry this actually wrote.
    """
    monkeypatch.setattr(autostart.sys, "frozen", False, raising=False)

    command = autostart.command()

    assert "pythonw.exe" in command
    assert '"%s"' % "python.exe" not in command


def test_it_settles_for_python_when_there_is_no_pythonw(monkeypatch):
    """A stripped install may not ship it; a console beats not starting."""
    monkeypatch.setattr(Path, "exists", lambda self: False)

    assert autostart.command()
