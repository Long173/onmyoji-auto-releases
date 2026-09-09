"""Folding the shikigami that were filed twice.

The dataset came from two sources merged without reconciliation, so ~20 figures
had two records under different ids. Nothing that compared ids or names could
see it.

Two things here are worth more than the rest:

* **The stats actually arrive.** The fold went in twice before it worked, both
  times looking like it had: the duplicate disappeared from the list and every
  merged figure still showed hp 0. First because a stats block full of zeros is
  not an *empty* dict, then because "any non-zero number" is always true — every
  row carries a baseline crit_dmg of 150. A fold that quietly keeps the empty
  half is worse than no fold, because the list looks right.
* **The pairs point at figures that exist.** A typo in an id is invisible
  otherwise: the pair simply never fires and the duplicate stays.
"""
from __future__ import annotations

import copy

import pytest

from wiki import duplicates
from wiki.repository import WikiRepository

# What the game itself has, for the arithmetic that confirmed the SP pairing.
GAME_SP_COUNT = 50


@pytest.fixture(scope="module")
def dataset():
    repository = WikiRepository()
    repository.load()
    return repository


def stats_of(hp=0, attack=0):
    """A stats block shaped like the real ones, including the baselines."""
    return {
        "hp": {"tier": "", "value": hp},
        "attack": {"tier": "", "value": attack},
        "speed": {"tier": "", "value": 0},
        # Present on every row whether it was filled in or not — the reason
        # "any non-zero number" was the wrong test.
        "crit_dmg": {"tier": "", "value": 150},
        "crit_rate": {"tier": "", "value": 10},
    }


# ── the table itself ────────────────────────────────────────────────────────


def test_no_id_is_listed_twice():
    """A figure folded into two different survivors would lose data silently."""
    kept = [k for k, _ in duplicates.PAIRS]
    dropped = [d for _, d in duplicates.PAIRS]
    assert len(set(dropped)) == len(dropped), "an id is folded away twice"
    assert not set(kept) & set(dropped), "an id is both kept and dropped"


def test_a_pair_never_points_at_itself():
    for keep, drop in duplicates.PAIRS:
        assert keep != drop


def test_every_id_in_the_table_exists(dataset):
    """A typo makes a pair a no-op, and the duplicate stays on the list."""
    known = {row.id for row in dataset.dataset.shikigami}
    dropped = {d for _, d in duplicates.PAIRS}
    missing_keep = [k for k, _ in duplicates.PAIRS if k not in known]
    # The dropped ids are gone from the loaded dataset by definition, so they
    # are checked against the raw rows instead.
    raw = {row.get("id") for row in dataset._read_bundled_rows()["shikigami"]}
    assert not missing_keep, "kept ids not in the dataset: %s" % missing_keep
    unknown = [d for d in dropped if d not in raw and d not in known]
    assert not unknown, "dropped ids exist in neither place: %s" % unknown


# ── the fold ────────────────────────────────────────────────────────────────


def test_one_record_survives_each_pair():
    rows = [{"id": "keep", "stats": stats_of()}, {"id": "drop", "stats": stats_of(100, 20)}]
    pairs = (("keep", "drop"),)
    out = _merge_with(pairs, rows)

    assert [r["id"] for r in out] == ["keep"]


def test_the_survivor_gains_the_stats_it_was_missing():
    """The bug that shipped twice: the fold ran and the numbers stayed at zero."""
    rows = [{"id": "keep", "stats": stats_of()},
            {"id": "drop", "stats": stats_of(9912, 3377)}]
    out = _merge_with((("keep", "drop"),), rows)

    assert out[0]["stats"]["hp"]["value"] == 9912
    assert out[0]["stats"]["attack"]["value"] == 3377


def test_a_baseline_only_stats_block_counts_as_empty():
    """Every row carries crit_dmg 150, so "any non-zero" was always true."""
    assert duplicates._no_numbers(stats_of()) is True
    assert duplicates._no_numbers(stats_of(1, 0)) is False
    assert duplicates._no_numbers(stats_of(0, 1)) is False
    assert duplicates._no_numbers({}) is True
    assert duplicates._no_numbers(None) is True


def test_real_stats_are_never_overwritten():
    rows = [{"id": "keep", "stats": stats_of(500, 50)},
            {"id": "drop", "stats": stats_of(9912, 3377)}]
    out = _merge_with((("keep", "drop"),), rows)

    assert out[0]["stats"]["hp"]["value"] == 500, "clobbered the good half"


def test_the_vietnamese_name_is_what_survives():
    """The whole reason that side is the one kept."""
    rows = [{"id": "keep", "name_vi": "Đại Thiên Cẩu", "name_en": ""},
            {"id": "drop", "name_vi": "", "name_en": "Ootengu"}]
    out = _merge_with((("keep", "drop"),), rows)

    assert out[0]["name_vi"] == "Đại Thiên Cẩu"
    assert out[0]["name_en"] == "Ootengu", "the romaji was worth keeping too"


