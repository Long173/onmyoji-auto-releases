"""User-proposed wiki edits, and the owner's approval step.

Nothing a user does here touches the live table. Edits go into
``shikigami_submissions`` as *proposals*, and only the owner's approval copies one
into ``shikigami``. That shape is forced by a fact this project has already
demonstrated on itself: **anything shipped inside the app can be read out of it.**
The `contact` module was pulled from a released .exe in three lines, credentials
and all. So the app carries the anon key and nothing else, and the anon key is
allowed to INSERT proposals and nothing else.

The three roles, kept apart on purpose:

* **The app** (anon key, shipped to everyone) — writes a proposal. It cannot read
  other people's proposals, cannot change one, and cannot reach the live table.
  That is enforced by the database, not by this file: RLS grants anon `insert`
  only, and its `with check` refuses any row that does not arrive as `pending`.
* **The review step** (service_role key, the owner's machine only) — lists what
  is waiting, and approves or rejects. The key is typed in by the owner and kept
  in their own settings; it is never part of a build.
* **This module** — the shape of a proposal, and the two operations, so the UI
  and any tool agree on both.

A rejected proposal is kept rather than deleted. Somebody who submits nonsense
twice is worth being able to see, and a queue that forgets what it refused
invites the same argument twice.
"""
from __future__ import annotations

import base64
import copy
import json
import logging
import re
import urllib.error
import urllib.parse
import unicodedata
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from wiki.config import SupabaseConfig

logger = logging.getLogger(__name__)

TABLE = "shikigami_submissions"
LIVE_TABLE = "shikigami"
TIMEOUT_SECONDS = 20

ADD = "add"
EDIT = "edit"
DELETE = "delete"
KINDS = (ADD, EDIT, DELETE)

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"

# The database refuses anything longer, so the app should not send it and then
# report a failure it could have explained. Kept a little under the SQL guard of
# 20000 so a rejection here is always the app's own doing.
MAX_PAYLOAD_CHARS = 19000


LINE = "line"
TEXT = "text"
CHOICE = "choice"
LIST = "list"

RARITIES = ("N", "R", "SR", "SSR", "SP")


@dataclass(frozen=True)
class FormField:
    """One thing a user may propose changing, and how to show it."""

    key: str
    label: str
    kind: str = LINE
    hint: str = ""
    choices: Tuple[str, ...] = ()


# What the form offers, in the order it offers it.
#
# The nested columns — ``skills``, ``stats``, ``slot_mains`` — are deliberately
# absent. A text box cannot express a skill table, and offering one would let
# somebody flatten a record's skills by filling in a box they misunderstood.
# They are carried through an edit untouched by :func:`apply_edits`.
FORM_FIELDS: Tuple[FormField, ...] = (
    FormField("name_vi", "Tên tiếng Việt", LINE),
    FormField("name_en", "Tên tiếng Anh", LINE),
    FormField("rarity", "Độ hiếm", CHOICE, choices=RARITIES),
    FormField("friendly_name", "Tên gọi khác", LIST, "Mỗi tên một dòng, hoặc cách nhau bằng dấu phẩy"),
    FormField("description", "Mô tả", TEXT),
    FormField("obtain", "Cách nhận", LIST, "Mỗi cách một dòng"),
    FormField("recommended_souls", "Ngự hồn gợi ý", LIST, "Mã ngự hồn, mỗi mã một dòng"),
    FormField("countered_by", "Bị khắc chế bởi", LIST, "Mã thức thần, mỗi mã một dòng"),
    FormField("lore", "Cốt truyện", TEXT),
)

FIELDS_BY_KEY = {f.key: f for f in FORM_FIELDS}

# Long enough for every real name, short enough that an id stays a handle.
MAX_ID_CHARS = 48


# What a skill looks like on the server, measured across all 270 records:
#
#   name  image  description  levels   784 skills carry all four
#   cost                               139
#   effects  alt_forms                 22
#   levels[] = {level: int, description: text}   1501 of them
#
# The form shows the first four and nothing else. The rest is carried through
# untouched, which is the whole reason these helpers exist: approval upserts the
# entire row, so a key this code forgets is a key the database loses.
SKILL_TEXT_FIELDS = ("name", "description")
DEFAULT_SKILL_LEVELS = 5


