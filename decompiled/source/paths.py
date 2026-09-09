"""Where everything lives, in both a checkout and a packaged build.

Two roots, because a frozen build separates them:

* :data:`BUNDLE_ROOT` — read-only assets that ship with the app (fonts,
  templates, the wiki dataset). Under PyInstaller this is the extracted
  ``_MEIPASS`` folder, which is temporary and must never be written to.
* :data:`APP_ROOT` — the writable side (logs, caches, ``.env``). Under
  PyInstaller this is the folder holding the .exe, so a user can find their
  logs and drop a ``.env`` next to the program.

In a checkout the two are the same folder, which is why the split was easy to
miss until the app was packaged.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable

FROZEN = bool(getattr(sys, "frozen", False))

# Source lives at <root>/decompiled/source.
_CHECKOUT_ROOT = Path(__file__).resolve().parents[2]

APP_ROOT: Path = (
    Path(sys.executable).resolve().parent if FROZEN else _CHECKOUT_ROOT
)
BUNDLE_ROOT: Path = (
    Path(getattr(sys, "_MEIPASS", _CHECKOUT_ROOT)) if FROZEN else _CHECKOUT_ROOT
)

# ── read-only, shipped ──────────────────────────────────────────────────────
ASSET_DIR: Path = BUNDLE_ROOT / "assets"
FONT_DIR: Path = ASSET_DIR / "fonts"
SCREENSHOT_DIR: Path = BUNDLE_ROOT / "screenshots"

# ── writable ────────────────────────────────────────────────────────────────


def _is_writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".write-probe"
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def _writable_root() -> Path:
    """Beside the app, or under LOCALAPPDATA when that folder is read-only.

    Someone will drop the .exe into Program Files, where a normal account
    cannot write. Crashing on the first log line is a poor way to find out.
    """
    if _is_writable(APP_ROOT):
        return APP_ROOT
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    # Folder name kept from before the rename: it already holds this user's logs
    # and wiki cache, and renaming it would strand both in a folder nothing
    # reads any more.
    return Path(base or Path.home()) / "OnmyojiAuto"


DATA_ROOT: Path = _writable_root()
LOG_DIR: Path = DATA_ROOT / "logs"
CACHE_DIR: Path = DATA_ROOT / "cache"
WIKI_CACHE_DIR: Path = CACHE_DIR / "wiki"
IMAGE_CACHE_DIR: Path = CACHE_DIR / "images"


def _first_existing(candidates: Iterable[Path], fallback: Path) -> Path:
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return fallback


# The wiki dataset — JSON and artwork — is the Flutter app's.
#
# Packaged: a folder dropped beside the .exe wins, so a newer dataset can be
# supplied without a rebuild; failing that, the copy inside the bundle. The
# checkout path is meaningless once frozen — __file__ then points inside the
# extracted bundle — so it is not considered at all.
#
# Checkout: read the sibling project directly, so the two never drift while
# developing.
_WIKI_CANDIDATES = (
    (APP_ROOT / "wiki", BUNDLE_ROOT / "wiki")
    if FROZEN
    else (_CHECKOUT_ROOT.parent / "onmyoji_wiki", APP_ROOT / "wiki")
)
WIKI_ROOT: Path = _first_existing(_WIKI_CANDIDATES, _WIKI_CANDIDATES[0])
DEFAULT_WIKI_DATA_DIR: Path = WIKI_ROOT / "assets" / "data"


def template(*parts: str) -> str:
    """Absolute path of a template image under ``screenshots/``.

    ``cv2.imdecode`` takes bytes, but the callers pass paths as ``str``.
    """
    return str(SCREENSHOT_DIR.joinpath(*parts))


def ensure_cache_dirs() -> None:
    for directory in (CACHE_DIR, WIKI_CACHE_DIR, IMAGE_CACHE_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def describe() -> str:
    """One line for the log, so a packaged build can be diagnosed remotely."""
    return "frozen=%s app=%s data=%s bundle=%s wiki=%s" % (
        FROZEN,
        APP_ROOT,
        DATA_ROOT,
        BUNDLE_ROOT,
        WIKI_ROOT if WIKI_ROOT.is_dir() else "(khong co)",
    )
