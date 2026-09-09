"""Group collected parade sprites so each shikigami can be labelled once.

    python tools/cluster_figures.py cache/figures --min-sightings 5

Writes one picture per group to `cache/label-rarity/`, a contact sheet to look
at, and `manifest.json` recording which sprites went into each group.

Only the rare figures need labelling — that is the one grade the loop spends
beans on. Say which groups they are with::

    python tools/promote_group.py RARE 003 007

which files **every** pose in those groups, not just the picture on the sheet.
Coverage is what matters for a rank the loop acts on: a pose it fails to
recognise is a throw not taken.

Groups the library already recognises are left out by default, so a second pass
only shows what is new. `--min-sightings` drops the long tail — a group seen
once in ten rounds is usually two figures overlapping for a single frame rather
than a shikigami.

Grouping is by colour, not by shape — see :mod:`parade_figures` for why, and
for the measurements that settled it.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "decompiled" / "source"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

import parade_figures  # noqa: E402

# Same figure or not. Measured on 240 live sprites: at this the groups came out
# one shikigami each, at a spread of poses.
TOGETHER = 0.85
SHEET_COLUMNS = 8
CELL = (104, 120)


def read(path):
    return cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)


def group(paths):
    """[(representative path, [members])], biggest group first."""
    marks, groups = [], []
    for path in paths:
        sprite = read(path)
        if sprite is None:
            continue
        mark = parade_figures.signature(sprite)
        if mark is None:
            continue
        placed = False
        for index, known in enumerate(marks):
            if parade_figures.alike(mark, known) >= TOGETHER:
                groups[index].append(path)
                placed = True
                break
        if not placed:
            marks.append(mark)
            groups.append([path])
    groups.sort(key=len, reverse=True)
    return groups


# Rounds a group must appear in before it can be called common without anyone
# looking. Measured over ten rounds: all thirteen rare shikigami a player
# picked out appeared in exactly one round each, while 69% of commons appeared
# in more than one. Applying this rule to that data filed 132 of the 179
# commons correctly and mislabelled none of the thirteen rare figures.
#
# The errors it does make are the harmless kind. A common it misses stays
# unlabelled, and an unlabelled figure is thrown at — that costs some
# selectivity, never a missed rare.
COMMON_ROUNDS = 2
# Asked of parade_figures rather than spelled out, because the pictures are
# allowed to live on another drive. Hardcoding the original path once created a
# second, stray library on the full drive: a cycle filed 23 groups into it while
# the packer read the real one, and the run went ten cycles without the library
# growing at all.


def common_dir():
    return parade_figures.raw_library_dir() / "COMMON"
# Groups the round rule called common but that look like a rare figure already
# in the library. Filing those is the one mistake that loses a rare shikigami,
# so they are set aside for a person instead.
HELD_DIR = ROOT / "cache" / "common-held-back"


def repack():
    """Rebuild the packed signature file after filing anything.

    Without this the pictures land on disk and change nothing: what every
    reader consults is the packed file, so an unrepacked batch is invisible.
    In a long unattended run that is quietly fatal — the library stops growing
    after the first cycle and every later cycle re-discovers the same commons.
    """
    return subprocess.call(
        [sys.executable, str(Path(__file__).with_name("pack_library.py"))]
    )


def rounds_of(members):
    """Which collection rounds a group's sprites came from."""
    found = set()
    for path in members:
        match = re.match(r"r(\d+)_", Path(path).name)
        if match:
            found.add(int(match.group(1)))
    return found


def resembles_a_rare(sprite):
    """Whether this figure looks like something already filed as SP or SSR.

    Checked before anything is filed as common, because that is the one write
    this tool can make that loses a rare shikigami: a common exemplar sitting
    close to a rare one will match the next pose of the rare one first, and the
    loop passes it over. Everything else the rule gets wrong is recoverable.
    """
    mark = parade_figures.signature(sprite)
    if mark is None:
        return False
    for rank in parade_figures.TARGET_RANKS:
        for known in parade_figures.library().get(rank, ()):
            if parade_figures.alike(mark, known) >= parade_figures.MATCH_ACCURACY:
                return True
    return False


def file_as_common(members):
    """File a whole group as common. Returns False if it was held back.

    Every pose is checked, not just the one on the sheet. Checking the
    representative alone let sibling poses through, and one of those sitting
    close to a rare figure is enough to make the loop pass that rare over —
    which is the single mistake here that costs a throw.
    """
    if any(resembles_a_rare(read(member)) for member in members):
        HELD_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(members[0]), str(HELD_DIR / Path(members[0]).name))
        return False
    target = common_dir()
    target.mkdir(parents=True, exist_ok=True)
    stem = Path(members[0]).stem
    for index, source in enumerate(members):
        destination = target / ("auto_%s_%02d.png" % (stem, index))
        if not destination.exists():
            shutil.copy(str(source), str(destination))
    return True


# A batch a person can actually work through: a dozen figures a page, printed
# large, each with its number where the eye lands. The one-page-of-192 sheet
# that came before this was technically complete and practically unusable.
LOT_SIZE = 12
LOT_COLUMNS = 4
LOT_CELL = (240, 300)


