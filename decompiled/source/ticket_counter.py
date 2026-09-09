"""Decide whether the Realm Raid ticket counter reads zero.

The counter is drawn as ``0/30`` in the top-right corner. Two things rule out
simply template-matching the whole string:

* ``0/30`` is a substring of ``10/30``, so a sliding match would fire on both.
* The text is centred in its pill, so every glyph shifts sideways when the
  numerator gains a digit — fixed coordinates cannot be trusted either.

What is reliable is the *leftmost* glyph. It is the first digit of the
numerator: ``0`` when the tickets are gone, ``1``/``2``/``3``… otherwise. So the
counter is segmented into glyphs and only that first one is compared against a
stored ``0``. This holds whatever the denominator is.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

MIN_GLYPH_AREA = 10
MIN_GLYPH_HEIGHT = 6
MATCH_THRESHOLD = 0.72

Glyph = Tuple[int, int, int, int]


def find_glyphs(grey: np.ndarray) -> List[Glyph]:
    """Bright glyph boxes in a greyscale crop, ordered left to right.

    The split point is chosen per crop rather than fixed. It used to be a
    constant 170, which held only while the counter was bright text on a dark
    pill. It is not always: the guild board writes its count dark on a light
    panel, and — the case that actually broke — the game dims everything behind
    an open enemy card, at which point both the ink and the panel sat above any
    fixed line and the whole strip came back as one blob.

    Otsu picks the split from the crop's own histogram, so only the *contrast*
    between ink and panel has to survive, not any particular brightness.
    """
    if grey is None or grey.size == 0:
        return []
    _, mask = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    glyphs = [
        (int(x), int(y), int(w), int(h))
        for x, y, w, h, area in stats[1:]
        if area >= MIN_GLYPH_AREA and h >= MIN_GLYPH_HEIGHT
    ]
    glyphs.sort()
    return glyphs


def leftmost_glyph(grey: np.ndarray) -> Optional[np.ndarray]:
    """The first glyph of the counter, or ``None`` if nothing legible is there."""
    glyphs = find_glyphs(grey)
    if not glyphs:
        return None
    x, y, w, h = glyphs[0]
    return grey[y:y + h, x:x + w]


def score_against_zero(grey: np.ndarray, zero_template: np.ndarray) -> float:
    """Correlation of the counter's first glyph with a known ``0``.

    Returns ``-1.0`` when there is no glyph to compare.
    """
    glyph = leftmost_glyph(grey)
    if glyph is None or glyph.size == 0:
        return -1.0
    resized = cv2.resize(
        glyph,
        (zero_template.shape[1], zero_template.shape[0]),
        interpolation=cv2.INTER_AREA,
    )
    result = cv2.matchTemplate(resized, zero_template, cv2.TM_CCOEFF_NORMED)
    return float(result[0][0])


def is_zero(grey: np.ndarray, zero_template: np.ndarray) -> bool:
    """True when the ticket counter's numerator is ``0``."""
    score = score_against_zero(grey, zero_template)
    if score >= MATCH_THRESHOLD:
        logger.debug("Ticket counter reads zero (score %.3f)", score)
        return True
    return False
