"""Register the bundled typefaces with Qt and report what actually loaded.

The design calls for three families that Windows does not ship: Cormorant
Garamond (display), Lora (body) and IBM Plex Mono (labels and figures). They
live in ``assets/fonts`` as static instances — variable fonts were flattened at
weights 400/600 with fonttools, because Qt 5 only exposes a variable font's
default instance and would otherwise fake the bold.

Every family degrades to a system stand-in, so a missing file costs polish and
nothing else.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Sequence

from PyQt5 import QtGui

from paths import FONT_DIR

logger = logging.getLogger(__name__)

# family -> the files that provide it
_BUNDLED: Dict[str, Sequence[str]] = {
    "Cormorant Garamond": ("CormorantGaramond-400.ttf", "CormorantGaramond-600.ttf"),
    "Lora": ("Lora-400.ttf", "Lora-600.ttf"),
    "IBM Plex Mono": ("IBMPlexMono-400.ttf", "IBMPlexMono-500.ttf"),
}

# Ordered stand-ins, best first, used when the bundled file is unavailable.
_FALLBACKS: Dict[str, Sequence[str]] = {
    "Cormorant Garamond": ("Georgia", "Times New Roman", "serif"),
    "Lora": ("Georgia", "Times New Roman", "serif"),
    "IBM Plex Mono": ("Consolas", "Courier New", "monospace"),
}

_resolved: Dict[str, str] = {}


def load() -> Dict[str, str]:
    """Register every bundled font. Call once, before building any widget.

    Returns the mapping of requested family -> family Qt will actually use.
    """
    if _resolved:
        return _resolved

    database_families = set(QtGui.QFontDatabase().families())

    for family, files in _BUNDLED.items():
        loaded: List[str] = []
        for file_name in files:
            path = FONT_DIR / file_name
            if not path.is_file():
                logger.warning("Font file missing: %s", path)
                continue
            font_id = QtGui.QFontDatabase.addApplicationFont(str(path))
            if font_id == -1:
                logger.warning("Qt rejected font file: %s", path)
                continue
            loaded.extend(QtGui.QFontDatabase.applicationFontFamilies(font_id))

        if loaded:
            # Qt reports the family name from the file, which is what must be
            # asked for later — it is not always the name we used as the key.
            _resolved[family] = loaded[0]
        else:
            _resolved[family] = _first_available(_FALLBACKS[family], database_families)
            logger.warning(
                "Falling back to %r for %r", _resolved[family], family
            )

    logger.info("Fonts resolved: %s", _resolved)
    return _resolved


def _first_available(candidates: Sequence[str], available: set) -> str:
    for name in candidates:
        if name in available:
            return name
    return candidates[-1]


def family(name: str) -> str:
    """Family name to hand to QFont, after fallback resolution."""
    if not _resolved:
        load()
    return _resolved.get(name, name)
