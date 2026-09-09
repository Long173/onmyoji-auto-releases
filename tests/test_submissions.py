"""Proposed wiki edits, and the owner's approval.

No network here: the HTTP layer is stubbed, so these run offline and cannot
touch the real database. What they pin is the part that would be expensive to
get wrong.

The rules that matter most, in order:

* **A proposal is always sent as pending.** The database's RLS refuses anything
  else, and the app should agree with it rather than discover the disagreement
  as a rejected request.
* **Approval writes to the live table first, then marks the queue.** The other
  order loses the change while claiming it was applied.
* **Rejections are kept.** A queue that forgets what it refused invites the same
  argument twice.
* **Review refuses to run without a key.** The whole point of the two-step is
  that the shipped app cannot reach the live table; a review path that quietly
  fell back to the anon key would undo that.
"""
from __future__ import annotations

import json

import pytest

from wiki import submissions
from wiki.config import SupabaseConfig
from wiki.submissions import ADD, DELETE, EDIT, Submission, SubmissionError

CONFIG = SupabaseConfig(url="https://example.supabase.co", anon_key="anon-key")
SERVICE = "service-key"


class Calls(list):
    """The requests made, plus the answers to give back.

    A subclass rather than a bare list with an attribute stuck on it: a plain
    ``list`` refuses attribute assignment, which is easy to write and fails at
    the point of use rather than the point of the mistake.
    """

    def __init__(self):
        super().__init__()
        self.answers = {}


@pytest.fixture
def calls(monkeypatch):
    """Record every request the module would make, and answer them."""
    made = Calls()

    def fake(config, table, key, method="GET", params="", body=None, prefer=""):
        made.append({"table": table, "key": key, "method": method,
                     "params": params, "body": body, "prefer": prefer})
        return made.answers.get((table, method), None)

    monkeypatch.setattr(submissions, "_request", fake)
    return made


def a_payload(**extra):
    row = {"id": "ootengu", "name_vi": "Đại Thiên Cẩu", "rarity": "SSR"}
    row.update(extra)
    return row


# ── building a proposal ─────────────────────────────────────────────────────


def test_a_proposal_is_always_pending():
    """RLS refuses anything else; the app should not have to find that out."""
    row = submissions.build(ADD, a_payload())

    assert row["status"] == submissions.PENDING


def test_an_edit_must_say_what_it_edits():
    with pytest.raises(SubmissionError):
        submissions.build(EDIT, a_payload(), target_id="")


def test_a_delete_must_say_what_it_deletes():
    with pytest.raises(SubmissionError):
        submissions.build(DELETE, target_id="")


def test_a_delete_needs_no_payload():
    row = submissions.build(DELETE, target_id="ootengu")

    assert row["payload"] is None
    assert row["target_id"] == "ootengu"


def test_an_add_with_nothing_in_it_is_refused():
    with pytest.raises(SubmissionError):
        submissions.build(ADD, {})


def test_an_unknown_kind_is_refused():
    with pytest.raises(SubmissionError):
        submissions.build("drop-everything", a_payload())


def test_an_oversized_payload_is_refused_before_it_is_sent():
    """The database's guard is 20000 characters; failing here explains why."""
    huge = a_payload(lore="x" * 25000)

    with pytest.raises(SubmissionError) as caught:
        submissions.build(ADD, huge)

    assert "quá dài" in str(caught.value)


def test_the_author_is_trimmed_not_trusted():
    row = submissions.build(ADD, a_payload(), author="  " + "n" * 200)

    assert len(row["author"]) <= 80


def test_a_blank_author_becomes_null_rather_than_empty_string():
    row = submissions.build(ADD, a_payload(), author="   ")

    assert row["author"] is None


# ── sending one ─────────────────────────────────────────────────────────────


def test_submitting_uses_the_anon_key(calls):
    """The shipped app has no other key, and must need no other."""
    submissions.submit(CONFIG, submissions.build(ADD, a_payload()))

    assert calls[0]["key"] == "anon-key"
    assert calls[0]["method"] == "POST"
    assert calls[0]["table"] == submissions.TABLE


def test_submitting_never_touches_the_live_table(calls):
    submissions.submit(CONFIG, submissions.build(ADD, a_payload()))

    assert all(c["table"] != submissions.LIVE_TABLE for c in calls)


def test_submitting_asks_for_nothing_back(calls):
    """Anon has no select on the queue, so there is nothing to read."""
    submissions.submit(CONFIG, submissions.build(ADD, a_payload()))

    assert "return=minimal" in calls[0]["prefer"]


def test_submitting_without_configuration_says_so(monkeypatch):
    with pytest.raises(SubmissionError):
        submissions.submit(SupabaseConfig(), {"kind": ADD})