def readable_lots(groups, folder):
    """Write `lo01.png`, `lo02.png`, ... for a person to page through."""
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("lo*.png"):
        old.unlink()

    width, height = LOT_CELL
    written = []
    for start in range(0, len(groups), LOT_SIZE):
        cells = []
        for members in groups[start:start + LOT_SIZE]:
            sprite = read(members[0])
            scale = min((width - 20) / sprite.shape[1], (height - 60) / sprite.shape[0])
            small = cv2.resize(
                sprite,
                (max(1, int(sprite.shape[1] * scale)), max(1, int(sprite.shape[0] * scale))),
            )
            cell = np.full((height, width, 3), 30, np.uint8)
            top = height - 50 - small.shape[0]
            left = (width - small.shape[1]) // 2
            cell[top:top + small.shape[0], left:left + small.shape[1]] = small
            cells.append((cell, len(members)))
        block = []
        for index, (cell, seen) in enumerate(cells):
            number = start + index
            cv2.putText(cell, "%03d" % number, (10, height - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 255, 255), 3)
            cv2.putText(cell, "x%d" % seen, (width - 78, height - 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (170, 170, 170), 2)
            cv2.rectangle(cell, (0, 0), (width - 1, height - 1), (90, 90, 90), 2)
            block.append(cell)
        while len(block) % LOT_COLUMNS:
            block.append(np.full((height, width, 3), 30, np.uint8))
        rows = [np.hstack(block[i:i + LOT_COLUMNS])
                for i in range(0, len(block), LOT_COLUMNS)]
        target = folder / ("lo%02d.png" % (start // LOT_SIZE + 1))
        cv2.imencode(".png", np.vstack(rows))[1].tofile(str(target))
        written.append(target)
    return written


def contact_sheet(groups, target):
    cells = []
    for index, members in enumerate(groups):
        sprite = read(members[0])
        scale = min(CELL[0] / sprite.shape[1], CELL[1] / sprite.shape[0])
        small = cv2.resize(
            sprite,
            (max(1, int(sprite.shape[1] * scale)), max(1, int(sprite.shape[0] * scale))),
        )
        cell = np.zeros((CELL[1] + 18, CELL[0], 3), np.uint8)
        cell[:small.shape[0], :small.shape[1]] = small
        cv2.putText(cell, "%02d  n=%d" % (index, len(members)),
                    (3, CELL[1] + 13), cv2.FONT_HERSHEY_PLAIN, 0.8, (0, 255, 255), 1)
        cells.append(cell)
    while len(cells) % SHEET_COLUMNS:
        cells.append(np.zeros_like(cells[0]))
    rows = [np.hstack(cells[i:i + SHEET_COLUMNS])
            for i in range(0, len(cells), SHEET_COLUMNS)]
    cv2.imencode(".png", np.vstack(rows))[1].tofile(str(target))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Group parade sprites for labelling")
    parser.add_argument("folder", help="thu muc chua anh sprite da thu")
    parser.add_argument("--min-sightings", type=int, default=1,
                        help="bo qua nhom it hon so lan nhin thay nay; mot nhom "
                             "chi thay dung 1 lan thuong la rac")
    parser.add_argument("--all", action="store_true",
                        help="giu ca nhung con thu vien da nhan ra "
                             "(mac dinh chi hien con chua biet)")
    parser.add_argument("--auto-common", action="store_true",
                        help="nhom nao xuat hien o >= 2 vong thi tu xep vao "
                             "COMMON, khong can nguoi nhin")
    args = parser.parse_args(argv)

    paths = sorted(Path(args.folder).glob("*.png"))
    if not paths:
        print("Khong co anh nao trong %s" % args.folder)
        return 1

    groups = group(paths)
    parade_figures.reload_library()

    kept, known, thin, filed, held = [], 0, 0, 0, 0
    for members in groups:
        if not args.all and parade_figures.rarity_of(read(members[0])):
            known += 1
            continue
        if args.auto_common and len(rounds_of(members)) >= COMMON_ROUNDS:
            if file_as_common(members):
                filed += 1
                continue
            held += 1
        if len(members) < args.min_sightings:
            thin += 1
            continue
        kept.append(members)
    # Seen most often first. A shikigami that walked past many times is one
    # that really is in the parade, not a one-frame artefact.
    kept.sort(key=len, reverse=True)

    out = ROOT / "cache" / "label-rarity"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.iterdir():
        if old.is_file():
            old.unlink()

    # The members matter as much as the picture. When a group is called SP or
    # SSR, every pose in it should go into the library — those are the ranks
    # the loop acts on, and a pose it cannot recognise is a throw not taken.
    manifest = {}
    for index, members in enumerate(kept):
        name = "%03d_thay%dlan.png" % (index, len(members))
        cv2.imencode(".png", read(members[0]))[1].tofile(str(out / name))
        manifest[name] = [str(p) for p in members]
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    lots = []
    if kept:
        contact_sheet(kept, out / "_all.png")
        lots = readable_lots(kept, out / "de_nhin")

    print("%d anh -> %d nhom" % (len(paths), len(groups)))
    if not args.all:
        print("   thu vien da nhan ra : %d (bo qua)" % known)
    if args.auto_common:
        print("   tu xep vao COMMON   : %d (o >= %d vong)" % (filed, COMMON_ROUNDS))
        if held:
            print("   giu lai cho nguoi xem: %d (giong mot con hiem da biet)" % held)
        if filed and repack() != 0:
            print()
            print("*** dong goi lai THAT BAI — %d nhom vua xep chua co tac dung. ***"
                  % filed)
            return 1
    if args.min_sightings > 1:
        print("   thay duoi %d lan     : %d (bo qua)" % (args.min_sightings, thin))
    print("   con lai CAN NGUOI XEM: %d" % len(kept))
    if lots:
        print()
        print("=> mo %s" % (out / "de_nhin"))
        print("   %d lo, moi lo 12 con, so vang la so nhom" % len(lots))
        print("   doc so cua nhung nhom la SSR/SP, roi:")
        print("     python tools/promote_group.py RARE 003 007")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
