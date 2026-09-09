"""A tab switch should not rebuild every card it showed a moment ago.

`render` cleared the grid and constructed a fresh card per record, so opening
the Thức thần tab built 270 widgets from scratch every single time. Measured on
the shipped dataset, 2026-09-08, after the pixmap cache was fixed:

    Thức thần   pass 1  597.8 ms | pass 2  225.0 ms | 270 cards
    Ngự hồn      pass 1   88.8 ms | pass 2   44.4 ms |  64 cards
    Hiệu ứng     pass 1   50.7 ms | pass 2   49.8 ms | 109 cards

That 225 ms is pure widget construction — layouts, stylesheets, badges — and it
was paid again on every visit, which is what the tabs felt slow doing. The auto
task pages never felt slow because they carry a handful of cards, not hundreds.

The cards are keyed by record id and dropped when the dataset is replaced. That
invalidation is the part worth testing: a reused card showing pre-sync data
would be a worse bug than a slow tab.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from PyQt5 import QtWidgets  # noqa: E402


@pytest.fixture
def views(qt_app):
    """The two grid views, over a handful of real records.

    Real ones rather than fakes: the card reads several fields off a record and
    a stand-in would drift. Only a few, because decoding the whole roster's
    artwork inside a test process takes the process down with it.
    """
    from wiki.images import ImageResolver
    from wiki.repository import WikiRepository
    from ui.wiki_views import ShikigamiListView, SoulListView

    repository = WikiRepository()
    repository.load()
    resolver = ImageResolver()
    return {
        "shiki": (ShikigamiListView(resolver), repository.shikigami()[:6]),
        "souls": (SoulListView(resolver), repository.souls()[:6]),
    }


def cards_in(view):
    """The card widgets currently placed in the grid, in order.

    Drains the event loop first: `render` returns before the grid is full — see
    tests/test_wiki_progressive_fill.py — and reuse is about which objects come
    back, not about when.
    """
    for _ in range(400):
        if not view.is_filling:
            break
        QtWidgets.QApplication.processEvents()
    grid = view._grid
    return [grid.itemAt(i).widget() for i in range(grid.count())
            if grid.itemAt(i).widget() is not None]


@pytest.mark.parametrize("which", ["shiki", "souls"])
def test_rendering_the_same_list_again_reuses_the_cards(views, which):
    view, records = views[which]

    view.render(records)
    first = cards_in(view)
    view.render(records)
    again = cards_in(view)

    assert first, "rendered no cards at all"
    assert [id(c) for c in first] == [id(c) for c in again], (
        "rebuilt every card for a list that had not changed"
    )


def test_a_narrowed_list_keeps_the_cards_it_still_shows(views):
    """Changing the rarity filter is a re-render with fewer records."""
    view, records = views["shiki"]

    view.render(records)
    kept = {id(c) for c in cards_in(view)}
    view.render(records[:3])

    assert len(cards_in(view)) == 3
    assert {id(c) for c in cards_in(view)} <= kept


def test_cards_dropped_from_the_grid_are_not_left_on_screen(views):
    """Taken out of the layout, not merely un-parented somewhere visible."""
    view, records = views["shiki"]

    view.render(records)
    view.render(records[:2])
    QtWidgets.QApplication.processEvents()

    on_show = [c for c in view.findChildren(QtWidgets.QWidget)
               if getattr(c, "_record_id", None) and c.isVisible()]
    assert len(on_show) <= 2, "left %d cards showing for a 2-record list" % len(on_show)


@pytest.mark.parametrize("which", ["shiki", "souls"])
def test_a_replaced_dataset_throws_the_cards_away(views, which):
    """The invalidation. A sync brings new names, art and rarities, and a card
    kept from before would quietly show the old ones."""
    view, records = views[which]

    view.render(records)
    before = [id(c) for c in cards_in(view)]
    view.forget_cards()
    view.render(records)

    assert [id(c) for c in cards_in(view)] != before, (
        "kept cards built from the dataset that was just replaced"
    )


# ── the effects table ───────────────────────────────────────────────────────
#
# Not a card grid but the same waste: 109 rows torn down and rebuilt on every
# visit. Cheaper per row than a portrait card — no artwork to decode, 0.4 ms
# apiece — but it added up to the tab that measured slowest once the two grids
# had been fixed:
#
#     first switch to Hiệu ứng   124.0 ms
#
# Rows have no images, so filling progressively buys little; reuse is the whole
# fix here.


@pytest.fixture
def effects(qt_app):
    from wiki.repository import WikiRepository
    from ui.wiki_views import EffectsView

    repository = WikiRepository()
    repository.load()
    from wiki.images import ImageResolver

    return EffectsView(ImageResolver()), repository.effects()


def rows_in(view):
    rows = view._rows
    return [rows.itemAt(i).widget() for i in range(rows.count())
            if rows.itemAt(i).widget() is not None]


def test_rendering_the_effects_table_again_reuses_the_rows(effects):
    view, records = effects

    view.render(records)
    first = rows_in(view)
    view.render(records)

    assert first, "rendered no rows at all"
    assert [id(r) for r in first] == [id(r) for r in rows_in(view)]


def test_a_narrowed_effects_table_shows_only_what_was_asked_for(effects):
    view, records = effects

    view.render(records)
    view.render(records[:4])

    assert len(rows_in(view)) == 4


def test_a_replaced_dataset_throws_the_effect_rows_away(effects):
    view, records = effects

    view.render(records)
    before = [id(r) for r in rows_in(view)]
    view.forget_cards()
    view.render(records)

    assert [id(r) for r in rows_in(view)] != before
