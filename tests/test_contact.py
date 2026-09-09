"""The contact details, and the two places they surface.

The point of these tests is that an *unfilled* build stays silent. Showing a
heading with nothing under it, or a release page advertising a blank Zalo
number, is worse than showing nothing at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PyQt5 import QtWidgets

import contact

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import publish_release  # noqa: E402 - needs the path above


FILLED = (("Facebook", "fb.com/someone"), ("Zalo", "0900 000 000"))


@pytest.fixture
def filled(monkeypatch):
    monkeypatch.setattr(contact, "CONTACTS", FILLED)
    return FILLED


@pytest.fixture
def empty(monkeypatch):
    monkeypatch.setattr(contact, "CONTACTS", ())


# ── the data ────────────────────────────────────────────────────────────────


def test_has_any_is_false_when_nothing_is_filled_in(empty):
    assert contact.has_any() is False


def test_has_any_is_false_when_every_value_is_blank(monkeypatch):
    monkeypatch.setattr(contact, "CONTACTS", (("Facebook", ""), ("Zalo", "   ")))
    assert contact.has_any() is False


def test_rows_drop_the_entries_with_no_value(monkeypatch):
    monkeypatch.setattr(
        contact, "CONTACTS", (("Facebook", "fb.com/x"), ("Zalo", ""))
    )
    assert contact.rows() == (("Facebook", "fb.com/x"),)


def test_rows_trim_surrounding_space(monkeypatch):
    monkeypatch.setattr(contact, "CONTACTS", (("Zalo", "  0900  "),))
    assert contact.rows() == (("Zalo", "0900"),)


def test_rows_keep_the_declared_order(filled):
    assert [name for name, _ in contact.rows()] == ["Facebook", "Zalo"]


# ── the release page ────────────────────────────────────────────────────────


def test_markdown_is_empty_when_nothing_is_filled_in(empty):
    assert contact.as_markdown() == ""


def test_markdown_lists_every_entry(filled):
    text = contact.as_markdown()
    assert "## Liên hệ" in text
    assert "fb.com/someone" in text
    assert "0900 000 000" in text


def test_release_body_appends_the_section_to_the_changelog(filled):
    body = publish_release.release_body("- Thêm phụ bản ngự hồn", "")
    assert body.startswith("- Thêm phụ bản ngự hồn")
    assert "fb.com/someone" in body


def test_release_body_falls_back_to_notes_when_there_is_no_changelog(filled):
    body = publish_release.release_body("", "Sửa lỗi bấm nhầm")
    assert "Sửa lỗi bấm nhầm" in body
    assert "fb.com/someone" in body


def test_release_body_is_only_the_changelog_when_no_contact_is_set(empty):
    assert publish_release.release_body("- Thêm phụ bản", "") == "- Thêm phụ bản"


def test_release_body_has_no_dangling_separator_when_nothing_is_set(empty):
    assert "---" not in publish_release.release_body("", "Sửa lỗi")


def test_release_body_does_not_start_with_a_separator_when_changelog_is_empty(filled):
    assert publish_release.release_body("", "").startswith("## Liên hệ")


# ── the settings dialog ─────────────────────────────────────────────────────


def _label_texts(widget: QtWidgets.QWidget) -> list:
    return [child.text() for child in widget.findChildren(QtWidgets.QLabel)]


def _dialog(qt_app):
    """The settings surface. A page in the main window since it outgrew a modal."""
    from ui.settings_page import SettingsPage

    return SettingsPage({})


def test_settings_page_shows_the_contact_details(qt_app, filled):
    texts = _label_texts(_dialog(qt_app))
    assert "LIÊN HỆ" in texts
    assert "fb.com/someone" in texts
    assert "0900 000 000" in texts


def test_settings_page_omits_the_heading_when_nothing_is_set(qt_app, empty):
    assert "LIÊN HỆ" not in _label_texts(_dialog(qt_app))


def test_settings_page_still_shows_the_version_block(qt_app, filled):
    """The contact block is an addition, not a replacement."""
    assert "PHIÊN BẢN" in _label_texts(_dialog(qt_app))


def test_settings_page_links_to_the_releases_page(qt_app, filled):
    """The one public address this app has. There is no source repo."""
    import updater

    texts = _label_texts(_dialog(qt_app))
    assert "TRANG PHÁT HÀNH" in texts
    assert any(updater.REPO_URL in text for text in texts), updater.REPO_URL


def test_the_link_is_the_same_address_the_updater_uses(qt_app):
    """Written out twice, the two would drift and one would point nowhere."""
    import updater

    assert updater.REPO_URL
    assert updater.DEFAULT_MANIFEST_URL.startswith(updater.REPO_URL + "/")


def test_the_link_opens_in_a_browser_and_can_still_be_copied(qt_app, filled):
    """Clickable is not enough: a machine with no browser, or a screen share."""
    from PyQt5 import QtCore
    import updater

    dialog = _dialog(qt_app)
    links = [child for child in dialog.findChildren(QtWidgets.QLabel)
             if updater.REPO_URL in child.text()]
    assert links, "no label carries the address"
    link = links[0]
    assert link.openExternalLinks()
    assert link.textInteractionFlags() & QtCore.Qt.TextSelectableByMouse
    dialog.deleteLater()


def test_the_releases_section_is_left_out_when_there_is_no_address(qt_app, monkeypatch):
    """A build with no account filled in shows nothing rather than a dead row."""
    import updater

    monkeypatch.setattr(updater, "REPO_URL", "")

    assert "TRANG PHÁT HÀNH" not in _label_texts(_dialog(qt_app))


def test_contact_values_can_be_selected_for_copying(qt_app, filled):
    """A number nobody can copy out is barely a contact detail."""
    from PyQt5 import QtCore

    # Held in a local: dropping the dialog frees its children mid-comprehension.
    dialog = _dialog(qt_app)
    selectable = [
        child.text()
        for child in dialog.findChildren(QtWidgets.QLabel)
        if child.textInteractionFlags() & QtCore.Qt.TextSelectableByMouse
    ]
    assert "fb.com/someone" in selectable
    assert "0900 000 000" in selectable


# ── the settings live in the window, not a dialog ───────────────────────────
#
# It was a modal, and outgrew one: rendered on its own the page stands 895 px
# tall, which is a lot of box to put in front of a window with room to spare.
# Moving it also settled an inconsistency — a task's own settings apply the
# moment they change, and this was the only screen with an OK button.


def test_the_sidebar_offers_settings_as_a_page(qt_app, dashboard):
    from ui.task_sidebar import SETTINGS

    assert SETTINGS in dashboard._sidebar._rows


def test_going_to_the_settings_page_shows_it(qt_app, dashboard):
    from ui.task_sidebar import SETTINGS

    dashboard._show_page(SETTINGS)

    assert dashboard._stack.currentWidget() is dashboard._settings_page
    assert dashboard._page == SETTINGS


def test_f9_goes_to_the_page_rather_than_opening_anything(qt_app, dashboard):
    from ui.task_sidebar import SETTINGS

    dashboard._open_settings()

    assert dashboard._page == SETTINGS


def test_a_change_applies_at_once_with_no_ok_button(qt_app, dashboard):
    import tasks

    dashboard._on_app_setting("notify_on_finish", True)

    assert tasks.as_bool(dashboard._manager.app_config.get("notify_on_finish"))


def test_the_page_rereads_the_registry_backed_switch_each_time(qt_app, dashboard, monkeypatch):
    """It can be switched off from Task Manager while the app is open."""
    import autostart
    from ui.task_sidebar import SETTINGS

    monkeypatch.setattr(autostart, "is_enabled", lambda: True)
    dashboard._show_page(SETTINGS)
    assert dashboard._settings_page.values()["start_with_windows"] is True

    monkeypatch.setattr(autostart, "is_enabled", lambda: False)
    dashboard._show_page(SETTINGS)

    assert dashboard._settings_page.values()["start_with_windows"] is False


def test_rereading_does_not_write_the_value_back(qt_app, dashboard, monkeypatch):
    """Re-seeding a switch must not look like the user having flicked it.

    Without blocking the control's signal, opening the page would report a
    change and the app would write back the value it had just read.
    """
    import autostart
    from ui.task_sidebar import SETTINGS

    written = []
    monkeypatch.setattr(autostart, "is_enabled", lambda: True)
    monkeypatch.setattr(autostart, "set_enabled",
                        lambda wanted: written.append(wanted) or True)

    dashboard._show_page(SETTINGS)

    assert written == []


def test_the_settings_page_scrolls(qt_app):
    """Unscrolled, the blocks at the bottom were simply out of reach.

    The content stands about 949 px tall — more than the window's content area
    on a laptop — so the version, contact and licence blocks below the switches
    could not be got to at all.
    """
    page = _dialog(qt_app)

    scroll = page.findChild(QtWidgets.QScrollArea)
    assert scroll is not None
    assert scroll.widgetResizable()
    assert scroll.widget().sizeHint().height() > 600, "nothing to scroll?"


def test_the_settings_page_is_inset_like_a_task_page(qt_app):
    """Text against the left edge of the window reads as a mistake."""
    page = _dialog(qt_app)
    scroll = page.findChild(QtWidgets.QScrollArea)

    margins = scroll.widget().layout().contentsMargins()

    assert margins.left() >= 24, margins.left()
    assert margins.left() == margins.right()
