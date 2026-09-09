"""Rebuild assets/fonts from the upstream Google Fonts repository.

Run once; the resulting .ttf files are committed alongside the app.

    pip install fonttools
    python tools/fetch_fonts.py

Two things this script exists to get right:

* The ``fonts.googleapis.com`` CSS endpoint serves subsetted, obfuscated files
  that are not valid TrueType, so the fonts come from the google/fonts repo.
* Cormorant Garamond and Lora ship only as variable fonts, and Qt 5 exposes a
  variable font's default instance alone — asking for weight 600 would get a
  synthesised fake bold. Each is therefore flattened into static instances at
  the two weights the design uses.
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

RAW_BASE = "https://raw.githubusercontent.com/google/fonts/main"
FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"

# Static faces that upstream already provides.
STATIC = {
    "IBMPlexMono-400.ttf": "ofl/ibmplexmono/IBMPlexMono-Regular.ttf",
    "IBMPlexMono-500.ttf": "ofl/ibmplexmono/IBMPlexMono-Medium.ttf",
}

# Variable faces to instance, as name -> (upstream path, weights).
VARIABLE = {
    "CormorantGaramond": ("ofl/cormorantgaramond/CormorantGaramond%5Bwght%5D.ttf", (400, 600)),
    "Lora": ("ofl/lora/Lora%5Bwght%5D.ttf", (400, 600)),
}

TRUETYPE_MAGIC = {b"\x00\x01\x00\x00", b"true", b"ttcf", b"OTTO"}


def download(relative_path: str, target: Path) -> None:
    url = "%s/%s" % (RAW_BASE, relative_path)
    print("  fetching %s" % url)
    urllib.request.urlretrieve(url, target)
    magic = target.read_bytes()[:4]
    if magic not in TRUETYPE_MAGIC:
        raise SystemExit("%s is not a TrueType file (magic %r)" % (target.name, magic))


def main() -> int:
    try:
        from fontTools.ttLib import TTFont
        from fontTools.varLib import instancer
    except ImportError:
        raise SystemExit("fonttools is required: pip install fonttools")

    FONT_DIR.mkdir(parents=True, exist_ok=True)

    for name, path in STATIC.items():
        download(path, FONT_DIR / name)

    for name, (path, weights) in VARIABLE.items():
        source = FONT_DIR / ("%s-var.ttf" % name)
        download(path, source)
        for weight in weights:
            target = FONT_DIR / ("%s-%d.ttf" % (name, weight))
            instance = instancer.instantiateVariableFont(
                TTFont(source), {"wght": weight}, updateFontNames=True
            )
            instance.save(target)
            print("  instanced %s at wght=%d" % (target.name, weight))
        source.unlink()

    print("\nfonts in %s:" % FONT_DIR)
    for path in sorted(FONT_DIR.glob("*.ttf")):
        print("  %-28s %8d bytes" % (path.name, path.stat().st_size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
