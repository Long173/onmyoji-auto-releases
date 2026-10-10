"""Wiki records.

The bundled JSON and the Supabase tables share one shape by design (see the
comment at the top of ``supabase/migrations/0001_init.sql``), so a single
``from_row`` handles both. Every field is treated as optional: the dataset was
scraped, and plenty of records are missing an English name, stats or lore.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence, Tuple

from wiki.search import normalize

RARITY_ORDER = {"SP": 0, "SSR": 1, "SR": 2, "R": 3, "N": 4}
RARITY_CHOICES = ("Tất cả", "SP", "SSR", "SR", "R", "N")

SOUL_KIND_LABELS = {"normal": "Ngự hồn thường", "boss": "Ngự hồn boss"}
EFFECT_KIND_LABELS = {"buff": "Tăng ích", "debuff": "Bất lợi", "other": "Khác"}

# Order and labels for the stat table in the detail view.
STAT_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("hp", "Sinh mệnh"),
    ("attack", "Tấn công"),
    ("defense", "Phòng thủ"),
    ("speed", "Tốc độ"),
    ("crit_rate", "Bạo kích"),
    ("crit_dmg", "ST bạo kích"),
    ("accuracy", "Chính xác"),
    ("resist", "Kháng hiệu ứng"),
)
PERCENT_STATS = {"crit_rate", "crit_dmg", "accuracy", "resist"}

# Codes used by `slot_mains` for the main stat on soul positions 2, 4 and 6.
# Wording matches STAT_FIELDS above so the detail page reads consistently.
SLOT_MAIN_LABELS = {
    "hp_pct": "Sinh mệnh %",
    "atk_pct": "Tấn công %",
    "def_pct": "Phòng thủ %",
    "spd": "Tốc độ",
    "crit_pct": "Bạo kích",
    "crit_dmg_pct": "ST bạo kích",
}


def slot_main_label(code: str) -> str:
    """Vietnamese name for a slot-main code.

    An unrecognised code is tidied up rather than dropped — showing
    ``Effect hit %`` beats hiding a stat the source knows about.
    """
    known = SLOT_MAIN_LABELS.get(code)
    if known:
        return known
    pretty = code.replace("_pct", " %").replace("_", " ").strip()
    return pretty[:1].upper() + pretty[1:] if pretty else code


def _text(row: Dict[str, Any], key: str) -> str:
    value = row.get(key)
    return value.strip() if isinstance(value, str) else ""


def _slot_order(item: Tuple[str, Any]) -> Tuple[int, str]:
    """Sort slot keys numerically — "10" must not come before "2"."""
    key = item[0]
    try:
        return (int(key), "")
    except (TypeError, ValueError):
        return (10_000, str(key))


def _whole_number(value: Any) -> Optional[int]:
    """An int, or None for anything that is not one.

    ``None`` rather than 0 on failure: zero is a real cost that 30 skills have,
    so it cannot double as "the row did not say".
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _list(row: Dict[str, Any], key: str) -> List[str]:
    value = row.get(key)
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _level_rows(levels: List[Any], description: str) -> List[Tuple[str, str]]:
    """The upgrade ladder, as captioned rows.

    Level 1 repeats the owning skill's description in nearly every record, so
    any level whose text matches the summary is dropped rather than printed
    twice. Shared by a skill and by the EX form hanging off it, because the game
    gives the form its own ladder under the same rule.
    """
    summary = (description or "").strip()
    rows: List[Tuple[str, str]] = []
    for entry in levels or []:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("description") or "").strip()
        if not text or text == summary:
            continue
        number = entry.get("level")
        rows.append(("Cấp %s" % number if number is not None else "Cấp", text))
    return rows


