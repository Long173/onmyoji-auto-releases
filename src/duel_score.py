"""Reading the Duel score off the lobby — "1958/2000" under the tier.

The auto PvP task stops when a target score is reached (2400, 2700, or 3000 for
Danh sĩ), so it has to *read* the number, not recognise a picture of it. The
method is the one :mod:`raid_tickets` uses on the ticket counter: lit columns in
a fixed strip split into runs, one run per glyph, and each glyph is compared
with a template of every character it could be.

Measured on the 19 lobby screens of recordings/pvp (1000/1200 up to 1958/2000,
every digit represented), at template scale:

* Any brightness split from 100 to 150 segments every one of them into exactly
  the right number of glyphs once runs narrower than 2 px are dropped; 135 is
  the middle. A split of 120 cut one "8" in two.
* The text starts at the same column whatever the digits, and is always
  "NNNN/NNNN" in this range, so nothing has to be centred or aligned.

Comparing glyphs is where the ticket counter's method did not carry over.
Sliding a template across a padded glyph (``raid_tickets.looks_like``) could not
tell 5, 6 and 8 apart here: a "6" from 1760 scored 0.90 as a 5, 0.88 as an 8 and
only 0.84 as itself. These glyphs are seven pixels wide and the differences are
a pixel or two at one corner, which a few pixels of slide wash out. So nothing
slides. Each glyph is cut to its own ink, stretched to one fixed size and
compared pixel for pixel with stored examples — several per character, because
one "6" alone still lost to a "5" (the screen is resized to template scale, and
the same digit lands on the pixel grid differently from frame to frame). Left
out of the examples in turn, every one of the 171 glyphs on the recording was
read right, by at least 0.14 over the next character; the worst right answer
scored 0.85.

The examples named ``*_live*`` come from the tool's own capture of a 1122x633
client rather than from the 1136x640 recording scaled down. The first live run
stopped on its first lobby: its slash was 4 px wide, every recorded one 3, and
it scored 0.66 against them. Rendered at the reference size, glyphs come out a
pixel wider than resized ones; the narrow ones feel that most.

A glyph is only compared with examples of about its own width. "1" is two
pixels wide and the slash three, and stretched to the common size either looks
like any vertical stroke. Width rules them out first.

The reading is checked as a whole, and anything that does not hold up comes
back as :data:`UNREADABLE` rather than as a number: a popup over the lobby, or a
half-faded screen. The task treats "cannot read" as a reason to stop, because
the alternative is fighting on past a target it cannot see.

**Danh sĩ has no score.** From Celebrity up the lobby counts stars instead —
"5/30" beside a star, about ten pixels lower than the score sits — so the rule,
as the player put it, is that a number short of four digits means Danh sĩ has
been reached. :data:`CELEBRITY` is that answer. Both lines are looked at; on the
21 tier lobbies the star line never once read as a short "N/M", and on the one
Celebrity lobby (a player's screenshot) it read "5/30" exactly.
"""
from __future__ import annotations

import glob
import logging
import os
import re
from typing import Dict, List, Optional, Tuple, Union

import cv2
import numpy as np

import geometry
from paths import template

logger = logging.getLogger(__name__)

# A column counts as lit above this. See the module docstring.
LIT = 135
# Runs narrower than this are fringing. "1", the narrowest glyph, is 2 px.
MIN_GLYPH_WIDTH = 2
# An example is tried only on glyphs within this many pixels of its width.
WIDTH_SLACK = 2
# Every glyph is stretched to this (width, height) before comparing.
NORMAL_SIZE = (14, 26)
# The best example must score at least this, and beat the best example of any
# other character by at least MARGIN. Measured: 0.85 and 0.14 at worst.
GLYPH_THRESHOLD = 0.75
MARGIN = 0.05

UNREADABLE = None
# The lobby shows a star count, not a score: Danh sĩ or above.
CELEBRITY = "celebrity"

SLASH = "/"
CHARACTERS = tuple("0123456789") + (SLASH,)

Run = Tuple[int, int]
Score = Tuple[int, int]
Reading = Union[Score, str, None]

# "5/30": short of the four digits every tier score has.
_STAR_COUNT = re.compile(r"\d{1,3}/\d{1,3}")


def glyph_runs(band: np.ndarray, lit: int = LIT) -> List[Run]:
    """Column ranges of the strip that hold something bright enough."""
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