# ── the queue ───────────────────────────────────────────────────────────────


def test_pending_needs_the_service_key(calls):
    with pytest.raises(SubmissionError) as caught:
        submissions.pending(CONFIG, "")

    assert "service_role" in str(caught.value)
    assert calls == [], "it asked the server anyway"


def test_pending_asks_only_for_pending_rows(calls):
    submissions.pending(CONFIG, SERVICE)

    assert "status=eq.pending" in calls[0]["params"]
    assert calls[0]["key"] == SERVICE


def test_pending_reads_rows_into_submissions(calls):
    calls.answers[(submissions.TABLE, "GET")] = [
        {"id": 7, "kind": EDIT, "target_id": "ootengu",
         "payload": a_payload(), "author": "Ayu", "created_at": "2026-08-27",
         "status": "pending"},
    ]

    got = submissions.pending(CONFIG, SERVICE)

    assert len(got) == 1
    assert got[0].id == 7 and got[0].kind == EDIT
    assert got[0].payload["name_vi"] == "Đại Thiên Cẩu"
    assert got[0].is_pending


def test_a_payload_that_arrives_as_text_is_still_read():
    """jsonb comes back parsed; a text column comes back as a string."""
    row = Submission.from_row({"id": 1, "kind": ADD,
                               "payload": json.dumps(a_payload())})

    assert row.payload["id"] == "ootengu"


def test_a_payload_that_is_nonsense_becomes_empty_rather_than_crashing():
    row = Submission.from_row({"id": 1, "kind": ADD, "payload": "not json {{"})

    assert row.payload == {}


def test_a_submission_describes_itself_for_a_list():
    row = Submission.from_row({"id": 1, "kind": EDIT, "target_id": "ootengu",
                               "payload": a_payload()})

    assert "Sửa" in row.describes
    assert "Đại Thiên Cẩu" in row.describes


# ── approving ───────────────────────────────────────────────────────────────


def an_edit(**extra):
    row = {"id": 3, "kind": EDIT, "target_id": "ootengu", "payload": a_payload(),
           "status": "pending"}
    row.update(extra)
    return Submission.from_row(row)


def test_approving_needs_the_service_key(calls):
    with pytest.raises(SubmissionError):
        submissions.approve(CONFIG, "", an_edit())

    assert calls == []


def test_approving_writes_the_live_table_before_marking_the_queue(calls):
    """The other order loses the change while claiming it was applied."""
    submissions.approve(CONFIG, SERVICE, an_edit())

    tables = [c["table"] for c in calls]
    assert tables == [submissions.LIVE_TABLE, submissions.TABLE], tables


def test_approving_an_edit_keeps_the_target_id(calls):
    """A payload with a different id in it must not create a second record."""
    edit = an_edit(payload=a_payload(id="something-else"))

    submissions.approve(CONFIG, SERVICE, edit)

    assert calls[0]["body"][0]["id"] == "ootengu"


def test_approving_upserts_rather_than_duplicating(calls):
    submissions.approve(CONFIG, SERVICE, an_edit())

    assert "merge-duplicates" in calls[0]["prefer"]


def test_approving_a_delete_deletes_from_the_live_table(calls):
    delete = Submission.from_row({"id": 9, "kind": DELETE,
                                  "target_id": "ootengu", "status": "pending"})

    submissions.approve(CONFIG, SERVICE, delete)

    assert calls[0]["method"] == "DELETE"
    assert "id=eq.ootengu" in calls[0]["params"]


def test_approving_something_with_no_id_is_refused(calls):
    """Otherwise it would write a row the wiki can never look up."""
    broken = Submission.from_row({"id": 4, "kind": ADD, "payload": {"name_vi": "x"}})

    with pytest.raises(SubmissionError):
        submissions.approve(CONFIG, SERVICE, broken)

    assert all(c["table"] != submissions.TABLE for c in calls), "it marked it anyway"


def test_approving_records_when_and_what(calls):
    submissions.approve(CONFIG, SERVICE, an_edit(), note="ok")

    marked = calls[-1]
    assert marked["method"] == "PATCH"
    assert marked["body"]["status"] == submissions.APPROVED
    assert marked["body"]["reviewed_at"]
    assert marked["body"]["review_note"] == "ok"


# ── rejecting ───────────────────────────────────────────────────────────────


def test_rejecting_keeps_the_row(calls):
    """Deleting it invites the same proposal, and the same argument, again."""
    submissions.reject(CONFIG, SERVICE, 5, note="sai hết")

    assert calls[0]["method"] == "PATCH"
    assert calls[0]["body"]["status"] == submissions.REJECTED
    assert calls[0]["body"]["review_note"] == "sai hết"