@dataclass(frozen=True)
class SkillForm:
    """The form a skill permanently turns into.

    Three skills in the dataset have one. It is a whole second skill — its own
    name, art, tags and text — and it used to be read off the row by nothing at
    all, so a reader could not learn that the skill they were looking at becomes
    something else.
    """

    name: str
    description: str = ""
    image: str = ""
    effects: List[str] = field(default_factory=list)
    # The form is a skill in its own right: the game shows it with its own
    # demon-fire cost and its own Lv.2 to Lv.5 ladder. The three forms already
    # in the dataset carry neither, so both are optional.
    cost: Optional[int] = None
    levels: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def cost_label(self) -> str:
        return "" if self.cost is None else str(self.cost)

    @property
    def level_rows(self) -> List[Tuple[str, str]]:
        return _level_rows(self.levels, self.description)


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    levels: List[Dict[str, Any]] = field(default_factory=list)
    image: str = ""
    # Orbs of demon fire the skill spends: 0 to 4, on 139 of the 784 skills.
    # ``None`` means the row does not say — which is not the same as free, and 30
    # skills really are free.
    cost: Optional[int] = None
    # Tags naming what the skill does, as ids into the `effects` table. All 20
    # that appear resolve there, so they can be shown as words rather than slugs.
    effects: List[str] = field(default_factory=list)
    alt_forms: List[SkillForm] = field(default_factory=list)

    @property
    def cost_label(self) -> str:
        """The cost as it is written beside a skill, or empty when unknown.

        A plain number: the icon beside it says what the number counts, the same
        way the game and the Vietnamese source do — "(2 🔥)".
        """
        return "" if self.cost is None else str(self.cost)

    @property
    def level_rows(self) -> List[Tuple[str, str]]:
        """``("Cấp 2", "Sát thương = 80%")`` for every level worth showing."""
        return _level_rows(self.levels, self.description)


@dataclass(frozen=True)
class Shikigami:
    id: str
    name_vi: str = ""
    name_jp: str = ""
    name_en: str = ""
    friendly_name: List[str] = field(default_factory=list)
    rarity: str = "N"
    description: str = ""
    obtain: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    skills: List[Skill] = field(default_factory=list)
    recommended_souls: List[str] = field(default_factory=list)
    countered_by: List[str] = field(default_factory=list)
    slot_mains: Dict[str, Any] = field(default_factory=dict)
    lore: str = ""
    image: str = ""
    source_url: str = ""
    sort_index: int = 0

    @staticmethod
    def from_row(row: Dict[str, Any]) -> "Shikigami":
        skills = [
            Skill(
                name=_text(entry, "name"),
                description=_text(entry, "description"),
                levels=list(entry.get("levels") or []),
                image=_text(entry, "image"),
                cost=_whole_number(entry.get("cost")),
                effects=_list(entry, "effects"),
                alt_forms=[
                    SkillForm(
                        name=_text(form, "name"),
                        description=_text(form, "description"),
                        image=_text(form, "image"),
                        effects=_list(form, "effects"),
                        cost=_whole_number(form.get("cost")),
                        levels=list(form.get("levels") or []),
                    )
                    for form in (entry.get("alt_forms") or [])
                    if isinstance(form, dict) and _text(form, "name")
                ],
            )
            for entry in (row.get("skills") or [])
            if isinstance(entry, dict)
        ]
        return Shikigami(
            id=_text(row, "id"),
            name_vi=_text(row, "name_vi"),
            name_jp=_text(row, "name_jp"),
            name_en=_text(row, "name_en"),
            friendly_name=_list(row, "friendly_name"),
            rarity=(_text(row, "rarity") or "N").upper(),
            description=_text(row, "description"),
            obtain=_list(row, "obtain"),
            stats=dict(row.get("stats") or {}),
            skills=skills,
            recommended_souls=_list(row, "recommended_souls"),
            countered_by=_list(row, "countered_by"),
            slot_mains=dict(row.get("slot_mains") or {}),
            lore=_text(row, "lore"),
            image=_text(row, "image"),
            source_url=_text(row, "source_url"),
            sort_index=int(row.get("sort_index") or 0),
        )

    @property
    def display_name(self) -> str:
        """Vietnamese name, else any other name, else the id."""
        return self.name_vi or self.name_en or self.name_jp or self.id

    @property
    def secondary_name(self) -> str:
        for candidate in (self.name_en, self.name_jp):
            if candidate and candidate != self.display_name:
                return candidate
        return ""

    @property
    def stat_rows(self) -> List[Tuple[str, str]]:
        """Populated stats only — most scraped records have zeroes throughout."""
        rows: List[Tuple[str, str]] = []
        for key, label in STAT_FIELDS:
            entry = self.stats.get(key)
            value = entry.get("value") if isinstance(entry, dict) else entry
            if not value:
                continue
            suffix = "%" if key in PERCENT_STATS else ""
            rows.append((label, "{:,}{}".format(value, suffix).replace(",", " ")))
        return rows

    @property
    def slot_main_rows(self) -> List[Tuple[str, str]]:
        """One row per soul position, e.g. ``("Vị trí 2", "Tấn công % / Tốc độ")``.

        The raw field is ``{"2": ["atk_pct", "spd"], ...}``; rendering it
        directly printed Python list syntax and internal stat codes.
        """
        rows: List[Tuple[str, str]] = []
        for slot, value in sorted(self.slot_mains.items(), key=_slot_order):
            options = value if isinstance(value, (list, tuple)) else [value]
            labels = [
                slot_main_label(str(option).strip())
                for option in options
                if str(option).strip()
            ]
            if labels:
                rows.append(("Vị trí %s" % slot, " / ".join(labels)))
        return rows

    @property
    def sort_key(self) -> Tuple[int, int, str]:
        return (RARITY_ORDER.get(self.rarity, 9), self.sort_index, self.display_name)

    @property
    def haystack(self) -> str:
        return " ".join(
            [self.name_vi, self.name_en, self.name_jp, self.id] + self.friendly_name
        )


