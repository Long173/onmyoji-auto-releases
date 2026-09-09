"""Record the distinct screens a game window passes through.

Used when adding a task: play one cycle of the activity by hand while this
watches, and it saves one frame per *screen*, not one per second. Near-identical
frames are dropped, so a two-minute run leaves a handful of pictures to look at
instead of a hundred.

    python tools/record_screens.py --out souls --seconds 240

Options:
    --window N     which game window (default: the first found; --list to see)
    --seconds N    how long to watch (default 180)
    --every N      seconds between grabs (default 1.0)
    --threshold N  how different a frame must be to count as a new screen,
                   0-100 (default 3.0). Lower catches more, and more noise.

Nothing is clicked; this only reads the screen.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "decompiled" / "source"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from auto import window_scanner  # noqa: E402
from game_control import CaptureError, GameControl  # noqa: E402

# Deliberately NOT under screenshots/: the spec bundles that whole folder into
# the .exe, so a recording session left there would ship to users.
OUT_ROOT = ROOT / "recordings"


def difference(a, b) -> float:
    """Mean absolute difference between two frames, as a percentage."""
    if a is None or b is None or a.shape != b.shape:
        return 100.0
    # Downscale first: a full-size diff is slow and over-sensitive to the
    # animation that never stops in this game (water, cloth, particles).
    small_a = cv2.resize(a, (160, 90), interpolation=cv2.INTER_AREA)
    small_b = cv2.resize(b, (160, 90), interpolation=cv2.INTER_AREA)
    return float(np.mean(cv2.absdiff(small_a, small_b))) / 255.0 * 100.0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Record distinct game screens")
    parser.add_argument("--out", default="recording", help="folder name under screenshots/_recordings")
    parser.add_argument("--window", type=int, default=0, help="index from --list")
    parser.add_argument(
        "--hwnd", default="",
        help="pick by handle instead, e.g. 0x0003074A — steadier than an index, "
             "which shifts if a window opens or closes between listing and recording",
    )
    parser.add_argument("--seconds", type=float, default=180.0)
    parser.add_argument("--every", type=float, default=1.0)
    parser.add_argument("--threshold", type=float, default=3.0)
    parser.add_argument("--list", action="store_true", help="list game windows and exit")
    args = parser.parse_args(argv)

    windows = window_scanner.scan()
    if not windows:
        print("Khong thay cua so game nao dang mo.")
        return 1
    if args.list:
        for index, window in enumerate(windows):
            print("  [%d] %s" % (index, window.descriptor))
        return 0
    if args.hwnd:
        try:
            wanted = int(args.hwnd, 0)
        except ValueError:
            print("HWND khong doc duoc: %r" % args.hwnd)
            return 1
        matches = [w for w in windows if w.hwnd == wanted]
        if not matches:
            print("Khong thay cua so 0x%08X. Dang mo:" % wanted)
            for window in windows:
                print("  %s" % window.descriptor)
            return 1
        window = matches[0]
    else:
        if not 0 <= args.window < len(windows):
            print("Khong co cua so so %d (co %d cua so)." % (args.window, len(windows)))
            return 1
        window = windows[args.window]
    folder = OUT_ROOT / args.out
    folder.mkdir(parents=True, exist_ok=True)
    for stale in folder.glob("*.png"):
        stale.unlink()

    print("Ghi cua so: %s" % window.descriptor)
    print("Luu vao   : %s" % folder)
    print("Chay %.0f giay, chup moi %.1fs, nguong doi %.1f%%"
          % (args.seconds, args.every, args.threshold))
    print("Cu choi binh thuong. Ctrl+C de dung som.\n")

    control = GameControl(window.hwnd)
    previous = None
    saved = 0
    started = time.time()
    try:
        while time.time() - started < args.seconds:
            try:
                frame = control.full_shot()
            except CaptureError as exc:
                print("  chup that bai: %s" % exc)
                time.sleep(args.every)
                continue

            delta = difference(previous, frame)
            if delta >= args.threshold:
                saved += 1
                elapsed = time.time() - started
                name = "%02d_%06.1fs.png" % (saved, elapsed)
                ok, buffer = cv2.imencode(".png", frame)
                if ok:
                    (folder / name).write_bytes(buffer.tobytes())
                    print("  [%02d] %6.1fs  khac %.1f%%  -> %s" % (saved, elapsed, delta, name))
                previous = frame.copy()
            time.sleep(args.every)
    except KeyboardInterrupt:
        print("\n  dung som.")
    finally:
        control.close()

    print("\nXong: %d man hinh khac nhau trong %s" % (saved, folder))
    return 0


if __name__ == "__main__":
    sys.exit(main())