def normalise(glyph: np.ndarray) -> Optional[np.ndarray]:
    """The glyph cut to its ink, stretched to NORMAL_SIZE, zero mean, unit norm."""
    rows = np.where(glyph.max(axis=1) > LIT)[0]
    if rows.size == 0:
        return None
    ink = glyph[rows[0]:rows[-1] + 1]
    out = cv2.resize(ink, NORMAL_SIZE, interpolation=cv2.INTER_LINEAR)
    out = out.astype(np.float32)
    out -= out.mean()
    norm = float(np.linalg.norm(out))
    return out / norm if norm else None


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Correlation of two normalised glyphs: 1.0 is identical."""
    return float((a * b).sum())


def load_examples() -> Dict[str, List[np.ndarray]]:
    """Every stored example, by character: ``digits/6_00.png`` is a "6"."""
    folder = template("Duel", "digits")
    examples: Dict[str, List[np.ndarray]] = {}
    for path in sorted(glob.glob(os.path.join(folder, "*.png"))):
        name = os.path.basename(path).split("_")[0]
        character = SLASH if name == "slash" else name
        image = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ValueError("Could not read the glyph example %s" % path)
        examples.setdefault(character, []).append(image)
    missing = set(CHARACTERS) - set(examples)
    if missing:
        raise ValueError("No glyph examples for %s in %s"
                         % ("".join(sorted(missing)), folder))
    return examples


class ScoreReader:
    """Reads the lobby score. Built once so the examples load once."""

    def __init__(self, examples: Optional[Dict[str, List[np.ndarray]]] = None) -> None:
        raw = examples if examples is not None else load_examples()
        # (width, normalised pixels) per example; normalised once, here.
        self._examples = {
            character: [(image.shape[1], normalise(image)) for image in images]
            for character, images in raw.items()
        }

    def read(self, frame: np.ndarray) -> Reading:
        """From a greyscale frame at template scale: (score, next tier's
        score), :data:`CELEBRITY`, or :data:`UNREADABLE`."""
        for box in (geometry.DUEL_SCORE_BOX, geometry.DUEL_STARS_BOX):
            (x1, y1), (x2, y2) = box
            text = self.read_text(frame[y1:y2, x1:x2])
            if text is None:
                continue
            score = parse(text)
            if score is not None:
                return score
            if is_star_count(text):
                logger.debug("Duel lobby shows %r: Danh sĩ", text)
                return CELEBRITY
        return UNREADABLE

    def read_band(self, band: np.ndarray) -> Optional[Score]:
        """The score in one strip, or unreadable. Separated for tests."""
        text = self.read_text(band)
        return None if text is None else parse(text)

    def read_text(self, band: np.ndarray) -> Optional[str]:
        """Every glyph in the strip, or None if any one will not classify."""
        # A run touching an edge of the box is something the box cut through.
        runs = [run for run in glyph_runs(band)
                if run[0] > 0 and run[1] < band.shape[1]]
        text = ""
        for start, end in runs:
            character = self._classify(band[:, start:end])
            if character is None:
                return None
            text += character
        return text or None

    def _classify(self, glyph: np.ndarray) -> Optional[str]:
        width = glyph.shape[1]
        shape = normalise(glyph)
        if shape is None:
            return None
        best: Dict[str, float] = {}
        for character, examples in self._examples.items():
            fits = [similarity(shape, pixels) for example_width, pixels in examples
                    if pixels is not None
                    and abs(example_width - width) <= WIDTH_SLACK]
            if fits:
                best[character] = max(fits)
        scores = sorted(((score, character) for character, score in best.items()),
                        reverse=True)
        if not scores or scores[0][0] < GLYPH_THRESHOLD:
            return None
        if len(scores) > 1 and scores[0][0] - scores[1][0] < MARGIN:
            return None
        return scores[0][1]


def is_star_count(text: str) -> bool:
    """"5/30" — a number short of four digits, which only Danh sĩ shows."""
    return bool(_STAR_COUNT.fullmatch(text or ""))


def parse(text: str) -> Optional[Score]:
    """"1958/2000" -> (1958, 2000). Anything else is unreadable."""
    left, slash, right = text.partition(SLASH)
    if not slash or not left.isdigit() or not right.isdigit():
        logger.debug("Duel score: %r is not N/M", text)
        return UNREADABLE
    if not (3 <= len(left) <= 4 and 3 <= len(right) <= 4):
        return UNREADABLE
    score, ceiling = int(left), int(right)
    if score > ceiling:
        # The bar fills towards the next tier; past it would be a misread.
        return UNREADABLE
    return score, ceiling
