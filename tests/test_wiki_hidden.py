"""The encyclopaedia is switched off, not removed.

The owner stopped developing it — others publish fuller data on the web — and
asked for the tool to be the automation and nothing else. So it is hidden at
the one switch every entry point reads, and its code stays where it is: turning
it back on is a one-word change, and nothing else has to be rebuilt.

Hidden means unreachable, not merely unlisted. A page nobody can see that still
syncs from Supabase in the background, or opens from a stale shortcut, is the
feature still running with the lights off.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from PyQt5 import QtWidgets  # noqa: E402

import features  # noqa: E402
from ui.task_sidebar import HOME, wiki_key  # noqa: E402
from ui.wiki_page import SECTIONS  # noqa: E402


def test_it_is_off():
    """Pinned, so turning it back on is a decision someone makes on purpose."""
    assert features.WIKI is False


def test_the_sidebar_carries_no_encyclopaedia(dashboard):
    rows = dashboard._sidebar._rows
    for section, _name in SECTIONS:
        assert wiki_key(section) not in rows, "%s is still listed" % section


def test_the_sidebar_has_no_encyclopaedia_heading(dashboard):
    labels = [w.text() for w in dashboard._sidebar.findChildren(QtWidgets.QLabel)]
    assert not any("Bách khoa" in text for text in labels), labels


def test_asking_for_the_wiki_opens_nothing(dashboard):
    """`--wiki` from an old shortcut must not bring the page — or its sync — back."""
    dashboard.open_wiki()

    assert dashboard._wiki is None, "the wiki page was built anyway"
    assert dashboard._page == HOME


def test_a_wiki_page_key_is_not_routed(dashboard):
    dashboard._show_page(wiki_key(SECTIONS[0][0]))

    assert dashboard._wiki is None
    assert dashboard._page == HOME


def test_settings_carry_no_wiki_review_block(dashboard):
    labels = [w.text() for w in dashboard._settings_page.findChildren(QtWidgets.QLabel)]
    assert not any("góp ý wiki" in text.lower() for text in labels), labels


# ── the build follows the same switch ───────────────────────────────────────


def spec_switch():
    """The spec's own reader, run on its own source — no PyInstaller needed."""
    import re
    from pathlib import Path

    spec = (Path(__file__).resolve().parents[1] / "onmyoji_auto.spec").read_text(
        encoding="utf-8")
    start = spec.index("def wiki_switch(")
    end = spec.index("\nWIKI_ON", start)
    namespace = {"re": re}
    exec(spec[start:end], namespace)
    return namespace["wiki_switch"]


def test_the_build_reads_the_switch_the_app_reads():
    """23 MB of dataset ships only while the wiki is on, and the build decides
    that from features.py. If its reader and the app disagree, the download
    either carries dead weight or a re-enabled wiki ships with no data."""
    from pathlib import Path

    source = (Path(features.__file__)).read_text(encoding="utf-8")
    assert spec_switch()(source) is features.WIKI


@pytest.mark.parametrize("line, expected", [
    ("WIKI = True", True),
    ("WIKI = False", False),
    ("WIKI=True", True),
    ("WIKI = True  # back on for 4.0", True),
    ("WIKI = False  # off since 3.19", False),
])
def test_the_build_s_reader_survives_ordinary_edits(line, expected):
    assert spec_switch()("# header\n%s\n" % line) is expected


def test_the_build_refuses_a_switch_it_cannot_read():
    with pytest.raises(SystemExit):
        spec_switch()("WIKI = os.environ.get('WIKI')\n")
