"""Wiki search, model parsing and repository queries.

Runs without the network and without the Flutter checkout: every test builds its
own rows, except the one that opts in to the real dataset when it is present.
"""
from __future__ import annotations

import json

import pytest

import paths
from wiki.config import SupabaseConfig, read_env_file, resolve
from wiki.images import ImageResolver
from wiki.models import Effect, Shikigami, Soul
from wiki.repository import BUNDLED, WikiRepository
from wiki.search import matches, normalize

# ── search ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Đại Thiên Cẩu", "dai thien cau"),
        ("Ibaraki Đồng Tử", "ibaraki dong tu"),
        ("Tư Kim Thần", "tu kim than"),
        ("MÁU XÁM", "mau xam"),
        ("  nhiều   khoảng  trắng ", "nhieu khoang trang"),
        ("", ""),
    ],
)
def test_normalize_strips_vietnamese_accents(raw, expected):
    assert normalize(raw) == expected


def test_d_with_stroke_is_handled():
    """Đ has no Unicode decomposition, so stripping marks alone misses it."""
    assert "d" in normalize("Đ")
    assert "đ" not in normalize("Đồng")


def test_matching_ignores_term_order():
    haystack = "Ibaraki Đồng Tử"
    assert matches("dong tu ibaraki", haystack)
    assert matches("IBARAKI", haystack)
    assert not matches("ibaraki seimei", haystack)


def test_empty_query_matches_everything():
    assert matches("", "bất kỳ")
    assert matches("   ", "bất kỳ")


# ── models ──────────────────────────────────────────────────────────────────


def test_shikigami_parses_a_scraped_row():
    record = Shikigami.from_row({
        "id": "tu_kim_than",
        "name_vi": "Tư Kim Thần",
        "name_jp": "Omoikane",
        "rarity": "ssr",
        "stats": {"hp": {"value": 11279}, "attack": {"value": 3377},
                  "crit_rate": {"value": 0}, "crit_dmg": {"value": 150}},
        "skills": [{"name": "DIỄM ĐỒ", "description": "Tấn công.",
                    "levels": [{"level": 1}, {"level": 2}]}],
        "image": "assets/images/shikigami/ssr/tu_kim_than.webp",
    })

    assert record.display_name == "Tư Kim Thần"
    assert record.secondary_name == "Omoikane"
    assert record.rarity == "SSR", "rarity should be upper-cased"
    assert len(record.skills[0].levels) == 2
    # Zero-valued stats are dropped; percentages keep their sign.
    assert record.stat_rows == [
        ("Sinh mệnh", "11 279"),
        ("Tấn công", "3 377"),
        ("ST bạo kích", "150%"),
    ]


def test_skill_levels_are_listed_without_repeating_the_summary():
    """Level 1 restates the skill description in nearly every record."""
    skill = Shikigami.from_row({
        "id": "x",
        "skills": [{
            "name": "DỰC KÍCH",
            "description": "Triệu hồi 1 con Dơi.",
            "levels": [
                {"level": 1, "description": "Triệu hồi 1 con Dơi."},
                {"level": 2, "description": "Sát thương = 80%"},
                {"level": 3, "description": "Sát thương = 85%"},
            ],
        }],
    }).skills[0]

    assert skill.level_rows == [
        ("Cấp 2", "Sát thương = 80%"),
        ("Cấp 3", "Sát thương = 85%"),
    ], "level 1 was printed twice, or a level went missing"


def test_a_level_that_differs_from_the_summary_is_kept():
    skill = Shikigami.from_row({
        "id": "x",
        "skills": [{
            "name": "K", "description": "Tóm tắt.",
            "levels": [{"level": 1, "description": "Khác hẳn tóm tắt."}],
        }],
    }).skills[0]

    assert skill.level_rows == [("Cấp 1", "Khác hẳn tóm tắt.")]


def test_levels_without_text_are_skipped():
    skill = Shikigami.from_row({
        "id": "x",
        "skills": [{
            "name": "K", "description": "Tóm tắt.",
            "levels": [{"level": 2, "description": "  "}, {"level": 3}],
        }],
    }).skills[0]

    assert skill.level_rows == []


def test_a_skill_with_no_levels_has_no_rows():
    skill = Shikigami.from_row({
        "id": "x", "skills": [{"name": "K", "description": "Chỉ có mô tả."}],
    }).skills[0]

    assert skill.level_rows == []