def read_skills(row: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """A working copy of a record's skills, safe to edit in place.

    Deep-copied on purpose. The editor mutates what it is given as boxes are
    typed in, and sharing structure with the row it was read from would let a
    cancelled edit stick.
    """
    skills = row.get("skills")
    if not isinstance(skills, (list, tuple)):
        return []
    return [copy.deepcopy(skill) for skill in skills if isinstance(skill, dict)]


def blank_skill(levels: int = DEFAULT_SKILL_LEVELS) -> Dict[str, Any]:
    """An empty skill with the usual number of levels.

    Five, because that is what the data has — 1501 levels across 784 skills,
    almost all of them 1 to 5. Somebody adding a skill should be filling boxes
    in, not first working out how many to ask for.
    """
    return {
        "name": "",
        "description": "",
        # 1 through 5 — the shape 271 of the server's skills have. Level 1 is
        # not shown as a box; it is filled from the description, which is why it
        # is here at all.
        "levels": [{"level": n, "description": ""} for n in range(1, levels + 1)],
    }


def editable_levels(skill: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """The level rows a user may type into: everything but level 1.

    Level 1 is the skill's description. Measured on the server: of the 291
    skills that have a level 1, 290 have it identical to the description
    character for character, and the odd one out differs by two characters near
    the end. Offering both as boxes is offering one sentence twice, and the copy
    that gets left behind is the one the level table shows.
    """
    return [entry for entry in (skill.get("levels") or [])
            if isinstance(entry, Mapping) and entry.get("level") != 1]


def clean_skills(skills: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The skills as they should be sent: trimmed, tidied, nothing lost.

    * A skill with no name is a row somebody added and thought better of, so it
      goes — otherwise every accidental "+ Thêm kỹ năng" ships an empty skill.
    * A level with no text goes the same way, which is what lets a five-row
      template serve a three-level skill.
    * **Level numbers are left exactly as they are.** Renumbering by position
      looked tidier and was wrong: ten skills carry two concatenated forms and
      are numbered ``1,2,3,4,5,2,3,4,5``, which positional renumbering turned
      into ``1..9`` — a shape the game does not have. Only a row that arrived
      without a number gets one, which means only a row just added in the
      editor.
    * A stored level 1 is rewritten from the description, and dropped with it.
      Nothing here *creates* a level 1: 484 skills have no levels at all and 9
      start at 2, and an edit must not invent a level table for them.
    """
    cleaned: List[Dict[str, Any]] = []
    for skill in skills or []:
        if not isinstance(skill, Mapping):
            continue
        kept = dict(skill)
        for field in SKILL_TEXT_FIELDS:
            kept[field] = str(kept.get(field) or "").strip()
        if not kept["name"]:
            continue

        levels: List[Dict[str, Any]] = []
        highest = 0
        for entry in (kept.get("levels") or []):
            if not isinstance(entry, Mapping):
                continue
            step = dict(entry)
            if step.get("level") == 1:
                # It is the description, and it is kept only as long as there
                # is one.
                if not kept["description"]:
                    continue
                step["description"] = kept["description"]
            else:
                text = str(step.get("description") or "").strip()
                if not text:
                    continue
                step["description"] = text
                if not isinstance(step.get("level"), int):
                    step["level"] = max(highest + 1, 2)
            highest = max(highest, step["level"] if isinstance(step.get("level"), int) else 0)
            levels.append(step)
        kept["levels"] = levels
        cleaned.append(kept)
    return cleaned


def slugify(name: str) -> str:
    """An id, from a name.

    Generated rather than typed. The id is the primary key and approving an
    ``add`` upserts on it, so a typo makes a second record and a collision
    silently overwrites an existing one — asking a contributor to invent one was
    asking them to get a database key right.

    Fed the **English/romaji** name, which is what ``shikigami`` ids are
    standardised on as of migration 0011 and what ``souls`` always used. Before
    that the table held a mix, and 97 records were renamed; deriving new ids
    from the Vietnamese name would have started the mixture over again.

    Measured on all 270 live records: every one has an English name, and the ids
    this produces from them are unique — no collisions, none empty.

    Returns an empty string when there is nothing usable, which the caller has
    to notice; sending an empty primary key would be worse than refusing.
    """
    text = str(name or "")
    # "Linh Ngạn Cơ (Suzuhiko Hime)/Linda" is one shikigami with three names.
    # The id is the first of them, which is also what the stored record does.
    for separator in ("(", "/"):
        text = text.split(separator)[0]
    # NFD splits a letter from its accents so the accents can be dropped; đ is a
    # letter in its own right and survives that untouched, so it goes by hand.
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("Đ", "D").replace("đ", "d").lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    if len(text) <= MAX_ID_CHARS:
        return text
    # Cut at a word rather than mid-syllable, and never leave a trailing "_".
    return text[:MAX_ID_CHARS].rsplit("_", 1)[0].strip("_")

# Columns of ``shikigami`` that a write must not mention. Checked against the
# live table rather than guessed:
#
# * the three ``*_unaccent`` columns are ``generated always ... stored``
#   (migrations 0004 and 0006) and Postgres rejects any value for them;
# * ``created_at`` must survive an update, and leaving it out of the payload is
#   what makes the upsert's DO UPDATE leave it alone;
# * ``updated_at`` has a ``before update`` trigger that sets it, so a value sent
#   here would only be a worse one.
#
# One of these in a payload fails the whole upsert, taking the rest of the
# proposal with it — which is why they are removed twice: when a proposal is
# built, and again when one is approved, since a proposal queued by an older
# build carries whatever that build sent.
UNWRITABLE_COLUMNS = frozenset({
    "name_vi_unaccent",
    "name_en_unaccent",
    "friendly_name_unaccent",
    "created_at",
    "updated_at",
})


def writable(row: Mapping[str, Any]) -> Dict[str, Any]:
    """A copy of ``row`` without the columns the database refuses."""
    return {key: value for key, value in row.items()
            if key not in UNWRITABLE_COLUMNS}


class SubmissionError(RuntimeError):
    """Something went wrong; the message is safe to show a user."""


@dataclass(frozen=True)
class Submission:
    """One proposed change, as it comes back from the queue."""

    id: int
    kind: str
    target_id: str
    payload: Dict[str, Any]
    author: str
    created_at: str
    status: str = PENDING
    app_version: str = ""
    review_note: str = ""

    @property
    def is_pending(self) -> bool:
        return self.status == PENDING

    @property
    def when(self) -> str:
        """When it was submitted, in the reader's own time.

        Postgres stores `timestamptz` and PostgREST serialises it in UTC, so
        printing the string as it arrives shows the reviewer somebody else's
        clock: a proposal sent at 18:49 in Vietnam was listed as 11:49. Seven
        hours is enough to move it to the wrong day.

        Anything unparsable is passed through unchanged — a stamp nobody can
        read still says more than a blank where a date should be.
        """
        raw = (self.created_at or "").strip()
        if not raw:
            return ""
        try:
            moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return raw
        if moment.tzinfo is None:
            # What the server means when it leaves the offset off.
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone().strftime("%Y-%m-%d %H:%M")

    @property
    def describes(self) -> str:
        """A one-line summary for a list."""
        name = (self.payload or {}).get("name_vi") or (self.payload or {}).get("name_en")
        who = name or self.target_id or "(không rõ)"
        return "%s · %s" % ({ADD: "Thêm", EDIT: "Sửa", DELETE: "Xoá"}.get(
            self.kind, self.kind), who)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Submission":
        payload = row.get("payload")
        if isinstance(payload, str):
            # PostgREST returns jsonb as parsed JSON, but a column that was
            # written as text comes back as a string. Read both rather than
            # crash on the one that was not expected.
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                payload = {}
        return cls(
            id=int(row.get("id") or 0),
            kind=str(row.get("kind") or ""),
            target_id=str(row.get("target_id") or ""),
            payload=payload if isinstance(payload, dict) else {},
            author=str(row.get("author") or ""),
            created_at=str(row.get("created_at") or ""),
            status=str(row.get("status") or PENDING),
            app_version=str(row.get("app_version") or ""),
            review_note=str(row.get("review_note") or ""),
        )


def build(kind: str, payload: Optional[Dict[str, Any]] = None,
          target_id: str = "", author: str = "", app_version: str = "") -> Dict[str, Any]:
    """The row an app sends. Validated here so a rejection is explainable.

    ``status`` is set to pending explicitly rather than left to the column
    default. The database's own check insists on it, and sending it makes that
    agreement visible from this side instead of only in the SQL.
    """
    if kind not in KINDS:
        raise SubmissionError("Loại góp ý không hợp lệ: %r" % kind)
    if kind in (EDIT, DELETE) and not target_id:
        raise SubmissionError("Sửa hoặc xoá thì phải nói rõ thức thần nào.")
    if kind in (ADD, EDIT) and not payload:
        raise SubmissionError("Chưa có nội dung nào để gửi.")
    if kind in (ADD, EDIT) and not str((payload or {}).get("id") or "").strip():
        # Refused here rather than at the two call sites. :func:`approve` cannot
        # write a row with no primary key, so a proposal without one is one the
        # owner can only ever reject — better not to let it into the queue, and
        # better to say so while the person who typed it is still looking.
        raise SubmissionError("Chưa có mã (id) cho thức thần.")
    body = {
        "kind": kind,
        "target_id": target_id or None,
        "payload": writable(payload) if payload else None,
        "author": (author or "").strip()[:80] or None,
        "app_version": (app_version or "").strip()[:20] or None,
        "status": PENDING,
    }
    if len(json.dumps(body.get("payload"), ensure_ascii=False)) > MAX_PAYLOAD_CHARS:
        raise SubmissionError("Nội dung quá dài, hãy bớt lại.")
    return body


# ── talking to the queue ────────────────────────────────────────────────────


def _request(config: SupabaseConfig, table: str, key: str, method: str = "GET",
             params: str = "", body: Any = None, prefer: str = "") -> Any:
    url = "%s/%s" % (config.rest_endpoint, table)
    if params:
        url += "?" + params
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {
        "apikey": key,
        "Authorization": "Bearer " + key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        if exc.code == 404 and TABLE in detail:
            raise SubmissionError(
                "Chưa có bảng góp ý trên server. Chạy "
                "supabase/migrations/0010_submissions.sql một lần trong SQL "
                "Editor của Supabase."
            ) from exc
        raise SubmissionError("Server trả lỗi %s: %s" % (exc.code, detail)) from exc
    except urllib.error.URLError as exc:
        raise SubmissionError("Không kết nối được server: %s" % exc.reason) from exc
    except json.JSONDecodeError as exc:
        raise SubmissionError("Server trả về dữ liệu không đọc được.") from exc


def submit(config: SupabaseConfig, row: Dict[str, Any]) -> None:
    """Send one proposal, with the anon key. Raises on failure.

    Deliberately returns nothing. Anon has no `select` on the queue, so there is
    no row to read back — and a "here is your submission id" that anon could
    then not look up would be a promise the database does not keep.
    """
    if not config.is_configured:
        raise SubmissionError("Chưa cấu hình Supabase.")
    _request(config, TABLE, config.anon_key, "POST", body=[row],
             prefer="return=minimal")
    logger.info("Submitted a %s proposal for %r", row.get("kind"), row.get("target_id"))


def pending(config: SupabaseConfig, service_key: str,
            limit: int = 200) -> List[Submission]:
    """What is waiting for the owner. Needs the service_role key."""
    _needs_key(service_key)
    params = urllib.parse.urlencode({
        "select": "*",
        "status": "eq." + PENDING,
        "order": "created_at.asc",
        "limit": str(limit),
    })
    rows = _request(config, TABLE, service_key, "GET", params=params) or []
    return [Submission.from_row(row) for row in rows]


def reject(config: SupabaseConfig, service_key: str, submission_id: int,
           note: str = "") -> None:
    """Mark one refused, and keep it.

    Kept rather than deleted so the same proposal does not come back as a
    surprise, and so a repeat offender is visible.
    """
    _needs_key(service_key)
    _mark(config, service_key, submission_id, REJECTED, note)


def approve(config: SupabaseConfig, service_key: str, submission: Submission,
            note: str = "") -> None:
    """Apply one proposal to the live table, then mark it approved.

    In that order, and it matters. If the write to ``shikigami`` fails the
    proposal stays pending and can be tried again; marking it approved first
    would lose the change with the queue claiming it had been applied.
    """
    _needs_key(service_key)
    if submission.kind == DELETE:
        _request(config, LIVE_TABLE, service_key, "DELETE",
                 params=urllib.parse.urlencode({"id": "eq." + submission.target_id}),
                 prefer="return=minimal")
    else:
        row = writable(submission.payload)
        if submission.kind == EDIT:
            row["id"] = submission.target_id
        if not row.get("id"):
            raise SubmissionError("Góp ý này không có id thức thần để ghi.")
        # Upsert: an `add` whose id already exists is a correction rather than a
        # duplicate, and a second identical approval should not fail.
        _request(config, LIVE_TABLE, service_key, "POST", body=[row],
                 prefer="resolution=merge-duplicates,return=minimal")
    _mark(config, service_key, submission.id, APPROVED, note)
    logger.info("Approved submission %d (%s %s)", submission.id,
                submission.kind, submission.target_id)


@dataclass(frozen=True)
class BatchResult:
    """What a batch did, split into what worked and what did not.

    Both halves, always. A batch that reports only its successes leaves the
    caller unable to say which rows are still waiting, and a batch that raises
    on the first failure leaves the queue half-settled with no record of where
    it stopped.
    """

    applied: List["Submission"] = field(default_factory=list)
    failures: List[Tuple["Submission", str]] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if not self.failures:
            return "Đã xử lý %d góp ý." % len(self.applied)
        return ("Đã xử lý %d, %d góp ý lỗi: %s"
                % (len(self.applied), len(self.failures),
                   "; ".join("#%d %s" % (row.id, reason)
                             for row, reason in self.failures[:3])))


def _each(config: SupabaseConfig, service_key: str,
          rows: Iterable["Submission"], settle) -> BatchResult:
    """Run one operation over several proposals, one at a time.

    Sequential on purpose. Each approval is two writes that must stay in order —
    the live table, then the queue — and running them concurrently would
    interleave the pairs for no gain worth having on a list this size.
    """
    _needs_key(service_key)
    result = BatchResult()
    for row in rows or []:
        try:
            settle(row)
        except SubmissionError as exc:
            result.failures.append((row, str(exc)))
            logger.warning("Batch: #%s failed: %s", row.id, exc)
            continue
        result.applied.append(row)
    return result


def apply_many(config: SupabaseConfig, service_key: str,
               rows: Iterable["Submission"], note: str = "") -> BatchResult:
    """Approve several proposals, keeping every guarantee of approving one."""
    return _each(config, service_key, rows,
                 lambda row: approve(config, service_key, row, note))


def reject_many(config: SupabaseConfig, service_key: str,
                rows: Iterable["Submission"], note: str = "") -> BatchResult:
    """Refuse several proposals, keeping every one of them."""
    return _each(config, service_key, rows,
                 lambda row: reject(config, service_key, row.id, note))


def _mark(config: SupabaseConfig, service_key: str, submission_id: int,
          status: str, note: str) -> None:
    _request(
        config, TABLE, service_key, "PATCH",
        params=urllib.parse.urlencode({"id": "eq.%d" % submission_id}),
        body={
            "status": status,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "review_note": (note or "").strip()[:500] or None,
        },
        prefer="return=minimal",
    )


def _needs_key(service_key: str) -> None:
    if not (service_key or "").strip():
        raise SubmissionError(
            "Bước duyệt cần service_role key — dán vào Cài đặt chung."
        )


# ── the form, as text ───────────────────────────────────────────────────────


def read_values(row: Mapping[str, Any]) -> Dict[str, str]:
    """One editable string per form field, for filling the boxes in.

    Everything comes back as ``str``, including the fields the row does not
    have. A form that has to keep asking "is this None or missing or empty"
    grows a branch per field; a form that is handed text does not.
    """
    values: Dict[str, str] = {}
    for spec in FORM_FIELDS:
        raw = row.get(spec.key)
        if spec.kind == LIST:
            values[spec.key] = "\n".join(
                str(item) for item in (raw or []) if str(item).strip()
            ) if isinstance(raw, (list, tuple)) else str(raw or "")
        else:
            values[spec.key] = str(raw if raw is not None else "")
    return values


def apply_edits(row: Mapping[str, Any], values: Mapping[str, str]) -> Dict[str, Any]:
    """A copy of ``row`` with the form's fields set from ``values``.

    A *copy*: the caller's row is what is on screen, and mutating it would make
    a cancelled edit stick.

    Fields the form does not know about are copied through untouched, which is
    the whole point. Approving an edit upserts the row it is given, so anything
    missing here would be missing from the database — an edit to a name would
    quietly delete the skill table. Keys in ``values`` that are not form fields
    are ignored rather than written, so a caller cannot set ``status`` or any
    other column through this door.
    """
    edited = dict(row)
    for key, text in values.items():
        spec = FIELDS_BY_KEY.get(key)
        if spec is None:
            continue
        if spec.kind == LIST:
            edited[key] = split_list(text)
        else:
            edited[key] = (text or "").strip()
    return edited


def split_list(text: str) -> List[str]:
    """Lines or commas, whichever the user reached for. Blanks dropped."""
    parts: Iterable[str] = (text or "").replace(",", "\n").splitlines()
    return [part.strip() for part in parts if part.strip()]


# ── the row being edited ────────────────────────────────────────────────────


def fetch_live(config: SupabaseConfig, target_id: str) -> Dict[str, Any]:
    """The current live row, read with the anon key.

    An edit is built on this rather than on the app's cached copy. The cache can
    be weeks old, and since approval upserts the whole row, editing a stale copy
    would silently revert every change made since that cache was written.
    """
    if not config.is_configured:
        raise SubmissionError("Chưa cấu hình Supabase.")
    rows = _request(config, LIVE_TABLE, config.anon_key, "GET", params=urllib.parse.urlencode({
        "select": "*",
        "id": "eq." + target_id,
        "limit": "1",
    })) or []
    if not rows:
        raise SubmissionError("Không tìm thấy thức thần %r trên server." % target_id)
    return rows[0]


SECRET_PREFIX = "sb_secret_"
PUBLISHABLE_PREFIX = "sb_publishable_"


def looks_like_service_key(key: str) -> bool:
    """Whether a pasted key is the one that may write the live table.

    Checked locally, and only to catch the likely mistake: pasting the key the
    app already ships into the review box, which the server would answer with a
    permission error that reads like a bug. This is not a security check — no
    signature is verified and none could be — the database decides what a key
    may do.

    Supabase issues two shapes and both have to be understood. The legacy pair
    are JWTs carrying a ``role`` claim. The current pair are opaque strings that
    announce themselves in the prefix, and this originally knew only about the
    JWTs — which refused a perfectly good ``sb_secret_`` key and left the review
    window locked with no way in.
    """
    text = (key or "").strip()
    if text.startswith(PUBLISHABLE_PREFIX):
        return False
    if text.startswith(SECRET_PREFIX):
        return len(text) > len(SECRET_PREFIX)
    parts = text.split(".")
    if len(parts) != 3:
        return False
    body = parts[1]
    body += "=" * (-len(body) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(body.encode("ascii")))
    except (ValueError, TypeError, json.JSONDecodeError):
        return False
    return isinstance(claims, dict) and claims.get("role") == "service_role"
