"""File a labelled group into the rarity library, every pose of it.

    python tools/promote_group.py RARE 003 007 012

The numbers are the leading digits of the pictures in `cache/label-rarity/`,
written there by `cluster_figures.py`. Each one stands for a group of sprites
that were all judged to be the same shikigami, and this copies the whole group
into `screenshots/DemonParade/rarity/<RANK>/`.

Copying the whole group rather than the one picture on the contact sheet is the
point. A shikigami turns as it walks, and the loop only throws at figures it
recognises — a pose missing from the library is a throw not taken, on exactly
the ranks the run exists to farm.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "decompiled" / "source"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

import parade_figures  # noqa: E402

BATCH = ROOT / "cache" / "label-rarity"
KEPT = ROOT / "cache" / "can-xem"
# Where the pictures actually are — they may be on another drive. See
# parade_figures.raw_library_dir.


def load_manifest():
    """Groups from the latest batch, plus every batch kept from earlier cycles.

    Both are needed. A long unattended run wipes its working folder each cycle,
    so the only surviving copy of an older batch is the one grow_library set
    aside — and a number read off one of those sheets has to still resolve.
    """
    manifest = {}
    for path in (KEPT / "manifest.json", BATCH / "manifest.json"):
        if path.is_file():
            manifest.update(json.loads(path.read_text(encoding="utf-8")))
    if not manifest:
        raise SystemExit(
            "Khong thay manifest o %s hay %s — chay tools/cluster_figures.py truoc"
            % (KEPT, BATCH)
        )
    return manifest


def members_of(manifest, number):
    """Every sprite in the group named by this number.

    Accepts a bare number for the latest batch, or one carrying its cycle —
    `007` or `c03_007` — because numbering restarts every cycle and a bare
    number can name more than one group once several batches are in play.
    """
    wanted = str(number)
    if wanted in manifest:
        return wanted, manifest[wanted]

    padded = wanted.zfill(3)
    matches = [(name, members) for name, members in manifest.items()
               if name.split("_")[0] == padded
               or name.split("_")[-1] == padded]
    if not matches:
        raise SystemExit("Khong co nhom nao mang so %s trong manifest" % wanted)
    if len(matches) > 1:
        names = ", ".join(name for name, _members in matches)
        raise SystemExit(
            "So %s ung voi nhieu nhom (%s) — ghi ro ca chu ky, vi du %s"
            % (wanted, names, matches[0][0])
        )
    return matches[0]


def group_id(name):
    """A short, stable name for a group that survives being put in a filename.

    Batches name their groups two ways — `003_thay12lan.png` for the current
    one, `c03_007` for a batch kept from an earlier cycle — and the underscore
    in the second would split the wrong way once it is embedded in a filename
    like `ssr_<id>_00.png`. Two groups from one cycle would then land on the
    same name and overwrite each other.
    """
    stem = name[:-4] if name.lower().endswith(".png") else name
    head = stem.split("_")[0]
    if head.isdigit():
        return head
    return stem.replace("_", "-")


_common_cache = None


def common_signatures():
    """Every common picture's signature, read once per run.

    Read per call, this is O(groups x pictures): filing 58 groups against a
    library of 5,000 meant a quarter of a million image decodes, which turned a
    labelling session into a coffee break.
    """
    global _common_cache
    if _common_cache is None:
        _common_cache = []
        for rank in parade_figures.COMMON_RANKS:
            folder = parade_figures.raw_library_dir() / rank
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.png")):
                mark = parade_figures.signature(parade_figures.read_image(str(path)))
                if mark is not None:
                    _common_cache.append((path, mark))
    return _common_cache


def conflicting_commons(members):
    """[(score, path)] for commons this group matches, worst first.

    A conflict is not automatically the rare group's fault, which is what an
    earlier version assumed. It refused the rare and kept the common, and that
    is the wrong way round when the common is the mistake: a rare filed as
    common is passed over on every future round and nobody ever finds out,
    while a common filed as rare merely costs a bean.
    """
    common = common_signatures()

    hits = {}
    for member in members:
        path = Path(member)
        if not path.is_file():
            continue
        mark = parade_figures.signature(parade_figures.read_image(str(path)))
        if mark is None:
            continue
        for other, other_mark in common:
            score = parade_figures.alike(mark, other_mark)
            if score >= parade_figures.MATCH_ACCURACY:
                hits[other] = max(hits.get(other, 0.0), score)
    return sorted(((score, path) for path, score in hits.items()), reverse=True)


def evict(paths):
    """Take mislabelled commons out of the library, whole group at a time.

    The group, not the single picture: a common group is one shikigami's poses,
    so if one pose is really a rare figure they all are, and leaving the rest
    behind would keep swallowing it.
    """
    gone = ROOT / "cache" / "common-evicted"
    gone.mkdir(parents=True, exist_ok=True)
    moved = 0
    for path in paths:
        stem = path.stem
        # auto_r09_s5239_01 -> auto_r09_s5239 ; common_038_01 -> common_038
        family = stem.rsplit("_", 1)[0]
        for sibling in sorted(path.parent.glob(family + "_*.png")):
            shutil.move(str(sibling), str(gone / sibling.name))
            moved += 1
    return moved


def move_from_audit(args, target):
    """Move whole groups between library folders, named by an audit sheet label.

    Separate from the collect-and-label path because nothing is being added
    here: the pictures are already in the library, filed under the wrong grade.
    A rare sitting in the common folder is the expensive mistake — the loop
    passes it over for good — so this exists to make correcting one a single
    command rather than a hand-written move.
    """
    source_rank = args.from_audit
    map_path = ROOT / "cache" / ("ra_soat_%s.json" % source_rank.lower())
    if not map_path.is_file():
        raise SystemExit(
            "Khong thay %s — chay tools/audit_library.py %s truoc"
            % (map_path, source_rank)
        )
    labels = json.loads(map_path.read_text(encoding="utf-8"))

    ranks = (list(parade_figures.COMMON_RANKS)
             if source_rank.upper() == "COMMON" else [source_rank])
    moved = 0
    for tag in args.groups:
        family = labels.get(tag)
        if family is None:
            print("khong co ma %s trong bang ra soat" % tag)
            continue
        files = []
        for rank in ranks:
            folder = parade_figures.raw_library_dir() / rank
            if folder.is_dir():
                files += sorted(folder.glob(family + "_*.png"))
        if not files:
            print("%s (%s): khong con anh nao" % (tag, family))
            continue
        for index, source in enumerate(files):
            destination = target / ("%s_%s_%02d.png"
                                    % (args.rarity.lower(), tag, index))
            if args.dry_run:
                continue
            shutil.move(str(source), str(destination))
        moved += len(files)
        print("%s (%s): %d anh -> %s/" % (tag, family, len(files), args.rarity))

    print()
    print("da chuyen %d anh%s" % (moved, " — DRY RUN" if args.dry_run else ""))
    if moved and not args.dry_run:
        code = subprocess.call(
            [sys.executable, str(Path(__file__).with_name("pack_library.py"))]
        )
        if code != 0:
            print("*** dong goi lai THAT BAI — thay doi chua co tac dung ***")
            return code
        parade_figures.reload_library()
        print("thu vien gio:", {r: len(v) for r, v in parade_figures.library().items()})
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="File a group into the rarity library")
    parser.add_argument("rarity", choices=parade_figures.RANKS)
    parser.add_argument("groups", nargs="+", help="so thu tu nhom, vd 003 007")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true",
                        help="nap ca nhom bi bao la qua giong con thuong")
    parser.add_argument("--from-audit", metavar="RANK",
                        help="cac so la ma tren bang ra soat cua RANK "
                             "(vd --from-audit COMMON g017): chuyen ca nhom "
                             "tu RANK sang bac dich")
    parser.add_argument("--evict", action="store_true",
                        help="con thuong nao dung nhom nay thi go no ra khoi "
                             "thu vien (dung khi con thuong moi la cai gan sai)")
    args = parser.parse_args(argv)

    target = parade_figures.raw_library_dir() / args.rarity
    target.mkdir(parents=True, exist_ok=True)

    if args.from_audit:
        return move_from_audit(args, target)

    manifest = load_manifest()

    copied = skipped = refused = 0
    for number in args.groups:
        name, members = members_of(manifest, number)
        gid = group_id(name)
        alive = [Path(p) for p in members if Path(p).is_file()]
        missing = len(members) - len(alive)

        if args.rarity in parade_figures.TARGET_RANKS:
            clashes = conflicting_commons(alive)
            if clashes and args.evict:
                removed = evict([path for _score, path in clashes])
                print("nhom %s: go %d anh thuong dung nhom nay (%s)"
                      % (gid, removed,
                         ", ".join("%.3f %s" % (sc, pt.name)
                                   for sc, pt in clashes[:3])))
                clashes = []
            if clashes and not args.force:
                refused += 1
                print("nhom %s: BO QUA — giong con thuong %.3f (%s)"
                      % (gid, clashes[0][0], clashes[0][1].name))
                print("   neu con thuong moi la cai gan sai, dung --evict."
                      " Neu hai con khac nhau that, dung --force.")
                continue
            print("nhom %s: %d anh%s -> %s/" % (
                gid, len(alive),
                " (%d anh da bi xoa)" % missing if missing else "",
                args.rarity))
        else:
            print("nhom %s: %d anh%s -> %s/" % (
                gid, len(alive),
                " (%d anh da bi xoa)" % missing if missing else "",
                args.rarity))
        for index, source in enumerate(alive):
            destination = target / ("%s_%s_%02d.png" % (
                args.rarity.lower(), gid, index))
            if destination.exists():
                skipped += 1
                continue
            if not args.dry_run:
                shutil.copy(source, destination)
            copied += 1

    print()
    print("da chep %d anh%s%s%s" % (
        copied,
        " (bo qua %d anh da co)" % skipped if skipped else "",
        " (tu choi %d nhom qua giong con thuong)" % refused if refused else "",
        " — DRY RUN, chua ghi gi" if args.dry_run else ""))
    if not args.dry_run and copied:
        # Repack, or this labelling changes nothing. What the app and the tools
        # read is the packed signature file, not these pictures, so a label
        # filed without repacking is invisible — including to a collection run
        # that is still going and would otherwise keep using the old library.
        code = subprocess.call(
            [sys.executable, str(Path(__file__).with_name("pack_library.py"))]
        )
        if code != 0:
            print()
            print("*** dong goi lai THAT BAI — nhan nay chua co tac dung. ***")
            print("    chay: python tools/pack_library.py")
            return code
        parade_figures.reload_library()
        library = parade_figures.library()
        print("thu vien gio:", {r: len(library.get(r, [])) for r in parade_figures.RANKS
                                if library.get(r)})
        print()
        print("chay lai test de kiem bien an toan:")
        print("  python -m pytest tests/test_parade_figures.py -q")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
