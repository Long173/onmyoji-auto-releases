"""Score a template against frames, so a new one is trusted for a reason.

    python tools/score_template.py screenshots/SoulsDungeon/fight.png \
        recordings/chu-phong-chuan/*.png

Prints the best match score per frame. What matters is the *gap*: the frames
that genuinely contain the thing should score far above the ones that do not.
A template whose best miss scores near its worst hit will fire at random.

Also useful for checking how much a client-size change costs — score a template
cut at one size against a recording made at another.
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "decompiled" / "source"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

import cv2  # noqa: E402
import numpy as np  # noqa: E402


def read(path: Path, gray: bool):
    data = np.frombuffer(path.read_bytes(), dtype=np.uint8)
    flag = cv2.IMREAD_GRAYSCALE if gray else cv2.IMREAD_COLOR
    image = cv2.imdecode(data, flag)
    if image is None:
        raise SystemExit("Khong doc duoc: %s" % path)
    return image


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Score a template against frames")
    parser.add_argument("template")
    parser.add_argument("frames", nargs="+", help="files or globs")
    parser.add_argument("--colour", action="store_true",
                        help="match in colour (default greyscale, like the app)")
    parser.add_argument("--threshold", type=float, default=0.9)
    args = parser.parse_args(argv)

    gray = not args.colour
    template_path = Path(args.template)
    if not template_path.is_absolute():
        template_path = ROOT / template_path
    template = read(template_path, gray)
    print("template: %s (%dx%d, %s)"
          % (template_path.name, template.shape[1], template.shape[0],
             "xam" if gray else "mau"))
    print("nguong  : %.2f\n" % args.threshold)

    paths = []
    for pattern in args.frames:
        expanded = sorted(glob.glob(pattern if Path(pattern).is_absolute()
                                    else str(ROOT / pattern)))
        paths.extend(Path(p) for p in expanded)
    if not paths:
        raise SystemExit("Khong tim thay khung hinh nao")

    hits, misses = [], []
    for path in paths:
        frame = read(path, gray)
        if frame.shape[0] < template.shape[0] or frame.shape[1] < template.shape[1]:
            print("  %-24s khung nho hon template, bo qua" % path.name)
            continue
        result = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(result)
        mark = "KHOP" if score >= args.threshold else "    "
        print("  %-24s %5.3f  tai (%4d,%3d)  %s  [%dx%d]"
              % (path.name, score, location[0], location[1], mark,
                 frame.shape[1], frame.shape[0]))
        (hits if score >= args.threshold else misses).append(score)

    print("\n  khop  : %d khung, thap nhat %.3f" % (len(hits), min(hits)) if hits
          else "\n  khop  : 0 khung")
    if misses:
        print("  khong : %d khung, cao nhat %.3f" % (len(misses), max(misses)))
    if hits and misses:
        gap = min(hits) - max(misses)
        verdict = "TOT" if gap >= 0.15 else ("HEP" if gap > 0.05 else "NGUY HIEM")
        print("  cach biet: %.3f  -> %s" % (gap, verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
