"""Push the wiki data fixes to Supabase — only the rows that need changing.

    python tools/push_wiki_fixes.py                # dry run, writes nothing
    SUPABASE_SERVICE_ROLE_KEY=... python tools/push_wiki_fixes.py --apply

Four changes, and nothing else:

    delete   20 duplicate rows      the same figure filed twice
    update    2 name_en values      two SSR carrying a frog's romaji name
    insert    3 rows                Bishamonten, Fuzenkitsune, Ignis Suzuhikohime
    upload    3 portraits           into the `assets` bucket

**Why not `onmyoji_wiki/tools/migrate/upload_to_supabase.py`.** That uploader
upserts all 287 rows from the local JSON, and the two sides have drifted: the
local files carry richer `skills` on 259 records, but Supabase is richer on 7.
A bulk upsert would improve most of the table and quietly flatten those 7 — and
it has no delete, so the duplicates would survive it. Touching 20 rows on
purpose is safer than touching 287 by accident.

**Where the lists come from.** All three tables are imported from the app's own
`wiki` package, not copied here. The client-side patches and this script are
then the same data by construction, so the database and the app cannot end up
disagreeing about which rows are duplicates.

**Deleting is the irreversible part**, so it is gated twice: nothing writes
without `--apply`, and the dry run prints every row it would remove, by name, so
the list can be read before it is acted on. There is no undo.

Uses PostgREST over urllib rather than the `supabase` package, so this needs no
dependency the app does not already have — the same choice
`wiki/supabase_client.py` made.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "decompiled" / "source"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

import paths  # noqa: E402
from wiki import additions, config, duplicates  # noqa: E402

TABLE = "shikigami"
BUCKET = "assets"
TIMEOUT = 60
KEY_ENV = "SUPABASE_SERVICE_ROLE_KEY"

# The columns the table actually has, after migrations 0007-0009. `name_jp` was
# dropped and `role` never existed there, so both are left behind — sending
# either is an error, not a no-op.
COLUMNS = (
    "id", "name_vi", "name_en", "friendly_name", "rarity", "description",
    "obtain", "stats", "skills", "recommended_souls", "countered_by",
    "slot_mains", "lore", "image", "source_url", "sort_index", "is_finish",
)


def bucket_key(path: str) -> str:
    """A storage key, the way the uploader spells it."""
    if not path or path.startswith(("http://", "https://")):
        return path or ""
    for prefix in ("assets/images/", "assets/"):
        if path.startswith(prefix):
            return path[len(prefix):]
    return path


def row_for_db(record: Dict[str, Any]) -> Dict[str, Any]:
    """One hand-entered record reshaped to the table's columns."""
    row = {name: record.get(name) for name in COLUMNS if name in record}
    row["id"] = record["id"]
    row["rarity"] = (record.get("rarity") or "").upper()
    row["image"] = bucket_key(record.get("image") or "")
    row.setdefault("sort_index", 0)
    row.setdefault("is_finish", False)
    for name in COLUMNS:
        row.setdefault(name, "" if name.endswith(("_vi", "_en", "description",
                                                  "lore", "source_url")) else None)
    # Empty containers rather than nulls, matching what the uploader sends.
    for name, blank in (("friendly_name", []), ("obtain", []), ("stats", {}),
                        ("skills", []), ("recommended_souls", []),
                        ("countered_by", []), ("slot_mains", {})):
        if row.get(name) is None:
            row[name] = blank
    return row


