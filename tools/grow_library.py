"""Collect parade rounds unattended and teach the library the common figures.

    python tools/grow_library.py --cycles 4 --rounds 10 --hwnd 0x60586

Each cycle plays some rounds, groups what it saw, and files every group that
turned up in two or more rounds straight into the common library. Nobody has to
look at anything: rare shikigami visit a single round and never come back,
commons come back, so appearing twice is itself the label. Measured over ten
rounds, the rule filed 132 of 179 commons and mislabelled none of the thirteen
rare figures.

The point is not the common library for its own sake. The loop throws at
whatever it *cannot* name, so every common learned narrows the throwing onto
the figures that might be rare. It starts at a third of everything on screen
and should fall as this runs.

Groups it could not settle are left in `cache/label-rarity/` for a person to
look through, and that pile shrinks each cycle.

Costs one ticket per round. Stop it whenever — the library keeps what it has
already learned.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "decompiled" / "source"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

import parade_figures  # noqa: E402

FIGURES = ROOT / "cache" / "figures"
# Cycles that may fail back to back before the run is called off. One failure
# is usually a popup; several in a row means the game is not where it should be
# — out of tickets, logged out, or on another screen entirely — and pressing on
# would just burn time.
GIVE_UP_AFTER = 2


def run(command):
    print("\n$ %s" % " ".join(str(c) for c in command), flush=True)
    # Unbuffered, so whoever is collecting this output — an overnight wrapper,
    # a person watching a terminal — sees each round as it happens rather than
    # in one lump when the cycle ends.
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    result = subprocess.run([sys.executable] + [str(c) for c in command], env=env)
    return result.returncode


def first_free_cycle():
    """The lowest cycle number no earlier run has already used.

    Cycle numbers restart at 1 every run, and the batches are filed under them.
    Two runs therefore both write `c01`, and the second silently overwrites the
    first — including the sprites behind it, so a number read off the older
    sheet stops resolving. Continuing the numbering costs nothing and keeps
    every batch a person has not looked at yet.
    """
    used = set()
    for lot in (ROOT / "cache" / "can-xem").glob("c*_lo*.png"):
        head = lot.name.split("_", 1)[0]
        if head.startswith("c") and head[1:].isdigit():
            used.add(int(head[1:]))
    return max(used) + 1 if used else 1


def keep_lots(cycle):
    """Preserve this cycle's unlabelled groups — pictures included.

    Each cycle wipes `cache/figures` and overwrites the batch folder, so
    without this both the sheets and the sprites behind them vanish one after
    another. Over a fifty-round run that lost four of five batches, between 33
    and 44 groups each; only the last survived to be looked at.

    Copying the sheets alone would not be enough. A number read off a sheet is
    only useful while the sprites it names still exist, so the members come too
    — otherwise a person labels a group in the morning and finds nothing left
    to file by the afternoon.
    """
    batch = ROOT / "cache" / "label-rarity"
    source = batch / "de_nhin"
    if not source.is_dir():
        return
    target = ROOT / "cache" / "can-xem"
    target.mkdir(parents=True, exist_ok=True)
    for lot in sorted(source.glob("lo*.png")):
        shutil.copy(str(lot), str(target / ("c%02d_%s" % (cycle, lot.name))))

    manifest_path = batch / "manifest.json"
    if not manifest_path.is_file():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    kept = {}
    for name, members in manifest.items():
        number = name.split("_")[0]
        folder = target / "sprites" / ("c%02d_%s" % (cycle, number))
        folder.mkdir(parents=True, exist_ok=True)
        saved = []
        for index, member in enumerate(members):
            source_file = Path(member)
            if not source_file.is_file():
                continue
            destination = folder / ("%02d.png" % index)
            shutil.copy(str(source_file), str(destination))
            saved.append(str(destination))
        if saved:
            kept["c%02d_%s" % (cycle, number)] = saved

    combined_path = target / "manifest.json"
    combined = {}
    if combined_path.is_file():
        combined = json.loads(combined_path.read_text(encoding="utf-8"))
    combined.update(kept)
    combined_path.write_text(json.dumps(combined, indent=1, ensure_ascii=False),
                             encoding="utf-8")


def library_size():
    parade_figures.reload_library()
    library = parade_figures.library()
    return {rank: len(marks) for rank, marks in sorted(library.items())}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Grow the common library unattended")
    parser.add_argument("--cycles", type=int, default=4)
    parser.add_argument("--rounds", type=int, default=10,
                        help="so vong moi chu ky; can it nhat 2 de luat hoat dong")
    parser.add_argument("--hwnd", default=None)
    parser.add_argument("--min-sightings", type=int, default=5)
    args = parser.parse_args(argv)

    if args.rounds < 2:
        print("Can it nhat 2 vong moi chu ky, vi luat dua tren viec xuat hien lai")
        return 1

    print("bat dau, thu vien dang co:", library_size())
    failed = 0
    first = first_free_cycle()
    if first > 1:
        print("danh so tiep tu c%02d (cac dot truoc da dung den c%02d)"
              % (first, first - 1))
    for offset in range(args.cycles):
        cycle = first + offset
        print("\n=== chu ky %d/%d (c%02d) — %d vong ==="
              % (offset + 1, args.cycles, cycle, args.rounds))
        collect = [ROOT / "tools" / "collect_figures.py", args.rounds]
        if args.hwnd:
            collect += ["--hwnd", args.hwnd]
        if run(collect) != 0:
            # One bad cycle is not a reason to abandon the ones after it. The
            # first long run aborted at cycle 4 and the remaining six never
            # ran, for a stall that had cleared by the time anyone looked.
            print("Chu ky c%02d thu that bai — thu lai mot lan" % cycle, flush=True)
            if run(collect) != 0:
                print("Van that bai, bo qua chu ky c%02d va di tiep" % cycle,
                      flush=True)
                failed += 1
                if failed >= GIVE_UP_AFTER:
                    print("That bai %d chu ky lien tiep, dung lai" % failed)
                    return 1
                continue
        failed = 0
        cluster = [ROOT / "tools" / "cluster_figures.py", FIGURES,
                   "--auto-common", "--min-sightings", args.min_sightings]
        if run(cluster) != 0:
            print("Gom nhom that bai, dung lai")
            return 1
        # Fold together any rare groups that turn out to be one shikigami.
        # Greedy grouping splits a figure across clusters whenever the cluster
        # it should have joined is represented by an off-angle pose, and each
        # split is another group somebody has to look at. Cheap, and it changes
        # no signature.
        run([ROOT / "tools" / "merge_duplicates.py", "RARE"])
        print("thu vien sau chu ky c%02d:" % cycle, library_size())
        keep_lots(cycle)

    lots = sorted((ROOT / "cache" / "can-xem").glob("*.png"))
    print()
    print("=== xong. %d lo can nguoi xem, o cache/can-xem/ ===" % len(lots))
    print("Moi lo 12 con, so vang la so nhom. Doc so cua nhung nhom la SSR/SP.")
    print("Cac nhom nay la nhung con may KHONG tu xep duoc — trong do co ca")
    print("con hiem, va may khong the tu nhan ra chung.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
