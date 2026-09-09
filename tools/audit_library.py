"""Lay a rarity library out for a person to check, hiding nothing.

    python tools/audit_library.py RARE            # every pose of every group
    python tools/audit_library.py COMMON          # one picture per group

Writes `cache/ra_soat_<rank>.png` and `cache/ra_soat_<rank>.json`, the second
being the map from the label printed on each cell to the group behind it, so a
number read off the sheet can be acted on:

    python tools/promote_group.py RARE --from-audit COMMON a017 a044

Two things this exists to catch, both of them invisible otherwise:

* **A rare filed as common.** The loop never throws at it again and nothing
  says so. Measured once: of 217 groups the round rule filed automatically,
  16 — 7.4% — were rare. That rule's premise, that rare shikigami visit a
  single round, is only mostly true.
* **A merged crop filed as rare.** Its colours are a blend of two shikigami, so
  it neither recognises the rare one alone nor stays clear of the common one
  beside it.

`--poses all` for RARE, and only the first picture for COMMON, because the two
questions are different sizes. A rare group has to be right pose by pose, and
there are a few hundred of them. The common library runs to thousands, and the
question there is only whether the group is common at all.

Do not trust an ordering to let you stop early. Sorting the commons by how much
they resemble the rare library put 18% rares in the first 22 groups against a
7.4% base rate — real signal, and nowhere near enough: two of the sixteen sat
in the last ten groups, under the scores that looked safest.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "decompiled" / "source"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

import parade_figures  # noqa: E402

CELL = (140, 175)
LABEL_WIDTH = 130
PER_ROW = 7
OUT_DIR = ROOT / "cache"


def families(ranks):
    """group family name -> its picture paths, across the given rank folders."""
    found = defaultdict(list)
    for rank in ranks:
        folder = parade_figures.raw_library_dir() / rank
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.png")):
            found[path.stem.rsplit("_", 1)[0]].append(path)
    return found


def cell_for(path, caption, note):
    width, height = CELL
    sprite = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
    scale = min((width - 10) / sprite.shape[1], (height - 40) / sprite.shape[0])
    small = cv2.resize(
        sprite,
        (max(1, int(sprite.shape[1] * scale)), max(1, int(sprite.shape[0] * scale))),
    )
    cell = np.full((height, width, 3), 26, np.uint8)
    top = height - 34 - small.shape[0]
    left = (width - small.shape[1]) // 2
    cell[top:top + small.shape[0], left:left + small.shape[1]] = small
    cv2.putText(cell, caption, (6, height - 17),
                cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 255, 255), 2)
    if note:
        cv2.putText(cell, note, (6, height - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (160, 160, 160), 1)
    cv2.rectangle(cell, (0, 0), (width - 1, height - 1), (80, 80, 80), 1)
    return cell


def sheet_every_pose(found):
    """One block per group: its label down the left, all its poses beside it."""
    width, height = CELL
    blocks, labels = [], {}
    for index, (family, files) in enumerate(sorted(found.items())):
        tag = "g%03d" % index
        labels[tag] = family
        lines = []
        for start in range(0, len(files), PER_ROW):
            cells = [cell_for(p, p.stem.split("_")[-1], "") for p in files[start:start + PER_ROW]]
            while len(cells) < PER_ROW:
                cells.append(np.full((height, width, 3), 22, np.uint8))
            lines.append(np.hstack(cells))
        body = np.vstack(lines)
        label = np.full((body.shape[0], LABEL_WIDTH, 3), 22, np.uint8)
        cv2.putText(label, tag, (6, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 255, 255), 2)
        cv2.putText(label, "x%d" % len(files), (6, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.44, (165, 165, 165), 1)
        short = family.replace("auto_", "")[:14]
        cv2.putText(label, short, (6, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (120, 120, 120), 1)
        block = np.hstack([label, body])
        cv2.line(block, (0, block.shape[0] - 1), (block.shape[1] - 1, block.shape[0] - 1),
                 (75, 75, 75), 1)
        blocks.append(block)
    # One block is one group here, which the caller needs in order to say which
    # groups a sheet covers.
    return blocks, labels, 1


def sheet_one_each(found):
    """One cell per group — for a library too large to show pose by pose."""
    width, height = CELL
    cells, labels = [], {}
    for index, (family, files) in enumerate(sorted(found.items())):
        tag = "g%03d" % index
        labels[tag] = family
        cells.append(cell_for(files[0], tag, "x%d" % len(files)))
    while len(cells) % PER_ROW:
        cells.append(np.full((height, width, 3), 26, np.uint8))
    rows = [np.hstack(cells[i:i + PER_ROW]) for i in range(0, len(cells), PER_ROW)]
    # A block is a row of PER_ROW groups, not one group — reporting it as one
    # made a sheet of 552 groups announce itself as covering g000..g078.
    return rows, labels, PER_ROW


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Lay out a library to check by eye")
    parser.add_argument("rank", help="RARE, COMMON, hoac 'commons' cho ca N/R/SR/COMMON")
    parser.add_argument("--poses", choices=("all", "first"), default=None,
                        help="mac dinh: all cho RARE, first cho phan con thuong")
    parser.add_argument("--per-sheet", type=int, default=25,
                        help="so nhom moi anh; 0 de don tat ca vao mot anh")
    args = parser.parse_args(argv)

    if args.rank.lower() == "commons":
        ranks, name = list(parade_figures.COMMON_RANKS), "COMMON"
    else:
        ranks, name = [args.rank], args.rank
    poses = args.poses or ("all" if name in parade_figures.TARGET_RANKS else "first")

    found = families(ranks)
    if not found:
        print("Khong co anh nao trong %s" % ", ".join(ranks))
        return 1

    blocks, labels, per_block = (
        sheet_every_pose if poses == "all" else sheet_one_each)(found)
    width = max(b.shape[1] for b in blocks)
    blocks = [
        b if b.shape[1] == width
        else np.hstack([b, np.full((b.shape[0], width - b.shape[1], 3), 22, np.uint8)])
        for b in blocks
    ]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    map_path = OUT_DIR / ("ra_soat_%s.json" % name.lower())
    map_path.write_text(json.dumps(labels, indent=1, ensure_ascii=False), encoding="utf-8")

    # Split into sheets a person can actually scroll. Showing every pose of a
    # hundred groups came to 27,000 pixels of one picture, which is complete and
    # unusable — the same trap as the batch of 192 on a single contact sheet.
    step = args.per_sheet if args.per_sheet > 0 else len(blocks)
    total = sum(len(v) for v in found.values())
    print("%s: %d anh, %d nhom — %s" % (
        name, total, len(found),
        "hien du moi dang" if poses == "all" else "mot anh moi nhom"))
    for index, start in enumerate(range(0, len(blocks), step), 1):
        picture = np.vstack(blocks[start:start + step])
        suffix = "" if len(blocks) <= step else "_%d" % index
        image_path = OUT_DIR / ("ra_soat_%s%s.png" % (name.lower(), suffix))
        cv2.imencode(".png", picture)[1].tofile(str(image_path))
        first_group = start * per_block
        last_group = min((start + step) * per_block, len(labels)) - 1
        print("   %d x %5d  nhom g%03d..g%03d -> %s" % (
            picture.shape[1], picture.shape[0],
            first_group, last_group, image_path.name))
    print("   ban do nhan -> %s" % map_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
