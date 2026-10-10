"""Loads the wiki dataset and keeps it up to date.

Three layers, in the order they are consulted:

1. ``cache/wiki/*.json`` — whatever the last Supabase sync wrote
2. the Flutter app's ``assets/data`` — the full dataset, shipped offline
3. nothing, which yields an empty dataset and a visible message

So the window works with no network and no credentials; syncing is an upgrade
path, not a requirement.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import paths
from wiki.config import SupabaseConfig
from wiki import additions, duplicates
from wiki.models import (Effect, Shikigami, Soul, filter_by_search)
from wiki.search import normalize
from wiki.supabase_client import SupabaseClient, SupabaseError

logger = logging.getLogger(__name__)

BUNDLED = "bundled"
CACHED = "cache"
REMOTE = "supabase"
EMPTY = "empty"

META_FILE = "meta.json"
COLLECTIONS = ("shikigami", "souls", "effects")


@dataclass
class Dataset:
    """An immutable snapshot of the three collections."""

    shikigami: List[Shikigami] = field(default_factory=list)
    souls: List[Soul] = field(default_factory=list)
    effects: List[Effect] = field(default_factory=list)
    source: str = EMPTY
    synced_at: float = 0.0

    @property
    def is_empty(self) -> bool:
        return not (self.shikigami or self.souls or self.effects)

    @property
    def counts(self) -> Dict[str, int]:
        return {
            "shikigami": len(self.shikigami),
            "souls": len(self.souls),
            "effects": len(self.effects),
        }

    def describe_source(self) -> str:
        if self.source == REMOTE or (self.source == CACHED and self.synced_at):
            return "Đã đồng bộ · " + _relative_time(self.synced_at)
        if self.source == BUNDLED:
            return "Dữ liệu đóng gói offline"
        return "Chưa có dữ liệu"


def _relative_time(timestamp: float) -> str:
    if not timestamp:
        return "không rõ"
    delta = max(0, time.time() - timestamp)
    if delta < 90:
        return "vừa xong"
    if delta < 3600:
        return "%d phút trước" % (delta // 60)
    if delta < 86400:
        return "%d giờ trước" % (delta // 3600)
    return "%d ngày trước" % (delta // 86400)


def _is_blank(value: Any) -> bool:
    """True for None, empty strings and empty collections — but not for 0."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return not value
    return False


def _read_json(path: Path) -> Any:
    """Parse a JSON file, or return ``None``.

    An absent file is the normal case on a first run — only a file that exists
    but cannot be parsed is worth a warning.
    """
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read %s", path, exc_info=True)
        return None


