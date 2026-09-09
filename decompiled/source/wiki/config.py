"""Where the Supabase credentials come from.

The anon key is safe to keep on disk: ``supabase/migrations/0002_rls.sql``
grants it SELECT and nothing else on the wiki tables. Resolution order, first
hit wins:

1. what the user typed into the wiki window (QSettings)
2. ``auto_ads/.env``
3. ``onmyoji_wiki/.env`` — so the Flutter app's credentials are reused
4. the process environment
5. the key built into the app

The last one is why a shipped build needs no setting up at all: see
:data:`BUNDLED_ANON_KEY` for why that key is safe to ship and what stops it
doing anything else.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from paths import APP_ROOT, WIKI_ROOT

logger = logging.getLogger(__name__)

URL_KEY = "SUPABASE_URL"
ANON_KEY = "SUPABASE_ANON_KEY"

# ── what a shipped build uses ───────────────────────────────────────────────
#
# Shipped on purpose, and safe to. Supabase calls this shape of key
# *publishable* because it is meant to live inside a client; what it may do is
# decided by row-level security on the server, not by keeping it secret.
# Measured against the live project:
#
#   * SELECT on the wiki tables — that is the whole point, it is public data;
#   * INSERT of a proposal that arrives as `pending` and carries no reviewer
#     fields — anything else is refused, `42501`;
#   * reading, changing or deleting the proposal queue — `401 permission
#     denied`, revoked outright rather than merely unpolicied;
#   * writing `shikigami` — `42501`.
#
# The alternative was making every user paste credentials before they could read
# a wiki page, in a tool meant to be handed to a game community. That is not a
# security measure, it is a locked door with the key taped to the README.
#
# The one real cost: nothing rate-limits inserts, so the queue can be spammed by
# anyone who extracts this. Rows are cheap and only the owner ever sees them.
#
# The key that *is* secret — the one that may write the live table — is never
# here. It is typed in on the owner's machine; see `load_service_key`.
BUNDLED_URL = "https://ghynhbhumsxsxwcoomij.supabase.co"
BUNDLED_ANON_KEY = "sb_publishable_OC-I7FCY19P60CCsPrAXhA_zw8MN8Xl"

# Beside the app first — that is where a packaged build's user would put one —
# then the Flutter project's, so a checkout reuses what is already configured.
ENV_FILES = (
    APP_ROOT / ".env",
    WIKI_ROOT / ".env",
)


@dataclass(frozen=True)
class SupabaseConfig:
    url: str = ""
    anon_key: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(self.url.strip() and self.anon_key.strip())

    @property
    def rest_endpoint(self) -> str:
        return self.url.rstrip("/") + "/rest/v1"

    @property
    def storage_endpoint(self) -> str:
        return self.url.rstrip("/") + "/storage/v1/object/public"


def read_env_file(path: Path) -> Dict[str, str]:
    """Parse a dotenv file. Blank lines, comments and quotes are handled."""
    values: Dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def resolve(stored: Optional[SupabaseConfig] = None) -> SupabaseConfig:
    """Best available credentials, or an empty config when there are none."""
    if stored is not None and stored.is_configured:
        return stored

    for path in ENV_FILES:
        if not path.is_file():
            continue
        values = read_env_file(path)
        candidate = SupabaseConfig(values.get(URL_KEY, ""), values.get(ANON_KEY, ""))
        if candidate.is_configured:
            logger.info("Supabase credentials loaded from %s", path)
            return candidate

    candidate = SupabaseConfig(os.environ.get(URL_KEY, ""), os.environ.get(ANON_KEY, ""))
    if candidate.is_configured:
        logger.info("Supabase credentials loaded from the environment")
        return candidate

    # Last, so a checkout or a fork pointing at its own project still wins.
    bundled = SupabaseConfig(BUNDLED_URL, BUNDLED_ANON_KEY)
    if bundled.is_configured:
        return bundled

    return SupabaseConfig()


URL_SETTING = "supabase_url"
ANON_SETTING = "supabase_anon_key"
# Remembered so a regular contributor does not retype their name every time.
# Here rather than in a UI module so the two places that write a proposal — the
# detail page and the delete dialog — cannot disagree on the spelling.
AUTHOR_SETTING = "submissionAuthor"


def load_config() -> SupabaseConfig:
    """The credentials this machine has, from settings then the fallbacks.

    Two callers now — the wiki page and the settings page — so the setting names
    live here rather than being spelled out at each one. A typo in the second
    copy would have read as "not configured yet" and quietly offered to set it
    up again.
    """
    import app_settings

    store = app_settings.open_store(app_settings.WIKI_SCOPE)
    return resolve(SupabaseConfig(
        str(store.value(URL_SETTING, "") or ""),
        str(store.value(ANON_SETTING, "") or ""),
    ))


# ── the owner's review key ──────────────────────────────────────────────────
#
# Kept apart from :class:`SupabaseConfig` on purpose. That object is passed
# around freely, gets logged, and is what a build ships; the service_role key
# bypasses every row-level policy in the database and belongs to exactly one
# machine. Keeping it out of the config object means no code path can send it
# somewhere by accident, because no code path is handed it unless it asks.
SERVICE_KEY_SETTING = "reviewServiceKey"


def load_service_key() -> str:
    """The service_role key this machine has stored, or an empty string."""
    import app_settings

    store = app_settings.open_store(app_settings.WIKI_SCOPE)
    return str(store.value(SERVICE_KEY_SETTING, "") or "").strip()


def save_service_key(key: str) -> None:
    """Store, or clear when given nothing."""
    import app_settings

    store = app_settings.open_store(app_settings.WIKI_SCOPE)
    key = (key or "").strip()
    if key:
        store.setValue(SERVICE_KEY_SETTING, key)
    else:
        store.remove(SERVICE_KEY_SETTING)
    logger.info("Review key %s", "stored" if key else "cleared")