def test_skill_keeps_its_icon_path():
    skill = Shikigami.from_row({
        "id": "x",
        "skills": [{"name": "K", "image": "assets/images/skills/6001.webp"}],
    }).skills[0]

    assert skill.image == "assets/images/skills/6001.webp"


def test_slot_mains_are_translated_not_dumped_raw():
    """The field is {"2": ["atk_pct", ...]}; printing it raw showed Python lists."""
    record = Shikigami.from_row({
        "id": "x",
        "slot_mains": {
            "6": ["crit_pct", "crit_dmg_pct"],
            "2": ["atk_pct", "spd", "hp_pct"],
            "4": ["def_pct"],
        },
    })

    assert record.slot_main_rows == [
        ("Vị trí 2", "Tấn công % / Tốc độ / Sinh mệnh %"),
        ("Vị trí 4", "Phòng thủ %"),
        ("Vị trí 6", "Bạo kích / ST bạo kích"),
    ], "slot mains are out of order or still showing internal codes"


def test_slot_mains_sort_numerically():
    record = Shikigami.from_row({"id": "x", "slot_mains": {"10": ["spd"], "2": ["spd"]}})
    assert [caption for caption, _ in record.slot_main_rows] == ["Vị trí 2", "Vị trí 10"]


def test_slot_mains_accept_a_bare_string():
    record = Shikigami.from_row({"id": "x", "slot_mains": {"2": "spd"}})
    assert record.slot_main_rows == [("Vị trí 2", "Tốc độ")]


def test_unknown_slot_codes_are_tidied_rather_than_dropped():
    record = Shikigami.from_row({"id": "x", "slot_mains": {"2": ["effect_hit_pct"]}})
    assert record.slot_main_rows == [("Vị trí 2", "Effect hit %")]


def test_empty_slot_mains_produce_no_rows():
    assert Shikigami.from_row({"id": "x"}).slot_main_rows == []
    assert Shikigami.from_row({"id": "x", "slot_mains": {"2": []}}).slot_main_rows == []


def test_shikigami_falls_back_when_the_vietnamese_name_is_missing():
    record = Shikigami.from_row({"id": "tsuchigumo", "name_en": "Tsuchigumo"})
    assert record.display_name == "Tsuchigumo"

    bare = Shikigami.from_row({"id": "only_id"})
    assert bare.display_name == "only_id"


def test_shikigami_tolerates_a_completely_empty_row():
    record = Shikigami.from_row({})
    assert record.stat_rows == []
    assert record.friendly_name == []
    assert record.display_name == ""


def test_soul_orders_effects_by_piece_count():
    record = Soul.from_row({
        "id": "binh_bo", "name_vi": "Binh Bộ", "name_en": "Hyosube", "kind": "normal",
        "effects": [{"pieces": 4, "description": "Bốn món."},
                    {"pieces": 2, "description": "Hai món."}],
    })

    assert [e.pieces for e in record.effects] == [2, 4]
    assert record.effects[0].tier_label == "2 món"
    assert record.summary == "Hai món."
    assert record.kind_label == "Ngự hồn thường"


def test_effect_kind_label():
    assert Effect.from_row({"id": "x", "kind": "buff"}).kind_label == "Tăng ích"
    assert Effect.from_row({"id": "x", "kind": "debuff"}).kind_label == "Bất lợi"
    assert Effect.from_row({"id": "x"}).kind_label == "Khác"


# ── repository ──────────────────────────────────────────────────────────────


