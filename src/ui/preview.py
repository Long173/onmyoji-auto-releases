"""Turn a captured game frame into something Qt can draw.

``GameControl`` hands back OpenCV's BGR byte order; Qt wants RGB. Two details
here are easy to get wrong and both fail quietly:

* **Stride.** ``QImage`` guesses bytes-per-line when it is not told, and guesses
  wrong for widths that are not a multiple of four — the picture comes out
  sheared diagonally. It is passed explicitly.
* **Buffer lifetime.** ``QImage`` wraps the numpy buffer without copying it.
  ``QPixmap.fromImage`` is what copies, so the array has to still be alive at
  that moment — hence the local variable rather than a chained expression.
"""
from __future__ import annotations

from typing import Any, Optional

from PyQt5 import QtGui

# 1136×640 is what the game gives; 16:9 within a rounding error, and the frame
# is letterboxed into the box anyway, so a fixed ratio is honest enough.
ASPECT = 16 / 9


def to_pixmap(frame: Optional[Any]) -> Optional[QtGui.QPixmap]:
    """Convert a BGR frame to a QPixmap. ``None`` in, ``None`` out."""
    if frame is None:
        return None
    try:
        import cv2
    except ImportError:  # pragma: no cover - cv2 ships with the app
        return None

    if getattr(frame, "ndim", 0) != 3 or frame.shape[2] not in (3, 4):
        return None

    height, width = frame.shape[:2]
    if not height or not width:
        return None

    conversion = cv2.COLOR_BGRA2RGB if frame.shape[2] == 4 else cv2.COLOR_BGR2RGB
    rgb = cv2.cvtColor(frame, conversion)
    # ascontiguousarray: a frame that arrived as a slice of a larger capture has
    # a stride wider than its width, which the explicit bytes-per-line below
    # would then describe incorrectly.
    import numpy as np

    rgb = np.ascontiguousarray(rgb)
    image = QtGui.QImage(
        rgb.data, width, height, width * 3, QtGui.QImage.Format_RGB888
    )
    return QtGui.QPixmap.fromImage(image)


def height_for(width: int) -> int:
    """Box height that keeps the game's aspect ratio at a given width."""
    return max(1, round(width / ASPECT))
