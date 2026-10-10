"""Telling a common parading shikigami from one worth a bean.

Aiming only pays if the loop can choose *which* figure to throw at, and the
choice runs the opposite way to the obvious one: it learns the **commons** and
throws at everything else. Rare shikigami visit a single round and never come
back, so no library of them can name the next one, while commons repeat and can
be learned. :func:`is_target` carries the measurements.

So the answer this module gives is really one bit — common, or not — and a
figure it cannot name counts as *not*.

A shikigami is recognised by its **colours**, not by its shape. That was
measured, not assumed:

* comparing the cut-out pixels: 220 sprites from a live round fell into 174
  clusters, 150 of them with a single member. Two pictures of one figure
  rarely recognised each other, because it turns as it walks and the pose
  changes more than the identity does.
* comparing a hue-and-saturation histogram of the same cut-outs: 62 clusters,
  18 singletons. Inspected by eye, each cluster held one shikigami in a spread
  of poses.

Colour survives what shape does not — turning, walking, limbs crossing, half
the figure behind another. And every shikigami here is drawn in its own
palette, which is exactly what a histogram measures.

What the app reads is `screenshots/DemonParade/rarity.npz`, one packed file of
signatures. Behind it is a folder per grade::

    screenshots/DemonParade/rarity/COMMON/*.png
    screenshots/DemonParade/rarity/RARE/*.png
    ...

but those pictures are only needed to rebuild the packed file — 4,769 of them
come to 146 MB against 1.6 MB packed, and they grow with every collection run.
See :func:`raw_library_dir` for moving them off a full drive, and
`tools/pack_library.py` for repacking after adding any.

Most of COMMON is filled in without anyone looking at it: a group seen in two
different rounds is a common by definition. RARE comes from a person, and it
earns its place twice over — the loop reports when it recognises one, and it is
the check that the common library has not quietly swallowed the figures it
exists to leave behind.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np

import paths
from game_control import read_image

logger = logging.getLogger(__name__)

# Folders the library is read from.
#
# RARE is the game's SP and SSR together. They were kept apart at first and the
# split earned nothing: the loop spends a bean on either and treats them
# identically, so telling them apart was labelling effort buying a number that
# changed no decision. COMMON is everything a player looked at and did not call
# rare. N, R and SR come from an earlier pass that graded commons individually;
# they behave exactly like COMMON.
RANKS = ("RARE", "SR", "R", "N", "COMMON")
# Grades not worth a bean. Note what is absent from this list: an unrecognised
# figure. See :func:`is_target` for why that is the whole point.
COMMON_RANKS = ("COMMON", "SR", "R", "N")
# Worth a bean, and named. Reported in the log as a bonus; the aiming does not
# depend on it, because an unnamed figure is a target too.
TARGET_RANKS = ("RARE",)

# Hue is what separates the palettes; saturation keeps a washed-out figure from
# matching a vivid one of the same hue. Value is left out deliberately — the
# parade is lit from behind and a figure's brightness swings as it walks.
HUE_BINS = 24
SATURATION_BINS = 8
# Below this a pixel is the blacked-out background around the cut-out.
BACKGROUND_LEVEL = 12
# A cut-out with less than this much figure in it says nothing useful.
MIN_PIXELS = 300
# Measured: same-figure pairs sit above this, different figures below.
MATCH_ACCURACY = 0.85


# Where the pictures live when they are wanted, which is only for rebuilding
# the packed file. They are bulky — some 4,700 of them at 151 MB, growing every
# time more rounds are collected — so they can be moved off a full drive:
#
#     setx ONMYOJI_RARITY_DIR D:\onmyoji\rarity
RAW_LIBRARY_VARIABLE = "ONMYOJI_RARITY_DIR"


def raw_library_dir() -> Path:
    """The folder of labelled pictures, wherever it has been put.

    Three places are consulted, in order: the environment variable, a pointer
    file beside where the pictures used to be, and finally that original place.

    The pointer file exists because an environment variable is only picked up
    by shells started after it was set, which is a confusing way to lose a
    library — a terminal opened five minutes earlier quietly falls back to an
    empty folder. A file in the project travels with it.
    """
    override = os.environ.get(RAW_LIBRARY_VARIABLE)
    if override:
        return Path(override)
    pointer = Path(paths.SCREENSHOT_DIR) / "DemonParade" / "rarity.where"
    if pointer.is_file():
        try:
            written = pointer.read_text(encoding="utf-8").strip()
        except OSError:
            logger.warning("Could not read %s", pointer, exc_info=True)
            written = ""
        if written:
            return Path(written)
    return Path(paths.SCREENSHOT_DIR) / "DemonParade" / "rarity"


def packed_library_path() -> Path:
    """The signatures, packed into one file. This is what the app reads."""
    return Path(paths.SCREENSHOT_DIR) / "DemonParade" / "rarity.npz"


def library_dirs():
    """Picture folders to fall back on when there is no packed file."""
    yield str(raw_library_dir())
    yield os.path.join(str(paths.DATA_ROOT), "DemonParade", "rarity")


def signature(sprite: np.ndarray) -> Optional[np.ndarray]:
    """A figure's colours, as one comparable vector."""
    if sprite is None or sprite.size == 0 or sprite.ndim != 3:
        return None
    hsv = cv2.cvtColor(sprite, cv2.COLOR_BGR2HSV)
    mask = (sprite.max(axis=2) > BACKGROUND_LEVEL).astype(np.uint8)
    if int(mask.sum()) < MIN_PIXELS:
        return None
    histogram = cv2.calcHist(
        [hsv], [0, 1], mask, [HUE_BINS, SATURATION_BINS], [0, 180, 0, 256]
    )
    cv2.normalize(histogram, histogram, 0, 1, cv2.NORM_MINMAX)
    return histogram.flatten().astype(np.float32)