class WikiRepository:
    """Owns the current :class:`Dataset` and the code paths that replace it."""

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self.data_dir = Path(data_dir) if data_dir else paths.DEFAULT_WIKI_DATA_DIR
        self.cache_dir = paths.WIKI_CACHE_DIR
        self.dataset = Dataset()

    # ── loading ─────────────────────────────────────────────────────────────

    def load(self) -> Dataset:
        self.dataset = self._load_cached() or self._load_bundled() or Dataset()
        logger.info(
            "Wiki dataset loaded from %s: %s", self.dataset.source, self.dataset.counts
        )
        return self.dataset

    def _load_cached(self) -> Optional[Dataset]:
        meta = _read_json(self.cache_dir / META_FILE)
        if not isinstance(meta, dict):
            return None
        rows = {}
        for collection in COLLECTIONS:
            data = _read_json(self.cache_dir / ("%s.json" % collection))
            if not isinstance(data, list):
                return None
            rows[collection] = data
        dataset = self._build(rows, CACHED)
        dataset.synced_at = float(meta.get("synced_at") or 0.0)
        return dataset if not dataset.is_empty else None

    def _read_bundled_rows(self) -> Dict[str, List[Dict[str, Any]]]:
        """Raw rows from the Flutter checkout, or empty lists if it is absent."""
        if not self.data_dir.is_dir():
            return {"shikigami": [], "souls": [], "effects": []}

        shikigami_rows: List[Dict[str, Any]] = []
        # Shikigami are split one file per rarity.
        for path in sorted((self.data_dir / "shikigami").glob("*.json")):
            data = _read_json(path)
            if isinstance(data, list):
                shikigami_rows.extend(data)

        return {
            "shikigami": shikigami_rows,
            "souls": _read_json(self.data_dir / "souls.json") or [],
            "effects": _read_json(self.data_dir / "effects.json") or [],
        }

    def _load_bundled(self) -> Optional[Dataset]:
        if not self.data_dir.is_dir():
            logger.warning("Bundled wiki data not found at %s", self.data_dir)
            return None
        dataset = self._build(self._read_bundled_rows(), BUNDLED)
        return dataset if not dataset.is_empty else None

    @staticmethod
    def _build(rows: Dict[str, Any], source: str) -> Dataset:
        # Folded here rather than at either source, so it holds whichever of the
        # two the dataset came from — and so a re-sync from Supabase cannot
        # bring the duplicates back. See :mod:`wiki.duplicates`.
        shikigami_rows = duplicates.merge_rows(
            [row for row in rows.get("shikigami") or [] if isinstance(row, dict)]
        )
        # Then the ones the game has and no source ever published. Folding first
        # matters: a hand-entered record must not be added on top of a duplicate
        # that is about to disappear.
        shikigami_rows = additions.add_missing(shikigami_rows)
        shikigami = [Shikigami.from_row(row) for row in shikigami_rows]
        souls = [
            Soul.from_row(row) for row in rows.get("souls") or [] if isinstance(row, dict)
        ]
        effects = [
            Effect.from_row(row) for row in rows.get("effects") or []
            if isinstance(row, dict)
        ]
        shikigami.sort(key=lambda s: s.sort_key)
        souls.sort(key=lambda s: (s.kind != "normal", s.sort_index, s.display_name))
        effects.sort(key=lambda e: (e.kind, e.sort_index, e.display_name))
        return Dataset(shikigami, souls, effects, source)

    # ── syncing ─────────────────────────────────────────────────────────────

    def sync(
        self,
        config: SupabaseConfig,
        progress: Optional[Callable[[str], None]] = None,
    ) -> Dataset:
        """Pull every collection from Supabase and cache it.

        Runs on a worker thread — it does network I/O and must not touch Qt.
        Raises :class:`SupabaseError` with a message meant for the user.
        """
        client = SupabaseClient(config)
        rows: Dict[str, Any] = {}
        for collection in COLLECTIONS:
            if progress is not None:
                progress("Đang tải %s…" % collection)
            rows[collection] = client.fetch_table(collection)

        self._fill_gaps_from_bundled(rows)
        dataset = self._build(rows, REMOTE)
        if dataset.is_empty:
            raise SupabaseError("Supabase không trả về dữ liệu nào.")
        dataset.synced_at = time.time()
        self._write_cache(rows, dataset.synced_at)
        self.dataset = dataset
        logger.info("Wiki synced from Supabase: %s", dataset.counts)
        return dataset

    def _fill_gaps_from_bundled(self, rows: Dict[str, Any]) -> int:
        """Copy fields the server left empty from the bundled dataset.

        The two sources are not equivalent: Supabase carries more effects and
        populated ``recommended_souls``, while ``name_jp`` was dropped there in
        migration 0009 and survives only in the shipped JSON. Syncing should
        never make the app know less, so blanks are backfilled per record.
        Existing server values are never touched.
        """
        bundled = self._read_bundled_rows()
        filled = 0

        for collection, remote_rows in rows.items():
            by_id = {
                row.get("id"): row
                for row in bundled.get(collection, [])
                if isinstance(row, dict) and row.get("id")
            }
            if not by_id:
                continue
            for remote in remote_rows:
                if not isinstance(remote, dict):
                    continue
                local = by_id.get(remote.get("id"))
                if local is None:
                    continue
                for key, value in local.items():
                    if _is_blank(remote.get(key)) and not _is_blank(value):
                        remote[key] = value
                        filled += 1

        if filled:
            logger.info("Backfilled %d empty field(s) from the bundled dataset", filled)
        return filled

    def _write_cache(self, rows: Dict[str, Any], synced_at: float) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            for collection in COLLECTIONS:
                (self.cache_dir / ("%s.json" % collection)).write_text(
                    json.dumps(rows[collection], ensure_ascii=False), encoding="utf-8"
                )
            (self.cache_dir / META_FILE).write_text(
                json.dumps({"synced_at": synced_at}), encoding="utf-8"
            )
        except OSError:
            # A failed cache write costs a re-sync next launch, nothing more.
            logger.warning("Could not write the wiki cache", exc_info=True)

    # ── queries ─────────────────────────────────────────────────────────────

    def shikigami(self, rarity: str = "Tất cả", query: str = "") -> List[Shikigami]:
        records = self.dataset.shikigami
        if rarity and rarity != "Tất cả":
            records = [s for s in records if s.rarity == rarity]
        return filter_by_search(records, query)

    def souls(self, kind: str = "Tất cả", query: str = "") -> List[Soul]:
        records = self.dataset.souls
        if kind and kind != "Tất cả":
            records = [s for s in records if s.kind_label == kind]
        return filter_by_search(records, query)

    def effects(self, kind: str = "Tất cả", query: str = "") -> List[Effect]:
        records = self.dataset.effects
        if kind and kind != "Tất cả":
            records = [e for e in records if e.kind_label == kind]
        return filter_by_search(records, query)

    def shikigami_by_id(self, record_id: str) -> Optional[Shikigami]:
        return next((s for s in self.dataset.shikigami if s.id == record_id), None)

    def soul_by_id(self, record_id: str) -> Optional[Soul]:
        return next((s for s in self.dataset.souls if s.id == record_id), None)

    def effect_by_id(self, record_id: str) -> Optional[Effect]:
        return next((e for e in self.dataset.effects if e.id == record_id), None)

    def resolve_soul(self, reference: str) -> Optional[Soul]:
        """Look a soul up by id, then by name — sources mix the two."""
        by_id = self.soul_by_id(reference)
        if by_id is not None:
            return by_id
        wanted = normalize(reference)
        return next(
            (s for s in self.dataset.souls if normalize(s.display_name) == wanted), None
        )

    def resolve_shikigami(self, reference: str) -> Optional[Shikigami]:
        by_id = self.shikigami_by_id(reference)
        if by_id is not None:
            return by_id
        wanted = normalize(reference)
        return next(
            (s for s in self.dataset.shikigami if normalize(s.display_name) == wanted),
            None,
        )

    def souls_using(self, shikigami: Shikigami) -> List[Soul]:
        resolved = [self.resolve_soul(ref) for ref in shikigami.recommended_souls]
        return [soul for soul in resolved if soul is not None]

    def shikigami_using(self, soul: Soul) -> List[Shikigami]:
        """Shikigami that recommend this soul — the reverse of the link above."""
        wanted = {soul.id, normalize(soul.display_name)}
        return [
            record
            for record in self.dataset.shikigami
            if any(
                ref in wanted or normalize(ref) in wanted
                for ref in record.recommended_souls
            )
        ]

    def search_everything(self, query: str, limit: int = 60) -> List[Dict[str, Any]]:
        """Mixed-type results for the global search view."""
        if not normalize(query):
            return []
        results: List[Dict[str, Any]] = []
        for record in filter_by_search(self.dataset.shikigami, query):
            subtitle = record.rarity
            if record.secondary_name:
                subtitle += " · " + record.secondary_name
            results.append({
                "type": "Thức thần", "id": record.id, "kind": "shikigami",
                "title": record.display_name, "subtitle": subtitle,
            })
        for record in filter_by_search(self.dataset.souls, query):
            results.append({
                "type": "Ngự hồn", "id": record.id, "kind": "soul",
                "title": record.display_name,
                "subtitle": record.summary or record.kind_label,
            })
        for record in filter_by_search(self.dataset.effects, query):
            results.append({
                "type": "Hiệu ứng", "id": record.id, "kind": "effect",
                "title": record.display_name, "subtitle": record.description,
            })
        return results[:limit]