@dataclass(frozen=True)
class SoulEffect:
    pieces: int
    description: str

    @property
    def tier_label(self) -> str:
        return "%d món" % self.pieces


@dataclass(frozen=True)
class Soul:
    id: str
    name_vi: str = ""
    name_en: str = ""
    kind: str = "normal"
    effects: List[SoulEffect] = field(default_factory=list)
    image: str = ""
    sort_index: int = 0

    @staticmethod
    def from_row(row: Dict[str, Any]) -> "Soul":
        effects = [
            SoulEffect(
                pieces=int(entry.get("pieces") or 0),
                description=_text(entry, "description"),
            )
            for entry in (row.get("effects") or [])
            if isinstance(entry, dict)
        ]
        return Soul(
            id=_text(row, "id"),
            name_vi=_text(row, "name_vi"),
            name_en=_text(row, "name_en"),
            kind=(_text(row, "kind") or "normal").lower(),
            effects=sorted(effects, key=lambda e: e.pieces),
            image=_text(row, "image"),
            sort_index=int(row.get("sort_index") or 0),
        )

    @property
    def display_name(self) -> str:
        return self.name_vi or self.name_en or self.id

    @property
    def secondary_name(self) -> str:
        return self.name_en if self.name_en and self.name_en != self.display_name else ""

    @property
    def kind_label(self) -> str:
        return SOUL_KIND_LABELS.get(self.kind, self.kind)

    @property
    def summary(self) -> str:
        return self.effects[0].description if self.effects else ""

    @property
    def haystack(self) -> str:
        return " ".join([self.name_vi, self.name_en, self.id, self.kind_label])


@dataclass(frozen=True)
class Effect:
    id: str
    name: str = ""
    en_name: str = ""
    kind: str = "other"
    description: str = ""
    image: str = ""
    sort_index: int = 0

    @staticmethod
    def from_row(row: Dict[str, Any]) -> "Effect":
        return Effect(
            id=_text(row, "id"),
            name=_text(row, "name"),
            en_name=_text(row, "en_name"),
            kind=(_text(row, "kind") or "other").lower(),
            description=_text(row, "description"),
            image=_text(row, "image"),
            sort_index=int(row.get("sort_index") or 0),
        )

    @property
    def display_name(self) -> str:
        return self.name or self.en_name or self.id

    @property
    def kind_label(self) -> str:
        return EFFECT_KIND_LABELS.get(self.kind, self.kind)

    @property
    def haystack(self) -> str:
        return " ".join([self.name, self.en_name, self.id, self.kind_label])


def filter_by_search(records: Sequence[Any], query: str) -> List[Any]:
    """Keep records whose haystack matches every term in ``query``."""
    normalized = normalize(query)
    if not normalized:
        return list(records)
    terms = normalized.split(" ")
    return [
        record
        for record in records
        if all(term in normalize(record.haystack) for term in terms)
    ]
