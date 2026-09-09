"""Crop a region out of a recorded frame — to inspect it, or to cut a template.

    # look at something, blown up
    python tools/crop_region.py recordings/chu-phong/01_0000.0s.png 1000 540 1136 640 --zoom 4

    # cut a template for matchTemplate (no zoom — it must be pixel-exact)
    python tools/crop_region.py recordings/chu-phong/57_0106.9s.png 1020 540 1136 610 \
        --out screenshots/SoulsDungeon/fight.png

Coordinates are left top right bottom, in the frame's own pixels. A template
saved this way is only valid for the client size it was captured at, which is
the same constraint the Realm Raid templates carry — see geometry.py.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "decompiled" / "source"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

import cv2  # noqa: E402
import numpy as np  # noqa: E402


def read(path: Path):
    data = np.frombuffer(path.read_bytes(), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise SystemExit("Khong doc duoc anh: %s" % path)
    return image


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Crop a region from a frame")
    parser.add_argument("frame")
    parser.add_argument("left", type=int)
    parser.add_argument("top", type=int)
    parser.add_argument("right", type=int)
    parser.add_argument("bottom", type=int)
    parser.add_argument("--zoom", type=int, default=1, help="scale up for inspection")
    parser.add_argument("--out", default="", help="where to write; default beside the frame")
    args = parser.parse_args(argv)

    source = Path(args.frame)
    if not source.is_absolute():
        source = ROOT / source
    image = read(source)
    height, width = image.shape[:2]

    left, top = max(0, args.left), max(0, args.top)
    right, bottom = min(width, args.right), min(height, args.bottom)
    if right <= left or bottom <= top:
        raise SystemExit("Vung cat rong: %d,%d -> %d,%d" % (left, top, right, bottom))

    crop = image[top:bottom, left:right]
    if args.zoom > 1:
        # INTER_NEAREST keeps the pixels crisp; a smooth upscale would invent
        # detail that is not in the capture.
        crop = cv2.resize(
            crop, (crop.shape[1] * args.zoom, crop.shape[0] * args.zoom),
            interpolation=cv2.INTER_NEAREST,
        )

    if args.out:
        target = Path(args.out)
        if not target.is_absolute():
            target = ROOT / target
    else:
        target = source.with_name(
            "%s_crop_%d-%d-%d-%d.png" % (source.stem, left, top, right, bottom)
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    ok, buffer = cv2.imencode(".png", crop)
    if not ok:
        raise SystemExit("Khong ma hoa duoc PNG")
    target.write_bytes(buffer.tobytes())

    print("nguon : %s (%dx%d)" % (source.name, width, height))
    print("cat   : (%d,%d) -> (%d,%d) = %dx%d"
          % (left, top, right, bottom, right - left, bottom - top))
    if args.zoom > 1:
        print("phong : x%d -> %dx%d" % (args.zoom, crop.shape[1], crop.shape[0]))
    print("luu   : %s" % target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