def test_rejecting_never_touches_the_live_table(calls):
    submissions.reject(CONFIG, SERVICE, 5)

    assert all(c["table"] == submissions.TABLE for c in calls)


def test_rejecting_needs_the_service_key(calls):
    with pytest.raises(SubmissionError):
        submissions.reject(CONFIG, "", 5)

    assert calls == []


# ── the table not being there yet ───────────────────────────────────────────


def test_a_missing_table_says_what_to_do(monkeypatch):
    """It does not exist until the owner runs the SQL once."""
    import urllib.error

    class Fake404(urllib.error.HTTPError):
        def __init__(self):
            super().__init__("u", 404, "Not Found", {}, None)

        def read(self):
            return (b'{"message":"Could not find the table '
                    b'\'public.shikigami_submissions\'"}')

    def boom(*_a, **_k):
        raise Fake404()

    monkeypatch.setattr(submissions.urllib.request, "urlopen", boom)

    with pytest.raises(SubmissionError) as caught:
        submissions.submit(CONFIG, submissions.build(ADD, a_payload()))

    assert "bảng góp ý" in str(caught.value)

# ── the editable fields, and reading/writing them as text ───────────────────


def test_the_form_never_offers_the_nested_fields():
    """A text box cannot express a skill table, and pretending otherwise
    would let somebody flatten one by accident."""
    offered = {f.key for f in submissions.FORM_FIELDS}

    assert not offered & {"skills", "stats", "slot_mains"}


def test_the_form_covers_the_names_and_the_rarity():
    offered = {f.key for f in submissions.FORM_FIELDS}

    assert {"name_vi", "name_en", "rarity"} <= offered


def test_reading_a_row_gives_text_for_every_field():
    values = submissions.read_values(a_payload(obtain=["Hộp quà", "Sự kiện"]))

    assert values["name_vi"] == "Đại Thiên Cẩu"
    assert "Hộp quà" in values["obtain"]
    assert set(values) == {f.key for f in submissions.FORM_FIELDS}


def test_reading_a_missing_field_gives_an_empty_string_not_none():
    values = submissions.read_values({"id": "x"})

    assert all(isinstance(v, str) for v in values.values())


def test_a_list_field_is_read_one_per_line():
    values = submissions.read_values({"obtain": ["a", "b"]})

    assert values["obtain"] == "a\nb"


def test_editing_keeps_the_fields_the_form_never_showed():
    """The live write is an upsert of the whole row, so anything dropped here
    is dropped from the database."""
    row = a_payload(skills=[{"name": "s"}], stats={"hp": 1}, sort_index=42)

    edited = submissions.apply_edits(row, {"name_vi": "Tên mới"})

    assert edited["skills"] == [{"name": "s"}]
    assert edited["stats"] == {"hp": 1}
    assert edited["sort_index"] == 42
    assert edited["name_vi"] == "Tên mới"


def test_editing_does_not_change_the_row_it_was_given():
    row = a_payload()

    submissions.apply_edits(row, {"name_vi": "khác"})

    assert row["name_vi"] == "Đại Thiên Cẩu"


def test_a_list_field_accepts_lines_or_commas():
    edited = submissions.apply_edits({}, {"obtain": "a\nb , c"})

    assert edited["obtain"] == ["a", "b", "c"]


def test_a_blank_list_field_becomes_an_empty_list():
    edited = submissions.apply_edits({}, {"obtain": "   "})

    assert edited["obtain"] == []


def test_text_is_trimmed():
    edited = submissions.apply_edits({}, {"name_vi": "  Tên  "})

    assert edited["name_vi"] == "Tên"


def test_an_unknown_key_is_ignored_rather_than_written():
    """The form is the only thing allowed to set columns here."""
    edited = submissions.apply_edits({}, {"status": "approved", "name_vi": "x"})

    assert "status" not in edited


# ── reading the live row before editing it ─────────────────────────────────


def test_fetching_the_live_row_uses_the_anon_key(calls):
    calls.answers[(submissions.LIVE_TABLE, "GET")] = [a_payload()]

    row = submissions.fetch_live(CONFIG, "ootengu")

    assert calls[0]["key"] == "anon-key"
    assert calls[0]["table"] == submissions.LIVE_TABLE
    assert "id=eq.ootengu" in calls[0]["params"]
    assert row["name_vi"] == "Đại Thiên Cẩu"


def test_fetching_a_row_that_is_not_there_says_so(calls):
    calls.answers[(submissions.LIVE_TABLE, "GET")] = []

    with pytest.raises(SubmissionError):
        submissions.fetch_live(CONFIG, "khong-co")


