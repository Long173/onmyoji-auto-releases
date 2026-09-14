"""The same shikigami filed twice, and how the two records get folded into one.

The dataset was built from two sources and they were never reconciled. The
timestamps say what happened: the Vietnamese rows were written on 11 May 2026,
and a batch from onmyoji.fandom.com was imported over the top on 14 May. Where
both sources covered a shikigami, the result is two records with different ids —
so nothing that compares ids or names finds them, and the encyclopaedia lists
the figure twice.

The two halves are worth keeping *both* of, which is why this merges rather than
deletes:

    onmyojicltl.wordpress.com   Vietnamese name, role, .webp art, often no stats
    onmyoji.fandom.com          real stats, romaji name only, .png art

Folding them keeps the Vietnamese name (this is a Vietnamese tool) and gains the
stats the Vietnamese row was missing. Deleting either side would have thrown
away something the other did not have.

**How the pairing was established, and how far to trust it.** Two automatic
methods were tried and both failed, so neither is used here:

* comparing the portraits by HSV histogram, the technique the parade library
  uses — one record came back as the best match for six different figures;
* matching on identical hp/attack — four pairs, two of them plainly wrong (it
  put the goldfish SP with the nine-lives cat).

What is left is reading the names: every pair below is the same name written two
ways, character for character, romaji against its Sino-Vietnamese reading —
``Ootengu`` 大天狗 against ``Đại Thiên Cẩu``, 大 → Đại, 天 → Thiên, 狗 → Cẩu.

The SP half of the table is confirmed by arithmetic rather than by eye. 65 SP
records minus these 16 pairs leaves 49; the game has 50, and the one it has that
the dataset does not is Suzuhikohime SP. 49 + 1 = 50, exactly, which no wrong
pairing would produce.

The SSR half is only four pairs and each is a character-exact reading. Every
other SSR the two sources hold is genuinely different — the sources turn out to
be mostly complementary, not overlapping — and SR, R and N have no overlap at
all: the Vietnamese source holds 7 SR, 2 R and no N, and none of those appear in
the fandom batch.

Adding a pair: put the id that should survive on the left. Nothing else needs
changing, and ``test_wiki_duplicates`` checks both ids still exist.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

# (id to keep, id to fold into it). The kept id is the Vietnamese-source record,
# so the encyclopaedia keeps the name a Vietnamese player would search for.
PAIRS: Tuple[Tuple[str, str], ...] = (
    # ── SP ──────────────────────────────────────────────────────────────────
    ("xich_anh_yeu_dao_co", "akakage_youtou_hime"),
    ("phuoc_cot_thanh_co", "bakkotsu_kiyohime"),
    ("kieu_lang_hoang_xuyen_chi_chu", "gyourou_arakawa_no_aruji"),
    ("dao_ha_than_ngu_soan_tan", "inari_miketsu"),
    ("tan_thien_ngoc_tao_tien", "jinten_tamamo_no_mae"),
    ("quy_vuong_tuu_thon_dong_tu", "oniou_shuten_douji"),
    ("ngu_oan_bat_nha", "oura_hannya"),
    ("luyen_nguc_ty_moc_dong_tu", "rengoku_ibaraki_douji"),
    ("thien_bang_tuyet_nu", "semigoori_yuki_onna"),
    ("thieu_vu_dai_thien_cau", "shouu_ootengu"),
    ("thuong_phong_nhat_muc_lien", "soufuu_ichimokuren"),
    ("thien_kiem_nhan_tam_quy_thiet", "tenken_jinshin_onikiri"),
    ("phu_the_thanh_hanh_dang", "ukiyo_aoandon"),
    ("mong_dan_ho_diep_tinh", "yumebiki_kochou_no_sei"),
    # Same figure, after migration 0011 renamed the Vietnamese half rather than
    # landing it on the romaji id the way it did for the other eighteen. Both
    # rows are in the bundled file — "Mộng Dẫn Hồ Điệp Tinh" and "Yumebiki
    # Kochou no Sei" — so without this line the encyclopaedia lists her twice
    # for anyone who has not synced. Found by counting: the fold left 51 SP
    # where the game's album has 50 of them plus Ignis Suzuhikohime.
    ("dreambound_chocho", "yumebiki_kochou_no_sei"),
    ("mong_son_bach_tang_chu", "yumeyama_hakuzousu"),
    ("thien_tam_van_ngoai_kinh", "zenshin_ungaikyou"),
    # ── SSR ─────────────────────────────────────────────────────────────────
    ("bach_tang_chu", "hakuzousu"),               # 白蔵主
    ("dai_thien_cau", "ootengu"),                 # 大天狗
    ("dai_nhac_hoan", "ootakemaru"),              # 大嶽丸
    ("tu_kim_than", "omoikane_no_kami"),          # 思金神
)

# Names the same import got wrong, and what they should say.
#
# Two SSR rows came out of it carrying a *frog's* English name — the Realm Raid
# frogs are separate records, and two of theirs leaked into the shikigami they
# are modelled on. On screen that put "Miketsu Frog" under Ngự Soạn Tân as her
# romaji name.
#
# It also cost a count: totting up frogs by name rather than by id swept these
# two SSR in with them, which is how 15 frogs got reported as 17.
#
# Corrected here rather than in the cache for the same reason as the folding
# above — a re-sync from Supabase would otherwise bring the frog names back.
# Keyed by id, and migration 0011 renamed these, so both spellings are listed:
# the pre-rename ids for a cache written before it, and the current ones for the
# bundled file, which still carries the frog names to this day. Only the second
# pair is reachable on a fresh install — which is where it was found, because a
# machine with a sync cache never reads the bundled rows at all.
WRONG_NAMES: Dict[str, Dict[str, str]] = {
    "ngu_soan_tan": {"name_en": "Miketsu"},
    "ngoc_tao_tien": {"name_en": "Tamamo no Mae"},
    "miketsu": {"name_en": "Miketsu"},
    "tamamo_no_mae": {"name_en": "Tamamo no Mae"},
}

# Fields where an empty value on the kept row should be filled from the other.
# Names are deliberately *not* in here: the kept row is the Vietnamese one and
# its name is the whole reason it is the one kept.
FILLABLE = (
    "stats", "skills", "recommended_souls", "slot_mains", "countered_by",
    "role", "obtain", "description", "lore", "name_en", "name_jp",
)


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (str, list, dict, tuple)):
        return len(value) == 0
    return False


def _no_numbers(stats: Any) -> bool:
    """Whether a stats block is empty *in the way this data is empty*.

    The Vietnamese rows do not omit their stats — they carry the whole shape
    with every number set to zero:

        {"hp": {"tier": "", "value": 0}, "attack": {"tier": "", "value": 0}, ...}

    A plain emptiness test passes that straight through as "already filled",
    which is exactly what happened the first time: the fold ran, the duplicate
    went away, and every merged figure still showed hp 0.

    "Any non-zero number" is not enough either — that was the second attempt.
    Every row, filled or not, carries a baseline ``crit_dmg: 150`` and
    ``crit_rate: 10``, so something is always non-zero. Health and attack are
    the two that are only ever present when the row was really populated, so
    they are what gets asked.
    """
    if not isinstance(stats, dict) or not stats:
        return True
    for field in ("hp", "attack"):
        entry = stats.get(field)
        value = entry.get("value") if isinstance(entry, dict) else entry
        if isinstance(value, (int, float)) and value:
            return False
    return True


def merge_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One row per shikigami, with each pair's two halves combined.

    Two ways of finding a pair, and both are needed.

    **By id.** Migration 0011 standardised shikigami ids on the English name,
    renaming 97 of them — and that landed both halves of these pairs on the same
    id, because the id the fandom.com row already had is exactly the id the
    Vietnamese row was renamed to. A duplicate now announces itself and no table
    is needed to spot it. This is the path that runs today.

    **By the table above.** A dataset written before that migration still has the
    old ids, and there is one on every machine that synced before it: the local
    cache. Dropping this pass would have made the encyclopaedia list those
    figures twice again for anyone who had not re-synced — which is the very bug
    this module exists to fix, arriving through a different door.

    Rows this does not know about are returned untouched and in their original
    order, so a dataset from anywhere else passes straight through.
    """
    for row in rows:
        if isinstance(row, dict):
            for field, value in WRONG_NAMES.get(row.get("id"), {}).items():
                row[field] = value

    # Identity, not id: after the rename the two halves of a pair *share* an id,
    # so an id is no longer enough to say which row to drop.
    dropped = set()

    # ── by id ───────────────────────────────────────────────────────────────
    grouped: Dict[Any, List[Dict[str, Any]]] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("id"):
            grouped.setdefault(row["id"], []).append(row)

    for same in grouped.values():
        if len(same) < 2:
            continue
        keep = _vietnamese_half(same)
        for other in same:
            if other is keep:
                continue
            _fill_from(keep, other)
            dropped.add(id(other))

    # ── by the table, for a dataset from before the rename ──────────────────
    by_id = {row["id"]: row for row in rows
             if isinstance(row, dict) and row.get("id")
             and id(row) not in dropped}
    for keep_id, drop_id in PAIRS:
        keep, drop = by_id.get(keep_id), by_id.get(drop_id)
        if keep is None or drop is None or keep is drop:
            # One side absent: nothing to fold, and nothing to complain about —
            # a partial dataset is a normal thing to be handed. `keep is drop`
            # is the post-rename case, folded above already.
            continue
        _fill_from(keep, drop)
        dropped.add(id(drop))

    return [row for row in rows if id(row) not in dropped]


def _vietnamese_half(same: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Which of two records for one shikigami to keep.

    The one carrying the Vietnamese name. This is a Vietnamese tool and that
    name is the whole reason that half is kept — the other half brings the
    stats, which :func:`_fill_from` takes across.

    Decided by looking at the rows rather than taking the first, because file
    order is not something to depend on: a re-export that happened to list the
    fandom.com half first would silently start dropping every Vietnamese name.
    """
    for row in same:
        if not _is_blank(row.get("name_vi")):
            return row
    return same[0]


def _fill_from(keep: Dict[str, Any], drop: Dict[str, Any]) -> None:
    """Copy across the fields the kept row is missing, and nothing else."""
    for field in FILLABLE:
        empty = (_no_numbers if field == "stats" else _is_blank)
        if empty(keep.get(field)) and not empty(drop.get(field)):
            keep[field] = drop[field]
