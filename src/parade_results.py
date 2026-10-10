"""Reading the Demon Parade result scroll: which shikigami, how many shards.

The scroll lays eight card slots out on a fixed grid, four across and two down.
Each card carries a portrait with a ``xN`` over its lower left, and a name on a
ribbon underneath::

    +-----------+
    |  portrait |
    |       x4  |
    +-----------+
     N  Blue Imp

Two different recognition problems, solved two different ways.

**Names** are matched on the lettering alone, cropped away from the ribbon.

Matching the whole 125-pixel strip was the first attempt and it very nearly
credited shards to the wrong shikigami. The ribbon is identical on every card,
so most of the correlation was the two pictures agreeing about the background:
`Kanko` and `Kappa` matched each other at 0.938 against a threshold of 0.95,
twelve thousandths of room. Worse, it did not generalise — two pictures of the
*same* name on differently shaded ribbons scored 0.65 to 0.74, well below the
false ceiling, so the library only worked by holding a copy of every variant it
had ever seen.

Cropped to the lettering, and with names of a different pixel width ruled out
before the pixels are compared at all:

* the closest two different names are `Kyonshi Imoto` and `Kyonshi Ototo` at
  0.787, which differ by one letter
* two pictures of one name score 0.86 at worst and 0.96 typically

That is a margin of 0.072 instead of 0.012, and one picture now covers a name
across ribbon shades instead of one picture per shade.

**Counts** sit on the portrait, so the background is different artwork every
time, and the glyph is white on some cards and gold on others. Template
matching was tried three ways and all three were too close to call:

* plain, on the whole ``xN``: right answer 0.36 to 1.00, margin as low as 0.20
* masked to the strokes: right answer 0.95 to 1.00, but a gold glyph read 3 as
  6 — and the ``x``, identical on every card, was carrying the match
* masked, in greyscale: 0.921 against 0.918. A coin toss.

So the digit is cut away from the ``x``, thresholded to its own strokes,
trimmed to its bounding box and scaled to a fixed size, then compared by how
much of the two shapes overlap. On the same nine cards: right answer 0.51 to
1.00, wrong answer never above 0.30. Colour stops mattering, and a glyph that
cannot be separated at all falls below :data:`COUNT_ACCURACY` and is reported
unreadable rather than guessed.

There is no OCR here and none is wanted: the only engines available would add
tens of megabytes to a build that is already large and already argued with by
antivirus. Both libraries are ordinary folders of small PNGs, and both grow —
:func:`unknown_crops` hands back whatever could not be read so it can be cut
and named later.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

import paths
from game_control import read_image
from paths import template

logger = logging.getLogger(__name__)

# --- Layout, measured at a client of 1122x633 -------------------------------
GRID_ORIGIN = (237, 145)      # top-left of the first card
GRID_STEP = (168, 192)        # to the next card across, and down
GRID_COLUMNS = 4
GRID_ROWS = 2

# Boxes relative to a card's own top-left corner.
NAME_BOX = (20, 155, 145, 180)
# Just the digit. The "x" beside it is identical on every card, so including it
# had every candidate matching every card.
DIGIT_BOX = (46, 124, 68, 148)
GLYPH_SIZE = (18, 24)

# "Pact shards not received yet." — what the scroll says after a round that hit
# nothing. Detected outright rather than inferred from finding no cards: the
# chibi artwork on that screen has enough dark pixels in one of the grid's name
# boxes to look like an occupied slot, and it duly produced a phantom card.
TPL_NO_SHARDS = template("DemonParade", "noShards.png")
NO_SHARDS_ACCURACY = 0.85

# --- Tuning ----------------------------------------------------------------
# Names are rendered identically every time, so a true match scores 1.000. The
# danger is the other direction: scored against each other, the seven captured
# names reach 0.841 (Koi against Nurikabe — both short, same ribbon), so a
# threshold below that files one shikigami under another's name. It was 0.75 to
# begin with and did exactly that to two cards out of seven.
#
# 0.92 was too close for comfort once the library grew. With sixteen names, a
# shikigami that is in none of them reached 0.918 against one that is — two
# thousandths from being filed under the wrong name, which is worse than being
# filed under none. The ribbon is the reason: it is identical on every card, so
# the correlation is mostly agreeing about the background.
#
# Isolating the lettering and comparing shapes was tried and is worse: 0.924
# between two real names and 0.959 for an unknown, because scaling every name
# to one size throws away length, which is the strongest signal there is.
#
# So the threshold moves instead. A true match is a pixel-identical rendering
# and scores 1.000, so raising the bar costs nothing and buys a wide margin.
NAME_ACCURACY = 0.82
# Two names of different pixel widths are different names, whatever their
# strokes look like. Checked before correlating, which is both cheaper and more
# decisive. One pixel of slack loses no true pair and rules out a great many
# false ones.
TEXT_WIDTH_SLACK = 1
# Shape overlap, not correlation. Measured across live cards: the right digit
# scores 0.51 at worst, and two different digits reach 0.438 (`2` against `3`).
#
# This has to sit above that 0.438, not merely above the noise. The library
# holds 2, 3, 4 and 6; a card showing a 5 or a 7 has no right answer available,
# and with the floor underneath the confusion ceiling it would be read as
# whichever wrong digit happened to score best. Unknown is the correct answer
# there — an unread count costs one line of the tally, a wrong one credits the
# shards to a number nobody won.
COUNT_ACCURACY = 0.47
# A slot with no card is nearly a flat colour. Real ribbons carry dark
# lettering; measured, an occupied name box has hundreds of dark pixels and an
# empty one has none.
OCCUPIED_DARK_PIXELS = 25
DARK_THRESHOLD = 120
GLYPH_THRESHOLD = 175

# What counts as a letter when finding where the lettering is. Slivers of torn
# ribbon are 3 and 4 pixels tall; the shortest real letter is 8, and that is a
# bare `i` stem one pixel wide.
LETTER_MIN_HEIGHT = 6
LETTER_MAX_HEIGHT = 20
LETTER_MAX_WIDTH = 20
LETTER_MAX_AREA = 200


def _library_dirs(kind: str):
    """Where name and count pictures are read from, in order.

    Two places, and both are read — the second adds to the first rather than
    replacing it:

    * inside the build, which is how a fresh install already knows 82 names
    * ``DemonParade/`` beside the .exe, which is how it learns more

    The second exists because the first is unreachable to whoever is running
    the program. The shipped folder lives in ``_internal/``, and the updater
    replaces ``_internal/`` wholesale — so a name added there would survive
    until the next update and then vanish. Beside the .exe is where logs, cache
    and ``.env`` already live, and the updater leaves all of it alone.
    """
    yield os.path.join(paths.SCREENSHOT_DIR, "DemonParade", kind)
    yield os.path.join(str(paths.DATA_ROOT), "DemonParade", kind)


def _library(kind: str) -> str:
    """The shipped folder. Kept for callers that only want to name a path."""
    return os.path.join(paths.SCREENSHOT_DIR, "DemonParade", kind)


# "Koi (2).png" is a second picture of Koi, not a shikigami called "Koi (2)".
# One picture per name is not enough: the ribbon is shaded by rarity, so the
# same name on a purple SR card and a blue R card are different pictures, and
# a run kept reporting names that were already in the library as unknown.
VARIANT = re.compile(r"\s*\(\d+\)$")


def label_of(filename: str) -> str:
    return VARIANT.sub("", os.path.splitext(filename)[0])


def text_crop(patch: np.ndarray) -> Optional[np.ndarray]:
    """The lettering, cut away from the ribbon around it.

    The ribbon is the same on every card, so leaving it in means comparing two
    pictures that already agree about most of their pixels.
    """
    if patch is None or patch.size == 0:
        return None
    grey = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    _threshold, light = cv2.threshold(
        grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    dark = 255 - light
    # Lettering is the sparser of the two sides, whichever way round the card
    # has it.
    marks = light if (light > 0).mean() < (dark > 0).mean() else dark

    total, _labels, stats, _c = cv2.connectedComponentsWithStats(marks, 8)
    letters = [
        stats[i] for i in range(1, total)
        if (LETTER_MIN_HEIGHT <= stats[i][3] <= LETTER_MAX_HEIGHT
            and stats[i][2] <= LETTER_MAX_WIDTH
            and stats[i][4] <= LETTER_MAX_AREA)
    ]
    if not letters:
        return None
    x1 = max(0, min(int(s[0]) for s in letters) - 1)
    y1 = max(0, min(int(s[1]) for s in letters) - 1)
    x2 = max(int(s[0]) + int(s[2]) for s in letters) + 1
    y2 = max(int(s[1]) + int(s[3]) for s in letters) + 1
    cut = patch[y1:y2, x1:x2]
    return cut if cut.size else None


def _load(kind: str) -> Dict[str, List[np.ndarray]]:
    out: Dict[str, List[np.ndarray]] = {}
    seen = False
    for folder in _library_dirs(kind):
        if not os.path.isdir(folder):
            continue
        seen = True
        for entry in sorted(os.listdir(folder)):
            if not entry.lower().endswith(".png"):
                continue
            try:
                out.setdefault(label_of(entry), []).append(
                    read_image(os.path.join(folder, entry))
                )
            except Exception:
                logger.warning(
                    "Could not read %s template %s", kind, entry, exc_info=True
                )
    if not seen:
        logger.warning("No %s templates anywhere", kind)
    return out


_names: Optional[Dict[str, np.ndarray]] = None
_counts: Optional[Dict[str, np.ndarray]] = None


def names() -> Dict[str, np.ndarray]:
    global _names
    if _names is None:
        _names = _load("names")
    return _names


def counts() -> Dict[str, np.ndarray]:
    global _counts
    if _counts is None:
        _counts = _load("counts")
    return _counts


def reload_libraries() -> None:
    """Drop the cached templates so a newly added one is picked up."""
    global _names, _counts
    _names = _counts = None


# --- recognition ------------------------------------------------------------


def glyph(patch: np.ndarray):
    """A digit reduced to its shape: binary, trimmed, scaled to one size.

    Otsu rather than a fixed threshold, because the digit is white over dark
    artwork on some cards and gold over light on others. The largest connected
    blob is taken as the digit, which also throws away the specks a busy
    portrait leaves behind.
    """
    if patch.size == 0:
        return None
    grey = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if binary.mean() > 127:
        binary = 255 - binary       # strokes must come out white
    total, labels, stats, _centroids = cv2.connectedComponentsWithStats(binary, 8)
    if total < 2:
        return None
    index = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h = stats[index][:4]
    shape = (labels == index).astype(np.uint8)[y:y + h, x:x + w] * 255
    if shape.size == 0:
        return None
    return cv2.resize(shape, GLYPH_SIZE, interpolation=cv2.INTER_NEAREST)


def overlap(left: np.ndarray, right: np.ndarray) -> float:
    """How much of two shapes coincide, 0 to 1."""
    a, b = left > 0, right > 0
    union = int((a | b).sum())
    return float((a & b).sum()) / union if union else 0.0


def _best_name(patch: np.ndarray):
    cut = text_crop(patch)
    if cut is None:
        return None, 0.0
    best_label, best_score = None, -1.0
    for label, pictures in names().items():
        for template in pictures:
            reference = text_crop(template)
            if reference is None:
                continue
            if abs(reference.shape[1] - cut.shape[1]) > TEXT_WIDTH_SLACK:
                continue
            if (reference.shape[0] > cut.shape[0]
                    or reference.shape[1] > cut.shape[1]):
                # Same width within slack but taller: pad so the match is still
                # possible rather than silently skipping the right answer.
                height = max(reference.shape[0], cut.shape[0])
                width = max(reference.shape[1], cut.shape[1])
                canvas = np.zeros((height, width, 3), dtype=np.uint8)
                canvas[:cut.shape[0], :cut.shape[1]] = cut
                haystack = canvas
            else:
                haystack = cut
            score = float(
                cv2.matchTemplate(haystack, reference, cv2.TM_CCOEFF_NORMED).max()
            )
            if score > best_score:
                best_label, best_score = label, score
    return best_label, best_score


def _best_digit(patch: np.ndarray):
    shape = glyph(patch)
    if shape is None:
        return None, 0.0
    best_label, best_score = None, -1.0
    for label, pictures in counts().items():
        for template in pictures:
            reference = glyph(template)
            if reference is None:
                continue
            score = overlap(shape, reference)
            if score > best_score:
                best_label, best_score = label, score
    return best_label, best_score


def _card_boxes(scale_x: float = 1.0, scale_y: float = 1.0):
    for row in range(GRID_ROWS):
        for column in range(GRID_COLUMNS):
            x = GRID_ORIGIN[0] + column * GRID_STEP[0]
            y = GRID_ORIGIN[1] + row * GRID_STEP[1]
            yield (round(x * scale_x), round(y * scale_y))


def _crop(frame: np.ndarray, origin, box, scale_x=1.0, scale_y=1.0):
    x1 = round((origin[0] / scale_x + box[0]) * scale_x)
    y1 = round((origin[1] / scale_y + box[1]) * scale_y)
    x2 = round((origin[0] / scale_x + box[2]) * scale_x)
    y2 = round((origin[1] / scale_y + box[3]) * scale_y)
    return frame[y1:y2, x1:x2]


def _is_occupied(name_patch: np.ndarray) -> bool:
    if name_patch.size == 0:
        return False
    grey = cv2.cvtColor(name_patch, cv2.COLOR_BGR2GRAY)
    return int((grey < DARK_THRESHOLD).sum()) >= OCCUPIED_DARK_PIXELS


def read_scroll(frame: np.ndarray, scale_x: float = 1.0, scale_y: float = 1.0):
    """Every card on the scroll, as ``(name, count)``.

    ``name`` is None when the ribbon matches nothing in the library, and
    ``count`` is None when the glyph does. Either way the card is still
    returned, so a caller can report that something was won without being able
    to say what.
    """
    if says_no_shards(frame):
        return []

    found: List[Tuple[Optional[str], Optional[int]]] = []
    for origin in _card_boxes(scale_x, scale_y):
        name_patch = _crop(frame, origin, NAME_BOX, scale_x, scale_y)
        if not _is_occupied(name_patch):
            continue

        name, name_score = _best_name(name_patch)
        if name_score < NAME_ACCURACY:
            logger.info("Unrecognised shikigami on the scroll (best %.3f)", name_score)
            name = None

        count_patch = _crop(frame, origin, DIGIT_BOX, scale_x, scale_y)
        label, count_score = _best_digit(count_patch)
        count = None
        if label is not None and count_score >= COUNT_ACCURACY:
            try:
                count = int(label)
            except ValueError:
                count = None
        if count is None:
            logger.info(
                "Unreadable shard count for %s (best %r at %.3f)",
                name or "?", label, count_score,
            )
        found.append((name, count))
    return found


def says_no_shards(frame: np.ndarray) -> bool:
    """Whether the scroll is the empty one. Scored 1.000 on both empty scrolls
    captured and at most 0.451 on every other screen."""
    try:
        banner = read_image(TPL_NO_SHARDS)
    except Exception:
        logger.warning("No noShards template", exc_info=True)
        return False
    if banner.shape[0] > frame.shape[0] or banner.shape[1] > frame.shape[1]:
        return False
    result = cv2.matchTemplate(frame, banner, cv2.TM_CCOEFF_NORMED)
    return float(result.max()) >= NO_SHARDS_ACCURACY


def unknown_crops(frame: np.ndarray, scale_x: float = 1.0, scale_y: float = 1.0):
    """Name and count patches that could not be read, for cutting into the
    library later. Keyed by a description of where they came from."""
    out: Dict[str, np.ndarray] = {}
    for index, origin in enumerate(_card_boxes(scale_x, scale_y)):
        name_patch = _crop(frame, origin, NAME_BOX, scale_x, scale_y)
        if not _is_occupied(name_patch):
            continue
        _label, score = _best_name(name_patch)
        if score < NAME_ACCURACY:
            out["name-%d" % index] = name_patch
        count_patch = _crop(frame, origin, DIGIT_BOX, scale_x, scale_y)
        _label, score = _best_digit(count_patch)
        if score < COUNT_ACCURACY:
            out["count-%d" % index] = count_patch
    return out
