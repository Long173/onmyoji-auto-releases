"""Switches for whole parts of the app.

One place, read by every entry point, so a part that is off is off everywhere
at once rather than hidden in one menu and still reachable from another.
"""
from __future__ import annotations

# The encyclopaedia — shikigami, souls and effects, synced from Supabase.
#
# Off since 3.19. Development stopped: others publish fuller data on the web,
# and the owner wants the tool to be the automation and nothing else. Its code
# is left intact — `ui/wiki_*`, `wiki/` and their tests — so this is the whole
# of turning it back on. While it is off the page is never built, so nothing
# syncs, downloads images or reads the bundled dataset in the background.
WIKI = False
