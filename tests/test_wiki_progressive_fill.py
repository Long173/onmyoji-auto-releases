"""Clicking a wiki tab must enter it, not freeze on the doorstep.

Measured on the shipped dataset, 2026-09-08, with the pixmap cache and card
reuse already fixed — so this is the cost that remains on the *first* visit of
a session, when nothing is cached yet:

    import ui.wiki_page       54.3 ms
    WikiPage()              514.8 ms   <- loads the repo and renders 270 cards
    first paint               2.9 ms
    ---------------------------------
    first click             572.0 ms

    first switch to Ngự hồn   80.7 ms
    first switch to Hiệu ứng  75.3 ms

Half a second with the event loop blocked: the tab does not appear, the window
does not repaint, and the click looks ignored. Deferring the whole render would
not help — a loading label that appears and then freezes for 500 ms is still a
frozen window.

So the grid fills in time-budgeted slices with the event loop running between
them. `render` places what it can and schedules the rest; the caller gets
control back within a frame, and a "đang tải" line shows while the rest arrives.
"""
from __future__ import annotations

import time

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from PyQt5 import QtWidgets  # noqa: E402

from ui import wiki_views  # noqa: E402


@pytest.fixture
def grid(qt_app):
    """The shikigami grid over the whole shipped roster — the slow case."""
    from wiki.images import ImageResolver
    from wiki.repository import WikiRepository
    from ui.wiki_views import ShikigamiListView

    repository = WikiRepository()
    repository.load()
    view = ShikigamiListView(ImageResolver())
    return view, repository.shikigami()


def placed(view):
    return view._grid.count()


def drain(view, limit=400):
    """Run the event loop until the grid has finished filling."""
    for _ in range(limit):
        if not view.is_filling:
            return
        QtWidgets.QApplication.processEvents()
    raise AssertionError("the grid never finished filling")


def test_render_places_one_screenful_and_leaves(grid):
    """The whole point: the click returns, so the tab can paint.

    Asserted structurally rather than on the clock. The first version of this
    test timed `render` and demanded under 100 ms; it passed alone and failed
    inside the file, because a shared test process gives wildly different
    numbers — the timings quoted above range over 786 to 987 ms for the same
    fill. A flaky assertion is worse than none, and the bound that actually
    holds is this one: `render` places at most a screenful, whatever a card
    happens to cost today.
    """
    view, records = grid
    screenful = wiki_views.FIRST_SLICE_ROWS * view._columns

    view.render(records)

    assert 0 < placed(view) <= screenful, (
        "placed %d cards for a %d-card screenful" % (placed(view), screenful)
    )
    assert placed(view) < len(records), "placed the whole list synchronously"


def test_the_rest_arrives_on_the_event_loop(grid):
    view, records = grid

    view.render(records)
    drain(view)

    assert placed(view) == len(records)


def test_the_count_is_the_final_one_from_the_start(grid):
    """A number that counts up as the grid fills reads as a bug, and it is the
    answer to "how many are there", not "how many have been drawn"."""
    view, records = grid

    view.render(records)

    assert view._count.text() == "%d kết quả" % len(records)


def test_the_loading_line_waits_before_announcing_itself(grid):
    """It appears on a long fill, but not in the first frame of one.

    isHidden rather than isVisible throughout: isVisible is False for any widget
    whose ancestors are not on screen, and this view is never shown in a test.
    What is asserted is the visibility the grid sets, not the compositing.
    """
    view, records = grid

    view.render(records)
    assert view._loading.isHidden(), "announced the wait in the first slice"

    deadline = time.perf_counter() + 3
    while (view.is_filling and view._loading.isHidden()
           and time.perf_counter() < deadline):
        QtWidgets.QApplication.processEvents()

    assert not view._loading.isHidden(), (
        "never showed the line while filling %d cards" % len(records)
    )

    drain(view)
    assert view._loading.isHidden()


def test_a_short_list_never_shows_the_loading_line(grid):
    """Eight cold portraits overrun one slice, so this still fills across the
    event loop — it just finishes long before the wait is worth mentioning."""
    view, records = grid

    view.render(records[:8])
    announced = False
    for _ in range(400):
        if not view._loading.isHidden():
            announced = True
        if not view.is_filling:
            break
        QtWidgets.QApplication.processEvents()

    assert not announced, "flashed the loading line on an eight-card list"
    assert placed(view) == 8


def test_rendering_again_abandons_a_fill_in_flight(grid):
    """Changing the rarity filter while the grid is still filling.

    The scheduled slices carry the old list; left to run they would keep adding
    records the user has just filtered out.
    """
    view, records = grid

    view.render(records)              # starts filling all 270
    view.render(records[:5])          # user narrows it immediately
    drain(view)

    assert placed(view) == 5, "the abandoned fill kept adding cards"


def test_forgetting_the_cards_abandons_a_fill_in_flight(grid):
    """A sync landing mid-fill. The slices hold records from the dataset that
    has just been replaced, and their cards have been destroyed."""
    view, records = grid

    view.render(records)
    view.forget_cards()
    drain(view)

    assert not view.is_filling
    assert placed(view) == 0


# ── filling without the flicker ─────────────────────────────────────────────
#
# Slicing the fill stopped the freeze but traded it for a stutter. Measured on
# the shipped roster, 2026-09-08, with the grid on screen:
#
#     48 slices, 56% of them over 16.7 ms (one frame at 60 Hz)
#     p50 17.8 | p90 23.5 | max 26.2 ms      total 880 ms
#
# Each slice hands back a grid one row taller, so Qt re-lays-out and repaints
# the whole thing every time — which is why the total came out *worse* than the
# 518 ms the blocking version took. The visible part is the reflow: rows shift,
# the scrollbar resizes, and the loading line — sitting under the grid — walks
# down the page a step per slice.
#
# So the first slice fills the screen and is painted, and the rest is placed
# with updates switched off on the grid host: no intermediate layout reaches
# the screen, and one repaint happens at the end.


def test_the_first_slice_reaches_the_screen_and_the_rest_does_not(grid):
    """What the user sees: a screenful at once, then the rest without flicker.

    The order matters and got this wrong once. Freezing the host on the way out
    of the first slice placed those cards and then denied the event loop any
    chance to paint them, so the grid stayed blank for the whole fill and
    filled in one jump at the end — the freeze this was meant to remove. So
    updates are still on when render returns, and go off at the top of the
    next slice.
    """
    view, records = grid

    view.render(records)

    assert view._grid.count() > 0, "placed nothing in the first slice"
    assert view._grid_host.updatesEnabled(), (
        "froze the host before its first slice could be painted"
    )

    QtWidgets.QApplication.processEvents()

    assert view.is_filling, "the fixture's list is too short to test this"
    assert not view._grid_host.updatesEnabled(), (
        "left the grid re-laying-out on every slice"
    )

    drain(view)

    assert view._grid_host.updatesEnabled(), (
        "finished the fill with the grid still frozen"
    )
    assert view._grid.count() == len(records)


def test_a_list_that_finishes_in_one_slice_is_never_frozen(grid):
    """Nothing to hide, so nothing is switched off."""
    view, records = grid

    view.render(records[:4])
    drain(view)

    assert view._grid_host.updatesEnabled()


def test_an_abandoned_fill_leaves_the_grid_painting_again(grid):
    """A fill cut short by a filter change or a sync must not leave the host
    frozen — nothing would ever repaint it."""
    view, records = grid

    view.render(records)
    view.forget_cards()
    drain(view)

    assert view._grid_host.updatesEnabled(), "abandoned the fill while frozen"
