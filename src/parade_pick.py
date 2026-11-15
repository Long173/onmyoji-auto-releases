"""Choosing the Demon Parade boss: the biggest candidate, measured by its silhouette.

The pick screen offers three shikigami as black silhouettes, and hitting the one
picked pays triple shards. Nothing on the screen says how rare a candidate is —
no name, no rarity letter, even once it is tapped and lights up in colour.

Size does, though. Measured over 205 pick screens (613 candidates) whose SSR and
SP candidates a player labelled by eye: an SSR/SP silhouette covered more area
than 86% of the common ones standing in the same place on the left, 96% in the
middle and 100% on the right. Picking the biggest — relative to what is usual
for its spot — chose the SSR/SP in 9 of the 13 screens that offered one. A
fixed spot, which is what the loop clicked before, chooses it about a third of
the time.

Why relative to the spot: the three stand at different depths of the stage, so
the same shikigami is drawn at a different size in each column. That is also
why a silhouette cannot simply be looked up — the same figure in another column
is drawn at another angle and does not match itself.

Only the silhouette is needed, which is on screen before anything is tapped, so
choosing costs no extra time.

Everything here works at the reference client size, 1122x633.
"""
from __future__ import annotations

from typing import List, NamedTuple, Optional, Tuple

import cv2
import numpy as np

import geometry

Point = Tuple[int, int]

# The three candidates' stretches of the stage. The Start drum begins at about
# x=950 in the bottom right, so the right-hand stretch stops short of it.
COLUMNS = ((0, 395), (395, 735), (735, 950))
STAGE_Y = (150, 560)
# A silhouette is drawn in near-black; the stage and sky behind never are.
SILHOUETTE_VALUE = 40
# Median silhouette area of a common shikigami in each column, in reference
# pixels, from the 588 non-SSR/SP candidates of the same 205 screens.
COMMON_AREA = (15047, 14481, 15592)
# Less than this and the column holds no figure worth the name — a frame caught
# mid-animation, or not the pick screen at all.
MIN_AREA = 2500
# The shortest of 614 real silhouettes stood 100 pixels tall. The dark strips the
# entry screen leaves in these boxes are 34 and 77 — flat bands of shadow, not
# figures — and this is what keeps them from being offered as a choice.
MIN_HEIGHT = 90
# The biggest of the same 614 covered 55,660 pixels. A stretch that is dark
# from edge to edge — a blacked-out or failed capture — is 88,000 to 162,000
# depending on the column (the right one is the narrowest), and is not a figure.
MAX_AREA = 70000
# Selected = its silhouette has lit up: most of what was near-black no longer is.
LIT_IF_DARK_SHARE_BELOW = 0.45


class Candidate(NamedTuple):
    column: int
    area: int
    relative: float          # area over the usual common area for this column
    taps: Tuple[Point, ...]  # points inside the body, best first
    mask: np.ndarray


def at_reference(frame: np.ndarray) -> np.ndarray:
    size = tuple(geometry.REFERENCE_CLIENT_SIZE)
    if (frame.shape[1], frame.shape[0]) == size:
        return frame
    return cv2.resize(frame, size, interpolation=cv2.INTER_AREA)


def _value(frame: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[..., 2]


def candidates(frame: np.ndarray) -> List[Candidate]:
    """The silhouettes on a pick screen, one per column that has one."""
    value = _value(at_reference(frame))
    found: List[Candidate] = []
    y1, y2 = STAGE_Y
    for column, (x1, x2) in enumerate(COLUMNS):
        mask = np.zeros(value.shape, np.uint8)
        mask[y1:y2, x1:x2] = (value[y1:y2, x1:x2] < SILHOUETTE_VALUE).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        total, labels, stats, _centres = cv2.connectedComponentsWithStats(mask, 8)
        if total < 2:
            continue
        biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        area = int(stats[biggest, cv2.CC_STAT_AREA])
        if (area < MIN_AREA or area > MAX_AREA
                or stats[biggest, cv2.CC_STAT_HEIGHT] < MIN_HEIGHT):
            continue
        body = (labels == biggest).astype(np.uint8)
        # Tap well inside the body, not on a fringe of cloth or a weapon tip: a
        # tap on empty ground deselects whatever was chosen.
        inner = cv2.erode(body, np.ones((15, 15), np.uint8))
        ys, xs = np.nonzero(inner if inner.any() else body)
        order = np.argsort(ys)
        taps = tuple((int(xs[order[int(len(order) * f)]]), int(ys[order[int(len(order) * f)]]))
                     for f in (0.6, 0.4, 0.8, 0.25))
        found.append(Candidate(column, area, area / COMMON_AREA[column], taps, body))
    return found


def choose(frame: np.ndarray) -> Optional[Candidate]:
    """The candidate most likely to be SSR/SP: the biggest for where it stands."""
    found = candidates(frame)
    if not found:
        return None
    return max(found, key=lambda c: c.relative)


def is_lit(frame: np.ndarray, candidate: Candidate) -> bool:
    """Whether this candidate has been selected — its silhouette turned to colour."""
    value = _value(at_reference(frame))
    inside = candidate.mask > 0
    if not inside.any():
        return False
    return float((value[inside] < SILHOUETTE_VALUE).mean()) < LIT_IF_DARK_SHARE_BELOW
