"""Design tokens for the "Classical" dark theme.

Every value here is lifted from the Claude Design source (`Onmyoji Auto v2.dc.html`
and `Onmyoji Wiki.dc.html`). Keep this module the single place they live: a
colour typed inline somewhere else is a colour that drifts.

Two CSS features the design leans on have no Qt Style Sheet equivalent, so they
are handled in Python instead:

* ``letter-spacing`` — use :func:`mono` / :func:`display`, which set tracking on
  the QFont itself.
* ``text-transform: uppercase`` — uppercase the string at the call site.
"""
from __future__ import annotations

from PyQt5 import QtGui

import fonts

APP_NAME = "Onmyoji Tool"
APP_SUBTITLE = "Trung tâm tác vụ"
APP_VERSION = "3.17"

# Storage identifiers, deliberately left at the old name. These are not labels
# — they are the address of the user's data:
#
#   ORGANISATION / SETTINGS_SCOPE -> HKCU\Software\OnmyojiAuto\RealmRaid
#
# Renaming them would point the app at an empty key, silently losing every
# saved setting and every remembered task queue (and orphaning the v2 → v3
# migration that reads them). Nobody sees these strings; leave them alone.
ORGANISATION = "OnmyojiAuto"
SETTINGS_SCOPE = "RealmRaid"
DEFAULT_WINDOW_TITLE = "陰陽師Onmyoji"

# ── Surfaces ────────────────────────────────────────────────────────────────
PAGE = "#100f0e"          # outermost backdrop
WINDOW = "#171614"        # window body
CHROME = "#131211"        # title bar and footer
BAR = "#1a1816"           # settings / search strip
SIDEBAR = "#141311"       # wiki navigation column
CARD = "#1c1a18"          # card body
INSET = "#171513"         # image frames, text inputs
HOVER = "#1e1c19"         # hovered chrome, active nav row
ROW_HOVER = "#1b1917"     # hovered list row

# Diagonal hatch used wherever an image has not loaded yet.
HATCH_LIGHT = "#201d1a"
HATCH_DARK = "#1b1917"

# ── Lines ───────────────────────────────────────────────────────────────────
BORDER = "#302c26"        # card outline
DIVIDER = "#2a2723"       # section rule
CONTROL = "#3a352e"       # button / input outline
CONTROL_STRONG = "#4a443c"  # checkbox outline
ROW_RULE = "#232120"      # table row rule
BORDER_HOVER = "#6b5a3c"  # card outline, hovered
CONTROL_HOVER = "#6b6259"  # neutral button outline, hovered

# ── Ink ─────────────────────────────────────────────────────────────────────
TEXT = "#edeae3"          # primary
TEXT_BODY = "#cfc9c1"     # long-form paragraphs
TEXT_SECONDARY = "#b8b2aa"
TEXT_MUTED = "#96908a"
TEXT_NAV = "#9a948c"
TEXT_DIM = "#8b857e"
TEXT_LABEL = "#7d7770"    # mono section labels
TEXT_FAINT = "#6c665f"    # placeholders, counts

# ── Accent (gold) ───────────────────────────────────────────────────────────
ACCENT = "#c9a15c"
ACCENT_HOVER = "#dcb877"
ACCENT_WASH = "rgba(201, 161, 92, 0.12)"   # hovered outline button
ACCENT_FILL = "rgba(201, 161, 92, 0.16)"   # selected chip
ACCENT_PRESSED = "rgba(201, 161, 92, 0.22)"

# ── Semantic ────────────────────────────────────────────────────────────────
# Demon fire — the orbs an active skill spends. Sampled from the game's own
# icon (assets/icons/demon_fire.png), not chosen: the badge sits right beside
# the artwork and a near-miss would read as a mistake.
DEMON_FIRE = "#2ea1da"
DEMON_FIRE_BORDER = "#1f4a63"

DANGER = "#c08a7e"
DANGER_BORDER = "#5c3f39"
DANGER_BORDER_HOVER = "#8c554b"
DANGER_WASH = "rgba(180, 86, 74, 0.12)"
CLOSE_HOVER = "#8c3a30"
ERROR = "#b4564a"
SUCCESS = "#8a9a7b"

