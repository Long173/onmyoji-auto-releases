"""Reading the Realm Raid ticket counter on the chapter panel — is it 30/30?

A sibling of :mod:`ticket_counter`, which asks the opposite question about the
same counter on a different screen. That one decides whether the raid loop has
run *out* of tickets, from the raid screen, and only needs the leftmost digit.
This one decides whether the map farm should break off and go raiding, from the
chapter panel, and needs the whole numerator: the cost of being wrong is
asymmetric — a missed 30/30 wastes a lap, a false 30/30 abandons the map to raid
with no tickets.

So this does not score the counter, it *reads* it. Lit columns inside the plaque
separate into runs — for "0/30", four of them 8, 5, 8 and 8 px wide — and each
run is one glyph. Three independent things then have to hold before the answer is
"full", and the two values most easily confused with 30/30 fail at the first:

    0/30, 6/30      one glyph before the slash, not two — rejected on the count
    10/30, 20/30    two glyphs, but the first is not a "3"
    30/30           two glyphs, "3" then "0"

Every glyph comparison is against a template cut from this very counter, and the
numbers say the thresholds are not delicate. The "3" template, matched against
each digit that could appear (harvested from the gold and sushi counters in the
same bar, same font, same size):

    3   0.996      the same digit elsewhere on screen, in another string
    8   0.762      the closest impostor of any digit
    6   0.637
    2   0.630      the worst that can actually appear before the slash
    1   0.392

and the "0" template: 1.000 on a real zero, 0.746 on the closest impostor. The
counter tops out at 30, so a two-digit numerator can only be 10-29 or 30 and its
first glyph can only be 1, 2 or 3 — leaving a gap of 0.37 between a real "3" and
the worst thing that could be mistaken for one. :data:`GLYPH_THRESHOLD` sits in
the middle of it.

**The denominator is checked too, and that is not redundant.** The last three
glyphs must read "/30" or nothing is reported at all. It is a free assertion that
the box still holds what this module thinks it holds: if the bar moves, the
window is an odd size, or the panel is not really on screen, the read fails
loudly as :data:`UNREADABLE` instead of quietly answering "not full" forever.

**30/30 itself has never been photographed.** Every measurement above comes from
a counter reading 0/30, and the true-positive case is inferred: the digits "3"
and "0" score 0.996 and 1.000 when the same glyphs are found elsewhere on the
same bar, so the numerator's copies should behave the same way. The synthetic
counters in the tests are built from those real glyphs and exercise the logic,
but they are not a photograph of the game rendering 30/30. Until one exists, that
is the one link in this chain that is reasoned rather than measured.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import cv2
import numpy as np

import geometry
from paths import template

logger = logging.getLogger(__name__)

TPL_DIGIT_3 = template("Ticket", "digit3.png")
TPL_DIGIT_0 = template("Ticket", "digit0.png")
TPL_SLASH = template("Ticket", "slash.png")

# A column counts as lit above this. The glyphs are near-white on a near-black
# plaque, so anything from about 60 to 200 segments identically; 110 is the
# middle of that.
LIT = 110
# Runs narrower than this are edge fringing rather than glyphs. The slash, the
# narrowest real glyph, is 5 px.
MIN_GLYPH_WIDTH = 3
# Above this, two glyphs are the same character. See the module docstring for
# the measurements this sits between.
GLYPH_THRESHOLD = 0.9

UNREADABLE = None

Run = Tuple[int, int]


def runs_of_lit_columns(band: np.ndarray, lit: int = LIT) -> List[Run]:
    """Split a strip into the column ranges that contain something."""
    on = band.max(axis=0) > lit
    found: List[Run] = []
    start: Optional[int] = None
    for index, value in enumerate(on):
        if value and start is None:
            start = index
        elif not value and start is not None:
            found.append((start, index))
            start = None
    if start is not None:
        found.append((start, len(on)))
    return [run for run in found if run[1] - run[0] >= MIN_GLYPH_WIDTH]


def looks_like(glyph: np.ndarray, template_image: np.ndarray) -> float:
    """How well one cut-out glyph matches a template of a known character.

    The glyph is padded before matching: a run's edges land a pixel either way
    depending on antialiasing, and without room to slide, a one-pixel offset
    reads as a different character.
    """
    pad = 4
    canvas = np.zeros(
        (glyph.shape[0] + 2 * pad, glyph.shape[1] + 2 * pad), dtype=glyph.dtype
    )
    canvas[pad:pad + glyph.shape[0], pad:pad + glyph.shape[1]] = glyph
    if canvas.shape[0] < template_image.shape[0] or canvas.shape[1] < template_image.shape[1]:
        return 0.0
    return float(
        cv2.minMaxLoc(cv2.matchTemplate(canvas, template_image, cv2.TM_CCOEFF_NORMED))[1]
    )


class TicketReader:
    """Reads the counter. Built once so the templates are loaded once."""

    def __init__(self, control) -> None:
        self._control = control
        self._digit3 = self._load(TPL_DIGIT_3)
        self._digit0 = self._load(TPL_DIGIT_0)
        self._slash = self._load(TPL_SLASH)

    @staticmethod
    def _load(path: str) -> np.ndarray:
        image = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ValueError("Could not read the glyph template %s" % path)
        return image

    def is_full(self) -> Optional[bool]:
        """True on 30/30, False on any other reading, None if unreadable.

        The three answers are deliberately distinct. A caller that treats "could
        not read" as "not full" merely wastes a lap; one that treats it as
        "full" walks off to raid with no tickets.
        """
        frame = self._control.reference_shot(gray=True)
        return self.read_band(self._band(frame))

    @staticmethod
    def _band(frame: np.ndarray) -> np.ndarray:
        (x1, y1), (x2, y2) = geometry.RAID_TICKET_BOX
        return frame[y1:y2, x1:x2]

    def read_band(self, band: np.ndarray) -> Optional[bool]:
        """The reading itself, given the strip of pixels. Separated for tests."""
        glyphs = runs_of_lit_columns(band)
        # "N/30" is four glyphs at least, five when the numerator has two.
        if len(glyphs) < 4:
            logger.debug("Ticket counter: %d glyphs, too few to be N/30", len(glyphs))
            return UNREADABLE

        def cut(run: Run) -> np.ndarray:
            return band[:, run[0]:run[1]]

        # The denominator, as an assertion that this really is the counter.
        if not (
            looks_like(cut(glyphs[-1]), self._digit0) > GLYPH_THRESHOLD
            and looks_like(cut(glyphs[-2]), self._digit3) > GLYPH_THRESHOLD
            and looks_like(cut(glyphs[-3]), self._slash) > GLYPH_THRESHOLD
        ):
            logger.debug("Ticket counter: the last three glyphs are not '/30'")
            return UNREADABLE

        numerator = glyphs[:-3]
        if len(numerator) != 2:
            # One glyph is 0-9; three would not be this counter at all.
            return False
        return bool(
            looks_like(cut(numerator[0]), self._digit3) > GLYPH_THRESHOLD
            and looks_like(cut(numerator[1]), self._digit0) > GLYPH_THRESHOLD
        )