def test_other_empty_fields_are_filled_in():
    rows = [{"id": "keep", "skills": [], "role": []},
            {"id": "drop", "skills": [{"name": "x"}], "role": ["attacker"]}]
    out = _merge_with((("keep", "drop"),), rows)

    assert out[0]["skills"] == [{"name": "x"}]
    assert out[0]["role"] == ["attacker"]


def test_rows_it_knows_nothing_about_pass_straight_through():
    rows = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    out = duplicates.merge_rows(copy.deepcopy(rows))

    assert [r["id"] for r in out] == ["a", "b", "c"]


def test_a_pair_with_one_half_absent_changes_nothing():
    """A partial dataset is a normal thing to be handed."""
    rows = [{"id": "keep", "stats": stats_of()}]
    out = _merge_with((("keep", "drop"),), rows)

    assert [r["id"] for r in out] == ["keep"]


def test_order_is_kept():
    rows = [{"id": "a"}, {"id": "drop"}, {"id": "keep"}, {"id": "z"}]
    out = _merge_with((("keep", "drop"),), rows)

    assert [r["id"] for r in out] == ["a", "keep", "z"]


# ── against the real dataset ────────────────────────────────────────────────


def test_the_loaded_dataset_holds_no_duplicate_ids(dataset):
    ids = [row.id for row in dataset.dataset.shikigami]
    assert len(ids) == len(set(ids))


def test_none_of_the_folded_records_are_still_listed(dataset):
    listed = {row.id for row in dataset.dataset.shikigami}
    still_there = [d for _, d in duplicates.PAIRS if d in listed]
    assert not still_there, "folded but still on the list: %s" % still_there


def test_the_sp_count_matches_the_game(dataset):
    """The arithmetic that confirmed the SP pairing was right.

    The fold takes 65 SP records down to 49 by merging 16 pairs. At that point
    the game had 50 and the odd one out was Suzuhikohime SP, absent from every
    source — 49 + 1 = 50 exactly, which no wrong pairing would produce. That was
    the evidence for the pairing, and it is why this number can be asserted at
    all.

    She has since been entered by hand (see :mod:`wiki.additions`), so the total
    is now the game's own. If this ever reads 49 again the addition has stopped
    loading; if it reads 51 something is being counted twice.
    """
    sp = [row for row in dataset.dataset.shikigami if row.rarity == "SP"]
    assert len(sp) == GAME_SP_COUNT


def test_there_is_nothing_left_to_fold(dataset):
    """The upstream data is clean now, so the fold is a no-op against it.

    It used to assert that the fold had filled in the missing stats — 46 records
    with no health before, 28 after. That assertion has gone hollow: the
    duplicates were deleted from Supabase and the merged stats written onto the
    survivors, so there is no pair left for the fold to act on and the count
    would pass whether the fold worked or not.

    What the fold actually does is covered by the unit tests above, which build
    their own pairs. What is worth checking here is the new state: none of the
    folded ids come back, which is also how a re-synced or re-imported duplicate
    would be caught.
    """
    listed = {row.id for row in dataset.dataset.shikigami}
    back = [drop for _keep, drop in duplicates.PAIRS if drop in listed]
    assert not back, "duplicates are back upstream: %s" % back


# ── names the import got wrong ──────────────────────────────────────────────


def test_the_frog_names_are_off_the_shikigami_records(dataset):
    """Two SSR rows carried a Realm Raid frog's romaji name.

    Checked by id rather than by name, which is the mistake that hid it: totting
    up frogs by name swept these two SSR in with the real frogs and reported 17
    where there are 15.
    """
    wrong = [row for row in dataset.dataset.shikigami
             if "frog" in (row.name_en or "").lower() and "frog" not in row.id]
    assert not wrong, "still carrying a frog's name: %s" % [r.id for r in wrong]


def test_the_frogs_themselves_keep_their_names(dataset):
    """The correction must not reach the records that are really frogs."""
    frogs = [row for row in dataset.dataset.shikigami if "frog" in row.id]
    assert len(frogs) == 15
    assert all("frog" in (row.name_en or "").lower() for row in frogs)


def test_a_correction_names_a_record_that_exists(dataset):
    known = {row.id for row in dataset.dataset.shikigami}
    missing = [i for i in duplicates.WRONG_NAMES if i not in known]
    assert not missing, "corrections for records that are not there: %s" % missing


def test_a_correction_replaces_whatever_was_there(dataset):
    rows = [{"id": "ngu_soan_tan", "name_en": "Miketsu Frog"}]
    out = duplicates.merge_rows(copy.deepcopy(rows))

    assert out[0]["name_en"] == "Miketsu"


# ── helper ──────────────────────────────────────────────────────────────────


