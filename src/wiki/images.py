"""Resolve a record's ``image`` field to a pixmap.

The field holds a Flutter-relative path such as
``assets/images/shikigami/ssr/tu_kim_than.webp``. Those files ship with the
wiki checkout, so lookups are local and instant. The same path minus the
``assets/images/`` prefix is the object key in the Supabase ``assets`` bucket,
which is how missing files are back-filled after a sync.

Nothing here touches the network on the UI thread: :meth:`pixmap` only ever
reads the disk, and :func:`download_missing` is meant for the sync worker.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence

from PyQt5 import QtGui

import paths

logger = logging.getLogger(__name__)

ASSET_PREFIX = "assets/images/"
# How much decoded artwork to keep in memory.
#
# A budget in bytes, not a count of entries. The count was the bug: it was set
# to 240 while the shipped roster is 270 shikigami, so a list render walked
# straight past the cap, entry 241 evicted entry 1, and the next render — which
# starts again at entry 1 — missed on every single lookup, each miss evicting
# exactly what the following one was about to ask for. Measured on that build:
# 300.9 ms per render at a hit rate of 0.0%, against 0.1 ms once the cap cleared
# the list. The cache was holding 240 pixmaps the whole time, about 78 MB, and
# answering nothing.
#
# Counting entries also bounds the wrong thing. This artwork runs from 8 KB
# (effect icons) to 324 KB (600x404 portraits), so 240 entries is 2 MB or 78 MB
# depending only on which tab was opened — no useful limit on either reading.
#
# 160 MB against the 96.2 MB the wiki ships today, measured 2026-09-08. The
# headroom is for new shikigami; test_image_cache fails when the artwork
# outgrows it, which is the warning that never came the first time.
MEMORY_CACHE_BYTES = 160 * 1024 * 1024


def pixmap_bytes(pixmap) -> int:
    """Memory a decoded pixmap occupies, near enough for a budget."""
    return pixmap.width() * pixmap.height() * pixmap.depth() // 8
# A sync should not turn into a multi-hundred-file download.
MAX_DOWNLOADS_PER_SYNC = 120


class ImageResolver:
    """Finds image files and caches the decoded pixmaps."""

    def __init__(self, wiki_root: Optional[Path] = None) -> None:
        self.wiki_root = wiki_root or paths.WIKI_ROOT
        self.cache_dir = paths.IMAGE_CACHE_DIR
        self._pixmaps: "OrderedDict[str, Optional[QtGui.QPixmap]]" = OrderedDict()
        # Size of each cached entry, and their running total. Kept alongside
        # rather than recomputed: a pixmap's dimensions are cheap to read but
        # the total is wanted on every insert.
        self._sizes: "Dict[str, int]" = {}
        self._cached_bytes = 0

    # ── paths ───────────────────────────────────────────────────────────────

    @staticmethod
    def storage_key(image_field: str) -> str:
        """Object key inside the ``assets`` bucket."""
        key = (image_field or "").strip().lstrip("/")
        if key.startswith(ASSET_PREFIX):
            key = key[len(ASSET_PREFIX):]
        return key

    def local_path(self, image_field: str) -> Optional[Path]:
        """First existing file for this field: wiki checkout, then image cache.

        The two data sources spell the field differently — the bundled JSON
        keeps Flutter's ``assets/images/souls/x.webp`` while Supabase stores the
        bucket key ``souls/x.webp`` — so both shapes are tried. Handling only
        one meant every image vanished the moment the user synced.
        """
        field = (image_field or "").strip()
        if not field:
            return None
        key = self.storage_key(field)
        candidates = (
            self.wiki_root / field,                        # as written
            self.wiki_root / "assets" / "images" / key,     # bucket key -> checkout
            self.cache_dir / key,                           # downloaded earlier
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    # ── pixmaps ─────────────────────────────────────────────────────────────

    def pixmap(self, image_field: str) -> Optional[QtGui.QPixmap]:
        """Decoded image, or ``None`` when there is no file for it.

        Results — including misses — are memoised, so a scrolling grid does not
        re-stat the same paths on every repaint.
        """
        field = (image_field or "").strip()
        if not field:
            return None
        if field in self._pixmaps:
            self._pixmaps.move_to_end(field)
            return self._pixmaps[field]

        pixmap = self._decode(field)
        self._pixmaps[field] = pixmap
        # A miss is remembered too, at no cost to the budget: it saves
        # re-stat'ing the same absent paths on every repaint.
        size = pixmap_bytes(pixmap) if pixmap is not None else 0
        self._sizes[field] = size
        self._cached_bytes += size
        self._evict_over_budget()
        return pixmap

    def _decode(self, field: str) -> Optional[QtGui.QPixmap]:
        """Read one image off disk. Separated so tests can serve fakes."""
        path = self.local_path(field)
        if path is None:
            return None
        candidate = QtGui.QPixmap(str(path))
        if candidate.isNull():
            logger.debug("Could not decode %s", path)
            return None
        return candidate

    def _evict_over_budget(self) -> None:
        """Drop least-recently-used entries until the total fits the budget.

        The entry just added is never the one dropped — evicting it would make
        every lookup on an oversized list a miss, which is the failure this
        whole arrangement exists to avoid.
        """
        while self._cached_bytes > MEMORY_CACHE_BYTES and len(self._pixmaps) > 1:
            oldest, _ = self._pixmaps.popitem(last=False)
            self._cached_bytes -= self._sizes.pop(oldest, 0)

    @property
    def cached_bytes(self) -> int:
        """Memory the cache is currently holding."""
        return self._cached_bytes

    @property
    def cached_count(self) -> int:
        """Entries currently cached, misses included."""
        return len(self._pixmaps)

    def forget(self, image_field: str) -> None:
        field = (image_field or "").strip()
        self._pixmaps.pop(field, None)
        self._cached_bytes -= self._sizes.pop(field, 0)

    def clear(self) -> None:
        self._pixmaps.clear()
        self._sizes.clear()
        self._cached_bytes = 0


def download_missing(
    resolver: ImageResolver,
    client,
    image_fields: Iterable[str],
    limit: int = MAX_DOWNLOADS_PER_SYNC,
) -> int:
    """Fetch images that have no local file. Runs on the sync worker thread.

    Returns how many files were written. Failures are skipped silently: a
    missing picture degrades to a placeholder, it does not fail the sync.
    """
    written = 0
    for field in image_fields:
        if written >= limit:
            logger.info("Stopped after %d image downloads", written)
            break
        field = (field or "").strip()
        if not field or resolver.local_path(field) is not None:
            continue
        key = resolver.storage_key(field)
        data = client.download(client.storage_url(key))
        if not data:
            continue
        target = resolver.cache_dir / key
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            resolver.forget(field)
            written += 1
        except OSError:
            logger.debug("Could not cache %s", target, exc_info=True)
    return written


def collect_image_fields(records: Sequence) -> list:
    """Every non-empty ``image`` on a set of records, including skill icons."""
    fields = []
    for record in records:
        image = getattr(record, "image", "")
        if image:
            fields.append(image)
        for skill in getattr(record, "skills", []) or []:
            if getattr(skill, "image", ""):
                fields.append(skill.image)
    return fields