def test_a_service_role_key_is_told_apart_from_the_anon_one():
    """Pasting the anon key into the review box would otherwise look like a
    server refusal rather than the mistake it is."""
    anon = _jwt({"role": "anon"})
    service = _jwt({"role": "service_role"})

    assert submissions.looks_like_service_key(service)
    assert not submissions.looks_like_service_key(anon)


def test_a_key_that_is_not_a_token_at_all_is_refused():
    assert not submissions.looks_like_service_key("hello")
    assert not submissions.looks_like_service_key("")


def _jwt(payload):
    import base64

    def seg(obj):
        raw = json.dumps(obj).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    return "%s.%s.signature" % (seg({"alg": "HS256"}), seg(payload))


# ── columns the database will not accept ────────────────────────────────────
#
# Checked against the live schema, not guessed: `shikigami` has 22 columns, of
# which `name_vi_unaccent`, `name_en_unaccent` and `friendly_name_unaccent` are
# GENERATED ALWAYS (migration 0004/0006) and reject any write. `name_jp` was
# dropped outright in migration 0009. Sending any of them fails the whole
# upsert, so a proposal must not carry them and the form must not offer one.


def a_live_row(**extra):
    """The shape the server actually returns."""
    row = {
        "id": "cat_diep", "name_vi": "Cát Diệp", "name_en": "Kuzunoha",
        "rarity": "SSR", "friendly_name": ["Cáo"], "obtain": [],
        "description": "", "lore": "", "image": "", "source_url": "",
        "countered_by": [], "recommended_souls": [], "sort_index": 3,
        "skills": [{"name": "s"}], "stats": {"hp": 1}, "slot_mains": {},
        "is_finish": True,
        "name_vi_unaccent": "cat diep", "name_en_unaccent": "kuzunoha",
        "friendly_name_unaccent": "cao",
        "created_at": "2025-01-01T00:00:00Z", "updated_at": "2025-06-01T00:00:00Z",
    }
    row.update(extra)
    return row


def test_the_form_does_not_offer_a_column_that_was_dropped():
    """`name_jp` went away in migration 0009; offering it would fail the write."""
    assert "name_jp" not in {f.key for f in submissions.FORM_FIELDS}


def test_a_generated_column_never_reaches_a_proposal():
    row = submissions.build(EDIT, a_live_row(), target_id="cat_diep")

    for column in ("name_vi_unaccent", "name_en_unaccent", "friendly_name_unaccent"):
        assert column not in row["payload"], column


def test_the_timestamps_are_left_to_the_database():
    """`created_at` must survive an update and `updated_at` has a trigger."""
    row = submissions.build(EDIT, a_live_row(), target_id="cat_diep")

    assert "created_at" not in row["payload"]
    assert "updated_at" not in row["payload"]


def test_the_columns_that_are_writable_do_survive():
    row = submissions.build(EDIT, a_live_row(), target_id="cat_diep")

    payload = row["payload"]
    assert payload["skills"] == [{"name": "s"}]
    assert payload["stats"] == {"hp": 1}
    assert payload["is_finish"] is True
    assert payload["sort_index"] == 3


def test_approving_an_older_proposal_still_strips_them(calls):
    """A proposal queued by an earlier build may carry them; approving it must
    not fail the whole upsert because of a column nobody chose to send."""
    stale = Submission.from_row({"id": 8, "kind": EDIT, "target_id": "cat_diep",
                                 "payload": a_live_row(), "status": "pending"})

    submissions.approve(CONFIG, SERVICE, stale)

    written = calls[0]["body"][0]
    assert "name_vi_unaccent" not in written
    assert "updated_at" not in written


def test_stripping_leaves_the_row_it_was_given_alone():
    row = a_live_row()

    submissions.writable(row)

    assert "name_vi_unaccent" in row


def test_a_proposal_with_no_id_is_refused_before_it_is_queued():
    """approve() cannot write a row with no primary key, so such a proposal is
    one the owner could only ever reject."""
    with pytest.raises(SubmissionError) as caught:
        submissions.build(ADD, {"name_vi": "Ai đó"})

    assert "mã" in str(caught.value)


def test_an_edit_still_needs_an_id_in_the_payload():
    with pytest.raises(SubmissionError):
        submissions.build(EDIT, {"name_vi": "Ai đó"}, target_id="ootengu")


# ── telling the two kinds of key apart ──────────────────────────────────────
#
# Supabase issues two shapes. The legacy pair are JWTs carrying `role`; the
# current pair are opaque strings that say what they are in the prefix:
# `sb_publishable_…` is meant to ship inside a client, `sb_secret_…` is not.
# A check that knew only about JWTs refused a perfectly good modern secret key
# and left the review window permanently locked.


def test_a_modern_secret_key_is_recognised():
    assert submissions.looks_like_service_key("sb_secret_" + "x" * 40)


