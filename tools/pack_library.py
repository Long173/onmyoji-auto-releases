"""Pack the rarity library into one small file of colour signatures.

    python tools/pack_library.py

Writes `screenshots/DemonParade/rarity.npz`. The app never needs the pictures
themselves — only the histogram taken from each — and the difference is large:
some 4,700 PNGs at 151 MB become about 3.6 MB, which also stops the build from
carrying a folder that grows every time more rounds are collected.

The pictures are still worth keeping, because a change to how a signature is
computed means recomputing them all. Keep them somewhere with room and point
the tools at it::

    setx ONMYOJI_RARITY_DIR D:\\onmyoji\\rarity

Run this again after adding to the library, or the app keeps reading the old
signatures.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "decompiled" / "source"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

import parade_figures  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Pack the rarity library")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    root = parade_figures.raw_library_dir()
    if not root.is_dir():
        print("Khong thay thu muc anh: %s" % root)
        print("Dat bien moi truong ONMYOJI_RARITY_DIR neu da chuyen di noi khac")
        return 1

    marks, ranks = [], []
    for rank in parade_figures.RANKS:
        folder = root / rank
        if not folder.is_dir():
            continue
        count = 0
        for entry in sorted(folder.iterdir()):
            if entry.suffix.lower() != ".png":
                continue
            mark = parade_figures.signature(parade_figures.read_image(str(entry)))
            if mark is None:
                continue
            marks.append(mark)
            ranks.append(rank)
            count += 1
        print("   %-7s %d anh" % (rank, count))

    if not marks:
        print("Khong doc duoc anh nao")
        return 1

    target = Path(args.out) if args.out else parade_figures.packed_library_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(target, marks=np.stack(marks), ranks=np.array(ranks))

    source_size = sum(p.stat().st_size for p in root.rglob("*.png"))
    print()
    print("da goi %d chu ky -> %s" % (len(marks), target))
    print("   anh goc : %.0f MB" % (source_size / 1e6))
    print("   goi lai : %.1f MB" % (target.stat().st_size / 1e6))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