STATUS = {
    "idle": (TEXT_DIM, BORDER, "Sẵn sàng"),
    "running": (ACCENT, "#4a3d28", "Đang chạy"),
    "paused": (ACCENT_HOVER, "#4a3d28", "Tạm dừng"),
    "error": (ERROR, "#4d2f2a", "Mất cửa sổ"),
    "done": (SUCCESS, "#38402f", "Hết vé"),
}

EFFECT_KIND_COLOR = {
    "buff": SUCCESS,
    "debuff": DANGER,
    "other": ACCENT,
}

# ── Shape ───────────────────────────────────────────────────────────────────
RADIUS = 4
RADIUS_SMALL = 3
RADIUS_BADGE = 2

# ── Type ────────────────────────────────────────────────────────────────────
DISPLAY_FAMILY = "Cormorant Garamond"
BODY_FAMILY = "Lora"
MONO_FAMILY = "IBM Plex Mono"


def _font(family_key: str, size: float, weight: int, tracking: float = 0.0) -> QtGui.QFont:
    font = QtGui.QFont(fonts.family(family_key))
    font.setPixelSize(round(size))
    font.setWeight(_qt_weight(weight))
    if tracking:
        # CSS tracking is in em; Qt wants a percentage where 100 means normal.
        font.setLetterSpacing(QtGui.QFont.PercentageSpacing, 100 + tracking * 100)
    font.setStyleStrategy(QtGui.QFont.PreferAntialias)
    return font


def _qt_weight(css_weight: int) -> int:
    """Map a CSS weight onto the 0-99 scale QFont uses in Qt 5."""
    return {400: QtGui.QFont.Normal, 500: QtGui.QFont.Medium,
            600: QtGui.QFont.DemiBold, 700: QtGui.QFont.Bold}.get(
        css_weight, QtGui.QFont.Normal)


def display(size: float, weight: int = 600) -> QtGui.QFont:
    """Cormorant Garamond — headings and card titles."""
    return _font(DISPLAY_FAMILY, size, weight)


def body(size: float = 13.5, weight: int = 400, italic: bool = False) -> QtGui.QFont:
    """Lora — prose, buttons, form labels."""
    font = _font(BODY_FAMILY, size, weight)
    font.setItalic(italic)
    return font


def mono(size: float = 10, tracking: float = 0.2, weight: int = 400) -> QtGui.QFont:
    """IBM Plex Mono — section labels, identifiers, figures.

    ``tracking`` is in em, matching the design's ``letter-spacing`` values.
    """
    return _font(MONO_FAMILY, size, weight, tracking)


def tabular(size: float = 17, weight: int = 400) -> QtGui.QFont:
    """Mono without tracking, with fixed-width digits for counters."""
    font = _font(MONO_FAMILY, size, weight)
    font.setStyleHint(QtGui.QFont.Monospace)
    return font


def app_stylesheet() -> str:
    """Base sheet applied once to the QApplication.

    Deliberately thin: component styling lives with the components, and the
    scrollbar rules are here only because they apply to every scroll area.
    """
    return f"""
    QWidget {{
        background: transparent;
        color: {TEXT};
    }}
    QToolTip {{
        background: {CARD};
        color: {TEXT};
        border: 1px solid {CONTROL};
        padding: 5px 8px;
    }}
    QMessageBox, QDialog {{
        background: {WINDOW};
    }}
    QMessageBox QLabel {{
        color: {TEXT};
        background: transparent;
    }}
    QMessageBox QPushButton {{
        background: transparent;
        color: {TEXT_SECONDARY};
        border: 1px solid {CONTROL};
        border-radius: {RADIUS}px;
        padding: 7px 18px;
        min-width: 78px;
    }}
    QMessageBox QPushButton:hover {{
        border-color: {CONTROL_HOVER};
        color: {TEXT};
    }}
    QMessageBox QPushButton:default {{
        color: {ACCENT};
        border-color: {ACCENT};
    }}
    QScrollArea, QScrollArea > QWidget > QWidget {{
        background: transparent;
        border: 0;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {CONTROL};
        border-radius: 5px;
        min-height: 40px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {CONTROL_HOVER};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        height: 0;
        background: transparent;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: {CONTROL};
        border-radius: 5px;
        min-width: 40px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        width: 0;
        background: transparent;
    }}
    """
