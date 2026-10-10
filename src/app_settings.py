"""Where the app's preferences live.

One function rather than a QSettings built at each call site, so there is a
single thing to redirect. Tests replace :func:`open_store` with one backed by a
temporary file; without that they would read and rewrite the real user's
settings in the Windows registry, and one test's saved task queue would decide
what the next test starts with.
"""
from __future__ import annotations

from PyQt5 import QtCore

import theme


WIKI_SCOPE = "Wiki"


def open_store(scope: str = theme.SETTINGS_SCOPE) -> QtCore.QSettings:
    """The user's preference store.

    ``scope`` separates unrelated groups of settings — the wiki keeps its
    Supabase credentials apart from the task settings. Every caller goes through
    here so a test can redirect all of them at once.
    """
    return QtCore.QSettings(theme.ORGANISATION, scope)
