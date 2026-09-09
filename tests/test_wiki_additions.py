"""The shikigami typed in by hand from the game's own pages.

These records exist because no source publishes them: the Vietnamese site
stopped on 22 Apr 2026 and the fandom batch was imported once. They were read
off the game on 23 Aug 2026.

Hand-entered data earns stricter tests than imported data, because there is no
upstream to blame and no second copy to compare against. Two things matter most:

* **Upstream wins.** The day a real source publishes one of these, that is the
  version to keep. A hand-typed record that quietly overrules a published one is
  how a dataset starts drifting away from the game.
* **The pictures are really there.** An image field pointing at nothing shows an
  empty card, and nothing in the app complains about it.
"""
from __future__ import annotations

import pytest

from wiki import additions
from wiki.images import ImageResolver
from wiki.repository import WikiRepository

# Confirmed by the user against their own account, and by the game's own
# "Collected: n/n" counters on the Shikigami Tales pages.
GAME = {"SP": 50, "SSR": 62, "SR": 66, "R": 37, "N": 14}
COLLAB = frozenset("""
tanjiro_kamado nezuko_kamado zenitsu_agatsuma inosuke_hashibira gintoki_sakata
kagura_sadaharu hatsune_miku kagamine_rin_len megurine_luka sakura_kinomoto
syaoran_li natsume_nyanko_sensei inuyasha sesshoumaru kikyou ichigo_kurosaki
rukia_kuchiki nura_rikuo kusuriuri mushishi wenren_yixuan shentu_ziye hozuki
yato_no_kami peach_maki_karashi
""".split())


@pytest.fixture(scope="module")
def loaded():
    repository = WikiRepository()
    repository.load()
    return repository.dataset.shikigami


def regular(rows, rarity):
    return [r for r in rows
            if r.rarity == rarity and r.id not in COLLAB and "frog" not in r.id]


# ── the records ─────────────────────────────────────────────────────────────


def test_all_three_are_in_the_loaded_dataset(loaded):
    ids = {row.id for row in loaded}
    for record in additions.RECORDS:
        assert record["id"] in ids, "%s never made it in" % record["id"]


def test_each_one_has_its_three_skills(loaded):
    by_id = {row.id: row for row in loaded}
    for record in additions.RECORDS:
        skills = by_id[record["id"]].skills
        assert len(skills) == 3, "%s has %d skills" % (record["id"], len(skills))
        for skill in skills:
            assert skill.name
            assert skill.description
            assert len(skill.levels) == 4, (
                "%s / %s has %d level-ups, expected Lv.2 to Lv.5"
                % (record["id"], skill.name, len(skill.levels))
            )


def test_every_picture_resolves_to_a_real_file(loaded):
    """An image field pointing at nothing shows a blank card and says nothing."""
    by_id = {row.id: row for row in loaded}
    resolver = ImageResolver()
    for record in additions.RECORDS:
        row = by_id[record["id"]]
        assert resolver.local_path(row.image) is not None, (
            "no file behind %s" % row.image
        )


def test_stats_are_left_empty_rather_than_zeroed(loaded):
    """Empty says "not known"; zeros would say "measured, and zero"."""
    by_id = {row.id: row for row in loaded}
    for record in additions.RECORDS:
        stats = by_id[record["id"]].stats or {}
        values = [entry.get("value") for entry in stats.values()
                  if isinstance(entry, dict)]
        assert not any(values), "%s claims real stats" % record["id"]


# ── not overruling a real source ────────────────────────────────────────────


def roster(*extra):
    """A list big enough to be taken for the real roster. See MIN_ROSTER."""
    filler = [{"id": "filler_%d" % i} for i in range(additions.MIN_ROSTER)]
    return list(extra) + filler


def test_upstream_wins_when_it_publishes_the_same_id():
    mine = {"id": "bishamonten", "name_en": "from upstream"}
    out = additions.add_missing(roster(mine))

    kept = [r for r in out if r["id"] == "bishamonten"]
    assert kept == [mine], "the hand-typed record overruled a published one"
    added = {r["id"] for r in out} - {r["id"] for r in roster(mine)}
    assert added == {"fuzenkitsune", "ignis_suzuhikohime"}


def test_nothing_is_added_twice():
    once = additions.add_missing(roster())
    twice = additions.add_missing(once)

    assert len(twice) == len(once)


def test_the_rows_it_is_given_are_not_mutated():
    rows = roster()
    before = len(rows)
    additions.add_missing(rows)

    assert len(rows) == before


def test_something_too_small_to_be_the_roster_is_left_alone():
    """A loader fixture, an excerpt, or somebody else's data.

    Found by breaking three loader tests, which build a three-record dataset to
    check that rarity files are read and that the sync cache beats the bundle.
    Appending to those turned a test about loading into a failing count.
    """
    rows = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    assert additions.add_missing(rows) == rows


def test_no_two_records_share_an_id():
    ids = [record["id"] for record in additions.RECORDS]
    assert len(set(ids)) == len(ids)


# ── the counts these were added to fix ──────────────────────────────────────


@pytest.mark.parametrize("rarity", ["SP", "SSR", "R", "N"])
def test_the_rarities_that_should_now_match_the_game_do(loaded, rarity):
    """SR is deliberately not here: it is one over and not yet explained."""
    assert len(regular(loaded, rarity)) == GAME[rarity]


def test_sr_is_still_one_over_and_that_is_known(loaded):
    """Pinned so the open question stays visible instead of being forgotten.

    One SR record is not in the game's list and has never been identified —
    most likely a collab that reads as an ordinary youkai name, which is what
    Hozuki, Yato no Kami and Peach Maki & Karashi all turned out to be. When it
    is found, add it to COLLAB and fold this test into the one above.
    """
    assert len(regular(loaded, "SR")) == GAME["SR"] + 1


def test_the_frogs_that_were_never_imported_are_still_recorded_as_missing(loaded):
    """Two frog records the import destroyed by writing their names elsewhere."""
    ids = {row.id for row in loaded}
    assert additions.STILL_MISSING
    for frog in additions.STILL_MISSING:
        assert frog not in ids, "%s exists now — take it off STILL_MISSING" % frog