def test_a_modern_publishable_key_is_not_a_secret_one():
    """It is the one that ships inside the app; treating it as the review key
    would turn a permission error into a mystery."""
    assert not submissions.looks_like_service_key("sb_publishable_" + "x" * 40)


def test_the_legacy_jwt_pair_still_works():
    assert submissions.looks_like_service_key(_jwt({"role": "service_role"}))
    assert not submissions.looks_like_service_key(_jwt({"role": "anon"}))


def test_a_prefix_with_nothing_after_it_is_not_a_key():
    assert not submissions.looks_like_service_key("sb_secret_")


# ── a build that needs no setting up ────────────────────────────────────────
#
# This is a tool handed to a game community. Asking every user to paste
# credentials before they can read a wiki page is not a security measure; the
# publishable key is meant to ship, and row-level security is what limits it.


def test_a_build_with_nothing_configured_still_works(monkeypatch, tmp_path):
    from wiki import config as wiki_config

    monkeypatch.setattr(wiki_config, "ENV_FILES", (tmp_path / "nope.env",))
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)

    resolved = wiki_config.resolve()

    assert resolved.is_configured, "a shipped build would demand a login"


def test_the_bundled_key_is_the_publishable_one():
    """Never the secret one. The whole design rests on this."""
    from wiki import config as wiki_config

    assert wiki_config.BUNDLED_ANON_KEY.startswith("sb_publishable_")
    assert not submissions.looks_like_service_key(wiki_config.BUNDLED_ANON_KEY)


def test_what_the_user_typed_still_wins(monkeypatch, tmp_path):
    """A fork pointing at its own project must not be overruled by ours."""
    from wiki import config as wiki_config

    monkeypatch.setattr(wiki_config, "ENV_FILES", (tmp_path / "nope.env",))
    mine = SupabaseConfig(url="https://mine.supabase.co", anon_key="sb_publishable_mine")

    assert wiki_config.resolve(mine) == mine


def test_an_env_file_still_wins(monkeypatch, tmp_path):
    from wiki import config as wiki_config

    env = tmp_path / ".env"
    env.write_text("SUPABASE_URL=https://theirs.supabase.co\n"
                   "SUPABASE_ANON_KEY=sb_publishable_theirs\n", encoding="utf-8")
    monkeypatch.setattr(wiki_config, "ENV_FILES", (env,))

    assert wiki_config.resolve().url == "https://theirs.supabase.co"


def test_no_secret_key_is_bundled():
    """The one key that must never ship. If this ever fails, rotate it.

    Looks for the *shape* of a secret key, not the word: the file talks about
    service_role at length on purpose, and a test that tripped over its own
    documentation would be turned off the first time it cried wolf.
    """
    import re
    from pathlib import Path

    import wiki.config as wiki_config

    source = Path(wiki_config.__file__).read_text(encoding="utf-8")

    assert "sb_secret_" not in source, "a modern secret key is in the source"
    # A legacy service_role key is a JWT: three long base64 segments.
    message = "a legacy JWT key is in the source"
    assert not re.search(r"eyJ[A-Za-z0-9_-]{20,}[.][A-Za-z0-9_-]{20,}", source), message


# ── the id is generated, not typed ──────────────────────────────────────────
#
# It is the primary key: approving an `add` upserts on it, so a typo makes a
# second record and a collision silently overwrites somebody else's. Asking a
# contributor to invent one was asking them to get a database key right.
#
# The rule is read off the data rather than invented. Of the 99 live records
# that have a Vietnamese name, 95 already have exactly the id this produces;
# the other four were named after their Japanese form years ago.


def test_the_ordinary_case():
    assert submissions.slugify("Đại Thiên Cẩu") == "dai_thien_cau"


def test_diacritics_are_stripped_not_replaced():
    assert submissions.slugify("Cát Diệp") == "cat_diep"
    assert submissions.slugify("Thần Vô Nguyệt") == "than_vo_nguyet"


def test_the_letter_d_with_a_stroke():
    """NFD leaves đ alone — it is a letter, not a letter plus an accent."""
    assert submissions.slugify("Chước Hoa Đào Hoa Yêu") == "chuoc_hoa_dao_hoa_yeu"


def test_an_alternate_name_in_brackets_is_dropped():
    """Matches the stored id for the one live record shaped like this."""
    assert submissions.slugify(
        "Linh Ngạn Cơ (Suzuhiko Hime)/Linda") == "linh_ngan_co"


def test_a_slash_separated_alternate_is_dropped():
    assert submissions.slugify("Tên Chính/Tên Khác") == "ten_chinh"


def test_punctuation_becomes_one_separator():
    assert submissions.slugify("A  --  B") == "a_b"


