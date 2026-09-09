"""The effects table shows each effect's icon.

Every Effect record carries an `image` — `effects/gnaw.webp` and so on — and
the table never drew it. Measured on the shipped dataset, 2026-09-09: 59 of the
109 effects have a file, at 44x44 or 30x30. The other 50 name a file that does
not exist locally and is not in the Supabase bucket either (checked five of
them, none present), so the icon column has to tolerate a gap rather than
assume one.

The resolver is passed in rather than built here so the icons share the one
pixmap cache with the shikigami and soul grids — see wiki/images.py, where a
cache that does not cover its working set answers nothing at all.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from PyQt5 import QtWidgets  # noqa: E402

from ui import wiki_views  # noqa: E402


class Icons:
    """A resolver that hands back a pixmap for whatever it is told to."""

    def __init__(self, *, present=True):
        from PyQt5 import QtGui

        self.asked = []
        self._present = present
        self._pixmap = QtGui.QPixmap(44, 44)
        self._pixmap.fill(QtGui.QColor("#c08040"))

    def pixmap(self, field):
        self.asked.append(field)
        return self._pixmap if self._present else None


class Effect:
    """The parts of a record the row reads."""

    def __init__(self, record_id, image):
        self.id = record_id
        self.image = image
        self.display_name = "Cắn Xé"
        self.en_name = "Gnaw"
        self.kind = "buff"
        self.kind_label = "buff"
        self.description = "Đánh cắp máu."


def icons_in(row):
    from PyQt5 import QtGui

    found = []
    for child in row.findChildren(QtWidgets.QLabel):
        pixmap = child.pixmap()
        if isinstance(pixmap, QtGui.QPixmap) and not pixmap.isNull():
            found.append(child)
    return found


def test_a_row_draws_the_effect_icon(qt_app):
    resolver = Icons()
    view = wiki_views.EffectsView(resolver)

    row = view._build_row(Effect("gnaw", "effects/gnaw.webp"))

    assert resolver.asked == ["effects/gnaw.webp"]
    assert icons_in(row), "the row drew no icon"


def test_the_icon_column_is_the_same_width_with_or_without_a_picture(qt_app):
    """Fifty of the 109 have no file. If the column collapsed for those, every
    name and category below would shift left of the ones above it."""
    with_picture = wiki_views.EffectsView(Icons())._build_row(
        Effect("gnaw", "effects/gnaw.webp"))
    without = wiki_views.EffectsView(Icons(present=False))._build_row(
        Effect("bat", "effects/bat.webp"))

    def first_column(row):
        layout = row.layout().itemAt(0).layout()
        return layout.itemAt(0).widget().width()

    assert first_column(with_picture) == first_column(without)


def test_a_missing_icon_is_not_an_error(qt_app):
    """A record naming a file nobody ever made is the ordinary case here."""
    view = wiki_views.EffectsView(Icons(present=False))

    row = view._build_row(Effect("bat", "effects/bat.webp"))

    assert icons_in(row) == []
    assert row is not None


def test_a_record_with_no_image_field_is_not_asked_about(qt_app):
    resolver = Icons()
    view = wiki_views.EffectsView(resolver)

    view._build_row(Effect("nameless", ""))

    assert resolver.asked == []


def test_the_header_still_lines_up_with_the_rows(qt_app):
    """The header gained a column too, or the captions sit over the wrong
    data."""
    resolver = Icons()
    view = wiki_views.EffectsView(resolver)
    row = view._build_row(Effect("gnaw", "effects/gnaw.webp"))

    header = view._header.layout()
    body = row.layout().itemAt(0).layout()
    widths = [header.itemAt(i).widget().width() for i in range(2)]
    row_widths = [body.itemAt(i).widget().width() for i in range(2)]

    assert widths == row_widths, "header columns do not match the row's"