def _merge_with(pairs, rows):
    """Run the fold against a made-up table, leaving the real one alone."""
    original = duplicates.PAIRS
    duplicates.PAIRS = pairs
    try:
        return duplicates.merge_rows(copy.deepcopy(rows))
    finally:
        duplicates.PAIRS = original


# ── the same shikigami twice under one id ───────────────────────────────────
#
# Migration 0011 renamed 97 shikigami ids to their English form, which landed
# both halves of every one of these pairs on the *same* id — the id the
# fandom.com row already had. That broke the pair table outright: it keys on the
# old Vietnamese ids, so `by_id.get(keep_id)` came back None and the fold
# silently stopped happening. 18 duplicates survived and the encyclopaedia
# listed those figures twice, which is the exact bug this module exists to fix.
#
# So a duplicate is now also found by its id, and the table is kept for the
# datasets that still use the old ids — every cache written before the rename.


def a_pair_sharing_an_id(row_id="bakkotsu_kiyohime"):
    """The shape the bundled dataset has after the rename."""
    return [
        {"id": row_id, "name_vi": "Phược Cốt Thanh Cơ", "name_en": "",
         "stats": {}, "skills": []},
        {"id": row_id, "name_vi": "", "name_en": "Bakkotsu Kiyohime",
         "stats": {"hp": {"value": 11000}}, "skills": [{"name": "x"}]},
    ]


def test_two_rows_under_one_id_become_one():
    folded = duplicates.merge_rows(a_pair_sharing_an_id())

    assert len(folded) == 1


def test_the_vietnamese_name_is_the_half_that_is_kept():
    """This is a Vietnamese tool; that name is the whole reason it is kept."""
    folded = duplicates.merge_rows(a_pair_sharing_an_id())

    assert folded[0]["name_vi"] == "Phược Cốt Thanh Cơ"


def test_the_other_half_hands_over_what_it_has():
    """It is the half with the stats; dropping it would lose them."""
    folded = duplicates.merge_rows(a_pair_sharing_an_id())

    assert folded[0]["stats"] == {"hp": {"value": 11000}}
    assert folded[0]["skills"] == [{"name": "x"}]
    assert folded[0]["name_en"] == "Bakkotsu Kiyohime"


def test_file_order_does_not_decide_which_half_wins():
    """A re-export listing the fandom half first would otherwise start dropping
    every Vietnamese name."""
    reversed_pair = list(reversed(a_pair_sharing_an_id()))

    folded = duplicates.merge_rows(reversed_pair)

    assert len(folded) == 1
    assert folded[0]["name_vi"] == "Phược Cốt Thanh Cơ"
    assert folded[0]["stats"] == {"hp": {"value": 11000}}


def test_two_rows_with_neither_name_still_become_one():
    rows = [{"id": "x", "name_vi": "", "stats": {}},
            {"id": "x", "name_vi": "", "stats": {"hp": {"value": 1}}}]

    folded = duplicates.merge_rows(rows)

    assert len(folded) == 1
    assert folded[0]["stats"] == {"hp": {"value": 1}}


def test_a_cache_written_before_the_rename_still_folds():
    """The pair table is what handles it, and is why it is still here."""
    old_style = [
        {"id": "phuoc_cot_thanh_co", "name_vi": "Phược Cốt Thanh Cơ", "stats": {}},
        {"id": "bakkotsu_kiyohime", "name_vi": "", "name_en": "Bakkotsu Kiyohime",
         "stats": {"hp": {"value": 11000}}},
    ]

    folded = duplicates.merge_rows(old_style)

    assert len(folded) == 1
    assert folded[0]["id"] == "phuoc_cot_thanh_co"
    assert folded[0]["stats"] == {"hp": {"value": 11000}}


def test_distinct_shikigami_are_left_alone():
    rows = [{"id": "ootengu", "name_vi": "Đại Thiên Cẩu"},
            {"id": "kuzunoha", "name_vi": "Cát Diệp"}]

    assert len(duplicates.merge_rows(rows)) == 2


def test_the_real_bundled_dataset_comes_out_clean():
    """The measurement that caught this: 287 records in, 18 duplicate ids out."""
    import collections
    import json
    from pathlib import Path as P

    folder = P(__file__).resolve().parents[1].parent / "onmyoji_wiki" / "assets" / "data" / "shikigami"
    if not folder.is_dir():
        pytest.skip("the wiki checkout is not beside this one")
    rows = []
    for path in sorted(folder.glob("*.json")):
        rows += json.loads(path.read_text(encoding="utf-8"))

    folded = duplicates.merge_rows([dict(r) for r in rows])

    counts = collections.Counter(r["id"] for r in folded)
    assert not [i for i, n in counts.items() if n > 1], "duplicates survived"
    assert len(folded) < len(rows), "nothing was folded at all"