@pytest.fixture
def repo(tmp_path):
    """A repository backed by a small dataset written to a temp directory."""
    data_dir = tmp_path / "data"
    (data_dir / "shikigami").mkdir(parents=True)

    (data_dir / "shikigami" / "ssr.json").write_text(json.dumps([
        {"id": "thien_cau", "name_vi": "Đại Thiên Cẩu", "rarity": "SSR",
         "name_jp": "Daitengu", "recommended_souls": ["ban_nguyet"],
         "countered_by": ["Diệu Thủ"]},
        {"id": "ibaraki", "name_vi": "Ibaraki Đồng Tử", "rarity": "SSR",
         "friendly_name": ["Ibaraki"]},
    ]), encoding="utf-8")
    (data_dir / "shikigami" / "sr.json").write_text(json.dumps([
        {"id": "dieu_thu", "name_vi": "Diệu Thủ", "rarity": "SR"},
    ]), encoding="utf-8")
    (data_dir / "souls.json").write_text(json.dumps([
        {"id": "ban_nguyet", "name_vi": "Bán Nguyệt", "kind": "normal",
         "effects": [{"pieces": 2, "description": "Tăng 15% sát thương."}]},
    ]), encoding="utf-8")
    (data_dir / "effects.json").write_text(json.dumps([
        {"id": "choang", "name": "Choáng", "en_name": "Stun", "kind": "debuff",
         "description": "Mất lượt."},
    ]), encoding="utf-8")

    repository = WikiRepository(data_dir)
    repository.cache_dir = tmp_path / "cache"
    repository.load()
    return repository


def test_loads_every_rarity_file(repo):
    assert repo.dataset.source == BUNDLED
    assert repo.dataset.counts == {"shikigami": 3, "souls": 1, "effects": 1}


def test_records_sort_by_rarity_then_name(repo):
    # SSR outranks SR, so Diệu Thủ comes last.
    assert [s.id for s in repo.dataset.shikigami][-1] == "dieu_thu"


def test_rarity_filter_combines_with_search(repo):
    assert len(repo.shikigami(rarity="SSR")) == 2
    assert len(repo.shikigami(rarity="SR")) == 1
    assert len(repo.shikigami()) == 3

    narrowed = repo.shikigami(rarity="SSR", query="ibaraki")
    assert [s.id for s in narrowed] == ["ibaraki"]
    assert repo.shikigami(rarity="SR", query="ibaraki") == []


def test_accent_free_search_finds_records(repo):
    assert [s.id for s in repo.shikigami(query="dai thien cau")] == ["thien_cau"]
    assert [s.id for s in repo.shikigami(query="IBARAKI")] == ["ibaraki"]
    assert repo.shikigami(query="khong ton tai") == []


def test_search_matches_a_nickname(repo):
    """friendly_name is why "Ibaraki" alone finds "Ibaraki Đồng Tử"."""
    assert [s.id for s in repo.shikigami(query="ibaraki")] == ["ibaraki"]


def test_cross_links_resolve_by_id_and_by_name(repo):
    thien_cau = repo.shikigami_by_id("thien_cau")

    souls = repo.souls_using(thien_cau)
    assert [s.id for s in souls] == ["ban_nguyet"], "id reference did not resolve"

    counter = repo.resolve_shikigami("Diệu Thủ")
    assert counter is not None and counter.id == "dieu_thu", "name reference failed"


def test_reverse_link_finds_users_of_a_soul(repo):
    soul = repo.soul_by_id("ban_nguyet")
    assert [s.id for s in repo.shikigami_using(soul)] == ["thien_cau"]


def test_global_search_spans_all_three_collections(repo):
    types = {row["type"] for row in repo.search_everything("choang")}
    assert types == {"Hiệu ứng"}

    results = repo.search_everything("ban nguyet")
    assert results and results[0]["kind"] == "soul"


def test_global_search_is_empty_for_a_blank_query(repo):
    assert repo.search_everything("   ") == []


def test_missing_data_directory_yields_an_empty_dataset(tmp_path):
    repository = WikiRepository(tmp_path / "nope")
    repository.cache_dir = tmp_path / "cache"
    dataset = repository.load()

    assert dataset.is_empty
    assert dataset.describe_source() == "Chưa có dữ liệu"


def test_sync_cache_is_preferred_over_bundled_data(repo, tmp_path):
    """A cached sync wins on the next load, and reports when it happened."""
    repo.cache_dir.mkdir(parents=True, exist_ok=True)
    (repo.cache_dir / "shikigami.json").write_text(
        json.dumps([{"id": "moi", "name_vi": "Mới", "rarity": "SP"}]), encoding="utf-8"
    )
    for name in ("souls", "effects"):
        (repo.cache_dir / ("%s.json" % name)).write_text("[]", encoding="utf-8")
    (repo.cache_dir / "meta.json").write_text(
        json.dumps({"synced_at": 1_700_000_000.0}), encoding="utf-8"
    )

    dataset = repo.load()
    assert [s.id for s in dataset.shikigami] == ["moi"]
    assert "Đã đồng bộ" in dataset.describe_source()


