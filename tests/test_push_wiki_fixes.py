"""The script that writes the wiki fixes to Supabase.

Nothing here touches the network. What is worth testing is the part that would
be expensive to get wrong:

* **Without ``--apply``, nothing writes.** This script deletes 20 rows from a
  shared database and there is no undo. A dry run that quietly wrote would be
  the worst possible bug in it.
* **Only the columns the table has.** The local records still carry ``name_jp``,
  which migration 0009 dropped, and ``role``, which the table never had.
  PostgREST rejects the whole request for an unknown column, so one stray field
  fails the entire push.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import push_wiki_fixes as push  # noqa: E402
from wiki import additions, duplicates  # noqa: E402


# ── nothing writes without --apply ──────────────────────────────────────────


class Exploding(push.Rest):
    """A Rest whose every request fails the test if it is ever sent."""

    def _send(self, method, path, body=None, headers=None):
        raise AssertionError("sent %s %s during a dry run" % (method, path))


def test_a_dry_run_sends_no_write_request():
    rest = Exploding("https://example.invalid", "key", apply=False)

    assert rest.delete(["a", "b"]) == 0
    assert rest.patch("a", {"name_en": "x"}) == 0
    assert rest.insert([{"id": "a"}]) == 0
    assert rest.upload("k", b"x", "image/png") is False


def test_a_dry_run_still_refuses_an_empty_delete_with_apply_on():
    """An empty id list must not become "delete everything"."""
    rest = Exploding("https://example.invalid", "key", apply=True)

    assert rest.delete([]) == 0
    assert rest.insert([]) == 0


# ── the payload matches the table ───────────────────────────────────────────


@pytest.mark.parametrize("record", additions.RECORDS,
                         ids=[r["id"] for r in additions.RECORDS])
def test_every_record_becomes_exactly_the_tables_columns(record):
    row = push.row_for_db(record)

    assert set(row) == set(push.COLUMNS), (
        "extra: %s, missing: %s"
        % (sorted(set(row) - set(push.COLUMNS)),
           sorted(set(push.COLUMNS) - set(row)))
    )


@pytest.mark.parametrize("dropped", ["name_jp", "role"])
def test_the_columns_the_table_does_not_have_are_left_behind(dropped):
    """0009 dropped name_jp; role was never there. Either one fails the push."""
    assert dropped not in push.COLUMNS
    row = push.row_for_db(dict(additions.RECORDS[0]))
    assert dropped not in row


def test_the_image_becomes_a_bucket_key():
    row = push.row_for_db({"id": "x", "rarity": "ssr",
                           "image": "assets/images/shikigami/ssr/x.png"})
    assert row["image"] == "shikigami/ssr/x.png"


@pytest.mark.parametrize("given,expected", [
    ("assets/images/a/b.png", "a/b.png"),
    ("assets/a/b.png", "a/b.png"),
    ("a/b.png", "a/b.png"),
    ("https://host/a.png", "https://host/a.png"),
    ("", ""),
])
def test_bucket_key_cases(given, expected):
    assert push.bucket_key(given) == expected


def test_rarity_is_upper_cased():
    assert push.row_for_db({"id": "x", "rarity": "sp"})["rarity"] == "SP"


def test_containers_go_as_empty_not_null():
    """Matching what the repo's own uploader sends, so columns stay consistent."""
    row = push.row_for_db({"id": "x", "rarity": "SP"})
    for field in ("friendly_name", "obtain", "skills", "recommended_souls",
                  "countered_by"):
        assert row[field] == []
    for field in ("stats", "slot_mains"):
        assert row[field] == {}


# ── the work list is the app's own list ─────────────────────────────────────


def test_the_rows_to_delete_are_the_folded_half_of_each_pair():
    """One source of truth: the client patch and this script cannot disagree."""
    from_script = [drop for _keep, drop in duplicates.PAIRS]

    assert len(from_script) == 20
    assert len(set(from_script)) == 20
    assert not set(from_script) & {keep for keep, _ in duplicates.PAIRS}


def test_the_portraits_it_would_upload_all_exist():
    files = push.portrait_files()

    assert len(files) == len(additions.RECORDS)
    for key, local in files:
        assert local.is_file(), "%s -> %s missing" % (key, local)
        assert local.stat().st_size > 1024