def test_it_does_not_start_or_end_with_a_separator():
    assert submissions.slugify("  !Tên!  ") == "ten"


def test_a_very_long_name_is_cut_at_a_word():
    got = submissions.slugify("Một " * 40)

    assert len(got) <= submissions.MAX_ID_CHARS
    assert not got.endswith("_")


def test_a_name_with_nothing_usable_gives_nothing():
    """The caller has to notice and say so, rather than send an empty key."""
    assert submissions.slugify("???") == ""
    assert submissions.slugify("") == ""
    assert submissions.slugify(None) == ""


def test_the_form_no_longer_offers_an_id_box():
    assert "id" not in {f.key for f in submissions.FORM_FIELDS}


def test_editing_never_touches_the_id():
    """Changing it would not rename anything — it would write a second record
    and leave the first behind."""
    edited = submissions.apply_edits({"id": "ootengu", "name_vi": "x"},
                                     {"name_vi": "Tên mới", "id": "khac"})

    assert edited["id"] == "ootengu"


# ── skills ──────────────────────────────────────────────────────────────────
#
# Left out of the form at first, on the grounds that a text box cannot express a
# skill table. True, but it left a hole with no bottom: a *new* shikigami could
# never be given skills at all, and skills are most of what a record is.
#
# The thing that would quietly destroy data here is the half of a skill the form
# does not show. 784 skills on the server carry `image`, 139 carry `cost`, 22
# carry `effects` and `alt_forms`. None of those have a box, and approving an
# edit upserts the whole row — so anything dropped here is dropped from the
# database.


def a_skill(**extra):
    skill = {
        "name": "THỜI TỊCH CHI QUỸ",
        "image": "skills/5831.webp",
        "description": "Tấn công mục tiêu gây 100% sát thương",
        "levels": [{"level": 1, "description": "100%"},
                   {"level": 2, "description": "105%"}],
        "cost": 3,
        "effects": ["stun"],
        "alt_forms": [{"name": "khác"}],
    }
    skill.update(extra)
    return skill


def test_reading_skills_out_of_a_row():
    got = submissions.read_skills({"skills": [a_skill()]})

    assert len(got) == 1
    assert got[0]["name"] == "THỜI TỊCH CHI QUỸ"
    assert len(got[0]["levels"]) == 2


def test_reading_skills_from_a_row_that_has_none():
    assert submissions.read_skills({}) == []
    assert submissions.read_skills({"skills": None}) == []


def test_reading_does_not_share_state_with_the_row():
    """The working copy is edited in place; the row must not follow."""
    row = {"skills": [a_skill()]}

    got = submissions.read_skills(row)
    got[0]["name"] = "đổi"
    got[0]["levels"][0]["description"] = "đổi"

    assert row["skills"][0]["name"] == "THỜI TỊCH CHI QUỸ"
    assert row["skills"][0]["levels"][0]["description"] == "100%"


def test_a_skill_that_arrives_as_nonsense_is_dropped():
    got = submissions.read_skills({"skills": [a_skill(), "not a skill", None]})

    assert len(got) == 1


def test_cleaning_keeps_the_fields_the_form_never_showed():
    """784 skills carry an image, 139 a cost, 22 effects and alt_forms."""
    cleaned = submissions.clean_skills([a_skill()])

    assert cleaned[0]["image"] == "skills/5831.webp"
    assert cleaned[0]["cost"] == 3
    assert cleaned[0]["effects"] == ["stun"]
    assert cleaned[0]["alt_forms"] == [{"name": "khác"}]


def test_cleaning_leaves_the_stored_level_numbers_alone():
    """Renumbering by position looked tidy and was wrong.

    Ten skills on the server carry two concatenated forms and are numbered
    ``1,2,3,4,5,2,3,4,5``. Positional renumbering turned that into ``1..9``,
    which is not a shape the game has — measured, not imagined.
    """
    shape = [{"level": n, "description": str(n)}
             for n in (1, 2, 3, 4, 5, 2, 3, 4, 5)]

    cleaned = submissions.clean_skills([a_skill(levels=shape)])

    assert [lv["level"] for lv in cleaned[0]["levels"]] == [1, 2, 3, 4, 5, 2, 3, 4, 5]


def test_a_level_with_no_number_is_given_the_next_one():
    """Only a row that arrived without one — a level just added in the editor."""
    cleaned = submissions.clean_skills([a_skill(levels=[
        {"level": 2, "description": "a"},
        {"description": "b"},
    ])])

    assert [lv["level"] for lv in cleaned[0]["levels"]] == [2, 3]


def test_cleaning_drops_a_level_with_nothing_in_it():
    cleaned = submissions.clean_skills([a_skill(levels=[
        {"level": 1, "description": "a"},
        {"level": 2, "description": "   "},
    ])])

    assert len(cleaned[0]["levels"]) == 1