# ── configuration and images ────────────────────────────────────────────────


def test_env_file_parsing_handles_comments_and_quotes(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# comment\n\nSUPABASE_URL='https://x.supabase.co'\n"
        'SUPABASE_ANON_KEY="abc123"\nJUNK\n',
        encoding="utf-8",
    )

    values = read_env_file(env)
    assert values["SUPABASE_URL"] == "https://x.supabase.co"
    assert values["SUPABASE_ANON_KEY"] == "abc123"
    assert "JUNK" not in values


def test_stored_credentials_win_over_env_files():
    stored = SupabaseConfig("https://stored.supabase.co", "stored-key")
    assert resolve(stored) is stored


def test_config_endpoints_are_built_from_the_project_url():
    config = SupabaseConfig("https://x.supabase.co/", "key")
    assert config.is_configured
    assert config.rest_endpoint == "https://x.supabase.co/rest/v1"
    assert config.storage_endpoint == "https://x.supabase.co/storage/v1/object/public"


def test_incomplete_config_is_not_usable():
    assert not SupabaseConfig("https://x.supabase.co", "").is_configured
    assert not SupabaseConfig("", "key").is_configured
    assert not SupabaseConfig().is_configured


def test_storage_key_drops_the_flutter_asset_prefix():
    resolver = ImageResolver()
    assert resolver.storage_key("assets/images/souls/x.webp") == "souls/x.webp"
    assert resolver.storage_key("souls/x.webp") == "souls/x.webp"
    assert resolver.storage_key("") == ""


def test_missing_image_resolves_to_nothing(tmp_path):
    resolver = ImageResolver(tmp_path)
    resolver.cache_dir = tmp_path / "cache"
    assert resolver.local_path("assets/images/souls/nope.webp") is None
    assert resolver.local_path("") is None


@pytest.mark.parametrize(
    "field",
    [
        "assets/images/souls/x.webp",  # as the bundled JSON writes it
        "souls/x.webp",                # as Supabase writes it (bucket key)
    ],
)
def test_both_image_field_spellings_find_the_same_file(tmp_path, field):
    """Syncing rewrites image paths; handling one spelling lost every picture."""
    target = tmp_path / "assets" / "images" / "souls" / "x.webp"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"not really an image, but it exists")

    resolver = ImageResolver(tmp_path)
    resolver.cache_dir = tmp_path / "cache"

    assert resolver.local_path(field) == target


def test_sync_backfills_fields_the_server_left_empty(repo, monkeypatch):
    """Migration 0009 dropped name_jp server-side; a sync must not lose it."""
    remote_rows = {
        "shikigami": [
            # Same ids as the bundled fixture, but name_jp gone and lore added.
            {"id": "thien_cau", "name_vi": "Đại Thiên Cẩu", "rarity": "SSR",
             "name_jp": None, "recommended_souls": ["ban_nguyet"],
             "lore": "Từ server."},
            {"id": "ibaraki", "name_vi": "Ibaraki Đồng Tử", "rarity": "SSR"},
        ],
        "souls": [{"id": "ban_nguyet", "name_vi": "Bán Nguyệt", "kind": "normal",
                   "effects": [{"pieces": 2, "description": "Từ server."}]}],
        "effects": [{"id": "choang", "name": "Choáng", "kind": "debuff",
                     "description": "Mất lượt."},
                    {"id": "moi", "name": "Mới", "kind": "buff",
                     "description": "Chỉ có trên server."}],
    }

    class FakeClient:
        def __init__(self, config):
            pass

        def fetch_table(self, table):
            return [dict(row) for row in remote_rows[table]]

    monkeypatch.setattr("wiki.repository.SupabaseClient", FakeClient)

    dataset = repo.sync(SupabaseConfig("https://x.supabase.co", "key"))

    # New server-only content arrives.
    assert dataset.counts["effects"] == 2
    # ...and the field the server no longer carries survives.
    thien_cau = repo.shikigami_by_id("thien_cau")
    assert thien_cau.name_jp == "Daitengu", "name_jp was lost on sync"
    assert [s.id for s in repo.shikigami(query="daitengu")] == ["thien_cau"], (
        "backfilled name is not searchable"
    )
    # A value the server does have is never overwritten by the bundled one.
    assert thien_cau.lore == "Từ server."


