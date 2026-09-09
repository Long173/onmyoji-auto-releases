"""Write the app icon out as files, for shortcuts and packaging.

The app itself never reads these — it draws the icon at runtime from
``ui/app_icon.py``, so nothing can drift out of sync. This exists so you can
point a desktop shortcut (or a future PyInstaller build) at a real file.

    python tools/export_icon.py

Produces ``assets/icon.ico`` (every size, PNG-compressed) and
``assets/icon-256.png``.

The .ico is assembled here rather than through ``QImageWriter``: Qt's ICO writer
takes a single image and stores it uncompressed, which gave a one-entry 270 KB
file. Windows picks the closest size out of a multi-entry icon, so a 16px
taskbar slot would otherwise be a downscaled 256px bitmap.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "decompiled" / "source"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

ICO_HEADER = "<HHH"        # reserved, type (1 = icon), image count
ICO_ENTRY = "<BBBBHHII"    # w, h, colours, reserved, planes, bpp, size, offset
ENTRY_SIZE = 16
HEADER_SIZE = 6


def png_bytes(pixmap) -> bytes:
    from PyQt5 import QtCore

    buffer = QtCore.QBuffer()
    buffer.open(QtCore.QIODevice.WriteOnly)
    pixmap.save(buffer, "PNG")
    return bytes(buffer.data())


def build_ico(pixmaps) -> bytes:
    """Pack pixmaps into a multi-size .ico with PNG-compressed entries."""
    payloads = [png_bytes(pixmap) for pixmap in pixmaps]

    header = struct.pack(ICO_HEADER, 0, 1, len(payloads))
    offset = HEADER_SIZE + ENTRY_SIZE * len(payloads)

    directory = b""
    for pixmap, payload in zip(pixmaps, payloads):
        side = pixmap.width()
        directory += struct.pack(
            ICO_ENTRY,
            0 if side >= 256 else side,   # 0 means 256 in this format
            0 if side >= 256 else side,
            0,
            0,
            1,
            32,
            len(payload),
            offset,
        )
        offset += len(payload)

    return header + directory + b"".join(payloads)


def main() -> int:
    from PyQt5 import QtWidgets

    # Held in a local: an unbound QApplication is collected immediately, and
    # the next QPixmap then fails with "Must construct a QGuiApplication".
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    assert app is not None

    import paths
    from ui import app_icon

    paths.ASSET_DIR.mkdir(parents=True, exist_ok=True)

    png = paths.ASSET_DIR / "icon-256.png"
    app_icon.render(256).save(str(png), "PNG")
    print("%-16s %7d bytes" % (png.name, png.stat().st_size))

    ico = paths.ASSET_DIR / "icon.ico"
    pixmaps = [app_icon.render(size) for size in app_icon.ICON_SIZES]
    ico.write_bytes(build_ico(pixmaps))
    print(
        "%-16s %7d bytes  (%s)"
        % (ico.name, ico.stat().st_size,
           ", ".join("%d" % p.width() for p in pixmaps))
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