def alike(left: np.ndarray, right: np.ndarray) -> float:
    return float(cv2.compareHist(left, right, cv2.HISTCMP_CORREL))


_library: Optional[Dict[str, List[np.ndarray]]] = None


def _packed_library() -> Optional[Dict[str, List[np.ndarray]]]:
    """The signatures read straight out of the packed file, if there is one."""
    path = packed_library_path()
    if not path.is_file():
        return None
    try:
        with np.load(str(path), allow_pickle=False) as bundle:
            marks, ranks = bundle["marks"], bundle["ranks"]
    except Exception:
        logger.warning("Could not read %s; falling back to the pictures", path,
                       exc_info=True)
        return None
    out: Dict[str, List[np.ndarray]] = {}
    for rank, mark in zip(ranks, marks):
        out.setdefault(str(rank), []).append(np.ascontiguousarray(mark))
    return out or None


def library() -> Dict[str, List[np.ndarray]]:
    """Rarity -> the colour signatures filed under it.

    Read from the packed file where there is one. The pictures behind it run to
    151 MB and grow with every collection run, which is a lot to carry into a
    build and a lot to decode at startup, while the signatures taken from them
    come to about 3.6 MB. Rebuild it with tools/pack_library.py after labelling
    anything new, or this keeps answering with the old library.
    """
    global _library
    if _library is None:
        _library = _packed_library()
    if _library is None:
        _library = {}
        for root in library_dirs():
            if not os.path.isdir(root):
                continue
            for rank in os.listdir(root):
                folder = os.path.join(root, rank)
                if not os.path.isdir(folder) or rank not in RANKS:
                    continue
                for entry in sorted(os.listdir(folder)):
                    if not entry.lower().endswith(".png"):
                        continue
                    try:
                        mark = signature(read_image(os.path.join(folder, entry)))
                    except Exception:
                        logger.warning("Could not read %s/%s", rank, entry,
                                       exc_info=True)
                        continue
                    if mark is not None:
                        _library.setdefault(rank, []).append(mark)
    return _library


def reload_library() -> None:
    global _library
    _library = None


def rarity_of(sprite: np.ndarray) -> Optional[str]:
    """The rarity of this figure, or None if it is not in the library."""
    mark = signature(sprite)
    if mark is None:
        return None
    best_rank, best_score = None, MATCH_ACCURACY
    for rank, marks in library().items():
        for known in marks:
            score = alike(mark, known)
            if score > best_score:
                best_rank, best_score = rank, score
    return best_rank


def is_target(rarity: Optional[str]) -> bool:
    """Whether this figure is worth a bean: anything not a known common.

    Beans, not time, are what runs out inside a round — 250 of them at 10 a
    throw is 25 throws, gone in about 15 seconds of a 60-second round — so the
    loop has to be selective. The question is which way to be selective, and
    that was settled by measurement rather than instinct.

    The instinct was to recognise the rare shikigami and throw only at those.
    It does not work, because **rare figures do not come back**. Across ten
    rounds, all thirteen rare shikigami a player picked out appeared in exactly
    one round each, against 31% for groups in general — odds of about 1.5 in
    ten million if they behaved like the rest. Commons are the opposite: 69% of
    them turned up in more than one round. Recognising thirteen rare figures
    therefore buys nothing for the fourteenth, and the game has some 151 of
    them; two live rounds of aiming that way put one throw on a rare figure out
    of seventy-five.

    So it runs the other way round. Commons repeat, so they can be learned, and
    everything the library does not recognise is worth a bean — including every
    rare shikigami nobody has ever labelled. An unknown figure is a target, not
    a pass.
    """
    return rarity not in COMMON_RANKS