def test_backfill_never_overwrites_a_server_value(repo, monkeypatch):
    remote_rows = {
        "shikigami": [{"id": "thien_cau", "name_vi": "Tên mới từ server",
                       "rarity": "SP", "name_jp": "Tengu"}],
        "souls": [],
        "effects": [],
    }

    class FakeClient:
        def __init__(self, config):
            pass

        def fetch_table(self, table):
            return [dict(row) for row in remote_rows[table]]

    monkeypatch.setattr("wiki.repository.SupabaseClient", FakeClient)
    repo.sync(SupabaseConfig("https://x.supabase.co", "key"))

    record = repo.shikigami_by_id("thien_cau")
    assert record.display_name == "Tên mới từ server"
    assert record.rarity == "SP"
    assert record.name_jp == "Tengu"


# ── the real dataset, when the wiki checkout is next door ────────────────────

real_data = pytest.mark.skipif(
    not paths.DEFAULT_WIKI_DATA_DIR.is_dir(),
    reason="onmyoji_wiki checkout not present",
)


@real_data
def test_the_shipped_dataset_loads_and_is_searchable():
    repository = WikiRepository()
    dataset = repository.load()

    assert dataset.counts["shikigami"] > 100
    assert dataset.counts["souls"] > 10
    assert dataset.counts["effects"] > 10
    # Every record must render a name rather than an empty card.
    assert all(record.display_name for record in dataset.shikigami)


@real_data
def test_every_shipped_shikigami_image_exists_on_disk():
    repository = WikiRepository()
    repository.load()
    resolver = ImageResolver()

    missing = [
        record.id
        for record in repository.dataset.shikigami
        if record.image and resolver.local_path(record.image) is None
    ]
    assert not missing, "images referenced but not on disk: %s" % missing[:5]


# ── the parts of a skill the model used to drop ─────────────────────────────
#
# `Skill` carried name, description, levels and image, and nothing else. The
# rows carry more: 139 skills have a `cost` — the demon-fire orbs the skill
# spends, 0 to 4 — 3 carry an `alt_forms` entry describing the form the skill
# permanently turns into, and 20 distinct `effects` tags mark what a skill does.
# None of it reached the screen, so a reader of the wiki could not see what a
# skill costs, which is the first thing anybody asks about an active skill.


def a_skill_row(**extra):
    row = {
        "name": "DỮ NGÃ LIÊU NGUYÊN",
        "description": "Di chuyển Tâm Hỏa của 1 đồng minh lên bản thân.",
        "image": "skills/1.webp",
        "cost": 2,
        "effects": ["fire_shikigami", "recall"],
        "levels": [{"level": 2, "description": "Sát thương = 40%"}],
        "alt_forms": [{
            "name": "THIÊN HỎA PHÁ VỌNG",
            "image": "skills/1_alt.webp",
            "effects": ["scorching_fire"],
            "description": "Tấn công AOE 3 lần.",
        }],
    }
    row.update(extra)
    return row


def a_record(**extra):
    row = {"id": "x", "rarity": "SP", "skills": [a_skill_row()]}
    row.update(extra)
    return row


def test_the_cost_is_read():
    skill = Shikigami.from_row(a_record()).skills[0]

    assert skill.cost == 2


def test_a_skill_with_no_cost_has_none_not_zero():
    """Zero is a real cost — 30 skills have it — so it cannot double as
    "unknown"."""
    row = a_skill_row()
    del row["cost"]

    skill = Shikigami.from_row(a_record(skills=[row])).skills[0]

    assert skill.cost is None


def test_a_cost_of_zero_survives():
    skill = Shikigami.from_row(a_record(skills=[a_skill_row(cost=0)])).skills[0]

    assert skill.cost == 0


def test_a_cost_that_is_not_a_number_is_ignored():
    skill = Shikigami.from_row(a_record(skills=[a_skill_row(cost="ba")])).skills[0]

    assert skill.cost is None


def test_the_effect_tags_are_read():
    skill = Shikigami.from_row(a_record()).skills[0]

    assert skill.effects == ["fire_shikigami", "recall"]