class Rest:
    """The few PostgREST and Storage calls this needs."""

    def __init__(self, url: str, key: str, apply: bool) -> None:
        self.base = url.rstrip("/")
        self.key = key
        self.apply = apply

    def _send(self, method: str, path: str, body: Optional[bytes] = None,
              headers: Optional[Dict[str, str]] = None) -> Any:
        request = urllib.request.Request(
            self.base + path, data=body, method=method,
            headers={
                "apikey": self.key,
                "Authorization": "Bearer " + self.key,
                **(headers or {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise SystemExit("%s %s -> HTTP %s\n%s"
                             % (method, path, exc.code, detail))
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return None

    def select(self, ids: List[str]) -> List[Dict[str, Any]]:
        if not ids:
            return []
        joined = ",".join('"%s"' % i for i in ids)
        query = "?select=id,name_vi,name_en,rarity&id=in.(%s)" % urllib.parse.quote(joined)
        return self._send("GET", "/rest/v1/%s%s" % (TABLE, query)) or []

    def select_full(self, ids: List[str]) -> List[Dict[str, Any]]:
        """Whole rows, for working out what a survivor is missing."""
        if not ids:
            return []
        joined = ",".join('"%s"' % i for i in ids)
        columns = ",".join(COLUMNS)
        query = "?select=%s&id=in.(%s)" % (columns, urllib.parse.quote(joined))
        return self._send("GET", "/rest/v1/%s%s" % (TABLE, query)) or []

    def delete(self, ids: List[str]) -> int:
        if not ids or not self.apply:
            return 0
        joined = ",".join('"%s"' % i for i in ids)
        query = "?id=in.(%s)" % urllib.parse.quote(joined)
        got = self._send("DELETE", "/rest/v1/%s%s" % (TABLE, query),
                         headers={"Prefer": "return=representation"})
        return len(got or [])

    def patch(self, row_id: str, fields: Dict[str, Any]) -> int:
        if not self.apply:
            return 0
        query = "?id=eq.%s" % urllib.parse.quote(row_id)
        got = self._send(
            "PATCH", "/rest/v1/%s%s" % (TABLE, query),
            body=json.dumps(fields).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Prefer": "return=representation"},
        )
        return len(got or [])

    def insert(self, rows: List[Dict[str, Any]]) -> int:
        if not rows or not self.apply:
            return 0
        got = self._send(
            "POST", "/rest/v1/%s" % TABLE,
            body=json.dumps(rows).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Prefer": "return=representation,resolution=merge-duplicates"},
        )
        return len(got or [])

    def upload(self, key: str, data: bytes, content_type: str) -> bool:
        if not self.apply:
            return False
        self._send(
            "POST", "/storage/v1/object/%s/%s" % (BUCKET, urllib.parse.quote(key)),
            body=data,
            headers={"Content-Type": content_type, "x-upsert": "true"},
        )
        return True


def bundled_rows() -> Dict[str, Dict[str, Any]]:
    """Every original record, by id — including the ones being deleted.

    The local JSON still holds all 287 rows from before the fold, which is the
    only place the deleted halves' stats survive.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for rarity in ("ssr", "sr", "sp", "r", "n"):
        path = paths.DEFAULT_WIKI_DATA_DIR / "shikigami" / ("%s.json" % rarity)
        if not path.is_file():
            continue
        for row in json.loads(path.read_text(encoding="utf-8")):
            if isinstance(row, dict) and row.get("id"):
                out[row["id"]] = row
    return out


def merge_patches(live: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """What each kept row is missing that its deleted twin was carrying.

    **This is the step that was missed the first time round**, and it cost real
    data. The client folds the pairs at load time, filling the Vietnamese row's
    empty stats from the fandom row. Deleting the fandom rows from the database
    without first writing those stats onto the survivor left 18 records back at
    hp 0 — the fold had nothing left to read from. The numbers were recoverable
    only because the local JSON still had them.

    The filling is done by ``duplicates.merge_rows`` itself rather than
    reimplemented here, so the database ends up with exactly what the app would
    have shown. Only columns the table actually has are returned.
    """
    bundled = bundled_rows()
    patches: Dict[str, Dict[str, Any]] = {}
    for keep_id, drop_id in duplicates.PAIRS:
        keep, drop = live.get(keep_id), bundled.get(drop_id)
        if keep is None or drop is None:
            continue
        before = json.dumps(keep, sort_keys=True, ensure_ascii=False)
        merged = duplicates.merge_rows([dict(keep), dict(drop)])[0]
        if json.dumps(merged, sort_keys=True, ensure_ascii=False) == before:
            continue
        changed = {name: merged[name] for name in COLUMNS
                   if name in merged and merged.get(name) != keep.get(name)}
        changed.pop("id", None)
        if changed:
            patches[keep_id] = changed
    return patches


def delete_list() -> List[str]:
    """Rows to remove from Supabase: the folded-away half of every pair.

    Deduplicated, because one row can be dropped by two pairs — a figure whose
    Vietnamese half was renamed has one survivor for a pre-rename cache and
    another for the bundled file, and both name the same row to fold away.
    Listing it twice would print it twice and ask Supabase to delete something
    already gone.

    A function rather than a comprehension at the call site so the test and the
    script cannot drift apart about what gets deleted.
    """
    return list(dict.fromkeys(drop for _keep, drop in duplicates.PAIRS))


def portrait_files() -> List[Tuple[str, Path]]:
    """(bucket key, local file) for each hand-entered record's portrait."""
    out = []
    for record in additions.RECORDS:
        key = bucket_key(record.get("image") or "")
        if not key:
            continue
        local = paths.WIKI_ROOT / "assets" / "images" / key
        out.append((key, local))
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Push only the changed wiki rows")
    parser.add_argument("--apply", action="store_true",
                        help="thuc su ghi len Supabase (khong co thi chi in ra)")
    parser.add_argument("--skip-deletes", action="store_true",
                        help="lam moi thu tru viec xoa 20 dong trung")
    args = parser.parse_args(argv)

    settings = config.resolve()
    url = settings.url
    service = os.environ.get(KEY_ENV, "").strip()
    if not url:
        print("Khong tim thay SUPABASE_URL (xem onmyoji_wiki/.env)")
        return 1
    if args.apply and not service:
        print("Thieu %s — khoa anon chi doc duoc, RLS chan ghi." % KEY_ENV)
        print("  %s=... python tools/push_wiki_fixes.py --apply" % KEY_ENV)
        return 1

    # The dry run only reads, so the anon key is enough for it. Worth the extra
    # branch: it means the list of rows to be deleted can be read and checked
    # before anybody has to hand over a key that can delete them.
    key = service or settings.anon_key
    if not key:
        print("Khong co khoa nao ca (ca anon) — xem onmyoji_wiki/.env")
        return 1
    print("khoa dang dung: %s" % ("service_role (ghi duoc)" if service
                                  else "anon (chi doc — du cho dry run)"))
    print()

    rest = Rest(url, key, args.apply)
    drop_ids = delete_list()
    fix_ids = sorted(duplicates.WRONG_NAMES)
    new_rows = [row_for_db(record) for record in additions.RECORDS]

    print("=== 1. Xoa %d dong trung ===" % len(drop_ids))
    present = {row["id"]: row for row in rest.select(drop_ids)}
    for drop in drop_ids:
        row = present.get(drop)
        if row is None:
            print("   %-30s (khong con tren Supabase)" % drop)
        else:
            print("   %-30s %-6s %s" % (drop, row.get("rarity"),
                                        row.get("name_en") or row.get("name_vi")))
    missing = [i for i in drop_ids if i not in present]
    print("   -> co %d/%d dong that su ton tai" % (len(present), len(drop_ids)))

    keep_ids = [keep for keep, _drop in duplicates.PAIRS]
    live = {row["id"]: row for row in rest.select_full(keep_ids)}
    patches = merge_patches(live)
    print()
    print("=== 1b. Bu lai cho %d dong duoc giu nhung con thieu du lieu ==="
          % len(patches))
    for row_id, fields in sorted(patches.items()):
        hp = ((fields.get("stats") or {}).get("hp") or {}).get("value")
        print("   %-32s %s%s" % (row_id, ", ".join(sorted(fields)),
                                 "  (hp=%s)" % hp if hp else ""))
    if not patches:
        print("   (khong con gi thieu)")

    print()
    print("=== 2. Sua %d ten bi ghi ten ech ===" % len(fix_ids))
    for row_id in fix_ids:
        print("   %-30s -> %s" % (row_id, duplicates.WRONG_NAMES[row_id]))

    print()
    print("=== 3. Them %d thuc than ===" % len(new_rows))
    for row in new_rows:
        print("   %-30s %-6s %d ky nang" % (row["id"], row["rarity"],
                                            len(row.get("skills") or [])))

    print()
    print("=== 4. Tai %d anh len bucket '%s' ===" % (len(portrait_files()), BUCKET))
    for bkey, local in portrait_files():
        size = local.stat().st_size if local.is_file() else -1
        print("   %-44s %s" % (bkey, "%d KB" % (size // 1024) if size >= 0
                               else "THIEU FILE"))

    if not args.apply:
        print()
        print("DRY RUN — chua ghi gi. Doc lai muc 1 cho ky, xoa la khong hoan tac duoc.")
        print("Chay that: %s=... python tools/push_wiki_fixes.py --apply" % KEY_ENV)
        return 0

    absent = [bkey for bkey, local in portrait_files() if not local.is_file()]
    if absent:
        print("\nDung lai: thieu file anh %s" % absent)
        return 1

    print()
    for row_id, fields in sorted(patches.items()):
        print("da bu %s: %d dong" % (row_id, rest.patch(row_id, fields)))
    if patches:
        print("-> bu xong %d dong truoc khi xoa" % len(patches))
    if args.skip_deletes:
        print("bo qua buoc xoa (--skip-deletes)")
    else:
        removed = rest.delete([i for i in drop_ids if i in present])
        print("da xoa %d dong" % removed)
    for row_id in fix_ids:
        print("da sua %s: %d dong" % (row_id, rest.patch(row_id, duplicates.WRONG_NAMES[row_id])))
    print("da them/cap nhat %d dong" % rest.insert(new_rows))
    for bkey, local in portrait_files():
        kind = mimetypes.guess_type(bkey)[0] or "application/octet-stream"
        rest.upload(bkey, local.read_bytes(), kind)
        print("da tai %s" % bkey)
    print()
    print("Xong. Bam Dong bo trong tool de kiem tra, hoac chay lai script nay: "
          "muc 1 phai bao 0/%d dong ton tai." % len(drop_ids))
    if missing:
        print("Luu y: %d id trong bang PAIRS khong co tren Supabase — "
              "co the da duoc don truoc do." % len(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
