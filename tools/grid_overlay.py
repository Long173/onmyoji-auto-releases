"""Draw a coordinate grid over a frame, so a spot can be named precisely.

    python tools/grid_overlay.py recordings/chu-phong-chuan/21_0048.0s.png

Used when a click target has to be agreed on: reading "around (560, 320)" off a
labelled picture beats describing it in words and hoping.
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

STEP = 100
MINOR = 50


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Overlay a coordinate grid")
    parser.add_argument("frame")
    parser.add_argument("--out", default="")
    parser.add_argument("--step", type=int, default=STEP)
    args = parser.parse_args(argv)

    source = Path(args.frame)
    if not source.is_absolute():
        source = ROOT / source
    data = np.frombuffer(source.read_bytes(), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise SystemExit("Khong doc duoc anh: %s" % source)

    height, width = image.shape[:2]
    overlay = image.copy()

    for x in range(0, width, MINOR):
        cv2.line(overlay, (x, 0), (x, height), (60, 60, 60), 1)
    for y in range(0, height, MINOR):
        cv2.line(overlay, (0, y), (width, y), (60, 60, 60), 1)
    image = cv2.addWeighted(overlay, 0.45, image, 0.55, 0)

    for x in range(0, width, args.step):
        cv2.line(image, (x, 0), (x, height), (0, 200, 255), 1)
        cv2.putText(image, str(x), (x + 3, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(image, str(x), (x + 3, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (0, 220, 255), 1, cv2.LINE_AA)
    for y in range(0, height, args.step):
        cv2.line(image, (0, y), (width, y), (0, 200, 255), 1)
        cv2.putText(image, str(y), (4, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(image, str(y), (4, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (0, 220, 255), 1, cv2.LINE_AA)

    target = Path(args.out) if args.out else source.with_name(source.stem + "_grid.png")
    if not target.is_absolute():
        target = ROOT / target
    target.parent.mkdir(parents=True, exist_ok=True)
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise SystemExit("Khong ma hoa duoc PNG")
    target.write_bytes(buffer.tobytes())
    print("khung %dx%d, luoi moi %dpx -> %s" % (width, height, args.step, target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
