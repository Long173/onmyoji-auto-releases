# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Onmyoji Tool.

    pip install pyinstaller
    pyinstaller onmyoji_auto.spec --noconfirm

Produces `dist/Onmyoji Tool/` — a folder holding the .exe and `_internal/`,
no console. `tools/publish_release.py` zips it for distribution.

The spec filename keeps its old spelling so existing build scripts and muscle
memory still work; only the produced .exe carries the new name.

What goes in, and why:

* `assets/fonts` — the three typefaces are not on a stock Windows install.
* `screenshots` — the templates the raid loop matches against.
* `wiki/assets` — the Flutter project's dataset and artwork, so the wiki works
  on a machine that has no checkout next to it. Roughly 14 MB of the build.

Logs, caches and `.env` are written beside the .exe, never into the extracted
bundle: see `paths.py`.
"""
import os
from pathlib import Path

ROOT = Path(os.getcwd()).resolve()
SOURCE = ROOT / "decompiled" / "source"
WIKI = ROOT.parent / "onmyoji_wiki" / "assets"

# ── what Windows says about the .exe ────────────────────────────────────────
#
# Read out of `theme.py` rather than written here as well: two places holding
# the version is two places to forget, and the one that gets forgotten is the
# one nobody looks at.
#
# This is what Task Manager's Startup tab, the Details tab and the file's
# Properties dialog read. Without it the Publisher column is blank and the app
# is listed by bare filename. Measured on this machine: Task Manager names a
# startup entry after the *executable in the command*, cut at the first unquoted
# space — not after the registry value, and not after a Startup-folder
# shortcut's name — so a build launched through `pythonw.exe` shows "pythonw"
# whatever else is done. The packaged .exe is the only thing that fixes it.
_version_source = (SOURCE / "theme.py").read_text(encoding="utf-8")
APP_VERSION = next(
    line.split("=", 1)[1].strip().strip('"')
    for line in _version_source.splitlines()
    if line.startswith("APP_VERSION")
)
# Windows wants exactly four numbers.
_numbers = tuple(int(part) for part in APP_VERSION.split(".")) + (0, 0, 0, 0)
VERSION_NUMBERS = _numbers[:4]

datas = [
    (str(ROOT / "assets" / "fonts"), "assets/fonts"),
    # The demon-fire orb beside a skill's cost, cut from the game itself.
    (str(ROOT / "assets" / "icons"), "assets/icons"),
    (str(ROOT / "screenshots"), "screenshots"),
]

# The licence travels with the build. PolyForm Noncommercial asks that anyone
# who gets a copy also gets the terms, and a .zip handed around in a chat group
# is exactly the case that rule is for — the copy on the releases page is no use
# to somebody who was handed the file by a friend.
# OpenCV's video writer goes through its FFMPEG backend, and that backend lives
# in a DLL PyInstaller does not pick up on its own. Without it `cv2.VideoWriter`
# simply refuses to open and recording fails in the packaged build while working
# perfectly from source — measured: mp4v, XVID and MJPG all report backend
# "FFMPEG", so there is no codec that avoids it.
#
# It costs about 28.6 MB of the download, which is the price of the feature.
binaries = []
_cv2_dir = Path(cv2.__file__).parent if (cv2 := __import__("cv2")) else None
if _cv2_dir is not None:
    for dll in sorted(_cv2_dir.glob("opencv_videoio_ffmpeg*.dll")):
        binaries.append((str(dll), "."))
        print("[spec] bundling %s (%.1f MB)" % (dll.name, dll.stat().st_size / 1e6))
if not binaries:
    print("[spec] WARNING: no opencv_videoio_ffmpeg dll found — recording will "
          "not work in this build")

if (ROOT / "LICENSE").is_file():
    datas.append((str(ROOT / "LICENSE"), "."))
else:
    print("[spec] no LICENSE found — building without it")

# The wiki dataset is optional at build time: without it the app still runs and
# the wiki offers to sync from Supabase instead.
if (WIKI / "data").is_dir():
    datas.append((str(WIKI / "data"), "wiki/assets/data"))
if (WIKI / "images").is_dir():
    datas.append((str(WIKI / "images"), "wiki/assets/images"))
else:
    print("[spec] onmyoji_wiki artwork not found — building without it")

# Qt's WebP plugin is what reads the wiki artwork; the others keep the UI and
# the frameless window working.
hiddenimports = [
    "PyQt5.QtCore",
    "PyQt5.QtGui",
    "PyQt5.QtWidgets",
]

# Nothing here is imported, and each drags in tens of megabytes.
excludes = [
    "tkinter",
    "matplotlib",
    "scipy",
    "pandas",
    "PIL",
    "IPython",
    "pytest",
    "setuptools",
    "PyQt5.QtWebEngineWidgets",
    "PyQt5.QtQml",
    "PyQt5.QtQuick",
    "PyQt5.QtMultimedia",
    "PyQt5.QtBluetooth",
    "PyQt5.QtNetworkAuth",
    "PyQt5.QtWebSockets",
    "PyQt5.Qt3DCore",
    "PyQt5.QtCharts",
    "PyQt5.QtDataVisualization",
]

a = Analysis(
    [str(SOURCE / "app.py")],
    pathex=[str(SOURCE)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    # Compile at -OO, which drops docstrings from the bundled bytecode.
    #
    # Not an attempt to stop anyone reading the code: a PyInstaller build is
    # trivially unpacked, and this project itself lives in a folder called
    # `decompiled/source`. What it does stop is handing over the *explanations*
    # for free. Measured on the 3.8 build: 52 KB of design notes — every
    # threshold with the measurement behind it, every approach that was tried
    # and failed and why — sat in the shipped .exe, and that is worth more to
    # somebody repackaging this than the bytecode is.
    #
    # Safe at level 2 here, and checked rather than assumed: the app contains no
    # `assert` statements for -O to strip, and nothing reads `__doc__` at
    # runtime. Both would have to stay true for this to remain harmless.
    optimize=2,
)

# `rarity.where` points at wherever this machine keeps the picture library —
# a path off the developer's own drive. The app never needs it in a build: it
# reads the packed `rarity.npz`, and the pointer only exists so the labelling
# tools can find the pictures behind it. Shipping it would put a stranger's
# D: drive in every install.
a.datas = [entry for entry in a.datas
           if not entry[0].replace("\\", "/").endswith("DemonParade/rarity.where")]

pyz = PYZ(a.pure)

from PyInstaller.utils.win32.versioninfo import (  # noqa: E402
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VSVersionInfo,
    VarFileInfo, VarStruct,
)

version_resource = VSVersionInfo(
    ffi=FixedFileInfo(filevers=VERSION_NUMBERS, prodvers=VERSION_NUMBERS,
                      mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1,
                      subtype=0x0, date=(0, 0)),
    kids=[
        # 0409 = en-US, 04B0 = Unicode. The strings themselves are Vietnamese
        # where they are read by people and English where they are read by
        # Windows.
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "Onmyoji Tool"),
            StringStruct("FileDescription", "Onmyoji Tool"),
            StringStruct("FileVersion", APP_VERSION),
            StringStruct("InternalName", "Onmyoji Tool"),
            StringStruct("OriginalFilename", "Onmyoji Tool.exe"),
            StringStruct("ProductName", "Onmyoji Tool"),
            StringStruct("ProductVersion", APP_VERSION),
            StringStruct("LegalCopyright",
                         "PolyForm Noncommercial 1.0.0 — phi thương mại"),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # one-dir: the libraries live beside the .exe
    name="Onmyoji Tool",
    version=version_resource,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX-packed binaries trip antivirus far more often
    console=False,      # no terminal window; logs go to logs/onmyoji_auto.log
    disable_windowed_traceback=False,
    icon=str(ROOT / "assets" / "icon.ico"),
)

# One directory, not one file. A one-file build has to unpack its whole 240 MB
# into %TEMP%\_MEIxxxxxx on *every* launch and load python312.dll back out of
# there, and that step is where installs actually broke: a user hit
#
#   Failed to load Python DLL '...\_MEI174516\python312.dll'
#
# The trailing digit of that folder name is the bootloader's retry counter — a
# healthy machine lands on the first try, so a 6 means it failed to create the
# directory five times over. Full disk, a %TEMP% littered with abandoned _MEI
# folders (4.3 GB of them measured on the dev machine), or antivirus deleting a
# freshly written DLL all produce it.
#
# One-dir has no unpacking step at all: the DLLs sit on disk, so there is
# nothing to fail, startup is far quicker, and antivirus stops re-scanning a
# brand-new python312.dll every single launch.
#
# The cost: what ships is a folder, distributed as a .zip, and the updater
# replaces two entries inside it rather than one file. Everything the user owns
# — logs\, cache\, .env, a wiki\ override — sits beside those and is left
# alone. See `updater.py`.
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Onmyoji Tool",
)