def test_cleaning_drops_a_skill_with_no_name():
    """An unnamed skill is a row somebody added and then thought better of."""
    cleaned = submissions.clean_skills([a_skill(name="  "), a_skill()])

    assert len(cleaned) == 1


def test_cleaning_trims_text():
    cleaned = submissions.clean_skills([a_skill(name="  Tên  ")])

    assert cleaned[0]["name"] == "Tên"


def test_a_blank_skill_has_the_usual_five_levels():
    """Five is what the data has: 1501 levels across 784 skills."""
    blank = submissions.blank_skill()

    assert [lv["level"] for lv in blank["levels"]] == [1, 2, 3, 4, 5]
    assert blank["name"] == ""


def test_a_blank_skill_survives_a_round_trip_as_nothing():
    """Adding a skill row and then not filling it in must not send an empty one."""
    assert submissions.clean_skills([submissions.blank_skill()]) == []


# ── level 1 is the description ──────────────────────────────────────────────
#
# Measured on the server: of the 291 skills that have a level 1, 290 have it
# character-for-character identical to the skill's own description, and the
# odd one out differs by two characters near the end. So level 1 is not a
# separate fact — it is the description, written twice.
#
# The editor therefore shows levels from 2 up, and level 1 follows the
# description box. Two boxes for one sentence is an invitation for them to
# drift, and the one that would have been left behind is the one the reader of
# a level table sees.


def test_level_one_follows_the_description():
    cleaned = submissions.clean_skills([a_skill(
        description="Mô tả mới",
        levels=[{"level": 1, "description": "cũ"},
                {"level": 2, "description": "105%"}])])

    assert cleaned[0]["levels"][0]["description"] == "Mô tả mới"


def test_a_skill_with_no_levels_is_not_given_one():
    """484 skills on the server have no levels at all; an edit must not invent
    a level table for them."""
    cleaned = submissions.clean_skills([a_skill(levels=[])])

    assert cleaned[0]["levels"] == []


def test_a_skill_numbered_from_two_is_left_that_way():
    """Nine skills are shaped (2, 3, 4, 5). Adding a level 1 would be a change
    nobody asked for."""
    cleaned = submissions.clean_skills([a_skill(levels=[
        {"level": 2, "description": "a"}, {"level": 3, "description": "b"}])])

    assert [lv["level"] for lv in cleaned[0]["levels"]] == [2, 3]


def test_level_one_goes_when_the_description_does():
    """Nothing should be left claiming to be level 1 with nothing in it."""
    cleaned = submissions.clean_skills([a_skill(
        description="  ",
        levels=[{"level": 1, "description": "cũ"},
                {"level": 2, "description": "105%"}])])

    assert [lv["level"] for lv in cleaned[0]["levels"]] == [2]


def test_a_blank_skill_has_level_one_and_four_more():
    """The shape 271 of the server's skills have: 1 through 5."""
    blank = submissions.blank_skill()

    assert [lv["level"] for lv in blank["levels"]] == [1, 2, 3, 4, 5]


def test_the_editable_levels_of_a_skill_skip_level_one():
    skill = a_skill(levels=[{"level": 1, "description": "x"},
                            {"level": 2, "description": "y"},
                            {"level": 3, "description": "z"}])

    assert [lv["level"] for lv in submissions.editable_levels(skill)] == [2, 3]


def test_a_skill_numbered_from_two_is_fully_editable():
    skill = a_skill(levels=[{"level": 2, "description": "y"}])

    assert [lv["level"] for lv in submissions.editable_levels(skill)] == [2]


# ── settling several at once ────────────────────────────────────────────────
#
# Fifteen proposals arrived from one batch of work, and one confirmation dialog
# per row is enough friction that people stop reading them — which costs more
# review than it buys. The answer is to act on a *selection*, so choosing what
# to apply is still a deliberate act, and to keep every guarantee of the single
# case: the live table first, the queue second, and a failure that stops nothing
# else.


def three_edits():
    return [Submission.from_row({"id": n, "kind": EDIT, "target_id": "r%d" % n,
                                 "payload": {"id": "r%d" % n, "name_vi": "x"},
                                 "status": "pending"})
            for n in (1, 2, 3)]


def test_applying_several_applies_each(calls):
    done = submissions.apply_many(CONFIG, SERVICE, three_edits())

    assert [row.id for row in done.applied] == [1, 2, 3]
    assert done.failures == []


def test_each_one_writes_the_live_table_before_its_queue_row(calls):
    submissions.apply_many(CONFIG, SERVICE, three_edits())

    tables = [c["table"] for c in calls]
    assert tables == [submissions.LIVE_TABLE, submissions.TABLE] * 3, tables


