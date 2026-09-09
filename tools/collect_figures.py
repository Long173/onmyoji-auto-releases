"""Collect pictures of parading shikigami, to label their rarity.

    python tools/collect_figures.py [so-vong]

Writes cut-out sprites to `cache/figures/`. Feed that to
`tools/cluster_figures.py`, which groups them one shikigami per group and
prepares a sheet to label from.

Nothing is thrown while collecting: a bean burst is a bright blob that the
background subtraction would happily report as a shikigami, and the point here
is to see the figures cleanly. That costs a ticket per round either way.

**The size limits are the thing to be careful with.** A first pass capped
sprites at 250x220 and produced 106 labelled groups with no SSR and no SP in
them at all. Re-collected at 520x420, the first SSR anyone had seen turned up
straight away — 118 wide by **264 tall**. The old cap had been throwing it away
on *height*, not width: this shikigami is tall and narrow, not big and broad.

Worth knowing which half of the cap does the damage. A third of the re-collected
sprites came back wider than 250 as well, but those turned out to be two figures
walking shoulder to shoulder and merging into one blob — see MAX_ASPECT. Width
was a red herring; height was the real loss.

If a rank never turns up, widen these before suspecting anything else.
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "decompiled" / "source"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

# Match the game's own DPI handling before anything measures a window.
ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

import demon_parade  # noqa: E402
import geometry  # noqa: E402
import realm_raid  # noqa: E402
import theme  # noqa: E402
from game_control import CaptureError, GameControl  # noqa: E402

OUT = ROOT / "cache" / "figures"

# One whole figure: not a sliver, not two of them merged. See the note above
# before narrowing these.
MIN_W, MAX_W = 55, 520
MIN_H, MAX_H = 60, 420
# A box this empty holds two figures with a gap, not one shikigami.
MIN_FILL = 0.25
# Two shikigami walking shoulder to shoulder touch, and then they come out of
# the component pass as one wide blob. That blob is useless for labelling: its
# colours are a blend of two palettes, so filing it under either one teaches
# the matcher to read a plain figure as its neighbour's rarity.
#
# Shape is what separates them, not emptiness. Measured over 106 hand-checked
# single figures against 33 suspect wide crops:
#
#     fill     singles 41% median, down to 25%  |  wide crops 35% median
#     w/h      singles 0.77 median, p95 1.41    |  wide crops 1.53 median
#
# Fill overlaps completely and cannot be used. At w/h < 1.4, 94% of the known
# singles survive and 25 of the 33 wide crops are dropped. Losing the last 6%
# costs nothing: a shikigami is seen dozens of times a round, and a frame where
# it stands clear of everyone else comes along soon enough.
MAX_ASPECT = 1.4
# Same as the worker uses, so what is collected is what the loop will see.
DIFFERENCE = 40
BACKGROUND_FRAMES = 7
BACKGROUND_GAP = 0.25
# How long to watch one round. The round runs about 60s; stopping short of that
# leaves time to catch the result scroll and dismiss it.
#
# Watch the whole round when the point is to see *everything* that walks past —
# a shikigami that only enters in the last stretch is exactly the one nobody has
# a picture of yet. 26s was the old default, from when the job was counting
# poses rather than hunting for a rank that has never been seen.
WATCH_SECONDS = 50
LOOK_GAP = 0.3
# Two crops differing by less than this per pixel are the same sighting.
SAME_SIGHTING = 6


def build(hwnd):
    control = GameControl(hwnd)
    control.refresh_metrics()
    return control


def look(control, template, threshold=0.9):
    """Whether this template is on screen. None if the screen cannot be read.

    A failed capture is a state to wait through, not a crash. When the game
    drops its connection it paints a "Connecting..." box and both PrintWindow
    and BitBlt start failing; an unwrapped call there killed an overnight run
    with a traceback, and the patient retry loop below never got to run even
    once.
    """
    control.invalidate_frame()
    control.begin_frame()
    try:
        return control.find(template, threshold=threshold)
    except CaptureError:
        return None
    finally:
        control.end_frame()


def shot(control):
    """The current frame, or None if the screen cannot be read just now."""
    control.invalidate_frame()
    control.begin_frame()
    try:
        return control.full_shot().copy()
    except CaptureError:
        return None
    finally:
        control.end_frame()


# How long to keep trying to reach a round before giving up on it.
#
# Generous on purpose. A fixed handful of attempts sounds equivalent and is not:
# a run of a hundred rounds died at round 37 because something the collector
# does not recognise — an event popup, most likely — sat on screen for longer
# than five tries lasted, and one unlucky minute cost the six cycles that had
# not started yet. Waiting costs nothing but time; giving up costs the run.
ENTER_DEADLINE_SECONDS = 180.0
UNKNOWN_SCREEN_PAUSE = 4.0


def enter_round(control):
    """Get to a round in progress, from wherever the game currently is."""
    deadline = time.time() + ENTER_DEADLINE_SECONDS
    complained = False
    while time.time() < deadline:
        if look(control, demon_parade.TPL_IN_ROUND):
            return True
        if look(control, demon_parade.TPL_ENTER):
            control.click(geometry.PARADE_ENTER)
            time.sleep(7)
        elif look(control, demon_parade.TPL_RESULT):
            control.click(geometry.PARADE_DISMISS)
            time.sleep(4)
        elif look(control, demon_parade.TPL_PICK):
            for point in geometry.PARADE_PICK_POINTS:
                control.click(point)
                time.sleep(2.5)
                if look(control, demon_parade.TPL_PICKED, 0.7):
                    break
            control.click(geometry.PARADE_START)
            time.sleep(7)
        else:
            # Nothing recognised. Say so once — a silent wait here looks
            # identical to a hang — then keep looking, because whatever is in
            # the way is usually a popup that goes on its own or on the next
            # press of Enter.
            if not complained:
                print("   khong nhan ra man hinh nao, dang doi...", flush=True)
                complained = True
            time.sleep(UNKNOWN_SCREEN_PAUSE)
    return bool(look(control, demon_parade.TPL_IN_ROUND))


class Kept:
    """Sprites saved so far, so the same standing figure is not saved 60 times.

    The round a sprite came from goes in its filename, and that is not
    bookkeeping — it is the label. Rare shikigami visit one round and never
    return, while commons come back: of thirteen rare figures picked out of ten
    rounds, all thirteen appeared in exactly one round, against 69% of commons
    appearing in more than one. So a group spanning two rounds can be filed as
    common without anyone looking at it.
    """

    def __init__(self, folder):
        self._folder = folder
        self._sprites = []

    def add(self, sprite, round_index):
        for other in self._sprites:
            if other.shape != sprite.shape:
                continue
            if float(np.abs(other.astype(int) - sprite.astype(int)).mean()) < SAME_SIGHTING:
                return False
        self._sprites.append(sprite)
        cv2.imencode(".png", sprite)[1].tofile(
            str(self._folder / ("r%02d_s%04d.png" % (round_index, len(self._sprites))))
        )
        return True

    def __len__(self):
        return len(self._sprites)


def background_of(control):
    """The scene with the parade taken out: the median of a burst of frames.

    None if too few frames could be read — the caller then skips this round
    rather than subtracting against a background built from nothing.
    """
    burst = []
    for _ in range(BACKGROUND_FRAMES):
        frame = shot(control)
        if frame is not None:
            burst.append(frame)
        time.sleep(BACKGROUND_GAP)
    if len(burst) < 3:
        return None
    return np.median(np.stack(burst).astype(np.uint8), axis=0).astype(np.uint8)


def cut_outs(frame, background):
    """Every figure in this frame, with the scenery behind it blacked out.

    Blacking out matters: the bridge and temple change as a figure walks, and
    left in they are most of what two crops of the same figure have in common
    — which is how 220 sprites once came back as 182 separate clusters.
    """
    difference = cv2.absdiff(frame, background).max(axis=2)
    mask = (difference > DIFFERENCE).astype(np.uint8) * 255
    top, bottom = geometry.PARADE_FIGURE_BAND
    mask[:top] = 0
    mask[bottom:] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    total, labels, stats, _centres = cv2.connectedComponentsWithStats(mask, 8)

    out = []
    for i in range(1, total):
        x, y, w, h, area = stats[i]
        if not (MIN_W <= w <= MAX_W and MIN_H <= h <= MAX_H):
            continue
        if area < MIN_FILL * w * h:
            continue
        if w > MAX_ASPECT * h:
            continue
        cut = frame[y:y + h, x:x + w].copy()
        cut[labels[y:y + h, x:x + w] != i] = 0
        out.append(cut)
    return out


def wait_out_round(control):
    for _ in range(30):
        if look(control, demon_parade.TPL_RESULT):
            control.click(geometry.PARADE_DISMISS)
            time.sleep(4)
            return
        time.sleep(2)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Collect parade sprites to label")
    parser.add_argument("rounds", nargs="?", type=int, default=2,
                        help="so vong can thu (moi vong ton 1 ve)")
    parser.add_argument("--watch", type=float, default=WATCH_SECONDS,
                        help="giay nhin moi vong (mac dinh %d, vong dai ~60s)"
                             % WATCH_SECONDS)
    parser.add_argument("--title", default=theme.DEFAULT_WINDOW_TITLE)
    # Several clients can be logged in at once, and only one of them is on the
    # parade. find_game_window returns whichever the shell enumerates first,
    # which on a three-window desktop was a boss fight.
    parser.add_argument("--hwnd", default=None,
                        help="chi dinh cua so game (vd 0x60586); "
                             "bo trong thi lay cua so dau tien tim thay")
    args = parser.parse_args(argv)

    if args.hwnd:
        hwnd = int(args.hwnd, 0)
    else:
        hwnd = realm_raid.find_game_window(args.title)
    realm_raid.resize_game_window(hwnd)
    control = build(hwnd)

    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()
    kept = Kept(OUT)

    seen = 0
    try:
        for index in range(args.rounds):
            if not enter_round(control):
                print("Khong vao duoc tran")
                return 1
            background = background_of(control)
            if background is None:
                print("vong %d: khong doc duoc man hinh, bo qua vong nay"
                      % (index + 1), flush=True)
                wait_out_round(control)
                continue
            deadline = time.time() + args.watch
            while time.time() < deadline:
                frame = shot(control)
                if frame is not None:
                    for cut in cut_outs(frame, background):
                        seen += 1
                        kept.add(cut, index + 1)
                time.sleep(LOOK_GAP)
            print("vong %d: da thay %d, giu %d khac nhau"
                  % (index + 1, seen, len(kept)), flush=True)
            wait_out_round(control)
    finally:
        control.close()

    print("TONG: %d sprite khac nhau tu %d lan nhin thay" % (len(kept), seen))
    print("tiep theo: python tools/cluster_figures.py %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
