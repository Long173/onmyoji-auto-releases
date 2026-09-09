"""Read-only PostgREST client for the wiki tables.

Deliberately built on ``urllib`` from the standard library rather than the
``supabase`` package: three GETs against a public read-only API do not justify
a dependency tree, and this keeps the desktop app installable with the same
requirements file as before.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Sequence

from wiki.config import SupabaseConfig

logger = logging.getLogger(__name__)

PAGE_SIZE = 500
TIMEOUT_SECONDS = 20
# PostgREST refuses an unbounded select on large tables; ask for pages instead.
MAX_PAGES = 40

TABLE_ORDER: Dict[str, Sequence[str]] = {
    "shikigami": ("rarity.asc", "sort_index.asc"),
    "souls": ("kind.asc", "sort_index.asc"),
    "effects": ("kind.asc", "sort_index.asc"),
    "manifest": ("collection.asc",),
}


class SupabaseError(RuntimeError):
    """A request to Supabase failed. The message is safe to show a user."""


class SupabaseClient:
    def __init__(self, config: SupabaseConfig) -> None:
        if not config.is_configured:
            raise SupabaseError("Chưa cấu hình Supabase URL và anon key.")
        self._config = config

    # ── requests ────────────────────────────────────────────────────────────

    def _get(self, path: str, params: Dict[str, Any]) -> Any:
        url = "%s/%s?%s" % (
            self._config.rest_endpoint,
            path,
            urllib.parse.urlencode(params, doseq=True),
        )
        request = urllib.request.Request(
            url,
            headers={
                "apikey": self._config.anon_key,
                "Authorization": "Bearer " + self._config.anon_key,
                "Accept": "application/json",
                "Accept-Profile": "public",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise SupabaseError(
                "Supabase trả về lỗi %s cho bảng %s: %s" % (exc.code, path, detail)
            ) from exc
        except urllib.error.URLError as exc:
            raise SupabaseError("Không kết nối được Supabase: %s" % exc.reason) from exc
        except json.JSONDecodeError as exc:
            raise SupabaseError("Supabase trả về dữ liệu không hợp lệ.") from exc

    def fetch_table(self, table: str) -> List[Dict[str, Any]]:
        """Every row of ``table``, walked one page at a time."""
        rows: List[Dict[str, Any]] = []
        for page in range(MAX_PAGES):
            params: Dict[str, Any] = {
                "select": "*",
                "limit": PAGE_SIZE,
                "offset": page * PAGE_SIZE,
            }
            order = TABLE_ORDER.get(table)
            if order:
                params["order"] = ",".join(order)
            batch = self._get(table, params)
            if not isinstance(batch, list):
                raise SupabaseError("Bảng %s trả về dữ liệu không phải danh sách." % table)
            rows.extend(batch)
            if len(batch) < PAGE_SIZE:
                return rows
        logger.warning("Stopped paging %s after %d pages", table, MAX_PAGES)
        return rows

    def fetch_manifest(self) -> Dict[str, int]:
        """collection -> version, used to decide whether a re-sync is needed."""
        rows = self.fetch_table("manifest")
        versions: Dict[str, int] = {}
        for row in rows:
            collection = str(row.get("collection") or "")
            if collection:
                versions[collection] = int(row.get("version") or 0)
        return versions

    # ── storage ─────────────────────────────────────────────────────────────

    def storage_url(self, key: str) -> str:
        """Public CDN URL for an object in the ``assets`` bucket."""
        return "%s/assets/%s" % (
            self._config.storage_endpoint,
            urllib.parse.quote(key.lstrip("/")),
        )

    def download(self, url: str) -> Optional[bytes]:
        """Fetch a public asset. Returns ``None`` rather than raising."""
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
                return response.read()
        except Exception:
            logger.debug("Asset download failed: %s", url, exc_info=True)
            return None