def test_the_alternate_form_is_read():
    skill = Shikigami.from_row(a_record()).skills[0]

    assert len(skill.alt_forms) == 1
    form = skill.alt_forms[0]
    assert form.name == "THIÊN HỎA PHÁ VỌNG"
    assert form.description == "Tấn công AOE 3 lần."
    assert form.image == "skills/1_alt.webp"
    assert form.effects == ["scorching_fire"]


def test_an_empty_alt_forms_list_is_no_alternate_form():
    """19 of the 22 skills that carry the key carry an empty list."""
    skill = Shikigami.from_row(a_record(skills=[a_skill_row(alt_forms=[])])).skills[0]

    assert skill.alt_forms == []


def test_nonsense_in_alt_forms_is_dropped_not_raised():
    row = a_skill_row(alt_forms=["not a form", None, {"name": "Thật"}])

    skill = Shikigami.from_row(a_record(skills=[row])).skills[0]

    assert [form.name for form in skill.alt_forms] == ["Thật"]


def test_the_cost_reads_as_orbs_of_demon_fire():
    """What the game shows beside an active skill, and what the Vietnamese
    source writes as "(2 🔥)"."""
    skill = Shikigami.from_row(a_record()).skills[0]

    assert skill.cost_label == "2"


def test_a_skill_with_no_cost_has_no_label():
    row = a_skill_row()
    del row["cost"]

    skill = Shikigami.from_row(a_record(skills=[row])).skills[0]

    assert skill.cost_label == ""


def test_a_free_skill_says_zero_rather_than_nothing():
    skill = Shikigami.from_row(a_record(skills=[a_skill_row(cost=0)])).skills[0]

    assert skill.cost_label == "0"


# ── an EX form is a skill in its own right ──────────────────────────────────
#
# The game gives a shikigami three skills. What looks like a fourth is an EX
# variant hanging off one of them — its icon sits under its parent's in the
# skill column, marked "Ex", and its panel carries its own demon-fire cost and
# its own Lv.2 to Lv.5 ladder.
#
# `SkillForm` began with name, art, tags and text, which is all the three
# existing rows carry. That was enough to name the form and not enough to
# describe it: the cost and the ladder had nowhere to go.


def a_form(**extra):
    form = {
        "name": "THIÊN HỎA PHÁ VỌNG",
        "description": "Tấn công AOE 3 lần.",
        "image": "skills/x_alt.webp",
        "effects": ["scorching_fire"],
        "cost": 3,
        "levels": [{"level": 2, "description": "Sát thương 3 lần đầu = 45%"},
                   {"level": 5, "description": "Sát thương lần cuối = 240%."}],
    }
    form.update(extra)
    return form


def a_record_with_a_form(**extra):
    skill = a_skill_row(alt_forms=[a_form(**extra)])
    return {"id": "x", "rarity": "SP", "skills": [skill]}


def test_the_form_carries_its_own_cost():
    form = Shikigami.from_row(a_record_with_a_form()).skills[0].alt_forms[0]

    assert form.cost == 3
    assert form.cost_label == "3"


def test_a_form_without_a_cost_says_nothing():
    """The three forms already in the dataset carry none."""
    row = a_form()
    del row["cost"]
    record = {"id": "x", "rarity": "SP",
              "skills": [a_skill_row(alt_forms=[row])]}

    form = Shikigami.from_row(record).skills[0].alt_forms[0]

    assert form.cost is None
    assert form.cost_label == ""


def test_the_form_carries_its_own_levels():
    form = Shikigami.from_row(a_record_with_a_form()).skills[0].alt_forms[0]

    assert [caption for caption, _ in form.level_rows] == ["Cấp 2", "Cấp 5"]


def test_a_form_level_that_repeats_the_summary_is_dropped():
    """The same rule the parent skill uses: level 1 is the description."""
    form = Shikigami.from_row(a_record_with_a_form(levels=[
        {"level": 1, "description": "Tấn công AOE 3 lần."},
        {"level": 2, "description": "45%"},
    ])).skills[0].alt_forms[0]

    assert [caption for caption, _ in form.level_rows] == ["Cấp 2"]


def test_a_form_with_no_levels_has_no_ladder():
    row = a_form()
    del row["levels"]
    record = {"id": "x", "rarity": "SP",
              "skills": [a_skill_row(alt_forms=[row])]}

    form = Shikigami.from_row(record).skills[0].alt_forms[0]

    assert form.level_rows == []
