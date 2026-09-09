"""Starting with Windows, straight into the tray.

Registered under ``HKCU\\...\\CurrentVersion\\Run``. A shortcut in the Startup
folder was tried instead, on the theory that Task Manager would then list the app
under the shortcut's name rather than under ``pythonw``. **It does not**, and the
measurement is worth keeping so nobody spends the afternoon on it twice:

* ``pythonw.exe`` has the file description "Python", and Task Manager showed
  "pythonw" — so it is not reading the description.
* ``StartupApproved\\StartupFolder`` listed ``Onmyoji Tool.lnk``, so Task Manager
  knew about the shortcut, and still showed "pythonw" — so it is not reading the
  shortcut's name either.
* A neighbouring entry pointing at an *unquoted* ``E:\\Level Up\\Level Up.exe``
  was listed as "Level".

Task Manager names a startup entry after the executable in the command, cut at
the first unquoted space. Nothing this module can do changes that. It reads
"pythonw" when the app is run from source and "Onmyoji Tool" from the packaged
build, whichever mechanism registers it — so the registry wins on being the
simpler of the two: no shell COM, no extra hidden imports in the frozen build,
and one value to read back.

**The registry is the source of truth here, not the app's own settings.** A
toggle backed by ``QSettings`` would go on saying "on" after somebody removed the
entry through Task Manager's Startup tab, and a setting that lies about the state
of the machine is worse than no setting. So the toggle is *displayed* from
:func:`is_enabled` and *applied* by writing the registry; nothing about it is
remembered anywhere else.

The command carries ``--tray``, which is what makes this different from simply
launching the app: no window, just the tray icon. Somebody who asked for it to
start with Windows did not ask for a window in their face at every sign-in.

Nothing here raises on failure. Writing under HKCU normally cannot fail, but a
locked-down or policy-managed machine can refuse, and the honest answer then is
"it did not take" rather than a traceback — see :func:`set_enabled`.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# Deliberately not the app's display name: this is a registry value name, and
# Task Manager does not show it (see the module docstring). It should be
# recognisable in the registry without being retyped if the app is renamed.
VALUE_NAME = "OnmyojiTool"

# The shortcut the experiment above left behind. Still removed whenever the
# toggle is used, so a machine that ran that build does not keep a second entry
# launching the app a second time at sign-in.
SHORTCUT_NAME = "Onmyoji Tool.lnk"

# The flag the registered command carries. Read by ``app.main``.
TRAY_FLAG = "--tray"


def _winreg():
    """The module, or None where there is no registry to talk to."""
    try:
        import winreg
    except ImportError:  # pragma: no cover - Windows-only app
        return None
    return winreg


def command() -> str:
    """What Windows should run at sign-in.

    Quoted, because both the packaged path and the developer's checkout sit under
    paths with spaces in them, and an unquoted command line silently runs the
    wrong thing — Task Manager's own list has a neighbour that got this wrong and
    is listed under half of its folder name.
    """
    if getattr(sys, "frozen", False):
        return '"%s" %s' % (Path(sys.executable).resolve(), TRAY_FLAG)
    # From source. Only really useful to whoever is working on the app, but it
    # should behave rather than quietly do nothing.
    #
    # Resolved against this file rather than ``sys.argv[0]``: argv is whatever
    # started the process, which for anything other than a plain ``python
    # app.py`` is not a path at all — under ``python -c`` it is the literal
    # string "-c", and the command came out pointing at a file called "-c".
    entry = Path(__file__).resolve().parent / "app.py"
    return '"%s" "%s" %s' % (_quiet_python(), entry, TRAY_FLAG)


def _quiet_python() -> Path:
    """``pythonw.exe`` where it exists, otherwise whatever is running.

    ``python.exe`` opens a console window, and this command runs at sign-in with
    ``--tray`` — the one thing it promises is that nothing appears on screen. A
    console flashing up every time the machine starts would break exactly that
    promise, in the most visible way possible.
    """
    running = Path(sys.executable).resolve()
    quiet = running.with_name("pythonw.exe")
    return quiet if quiet.exists() else running


def stored_command() -> str:
    """The command currently registered, or an empty string."""
    winreg = _winreg()
    if winreg is None:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
            return str(value)
    except FileNotFoundError:
        return ""
    except OSError as exc:
        logger.debug("Could not read the startup entry: %s", exc)
        return ""


def is_enabled() -> bool:
    """Whether Windows will start this app at sign-in."""
    return bool(stored_command())


def is_current() -> bool:
    """Whether the registered command still points at *this* build.

    A build that has been moved leaves a stale entry that starts nothing. Not
    used to decide the toggle's position — that would make it flip itself off
    for a reason the user cannot see — but :func:`set_enabled` rewrites the value
    every time it is turned on, so switching it off and on repairs a stale path.
    """
    return stored_command() == command()


def set_enabled(enabled: bool) -> bool:
    """Turn it on or off. Returns whether the registry now says what was asked.

    Reported rather than raised: a policy-managed machine can refuse the write,
    and the caller needs to be able to tell the user it did not take instead of
    showing a toggle that claims otherwise.
    """
    _remove_stray_shortcut()
    winreg = _winreg()
    if winreg is None:
        return False
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if enabled:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())
                logger.info("Startup entry set: %s", command())
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                    logger.info("Startup entry removed")
                except FileNotFoundError:
                    pass
    except OSError as exc:
        logger.warning("Could not change the startup entry: %s", exc)
        return False
    return is_enabled() == enabled


def startup_dir() -> Optional[Path]:
    """The user's Startup folder, or None if it cannot be found.

    Only needed to clean up after the shortcut experiment. Assembled from
    ``%APPDATA%`` rather than asked of the shell: this is a tidy-up, and a
    redirected profile that makes the guess wrong simply means there is nothing
    of ours there to remove.
    """
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _remove_stray_shortcut() -> None:
    """Delete the Startup-folder shortcut an interim build wrote.

    Leaving it beside the registry entry would start the app twice at sign-in.
    """
    folder = startup_dir()
    if folder is None:
        return
    try:
        (folder / SHORTCUT_NAME).unlink()
        logger.info("Removed the leftover startup shortcut")
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.debug("Could not remove the leftover shortcut: %s", exc)
