"""Fold groups that are the same shikigami into one.

    python tools/merge_duplicates.py RARE
    python tools/merge_duplicates.py RARE --dry-run

Grouping runs greedily: a sprite is compared against each cluster's *first*
picture and joins the first one it matches. When that representative happens to
be an off-angle pose, a sprite that any other member would have recognised
starts a cluster of its own instead. One shikigami then appears as several
groups, and every one of them has to be looked at separately.

Measured on a library of 98 rare groups: 63 shikigami, one of them split eight
ways and another six. Four of the splits dated from the very first labelling
pass, so this has been happening since the beginning.

Merging changes no signature — every picture stays in the library and
recognition is identical. What it changes is how much there is to review, and
how often a person is asked about the same figure twice.

Two groups are the same shikigami when *any* pose of one matches *any* pose of
the other, which is the same threshold the grouping itself uses. The comparison
is transitive here on purpose: A matching B and B matching C makes all three one
figure, because that is what the poses of a turning shikigami look like.
"""
from __future__ import annotations

import argparse
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


def read(path):
    return cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)


def families(folder):
    """group name -> [(path, signature)], skipping anything unreadable."""
    found = defaultdict(list)
    for path in sorted(folder.glob("*.png")):
        mark = parade_figures.signature(read(path))
        if mark is not None:
            found[path.stem.rsplit("_", 1)[0]].append((path, mark))
    return found


def clusters_of(found):
    """Group names bundled into one list per shikigami."""
    names = sorted(found)
    parent = {name: name for name in names}

    def root_of(name):
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    for index, first in enumerate(names):
        for second in names[index + 1:]:
            if root_of(first) == root_of(second):
                continue
            if any(parade_figures.alike(a, b) >= parade_figures.MATCH_ACCURACY
                   for _p, a in found[first] for _q, b in found[second]):
                parent[root_of(second)] = root_of(first)

    bundles = defaultdict(list)
    for name in names:
        bundles[root_of(name)].append(name)
    return [sorted(v) for v in bundles.values()]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Fold duplicate groups together")
    parser.add_argument("rank", default="RARE", nargs="?")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    folder = parade_figures.raw_library_dir() / args.rank
    if not folder.is_dir():
        print("Khong thay %s" % folder)
        return 1

    found = families(folder)
    bundles = clusters_of(found)
    duplicates = [b for b in bundles if len(b) > 1]

    if not duplicates:
        print("%s: %d nhom, khong co nhom trung" % (args.rank, len(found)))
        return 0

    folded = 0
    for members in duplicates:
        keep = members[0]
        existing = sorted(folder.glob(keep + "_*.png"))
        following = max(
            (int(p.stem.rsplit("_", 1)[1]) for p in existing), default=-1
        ) + 1
        for other in members[1:]:
            for path in sorted(folder.glob(other + "_*.png")):
                if not args.dry_run:
                    path.rename(folder / ("%s_%02d.png" % (keep, following)))
                following += 1
        folded += len(members) - 1
        print("   %-16s <- %s" % (
            keep, " ".join(m for m in members[1:])))

    print()
    print("%s: %d nhom -> %d thuc than (gop %d nhom)%s" % (
        args.rank, len(found), len(bundles), folded,
        " — DRY RUN, chua doi gi" if args.dry_run else ""))
    print("So anh khong doi — gop chi sap xep lai nhan nhom.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