def test_one_failure_does_not_stop_the_others(monkeypatch, calls):
    """A batch that gives up halfway leaves the queue half-settled and says
    nothing about which half."""
    def fussy(config, table, key, method="GET", params="", body=None, prefer=""):
        if table == submissions.LIVE_TABLE and "r2" in str(body):
            raise SubmissionError("server bận")
        return None

    monkeypatch.setattr(submissions, "_request", fussy)

    done = submissions.apply_many(CONFIG, SERVICE, three_edits())

    assert [row.id for row in done.applied] == [1, 3]
    assert [row.id for row, _ in done.failures] == [2]


def test_a_failure_says_why(monkeypatch, calls):
    def boom(*_a, **_k):
        raise SubmissionError("hết quyền")

    monkeypatch.setattr(submissions, "_request", boom)

    done = submissions.apply_many(CONFIG, SERVICE, three_edits())

    assert done.applied == []
    assert all("hết quyền" in reason for _row, reason in done.failures)


def test_applying_none_is_not_an_error(calls):
    done = submissions.apply_many(CONFIG, SERVICE, [])

    assert done.applied == [] and done.failures == []
    assert calls == []


def test_applying_needs_the_service_key(calls):
    with pytest.raises(SubmissionError):
        submissions.apply_many(CONFIG, "", three_edits())

    assert calls == []


def test_rejecting_several_keeps_them_all(calls):
    done = submissions.reject_many(CONFIG, SERVICE, three_edits(), note="trùng")

    assert [row.id for row in done.applied] == [1, 2, 3]
    assert all(c["table"] == submissions.TABLE for c in calls)
    assert all(c["body"]["status"] == submissions.REJECTED for c in calls)


def test_rejecting_several_never_touches_the_live_table(calls):
    submissions.reject_many(CONFIG, SERVICE, three_edits())

    assert all(c["table"] != submissions.LIVE_TABLE for c in calls)


# ── when a proposal was made ────────────────────────────────────────────────
#
# Postgres stores `timestamptz` and PostgREST serialises it in UTC. The window
# printed that string as it arrived, so a proposal sent at 18:49 in Vietnam was
# listed as 11:49 — reported as "it is 6pm, why does the queue say 11am".
#
# Seven hours is enough to put a submission on the wrong day, and the reviewer
# has no way to tell which reading they are looking at.


def test_the_same_instant_reads_the_same_however_it_was_written():
    """The real property: an offset is not part of when something happened."""
    as_utc = Submission.from_row({"id": 1, "kind": ADD,
                                  "created_at": "2026-08-28T11:49:00+00:00"})
    as_local = Submission.from_row({"id": 1, "kind": ADD,
                                    "created_at": "2026-08-28T18:49:00+07:00"})

    assert as_utc.when == as_local.when


def test_a_z_suffix_is_understood():
    """PostgREST writes one shape; other tools write the other."""
    zulu = Submission.from_row({"id": 1, "kind": ADD,
                                "created_at": "2026-08-28T11:49:00Z"})
    offset = Submission.from_row({"id": 1, "kind": ADD,
                                  "created_at": "2026-08-28T11:49:00+00:00"})

    assert zulu.when == offset.when


def test_microseconds_do_not_break_it():
    row = Submission.from_row({"id": 1, "kind": ADD,
                               "created_at": "2026-08-28T11:49:00.123456+00:00"})

    assert row.when


def test_it_is_shown_in_local_time():
    import datetime

    row = Submission.from_row({"id": 1, "kind": ADD,
                               "created_at": "2026-08-28T11:49:00+00:00"})
    expected = (datetime.datetime(2026, 8, 28, 11, 49,
                                  tzinfo=datetime.timezone.utc)
                .astimezone().strftime("%Y-%m-%d %H:%M"))

    assert row.when == expected


def test_a_timestamp_with_no_zone_is_read_as_utc():
    """Which is what the server means when it omits one."""
    import datetime

    row = Submission.from_row({"id": 1, "kind": ADD,
                               "created_at": "2026-08-28T11:49:00"})
    expected = (datetime.datetime(2026, 8, 28, 11, 49,
                                  tzinfo=datetime.timezone.utc)
                .astimezone().strftime("%Y-%m-%d %H:%M"))

    assert row.when == expected


def test_nothing_stays_nothing():
    assert Submission.from_row({"id": 1, "kind": ADD}).when == ""


def test_something_unreadable_is_shown_as_it_arrived():
    """Better a stamp nobody can parse than a blank where a date should be."""
    row = Submission.from_row({"id": 1, "kind": ADD, "created_at": "hôm qua"})

    assert row.when == "hôm qua"
