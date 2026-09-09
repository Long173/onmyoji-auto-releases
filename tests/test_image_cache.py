"""The pixmap cache has to hold the list it is asked to show.

Measured on the shipped dataset, 2026-09-08: 270 shikigami against a cache
capped at 240 entries. A list render touches all 270 images in order, so entry
241 evicts entry 1, and by the end entries 1-30 are gone. The *next* render
starts at entry 1 — just evicted — and from there every lookup misses, each one
evicting exactly what the following lookup is about to ask for. Textbook LRU
sequential-scan pathology, and the hit rate is precisely zero:

    cap=240   pass 2:  300.9 ms   hit rate:  0.0%  (0 of 810)
    cap=270   pass 2:    0.1 ms   hit rate: 66.7%  (540 of 810)

300 ms against 0.1 ms, from a constant that was 30 too small. And the cache was
holding 240 decoded pixmaps throughout — about 78 MB — so it paid the full
price of a cache while answering nothing.

Raising the number would fix today and break again at the next collaboration
banner. The deeper fault is that the cap bounds the wrong quantity: it counts
entries, while the resource worth protecting is memory, and these images run
from 8 KB to 324 KB apiece. 240 entries is anywhere between 2 MB and 78 MB
depending only on which tab you opened. So the budget is in bytes, and the
guard below is that it covers the whole shipped dataset.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtGui")

from wiki import images  # noqa: E402


class CountingResolver(images.ImageResolver):
    """Serves fake pixmaps of a stated size and counts the decodes."""

    def __init__(self, kb_each=64):
        super().__init__()
        self.decodes = 0
        self._bytes = kb_each * 1024

    def _decode(self, field):
        self.decodes += 1
        return _FakePixmap(self._bytes)


class _FakePixmap:
    def __init__(self, size):
        self._size = size

    def isNull(self):
        return False

    def cacheKey(self):
        return id(self)

    def width(self):
        return 100

    def height(self):
        return self._size // (100 * 4)

    def depth(self):
        return 32


def scan(resolver, fields, laps):
    """Walk the same list in the same order, the way a grid render does."""
    for _ in range(laps):
        for field in fields:
            resolver.pixmap(field)
    return resolver.decodes


def test_a_list_that_fits_the_budget_is_decoded_once():
    resolver = CountingResolver(kb_each=64)
    fields = ["img/%d.png" % i for i in range(40)]     # 40 x 64 KB = 2.5 MB

    assert scan(resolver, fields, laps=5) == len(fields)


def test_the_budget_is_counted_in_bytes_not_entries():
    """Two lists of the same length must not cost the same.

    Under the old entry cap, 240 thumbnails of 8 KB and 240 portraits of 324 KB
    were treated as equal — 2 MB and 78 MB held to the same limit.
    """
    # Sized so the small list fits the budget comfortably and the big one
    # cannot: 300 x 8 KB is 2.4 MB, 300 x 1 MB is 300 MB.
    small = CountingResolver(kb_each=8)
    big = CountingResolver(kb_each=1024)
    fields = ["img/%d.png" % i for i in range(300)]

    scan(small, fields, laps=1)
    scan(big, fields, laps=1)

    assert small.cached_bytes < big.cached_bytes
    assert small.cached_count > big.cached_count, (
        "the cache kept the same number of images regardless of their size"
    )


def test_the_budget_is_actually_enforced():
    """It is a cache, not a leak: something has to come out."""
    resolver = CountingResolver(kb_each=1024)
    fields = ["img/%d.png" % i for i in range(1000)]   # 1 GB if nothing evicts

    scan(resolver, fields, laps=1)

    assert resolver.cached_bytes <= images.MEMORY_CACHE_BYTES


def test_misses_are_remembered_without_costing_the_budget():
    """A record with no artwork is cached as a miss so the paths are not
    re-stat'ed on every repaint, and an absent image occupies no memory."""
    # The real resolver, not CountingResolver: this is about what _decode does
    # when there is no file, and CountingResolver replaces _decode outright.
    resolver = images.ImageResolver()
    resolver.local_path = lambda field: None

    resolver.pixmap("nope.png")
    resolver.pixmap("nope.png")

    assert resolver.cached_bytes == 0
    assert resolver.cached_count == 1


def test_the_budget_covers_every_image_the_wiki_ships():
    """The guard that would have caught this, and will catch it again.

    The roster grows with every collaboration banner. When the artwork outgrows
    the budget the list views fall off the cliff described at the top of this
    file rather than getting gradually slower — so this must fail loudly at
    that point, not be noticed by a user reporting that a tab "takes a while to
    show up".

    Sizes come from QImageReader, which reads only the header. Decoding all 376
    of them here killed the test process outright — the same GDI exhaustion the
    suite hits under load — and the byte total is what is being asked about,
    not the pixels.
    """
    from PyQt5 import QtGui
    from wiki.repository import WikiRepository

    repository = WikiRepository()
    repository.load()
    resolver = images.ImageResolver()

    total = counted = 0
    for kind in ("shikigami", "souls", "effects"):
        for record in getattr(repository, kind)():
            path = resolver.local_path(record.image)
            if path is None:
                continue
            size = QtGui.QImageReader(str(path)).size()
            if not size.isValid():
                continue
            # 32 bits per pixel, which is what these decode to — measured with
            # QPixmap.depth() across the whole dataset.
            total += size.width() * size.height() * 4
            counted += 1

    assert counted > 0, "found no artwork at all — is the wiki dataset present?"
    assert total <= images.MEMORY_CACHE_BYTES, (
        "the wiki ships %.1f MB of artwork across %d images but the cache "
        "budget is %.1f MB — a full render evicts what the next one needs and "
        "the hit rate goes to zero"
        % (total / 1048576, counted, images.MEMORY_CACHE_BYTES / 1048576)
    )
