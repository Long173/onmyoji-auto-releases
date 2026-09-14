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

import collections
import copy
import re
import unicodedata

import pytest

from wiki import duplicates
from wiki.repository import WikiRepository

# What the game itself has. Counted off the shikigami album in-game while the
# portraits were being recaptured: its SP block runs to 51 entries. It read 50
# here until Ignis Suzuhikohime was entered by hand in :mod:`wiki.additions` —
# she is the fifty-first, and this number was not moved with her.
GAME_SP_COUNT = 51


@pytest.fixture(scope="module")
def dataset():
    """The dataset as a fresh install reads it — the bundled files.

    Pinned to the bundle rather than ``load()``, which prefers a sync cache when
    one is on disk. That made every count here depend on whether the machine had
    ever pressed "Đồng bộ lại": a developer's cache holds the curated Supabase
    copy and passed, CI holds nothing and read the bundled rows, and the two
    disagree by two records. A test that asks a different question per machine
    cannot be trusted by either.

    The bundle is also the more useful of the two to assert on: it is what
    somebody who installs the app and never syncs actually sees.
    """
    repository = WikiRepository()
    repository.dataset = repository._load_bundled()
    if repository.dataset is None:
        pytest.skip("no bundled wiki data on this machine")
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


def _same_figure(name):
    """A display name reduced to what identifies the figure."""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


# ── the table itself ────────────────────────────────────────────────────────


def test_no_id_is_both_kept_and_dropped():
    """Folding a survivor into something else loses whichever half wins."""
    kept = {k for k, _ in duplicates.PAIRS}
    dropped = {d for _, d in duplicates.PAIRS}

    assert not kept & dropped, "an id is both kept and dropped: %s" % (kept & dropped)


def test_a_drop_has_at_most_one_live_survivor(dataset):
    """One id may be dropped by two pairs, and that is on purpose.

    Migration 0011 renamed one Vietnamese half instead of landing it on the
    romaji id, so Yumebiki Kochou no Sei has two possible survivors — the
    pre-rename ``mong_dan_ho_diep_tinh`` for an old cache, and
    ``dreambound_chocho`` for the bundled file. Only ever one of them is in a
    given dataset.

    Two of them present at once is what would be a bug: the row would be folded
    into the first survivor and then folded again into the second, and whatever
    the first gained from it would be dropped on the floor.
    """
    known = {row.id for row in dataset.dataset.shikigami}
    by_drop = {}
    for keep, drop in duplicates.PAIRS:
        if keep in known:
            by_drop.setdefault(drop, []).append(keep)
    contested = {d: k for d, k in by_drop.items() if len(k) > 1}

    assert not contested, "two live survivors for one row: %s" % contested


def test_a_pair_never_points_at_itself():
    for keep, drop in duplicates.PAIRS:
        assert keep != drop


# Two entries of the table name shikigami this build of the game does not have
# — collab figures the roster never carried. They are in the table because a
# pre-rename cache can still hold them.
ABSENT_FROM_THIS_BUILD = {"yumebiki_kochou_no_sei", "yumeyama_hakuzousu"}


def test_the_dropped_ids_are_the_ones_in_use_today(dataset):
    """The other column is the romaji id, which is what a record is called now.

    A typo here cannot be caught against a cache nobody has a copy of, but it
    can be caught against the live dataset: after the rename every dropped id
    is a real shikigami, bar the collab entries this build never had.
    """
    known = {row.id for row in dataset.dataset.shikigami}
    unknown = [d for _, d in duplicates.PAIRS
               if d not in known and d not in ABSENT_FROM_THIS_BUILD]

    assert not unknown, "dropped ids that name nothing: %s" % unknown


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


def test_no_shikigami_is_listed_under_two_records(dataset):
    """What "nothing is folded twice" has to mean now.

    It used to be spelled as "none of the dropped ids appear", which stopped
    being the same statement at migration 0011: the dropped id is the romaji
    one, and after the rename that is precisely the id every survivor has. The
    old spelling asked for 18 real records to be missing.

    The thing worth protecting was never a list of ids — it is that the
    encyclopaedia shows each figure once. That is asked directly here, by name,
    so it keeps working through any future renaming.
    """
    counts = collections.Counter(
        _same_figure(row.display_name) for row in dataset.dataset.shikigami
        if _same_figure(row.display_name)
    )
    twice = [name for name, n in counts.items() if n > 1]

    assert not twice, "listed under two records: %s" % twice


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
    raw = [row.get("id") for row in dataset._read_bundled_rows()["shikigami"]]
    paired = {i for i in raw if raw.count(i) > 1}
    loaded = [row.id for row in dataset.dataset.shikigami]

    # The bundled rows are *not* clean, and that is the current state rather
    # than a problem: migration 0011 renamed both halves of every pair onto one
    # id, so the file carries 287 rows under 269 ids. Written the other way
    # round first — asserting the raw rows held no duplicate — this went red
    # immediately, which is how the shape of the data got checked instead of
    # assumed.
    assert paired, "nothing is paired any more; the fold has stopped being used"
    assert len(loaded) == len(set(loaded)), "the fold left an id behind twice"
    for row_id in paired:
        assert loaded.count(row_id) == 1, (
            "%s went in twice and came out %d times" % (row_id,
                                                        loaded.count(row_id)))


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
