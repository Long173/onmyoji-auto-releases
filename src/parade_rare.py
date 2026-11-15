"""Recognising an SSR/SP boss candidate by how it looks once lit up.

The pick screen shows three black silhouettes. Tapping one lights it up in full
colour — still with no name and no rarity letter, but now it can be compared
with pictures of shikigami already known to be SSR/SP.

Size alone does not do it. On the Steam client, of 14 line-ups that held an
SSR/SP, the rare one stood anywhere from 0.6 to 3.8 times the usual size for
its spot, while common shikigami carrying something big — a fox statue, a
wardrobe, a giant frog — reached 1.9 to 2.8.

Each candidate stands in a fixed place per column and is drawn the same way
every time it is offered there, so a picture of it lit up in that column is a
template for it. Compared pixel by pixel inside its own silhouette, allowing a
few pixels of slack:

* the same shikigami in the same column scored 0.72 to 0.99 over 89 pairs on
  the Steam client, and 0.85 between the emulator and the Steam client;
* 848 common candidates scored at most 0.69 against any SSR/SP picture.

A shikigami in another column is drawn at another angle and does not match
itself, so each picture belongs to one column.

The library is a folder of PNGs whose alpha channel is the silhouette, named
``<anything>_c<column>_x<left>_y<top>.png`` at the reference size. It grows by
hand: every candidate the loop lights up is saved, unlabelled, under
``cache/parade-pick``; moving one that is SSR/SP into ``cache/parade-rare``
(or into ``screenshots/DemonParade/rare`` for everyone) teaches it.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Iterable, NamedTuple, Optional, Tuple

import cv2
import numpy as np

import parade_pick
import paths

logger = logging.getLogger(__name__)

LIBRARY_DIRS: Tuple[Path, ...] = (
    Path(paths.template("DemonParade", "rare")),
    paths.CACHE_DIR / "parade-rare",
)

MATCH_ACCURACY = 0.78
# How far the figure may sit from where its picture was taken. It stands on a
# fixed spot, but breathes and sways a little while idle.
SEARCH_SLACK = 20
# The silhouette is shrunk before comparing, so a pixel of slack at its edge
# does not drag the stage behind it into the comparison.
MASK_ERODE = 5
NAME = re.compile(r"_c(\d)_x(\d+)_y(\d+)\.png$")


class Sample(NamedTuple):
    name: str
    column: int
    x: int
    y: int
    image: np.ndarray       # BGR
    mask: np.ndarray        # uint8, 0 or 1, same size as image


def cut(lit_frame: np.ndarray, candidate) -> Tuple[np.ndarray, int, int]:
    """The lit candidate as BGRA, alpha its shrunken silhouette, and its corner."""
    lit = parade_pick.at_reference(lit_frame)
    ys, xs = np.nonzero(candidate.mask)
    x1, x2, y1, y2 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    mask = cv2.erode(candidate.mask[y1:y2, x1:x2].astype(np.uint8),
                     np.ones((MASK_ERODE, MASK_ERODE), np.uint8))
    image = cv2.cvtColor(lit[y1:y2, x1:x2], cv2.COLOR_BGR2BGRA)
    image[..., 3] = mask * 255
    return image, x1, y1


def unlabelled_dir() -> Path:
    """Where lit candidates wait to be labelled. Read late, so tests can move it."""
    return paths.CACHE_DIR / "parade-pick"


def save(lit_frame: np.ndarray, candidate, folder: Optional[Path] = None,
         prefix: Optional[str] = None) -> Path:
    """Keep a lit candidate as a library-ready PNG."""
    folder = unlabelled_dir() if folder is None else folder
    image, x, y = cut(lit_frame, candidate)
    folder.mkdir(parents=True, exist_ok=True)
    prefix = prefix or time.strftime("%Y%m%d-%H%M%S")
    target = folder / ("%s_c%d_x%d_y%d.png" % (prefix, candidate.column + 1, x, y))
    cv2.imencode(".png", image)[1].tofile(str(target))
    return target


def _read(path: Path) -> Optional[Sample]:
    found = NAME.search(path.name)
    if not found:
        return None
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 3 or image.shape[2] != 4:
        logger.warning("Skipping %s: not a BGRA picture", path.name)
        return None
    column, x, y = (int(v) for v in found.groups())
    return Sample(path.stem, column - 1, x, y, image[..., :3].copy(),
                  (image[..., 3] > 127).astype(np.uint8))


_cache: Optional[Tuple[Sample, ...]] = None


def library(folders: Iterable[Path] = LIBRARY_DIRS) -> Tuple[Sample, ...]:
    """Every SSR/SP picture known, read once per run."""
    global _cache
    if _cache is None:
        found = []
        for folder in folders:
            if folder.is_dir():
                for path in sorted(folder.glob("*.png")):
                    sample = _read(path)
                    if sample is not None:
                        found.append(sample)
        _cache = tuple(found)
        logger.info("SSR/SP library: %d picture(s)", len(_cache))
    return _cache


def reload_library() -> None:
    global _cache
    _cache = None


def score(lit_frame: np.ndarray, sample: Sample) -> float:
    """How well this picture matches what stands at its spot in the frame."""
    lit = parade_pick.at_reference(lit_frame)
    h, w = sample.image.shape[:2]
    top, left = max(0, sample.y - SEARCH_SLACK), max(0, sample.x - SEARCH_SLACK)
    area = lit[top:sample.y + h + SEARCH_SLACK, left:sample.x + w + SEARCH_SLACK]
    if area.shape[0] < h or area.shape[1] < w or not sample.mask.any():
        return 0.0
    result = cv2.matchTemplate(area, sample.image, cv2.TM_CCOEFF_NORMED,
                               mask=np.dstack([sample.mask] * 3))
    return float(np.nan_to_num(result, nan=-1.0, posinf=-1.0, neginf=-1.0).max())


def best_match(lit_frame: np.ndarray, candidate,
               samples: Optional[Tuple[Sample, ...]] = None) -> Tuple[float, Optional[str]]:
    """The best score among pictures for this candidate's column, and whose."""
    samples = library() if samples is None else samples
    best, name = 0.0, None
    for sample in samples:
        if sample.column != candidate.column:
            continue
        value = score(lit_frame, sample)
        if value > best:
            best, name = value, sample.name
    return best, name
