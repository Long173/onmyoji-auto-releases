"""Reading the chapter list down the right of the world map.

Exploration used to open its chapter by clicking one saved point — by default
the "Chapter 28" row of this list, where the list happens to rest. Any other
chapter meant scrolling the list by hand first and picking a new point, and a
list scrolled since then quietly opened whichever chapter had moved under it.
This reads the list instead, so the setting can be the chapter's number.

Every row starts with the word "Chapter" followed by the number, white on a
dark band. Two templates do the reading:

* ``chapterWord.png`` finds each row. Over 36 rows in twelve captures of the
  list at every scroll position it scored 0.88-1.00.
* ``chapter/NN.png`` — the number box, one per chapter, cut with the blank
  after a single digit kept in it, so "Chapter 1" cannot stand in for
  "Chapter 12". Each row is read as the best-scoring of the 28. Measured over
  the same 36 rows: no misreads; the closest a wrong number came was 0.054
  below the right one (26 against 20, the pairs that share a first digit are
  the near ones). Read with a template taken from a *different* capture, the
  right number still scored 0.90-0.995.

Digit-by-digit reading was tried first and dropped: thresholded glyphs shifted
by a pixel as the list stopped at different offsets, and ten digits came out
as 31 shapes.

What the reader also checks is that the rows it sees are consecutive. The list
shows three or four neighbours at a time, so "13, 14, 15" is a reading that
holds together and "13, 19, 15" is one that does not — and a reading that does
not is thrown away rather than clicked on.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

import geometry
from game_control import CaptureError, read_image
from paths import template

logger = logging.getLogger(__name__)

TPL_CHAPTER_WORD = template("Exploration", "chapterWord.png")
CHAPTER_DIR = os.path.join(os.path.dirname(TPL_CHAPTER_WORD), "chapter")
CHAPTERS = 28
# A row's "Chapter" word. Measured 0.88 at worst on a real row; partial rows at
# the list's edges score lower and are better skipped than half-read.
WORD_THRESHOLD = 0.8
# Below this the number box is not a chapter number at all. The right number
# scored 0.90 at worst; this only keeps out a row whose digits are covered.
NUMBER_FLOOR = 0.75
# Rows closer than this are the same row found twice.
ROW_SPACING = 10
# How far right of the word the number box reaches, in reference pixels.
NUMBER_WIDTH = 33
NUMBER_MARGIN = 2

Point = Tuple[int, int]


def consecutive(numbers: List[int]) -> bool:
    """Whether a top-to-bottom reading is a run of neighbouring chapters."""
    return all(b == a + 1 for a, b in zip(numbers, numbers[1:]))


class ChapterList:
    """Reads which chapters the world map's list is showing, and where."""

    def __init__(self, control, geo: geometry.Geometry) -> None:
        self._control = control
        self._geometry = geo
        self._word: Optional[np.ndarray] = None
        self._numbers: Dict[int, np.ndarray] = {}

    def _load(self) -> None:
        if self._word is not None:
            return
        self._word = read_image(TPL_CHAPTER_WORD, cv2.IMREAD_GRAYSCALE)
        for n in range(1, CHAPTERS + 1):
            self._numbers[n] = read_image(
                os.path.join(CHAPTER_DIR, "%02d.png" % n), cv2.IMREAD_GRAYSCALE)

    def read(self) -> List[Tuple[int, Point]]:
        """(chapter, where to click it) for each row in view, top to bottom.

        Empty when the list cannot be read or does not hold together — never a
        guess. Points are in the window's own client coordinates.
        """
        self._load()
        try:
            frame = self._control.reference_shot(gray=True)
        except CaptureError:
            return []
        rows = read_rows(frame, self._word, self._numbers)
        numbers = [n for n, _ in rows]
        if not consecutive(numbers):
            logger.info("Chapter list read as %s — not consecutive; reading again",
                        numbers)
            return []
        return [(n, self._geometry.point(p)) for n, p in rows]


def read_rows(frame: np.ndarray, word: np.ndarray,
              numbers: Dict[int, np.ndarray]) -> List[Tuple[int, Point]]:
    """(chapter, centre of its label) for each readable row, in reference pixels."""
    (x1, y1), (x2, y2) = geometry.EXPLORATION_CHAPTER_LIST
    band = frame[y1:y2, x1:x2]
    if band.shape[0] < word.shape[0] or band.shape[1] < word.shape[1]:
        return []
    scores = cv2.matchTemplate(band, word, cv2.TM_CCOEFF_NORMED)
    found: List[Tuple[int, int]] = []
    for y, x in sorted(zip(*np.where(scores > WORD_THRESHOLD)),
                       key=lambda p: -scores[p]):
        if all(abs(y - fy) > ROW_SPACING for fy, _ in found):
            found.append((int(y), int(x)))
    rows = []
    word_h, word_w = word.shape
    for y, x in sorted(found):
        top, left = y + y1, x + x1
        box = frame[max(0, top - NUMBER_MARGIN):top + word_h + NUMBER_MARGIN,
                    left + word_w - NUMBER_MARGIN:left + word_w + NUMBER_WIDTH]
        number = _best_number(box, numbers)
        if number is None:
            continue
        centre = (left + (word_w + NUMBER_WIDTH) // 2, top + word_h // 2)
        rows.append((number, centre))
    return rows


def _best_number(box: np.ndarray, numbers: Dict[int, np.ndarray]) -> Optional[int]:
    best, best_score = None, NUMBER_FLOOR
    for n, tpl in numbers.items():
        if box.shape[0] < tpl.shape[0] or box.shape[1] < tpl.shape[1]:
            continue
        score = float(cv2.matchTemplate(box, tpl, cv2.TM_CCOEFF_NORMED).max())
        if score > best_score:
            best, best_score = n, score
    return best
