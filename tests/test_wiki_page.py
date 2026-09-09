"""Wiki window rendering, and the stray-window bug that flashed popups.

A QWidget with no parent IS a top-level window. Calling ``setVisible(True)`` on
one before it has been added to a layout makes Qt map a real window on screen;
adding it to a layout a line later unmaps it. Doing that once per card meant a
burst of popups every time the shikigami list re-rendered — most visibly when
leaving a detail page.

The spy below fails on any widget that gets shown while it is still a window,
so the whole class of mistake is caught, not just the one instance of it.
"""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt5.QtWidgets")
from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


class StrayWindowSpy(QtCore.QObject):
    """Records every widget shown while it is still parentless."""

    def __init__(self):
        super().__init__()
        self.stray = []

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Show and isinstance(obj, QtWidgets.QWidget):
            if obj.isWindow():
                text = obj.text() if hasattr(obj, "text") else ""
                self.stray.append("%s(%r)" % (type(obj).__name__, text[:40]))
        return False


@pytest.fixture
def spy(qt_app):
    watcher = StrayWindowSpy()
    qt_app.installEventFilter(watcher)
    yield watcher
    qt_app.removeEventFilter(watcher)


@pytest.fixture
def wiki(qt_app, monkeypatch, tmp_path):
    """A WikiPage backed by a small dataset written to a temp directory."""
    data_dir = tmp_path / "data"
    (data_dir / "shikigami").mkdir(parents=True)

    # A mix: some records carry an other-language name, some do not — the
    # second line is shown for the first group and hidden for the second.
    (data_dir / "shikigami" / "ssr.json").write_text(json.dumps([
        {"id": "thien_cau", "name_vi": "Đại Thiên Cẩu", "name_en": "Daitengu",
         "rarity": "SSR", "description": "Sát thương diện rộng.",
         "skills": [{"name": "Phong Nhận", "description": "Gây sát thương."}]},
        {"id": "ibaraki", "name_vi": "Ibaraki Đồng Tử", "name_jp": "Ibaraki Doji",
         "rarity": "SSR"},
        {"id": "khong_ten_phu", "name_vi": "Không Tên Phụ", "rarity": "SSR"},
        # Worst case for layout: a very long name, long skill names, many tags.
        {"id": "dai_ten", "rarity": "SP",
         "name_vi": "Linh Ngạn Cơ (Suzuhiko Hime)/Linda Phiên Bản Rất Dài",
         "name_en": "Suzuhiko Hime Extended Edition Name",
         "friendly_name": ["Biệt danh một", "Biệt danh hai", "Biệt danh ba",
                           "Biệt danh bốn"],
         "description": "Mô tả dài " * 30,
         "slot_mains": {"2": ["atk_pct", "spd"], "4": ["hp_pct"],
                        "6": ["crit_pct", "crit_dmg_pct"]},
         "skills": [
             {"name": "LINH DIỄM CHƯỚC TÂM PHIÊN BẢN DÀI",
              "description": "Mô tả kỹ năng " * 20,
              "levels": [
                  # Level 1 repeats the description, as the real data does.
                  {"level": 1, "description": "Mô tả kỹ năng " * 20},
                  {"level": 2, "description": "Sát thương = 80%"},
                  {"level": 3, "description": "Sát thương = 85% " * 12},
              ]},
             {"name": "NGŨ SƠN HỎA TẾ", "description": "Ngắn."},
         ]},
    ]), encoding="utf-8")
    (data_dir / "souls.json").write_text(json.dumps([
        {"id": "ban_nguyet", "name_vi": "Bán Nguyệt", "kind": "normal",
         "effects": [{"pieces": 2, "description": "Tăng sát thương."}]},
    ]), encoding="utf-8")
    (data_dir / "effects.json").write_text(json.dumps([
        {"id": "choang", "name": "Choáng", "kind": "debuff", "description": "Mất lượt."},
    ]), encoding="utf-8")

    import ui.wiki_page as wiki_page
    from wiki.repository import WikiRepository

    def build_repository():
        repository = WikiRepository(data_dir)
        repository.cache_dir = tmp_path / "cache"
        return repository

    monkeypatch.setattr(wiki_page, "WikiRepository", build_repository)

    window = wiki_page.WikiPage()
    window.show()
    QtWidgets.QApplication.processEvents()
    yield window
    window.close()


def drain():
    QtWidgets.QApplication.processEvents()


# ── the reported bug ────────────────────────────────────────────────────────


def test_opening_the_list_shows_no_stray_windows(wiki, spy):
    wiki._render()
    drain()
    assert not spy.stray, "widgets were shown as windows: %s" % spy.stray


def test_detail_then_back_shows_no_stray_windows(wiki, spy):
    """The exact path that flashed popups: into a shikigami, then back."""
    wiki._open_shikigami("thien_cau")
    drain()
    spy.stray.clear()

    wiki._on_back()
    drain()

    assert not spy.stray, "going back flashed %d window(s): %s" % (
        len(spy.stray), spy.stray[:5]
    )


def test_repeated_navigation_stays_clean(wiki, spy):
    for record_id in ("thien_cau", "ibaraki", "khong_ten_phu"):
        wiki._open_shikigami(record_id)
        drain()
        wiki._on_back()
        drain()

    assert not spy.stray, "navigation flashed windows: %s" % spy.stray[:5]


def test_switching_tabs_shows_no_stray_windows(wiki, spy):
    for tab in ("souls", "effects", "shikigami"):
        wiki._on_nav(tab)
        drain()

    assert not spy.stray, "tab switching flashed windows: %s" % spy.stray[:5]


def test_searching_shows_no_stray_windows(wiki, spy):
    wiki._on_search("dai thien cau")
    drain()
    wiki._on_back()
    drain()

    assert not spy.stray, "search flashed windows: %s" % spy.stray[:5]


# ── the behaviour the setVisible call is there for ──────────────────────────


def test_second_line_is_shown_only_when_there_is_another_name(wiki):
    from ui.wiki_cards import ShikigamiCard
    from wiki.images import ImageResolver

    resolver = ImageResolver()
    with_name = ShikigamiCard(wiki._repository.shikigami_by_id("thien_cau"), resolver)
    without = ShikigamiCard(
        wiki._repository.shikigami_by_id("khong_ten_phu"), resolver
    )

    assert with_name._full_secondary == "Daitengu"
    assert without._full_secondary == ""
    # isVisible() needs a shown ancestor; isHidden() reports the explicit flag.
    assert not with_name._secondary.isHidden()
    assert without._secondary.isHidden(), "an empty second line still takes space"


# ── the detail page must fit, not scroll sideways ───────────────────────────
# Window minimum is 1040 wide; the sidebar takes 216 and its rule 1, leaving
# roughly 813 for content once the vertical scrollbar is accounted for. Content
# wider than that is clipped, because horizontal scrolling is switched off.

CONTENT_BUDGET = 813


def content_width(view):
    inner = view.findChild(QtWidgets.QScrollArea).widget()
    return inner.minimumSizeHint().width()


@pytest.mark.parametrize(
    "record_id", ["thien_cau", "ibaraki", "khong_ten_phu", "dai_ten"]
)
def test_shikigami_detail_fits_the_narrowest_window(wiki, record_id):
    wiki.resize(1040, 800)
    wiki._open_shikigami(record_id)
    drain()

    needed = content_width(wiki._shiki_detail)
    assert needed <= CONTENT_BUDGET, (
        "%s needs %dpx of width, only %dpx is available — the page would be "
        "clipped" % (record_id, needed, CONTENT_BUDGET)
    )


def test_soul_detail_fits_the_narrowest_window(wiki):
    wiki.resize(1040, 800)
    wiki._open_soul("ban_nguyet")
    drain()

    assert content_width(wiki._soul_detail) <= CONTENT_BUDGET


def test_long_names_wrap_instead_of_widening_the_page(wiki):
    """A single unwrapped title used to force the page past 1400px."""
    wiki._open_shikigami("dai_ten")
    drain()

    headings = [
        child
        for child in wiki._shiki_detail.findChildren(QtWidgets.QLabel)
        if child.text().startswith("Linh Ngạn Cơ")
    ]
    assert headings, "the heading was not found"
    assert headings[0].wordWrap(), "the heading does not wrap"


def test_skill_icon_slot_is_reserved_even_without_artwork(qt_app, tmp_path):
    """Every skill's text starts on the same edge, icon or not."""
    from ui.wiki_detail import SKILL_ICON, skill_icon
    from wiki.images import ImageResolver

    resolver = ImageResolver(tmp_path)
    resolver.cache_dir = tmp_path / "cache"

    empty = skill_icon(resolver, "")
    missing = skill_icon(resolver, "assets/images/skills/nope.webp")

    for slot in (empty, missing):
        assert slot.width() == SKILL_ICON
        assert slot.pixmap() is None or slot.pixmap().isNull()


def test_skill_level_count_is_no_longer_shown(wiki):
    wiki._open_shikigami("dai_ten")
    drain()

    texts = [
        child.text() for child in wiki._shiki_detail.findChildren(QtWidgets.QLabel)
    ]
    assert not any("CẤP" == text.split()[0] and "3 CẤP" in text for text in texts if text)
    assert "3 CẤP" not in texts, "the level-count caption is still rendered"


def test_skill_levels_are_rendered(wiki):
    wiki._open_shikigami("dai_ten")
    drain()

    texts = [
        child.text() for child in wiki._shiki_detail.findChildren(QtWidgets.QLabel)
    ]
    assert "CẤP 2" in texts, "the upgrade ladder is missing"
    assert "CẤP 3" in texts
    # Level 1 repeats the description and must not appear twice.
    assert texts.count("Mô tả kỹ năng " * 20) <= 1


def glyph_left(widget):
    """X of the first drawn glyph, honouring alignment and margins."""
    margins = widget.contentsMargins()
    metrics = QtGui.QFontMetrics(widget.font())
    inner = widget.width() - margins.left() - margins.right()
    offset = 0
    if widget.alignment() & QtCore.Qt.AlignRight:
        offset = inner - metrics.horizontalAdvance(widget.text())
    elif widget.alignment() & QtCore.Qt.AlignHCenter:
        offset = (inner - metrics.horizontalAdvance(widget.text())) // 2
    return margins.left() + offset


def glyph_baseline(widget):
    return widget.contentsMargins().top() + QtGui.QFontMetrics(widget.font()).ascent()


def test_level_tag_starts_on_the_same_edge_as_the_description(qt_app):
    """The tag was right-aligned in its column, so it sat slightly indented."""
    from ui.wiki_detail import level_row

    row = level_row("Cấp 2", "Sát thương = 80%")
    labels = row.findChildren(QtWidgets.QLabel)
    tag = next(child for child in labels if child.text() == "CẤP 2")

    assert glyph_left(tag) == 0, (
        "the level tag is indented by %dpx from its column edge" % glyph_left(tag)
    )


def test_level_tag_and_its_text_share_a_baseline(qt_app):
    """The tag is 10px mono, the text 13px body — top-aligning them misaligns."""
    from ui.wiki_detail import level_row

    row = level_row("Cấp 2", "Sát thương = 80%")
    labels = row.findChildren(QtWidgets.QLabel)
    tag = next(child for child in labels if child.text() == "CẤP 2")
    text = next(child for child in labels if child is not tag)

    drift = glyph_baseline(tag) - glyph_baseline(text)
    assert abs(drift) <= 1, "tag and text baselines differ by %dpx" % drift


def test_short_chips_do_not_wrap(wiki):
    """Wrapping every chip broke "tên gọi: Dơi SP" across two lines."""
    from ui.wiki_detail import outlined_chip

    short = outlined_chip("tên gọi: Dơi SP")
    long = outlined_chip("tên gọi: " + "rất dài " * 12)

    assert not short.wordWrap(), "a short chip was set to wrap"
    assert long.wordWrap(), "a long chip must wrap or it widens the page"


def test_slot_mains_render_in_vietnamese(wiki):
    wiki._open_shikigami("dai_ten")
    drain()

    texts = [
        child.text()
        for child in wiki._shiki_detail.findChildren(QtWidgets.QLabel)
    ]
    assert "Vị trí 2" in texts
    assert "Tấn công % / Tốc độ" in texts
    assert not any("atk_pct" in text for text in texts), "internal codes leaked"
    assert not any(text.startswith("[") for text in texts), "raw list syntax leaked"


def test_back_button_appears_only_in_detail(wiki):
    assert wiki._back.isHidden(), "back button visible on the list"

    wiki._open_shikigami("thien_cau")
    assert not wiki._back.isHidden(), "back button missing in detail"

    wiki._on_back()
    assert wiki._back.isHidden(), "back button stayed after returning"


# ── proposing changes, and who may approve them ─────────────────────────────


def _items(page, monkeypatch, service_key=""):
    """The contribute menu's entries, without showing it."""
    from wiki import config as wiki_config

    monkeypatch.setattr(wiki_config, "load_service_key", lambda: service_key)

    shown = {}

    def capture(self, point):
        shown["labels"] = [a.text() for a in self.actions()]
        shown["enabled"] = {a.text(): a.isEnabled() for a in self.actions()}

    monkeypatch.setattr(QtWidgets.QMenu, "exec_", capture)
    page._show_contribute_menu()
    return shown


def _a_service_key():
    import base64
    import json as _json

    def seg(obj):
        return base64.urlsafe_b64encode(
            _json.dumps(obj).encode("utf-8")).rstrip(b"=").decode("ascii")

    return "%s.%s.sig" % (seg({"alg": "HS256"}), seg({"role": "service_role"}))


def test_the_review_option_is_absent_without_a_key(wiki, monkeypatch):
    """Everybody else never learns it exists — the shipped app cannot reach the
    live table, and an option that only fails is worse than no option."""
    shown = _items(wiki, monkeypatch, service_key="")

    assert not any("Duyệt" in text for text in shown["labels"])


def test_an_anon_key_does_not_unlock_review(wiki, monkeypatch):
    import base64
    import json as _json

    anon = "%s.%s.sig" % (
        base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode(),
        base64.urlsafe_b64encode(
            _json.dumps({"role": "anon"}).encode()).rstrip(b"=").decode(),
    )

    shown = _items(wiki, monkeypatch, service_key=anon)

    assert not any("Duyệt" in text for text in shown["labels"])


def test_a_service_key_unlocks_review(wiki, monkeypatch):
    shown = _items(wiki, monkeypatch, service_key=_a_service_key())

    assert any("Duyệt" in text for text in shown["labels"])


def test_adding_is_always_offered(wiki, monkeypatch):
    shown = _items(wiki, monkeypatch)

    assert any("thêm" in text.lower() for text in shown["labels"])


def test_editing_needs_a_record_open(wiki, monkeypatch):
    """Greyed rather than hidden, so it is clear what to do to reach it."""
    shown = _items(wiki, monkeypatch)

    edit = [t for t in shown["labels"] if t.lower().startswith("đề xuất sửa")][0]
    assert not shown["enabled"][edit]


def test_editing_is_offered_once_a_record_is_open(wiki, monkeypatch):
    wiki._open_shikigami("thien_cau")
    drain()

    shown = _items(wiki, monkeypatch)

    edit = [t for t in shown["labels"] if t.lower().startswith("đề xuất sửa")][0]
    assert shown["enabled"][edit]
    assert "Đại Thiên Cẩu" in edit


def test_a_search_is_not_a_record(wiki, monkeypatch):
    """Search results span sections; nothing there is "the open shikigami"."""
    wiki._open_shikigami("thien_cau")
    wiki._on_search("thien")
    drain()

    assert wiki._open_record() is None


# ── editing in place, on the detail page ────────────────────────────────────
#
# The popup form was replaced by the detail page itself: every field a proposal
# changes already has a home in that layout. What matters is that the page can
# be trusted with somebody's half-written text, and that what it sends carries
# the whole row.


LIVE_ROW = {
    "id": "thien_cau",
    "name_vi": "Đại Thiên Cẩu",
    "name_en": "Daitengu",
    "rarity": "SSR",
    "friendly_name": ["Thiên cẩu"],
    "obtain": ["Hộp quà"],
    "description": "Sát thương diện rộng.",
    "lore": "",
    "recommended_souls": ["ban_nguyet"],
    "countered_by": [],
    # None of these have a text box; all of them must survive the trip.
    # A realistic skill: every level on the server carries a description —
    # measured, 0 of 1501 are blank — and a level with no text is dropped as an
    # unfilled row.
    # Level 1 repeats the description, as 290 of the server's 291 do.
    "skills": [{"name": "Phong Nhận", "image": "skills/1.webp",
                "description": "Gây sát thương.",
                "levels": [{"level": 1, "description": "Gây sát thương."},
                           {"level": 2, "description": "105%"}]}],
    "stats": {"hp": 11000},
    "slot_mains": {"2": ["atk_pct"]},
    "sort_index": 7,
    "image": "shikigami/ssr/thien_cau.webp",
    "source_url": "https://example.invalid/x",
    "is_finish": True,
}


@pytest.fixture
def editable(wiki, monkeypatch, instant_background, quiet_dialogs):
    """A page whose server hands back LIVE_ROW and records what is sent."""
    from wiki import submissions
    from wiki.config import SupabaseConfig

    state = {"sent": [], "row": dict(LIVE_ROW), "error": None,
             "asked": quiet_dialogs, "page": wiki}

    def fetch(config, target_id):
        if state["error"]:
            raise submissions.SubmissionError(state["error"])
        return dict(state["row"])

    monkeypatch.setattr(submissions, "fetch_live", fetch)
    monkeypatch.setattr(submissions, "submit",
                        lambda config, row: state["sent"].append(row))
    monkeypatch.setattr(wiki, "_stored_config", lambda: SupabaseConfig(
        url="https://example.supabase.co", anon_key="anon-key"))
    return state


def start_editing(page):
    page._open_shikigami("thien_cau")
    drain()
    page._propose("edit")
    drain()


def boxes(page):
    return page._shiki_detail._inputs


def test_editing_happens_on_the_page_not_in_a_dialog(editable):
    page = editable["page"]

    start_editing(page)

    assert page._stack.currentIndex() == 1, "not the detail view"
    assert page._edit_kind == "edit"
    assert boxes(page), "no editable fields on the page"


def test_the_boxes_open_filled_from_the_live_row(editable):
    page = editable["page"]

    start_editing(page)

    assert boxes(page)["name_vi"].text() == "Đại Thiên Cẩu"
    assert boxes(page)["rarity"].currentText() == "SSR"
    assert boxes(page)["obtain"].toPlainText() == "Hộp quà"
    assert boxes(page)["recommended_souls"].toPlainText() == "ban_nguyet"


def test_every_editable_field_has_a_box_on_the_page(editable):
    from wiki import submissions

    page = editable["page"]

    start_editing(page)

    assert set(boxes(page)) == {f.key for f in submissions.FORM_FIELDS}


def test_saving_keeps_the_fields_that_have_no_box(editable):
    """Approval upserts the whole row, so anything missing here is deleted."""
    page = editable["page"]
    start_editing(page)
    boxes(page)["name_vi"].setText("Tên mới")

    page._on_edit_saved()
    drain()

    payload = editable["sent"][0]["payload"]
    assert payload["name_vi"] == "Tên mới"
    assert payload["skills"] == LIVE_ROW["skills"], "approving this would wipe skills"
    assert payload["stats"] == LIVE_ROW["stats"]
    assert payload["slot_mains"] == LIVE_ROW["slot_mains"]
    assert payload["sort_index"] == 7
    assert payload["source_url"] == LIVE_ROW["source_url"]


def test_saving_targets_the_record_that_was_opened(editable):
    """Even after the name — which is what an id is generated from — changes."""
    page = editable["page"]
    start_editing(page)
    boxes(page)["name_vi"].setText("Một Cái Tên Hoàn Toàn Khác")

    page._on_edit_saved()
    drain()

    assert editable["sent"][0]["target_id"] == "thien_cau"
    assert editable["sent"][0]["payload"]["id"] == "thien_cau"


def test_there_is_no_id_box_at_all(editable):
    """It is a primary key. One typed by hand either duplicates a record or
    overwrites somebody else's."""
    page = editable["page"]

    start_editing(page)

    assert "id" not in boxes(page)


def test_a_successful_send_leaves_edit_mode(editable):
    page = editable["page"]
    start_editing(page)

    page._on_edit_saved()
    drain()

    assert page._edit_kind == ""
    assert not page._shiki_detail._inputs


def test_a_failed_send_keeps_what_was_typed(editable, monkeypatch):
    from wiki import submissions

    def boom(config, row):
        raise submissions.SubmissionError("mạng lỗi")

    page = editable["page"]
    start_editing(page)
    boxes(page)["name_vi"].setText("Tên mới")
    monkeypatch.setattr(submissions, "submit", boom)

    page._on_edit_saved()
    drain()

    assert page._edit_kind == "edit", "it threw the proposal away"
    assert boxes(page)["name_vi"].text() == "Tên mới"
    assert "mạng lỗi" in page._shiki_detail._status.text()


def test_a_record_that_cannot_be_read_does_not_open_an_editor(editable):
    page = editable["page"]
    editable["error"] = "mạng lỗi"

    start_editing(page)

    assert page._edit_kind == "", "it opened an editor over nothing"
    assert any("Không tải được" in title for title, _ in editable["asked"])


# ── the half-written proposal is not thrown away by accident ────────────────


def test_sync_cannot_run_while_editing(editable):
    """It rebuilds the repository and re-renders, taking the boxes with it."""
    page = editable["page"]

    start_editing(page)

    assert not page._sync_button.isEnabled()
    assert not page._search_field.isEnabled()


def test_the_chrome_comes_back_after_editing(editable):
    page = editable["page"]
    start_editing(page)

    page._on_edit_cancelled()
    drain()

    assert page._sync_button.isEnabled()
    assert page._search_field.isEnabled()


def test_leaving_asks_before_discarding(editable, monkeypatch):
    page = editable["page"]
    start_editing(page)
    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        staticmethod(lambda *a, **k: QtWidgets.QMessageBox.No))

    page._on_back()
    drain()

    assert page._edit_kind == "edit", "it discarded without asking"


def test_saying_yes_actually_leaves(editable):
    page = editable["page"]
    start_editing(page)

    page._on_back()
    drain()

    assert page._edit_kind == ""


def test_the_sidebar_cannot_silently_do_nothing(editable):
    """_render refuses to repaint over the boxes, so an unguarded nav would
    look broken rather than ask."""
    page = editable["page"]
    start_editing(page)

    page.show_section("souls")
    drain()

    assert page._edit_kind == ""
    assert page.section == "souls"


def test_a_link_inside_the_record_asks_too(editable, monkeypatch):
    page = editable["page"]
    start_editing(page)
    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        staticmethod(lambda *a, **k: QtWidgets.QMessageBox.No))

    page._open_soul("ban_nguyet")
    drain()

    assert page._edit_kind == "edit"


# ── adding ──────────────────────────────────────────────────────────────────


def test_adding_opens_an_empty_page(editable):
    page = editable["page"]

    page._propose("add")
    drain()

    assert page._edit_kind == "add"
    assert boxes(page)["name_vi"].text() == ""


def test_the_generated_id_is_shown_as_the_name_is_typed(editable):
    """Not editable, but not hidden either: an id that appears from nowhere is
    one nobody can search for or quote in a bug report."""
    page = editable["page"]
    page._propose("add")
    drain()

    boxes(page)["name_en"].setText("Ootengu")
    drain()

    assert "ootengu" in page._shiki_detail._generated_id.text()


def test_the_vietnamese_name_does_not_decide_the_id(editable):
    """Ids are standardised on the English name; generating from the Vietnamese
    one would recreate the mixture migration 0011 cleaned up."""
    page = editable["page"]
    page._propose("add")
    drain()

    boxes(page)["name_vi"].setText("Đại Thiên Cẩu")
    drain()

    assert "dai_thien_cau" not in page._shiki_detail._generated_id.text()


def test_adding_without_an_english_name_is_refused(editable):
    """There is nothing to generate an id from."""
    page = editable["page"]
    page._propose("add")
    drain()

    page._on_edit_saved()
    drain()

    assert editable["sent"] == []
    assert "tiếng anh" in page._shiki_detail._status.text().lower()


def test_adding_a_name_that_already_exists_is_refused(editable):
    """Approving an addition upserts on the id, so a second one would silently
    overwrite the first."""
    page = editable["page"]
    page._propose("add")
    drain()
    # The fixture already holds a record whose id is exactly this slug.
    boxes(page)["name_en"].setText("Ibaraki")

    page._on_edit_saved()
    drain()

    assert editable["sent"] == []
    assert "Đã có" in page._shiki_detail._status.text()
    assert "ibaraki" in page._shiki_detail._status.text()


def test_adding_sends_what_was_typed_under_a_generated_id(editable):
    page = editable["page"]
    page._propose("add")
    drain()
    boxes(page)["name_vi"].setText("Thức Thần Mới")
    boxes(page)["name_en"].setText("Brand New Spirit")
    boxes(page)["obtain"].setPlainText("Hộp quà" + chr(10) + "Sự kiện")

    page._on_edit_saved()
    drain()

    proposal = editable["sent"][0]
    assert proposal["kind"] == "add"
    assert proposal["target_id"] == "brand_new_spirit"
    assert proposal["payload"]["id"] == "brand_new_spirit"
    assert proposal["payload"]["obtain"] == ["Hộp quà", "Sự kiện"]


def test_the_name_of_the_contributor_is_remembered(editable):
    page = editable["page"]
    start_editing(page)
    page._shiki_detail._author_box.setText("Ayu")

    page._on_edit_saved()
    drain()
    start_editing(page)

    assert page._shiki_detail._author_box.text() == "Ayu"


# ── editing skills ──────────────────────────────────────────────────────────
#
# Left out of the first version of the editor, on the grounds that a text box
# cannot express a skill table. True, and it left a hole with no bottom: a *new*
# shikigami could never be given skills, and skills are most of what a record
# is.
#
# The list grows and shrinks, which is the part that goes wrong quietly: adding
# a second skill rebuilds the page, and anything typed into the first has to
# survive that.


def skill_boxes(page, index=0):
    return page._shiki_detail._skill_boxes[index]


def test_the_skills_are_editable_on_the_page(editable):
    page = editable["page"]

    start_editing(page)

    assert len(page._shiki_detail._skill_boxes) == 1
    assert skill_boxes(page)["name"].text() == "Phong Nhận"
    assert skill_boxes(page)["description"].toPlainText() == "Gây sát thương."
    # Level 1 has no box: it is the description, written twice in the data.
    assert [b.toPlainText() for b in skill_boxes(page)["levels"]] == ["105%"]


def test_editing_a_skill_is_what_gets_sent(editable):
    page = editable["page"]
    start_editing(page)
    skill_boxes(page)["name"].setText("PHONG NHẬN MỚI")
    skill_boxes(page)["levels"][0].setPlainText("999%")

    page._on_edit_saved()
    drain()

    sent = editable["sent"][0]["payload"]["skills"]
    assert sent[0]["name"] == "PHONG NHẬN MỚI"
    assert sent[0]["levels"][1] == {"level": 2, "description": "999%"}


def test_level_one_is_not_offered_as_a_box(editable):
    """It is the description. Two boxes for one sentence is an invitation for
    them to drift, and the copy left behind is the one the level table shows."""
    page = editable["page"]
    start_editing(page)

    assert len(skill_boxes(page)["levels"]) == 1


def test_level_one_follows_the_description_box(editable):
    page = editable["page"]
    start_editing(page)
    skill_boxes(page)["description"].setPlainText("Mô tả đã sửa")

    page._on_edit_saved()
    drain()

    levels = editable["sent"][0]["payload"]["skills"][0]["levels"]
    assert levels[0] == {"level": 1, "description": "Mô tả đã sửa"}


def test_the_skill_icon_survives_an_edit(editable):
    """It is a storage key for artwork that has to exist; there is no box for
    it, so it has to be carried through."""
    page = editable["page"]
    start_editing(page)
    skill_boxes(page)["name"].setText("Đổi tên")

    page._on_edit_saved()
    drain()

    assert editable["sent"][0]["payload"]["skills"][0]["image"] == "skills/1.webp"


def test_adding_a_skill_keeps_what_was_already_typed(editable):
    """The page is rebuilt to grow the list, and the boxes do not survive that
    — so they are read back first."""
    page = editable["page"]
    start_editing(page)
    skill_boxes(page)["name"].setText("ĐÃ SỬA")

    page._shiki_detail._add_skill()
    drain()

    assert len(page._shiki_detail._skill_boxes) == 2
    assert skill_boxes(page, 0)["name"].text() == "ĐÃ SỬA"


def test_a_new_skill_arrives_with_the_usual_five_levels(editable):
    page = editable["page"]
    start_editing(page)

    page._shiki_detail._add_skill()
    drain()

    # Five levels, four boxes: level 1 is the description.
    assert len(skill_boxes(page, 1)["levels"]) == 4


def test_an_added_skill_left_empty_is_not_sent(editable):
    """An accidental press of "Thêm kỹ năng" must not ship an empty skill."""
    page = editable["page"]
    start_editing(page)
    page._shiki_detail._add_skill()
    drain()

    page._on_edit_saved()
    drain()

    assert len(editable["sent"][0]["payload"]["skills"]) == 1


def test_a_filled_in_new_skill_is_sent(editable):
    page = editable["page"]
    start_editing(page)
    page._shiki_detail._add_skill()
    drain()
    skill_boxes(page, 1)["name"].setText("KỸ NĂNG HAI")
    skill_boxes(page, 1)["description"].setPlainText("Đánh một phát")
    skill_boxes(page, 1)["levels"][0].setPlainText("Sát thương 120%")

    page._on_edit_saved()
    drain()

    sent = editable["sent"][0]["payload"]["skills"]
    assert len(sent) == 2
    assert sent[1]["name"] == "KỸ NĂNG HAI"
    assert sent[1]["levels"] == [{"level": 1, "description": "Đánh một phát"},
                                 {"level": 2, "description": "Sát thương 120%"}]


def test_levels_left_blank_are_dropped_not_numbered(editable):
    """Which is how a five-row template serves a three-level skill without
    asking anybody to count."""
    page = editable["page"]
    start_editing(page)
    page._shiki_detail._add_skill()
    drain()
    skill_boxes(page, 1)["name"].setText("BA CẤP")
    skill_boxes(page, 1)["description"].setPlainText("cấp một")
    for index, text in enumerate(("hai", "ba")):
        skill_boxes(page, 1)["levels"][index].setPlainText(text)

    page._on_edit_saved()
    drain()

    levels = editable["sent"][0]["payload"]["skills"][1]["levels"]
    assert [lv["level"] for lv in levels] == [1, 2, 3]
    assert [lv["description"] for lv in levels] == ["cấp một", "hai", "ba"]


def test_removing_a_skill_removes_it(editable):
    page = editable["page"]
    start_editing(page)

    page._shiki_detail._remove_skill(0)
    drain()

    assert page._shiki_detail._skill_boxes == []

    page._on_edit_saved()
    drain()
    assert editable["sent"][0]["payload"]["skills"] == []


def test_adding_a_level_to_an_existing_skill(editable):
    page = editable["page"]
    start_editing(page)

    page._shiki_detail._add_level(0)
    drain()

    assert len(skill_boxes(page)["levels"]) == 2
    assert skill_boxes(page)["levels"][0].toPlainText() == "105%"


def test_an_added_level_is_numbered_after_the_last_one(editable):
    page = editable["page"]
    start_editing(page)

    page._shiki_detail._add_level(0)
    drain()
    skill_boxes(page)["levels"][1].setPlainText("110%")
    page._on_edit_saved()
    drain()

    levels = editable["sent"][0]["payload"]["skills"][0]["levels"]
    assert [lv["level"] for lv in levels] == [1, 2, 3]


def test_the_rest_of_the_record_survives_a_skill_rebuild(editable):
    """Rebuilding the page to grow the skills list must not lose the name."""
    page = editable["page"]
    start_editing(page)
    boxes(page)["name_vi"].setText("Tên đã sửa")

    page._shiki_detail._add_skill()
    drain()

    assert boxes(page)["name_vi"].text() == "Tên đã sửa"


def test_the_contributor_name_survives_a_skill_rebuild(editable):
    page = editable["page"]
    start_editing(page)
    page._shiki_detail._author_box.setText("Ayu")

    page._shiki_detail._add_skill()
    drain()

    assert page._shiki_detail._author_box.text() == "Ayu"


def test_a_new_record_can_be_given_skills(editable):
    """The hole this closes: before, an addition could carry none at all."""
    page = editable["page"]
    page._propose("add")
    drain()
    boxes(page)["name_vi"].setText("Thức Thần Mới")
    boxes(page)["name_en"].setText("Brand New Spirit")
    page._shiki_detail._add_skill()
    drain()
    skill_boxes(page, 0)["name"].setText("KỸ NĂNG ĐẦU")
    skill_boxes(page, 0)["description"].setPlainText("Sát thương 100%")

    page._on_edit_saved()
    drain()

    sent = editable["sent"][0]["payload"]
    assert sent["id"] == "brand_new_spirit"
    assert sent["skills"][0]["name"] == "KỸ NĂNG ĐẦU"


def test_an_addition_starts_with_no_skills(editable):
    page = editable["page"]

    page._propose("add")
    drain()

    assert page._shiki_detail._skill_boxes == []


# ── what the page shows about a skill ───────────────────────────────────────
#
# `cost` and `alt_forms` were read off the row by nothing at all: 139 skills
# carry a cost and 3 carry an alternate form, and none of it reached the screen.
# A reader could not learn what an active skill spends, which is the first thing
# anybody asks about one.


COSTED = {
    "id": "thien_cau", "name_vi": "Đại Thiên Cẩu", "name_en": "Ootengu",
    "rarity": "SSR",
    "skills": [{
        "name": "DỮ NGÃ LIÊU NGUYÊN",
        "description": "Di chuyển Tâm Hỏa của 1 đồng minh lên bản thân.",
        "cost": 2,
        "effects": ["scorching_fire"],
        "levels": [{"level": 2, "description": "Sát thương = 40%"}],
        "alt_forms": [{"name": "THIÊN HỎA PHÁ VỌNG",
                       "description": "Tấn công AOE 3 lần.",
                       "effects": ["recall"]}],
    }],
}


def shown(page) -> str:
    from PyQt5 import QtWidgets as W

    parts = []
    for child in page._shiki_detail.findChildren(W.QWidget):
        for reader in ("text", "toPlainText"):
            if hasattr(child, reader):
                try:
                    parts.append(str(getattr(child, reader)()))
                except TypeError:
                    pass
                break
    return "\n".join(parts)


@pytest.fixture
def costed(editable):
    editable["row"] = dict(COSTED)
    return editable


def cost_badges(page):
    """The cost badges on screen, by their own object name.

    Looked up by name rather than by hunting for the digit in the page text:
    "2" also appears in "Cấp 2" and "Sát thương = 40%", so a text search passes
    whether the badge is drawn or not — which it did, until this was tightened.
    """
    from PyQt5 import QtWidgets as W

    return [w for w in page._shiki_detail.findChildren(W.QFrame)
            if w.objectName() == "costBadge"]


def test_the_cost_is_shown(costed):
    page = costed["page"]
    from wiki.models import Shikigami
    page._shiki_detail.render(Shikigami.from_row(COSTED), (), ())
    drain()

    badges = cost_badges(page)
    assert len(badges) == 1
    assert "2" in badges[0].toolTip()


def test_a_skill_with_no_cost_gets_no_badge(costed):
    from wiki.models import Shikigami

    page = costed["page"]
    row = dict(COSTED)
    row["skills"] = [{k: v for k, v in COSTED["skills"][0].items() if k != "cost"}]

    page._shiki_detail.render(Shikigami.from_row(row), (), ())
    drain()

    assert cost_badges(page) == []


def test_a_free_skill_does_get_a_badge(costed):
    """Zero is a real cost — 30 skills have it — not a missing one."""
    from wiki.models import Shikigami

    page = costed["page"]
    row = dict(COSTED)
    row["skills"] = [dict(COSTED["skills"][0], cost=0)]

    page._shiki_detail.render(Shikigami.from_row(row), (), ())
    drain()

    assert len(cost_badges(page)) == 1


def test_the_alternate_form_is_shown(costed):
    page = costed["page"]
    from wiki.models import Shikigami
    page._shiki_detail.render(Shikigami.from_row(COSTED), (), ())
    drain()

    drawn = shown(page)
    assert "THIÊN HỎA PHÁ VỌNG" in drawn
    assert "Tấn công AOE 3 lần." in drawn
    assert "CHUYỂN THÀNH" in drawn


def test_effect_tags_are_shown_as_words_when_they_resolve(costed):
    page = costed["page"]
    page._shiki_detail.set_effect_names({"scorching_fire": "Thiêu Đốt",
                                         "recall": "Hồi Tố"})
    from wiki.models import Shikigami
    page._shiki_detail.render(Shikigami.from_row(COSTED), (), ())
    drain()

    drawn = shown(page)
    assert "Thiêu Đốt" in drawn
    assert "scorching_fire" not in drawn


def test_an_unresolved_tag_still_shows_its_id(costed):
    """A reader who sees `scorching_fire` at least has something to search
    for; a blank tells them nothing."""
    page = costed["page"]
    page._shiki_detail.set_effect_names({})
    from wiki.models import Shikigami
    page._shiki_detail.render(Shikigami.from_row(COSTED), (), ())
    drain()

    assert "scorching_fire" in shown(page)


def test_the_page_supplies_the_effect_names_from_its_dataset(editable):
    """The fixture dataset has one effect; the mapping must reach the view."""
    page = editable["page"]

    assert page._shiki_detail._effect_names.get("choang") == "Choáng"


def test_the_editor_still_shows_the_cost(costed):
    """It is carried through untouched, and a skill that showed its cost on the
    page and hid it here would look as though editing had dropped it."""
    page = costed["page"]
    start_editing(page)

    assert len(cost_badges(page)) == 1


def test_the_editor_says_the_alternate_form_is_kept(costed):
    page = costed["page"]
    start_editing(page)

    assert "THIÊN HỎA PHÁ VỌNG" in shown(page)


def test_editing_carries_the_cost_and_the_form_through(costed):
    page = costed["page"]
    start_editing(page)
    skill_boxes(page)["name"].setText("ĐỔI TÊN")

    page._on_edit_saved()
    drain()

    sent = costed["sent"][0]["payload"]["skills"][0]
    assert sent["cost"] == 2
    assert sent["alt_forms"][0]["name"] == "THIÊN HỎA PHÁ VỌNG"
    assert sent["effects"] == ["scorching_fire"]


# ── the demon-fire orb ──────────────────────────────────────────────────────
#
# The badge started with an emoji flame, which is orange. Demon fire in this
# game is blue, so the emoji was not standing in for the icon — it was a
# different thing wearing its place. The real one is cut out of a capture of the
# game's own skill panel.


def test_the_icon_ships_with_the_app():
    """A missing asset would leave every cost badge as a bare number."""
    import paths

    assert (paths.ASSET_DIR / "icons" / "demon_fire.png").is_file()


def test_the_icon_is_bundled_by_the_build():
    """`assets/` is not shipped wholesale — each folder is listed."""
    from pathlib import Path as P

    spec = P("onmyoji_auto.spec").read_text(encoding="utf-8")
    assert "assets/icons" in spec


def test_the_icon_has_transparency(qt_app):
    """It sits on a dark card; the game's parchment behind it had to go."""
    from PyQt5 import QtGui

    import paths

    image = QtGui.QImage(str(paths.ASSET_DIR / "icons" / "demon_fire.png"))
    assert not image.isNull()
    assert image.hasAlphaChannel()
    corners = [image.pixelColor(0, 0), image.pixelColor(image.width() - 1, 0)]
    assert all(colour.alpha() == 0 for colour in corners), "the background came too"


def test_the_icon_kept_its_bright_core(qt_app):
    """The first cut keyed on "bluer than green", which is false for near-white
    and left a hole where the core is."""
    from PyQt5 import QtGui

    import paths

    image = QtGui.QImage(str(paths.ASSET_DIR / "icons" / "demon_fire.png"))
    bright = [
        image.pixelColor(x, y)
        for y in range(image.height()) for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 200
        and min(image.pixelColor(x, y).red(),
                image.pixelColor(x, y).green(),
                image.pixelColor(x, y).blue()) > 170
    ]
    assert bright, "the core is transparent or missing"


def test_the_badge_draws_the_orb(qt_app):
    from ui import wiki_detail

    badge = wiki_detail.cost_badge("2")

    from PyQt5 import QtWidgets as W
    pictures = [w for w in badge.findChildren(W.QLabel) if w.pixmap() is not None]
    assert len(pictures) == 1
    assert not pictures[0].pixmap().isNull()


def test_the_badge_still_draws_without_the_icon(qt_app, monkeypatch):
    """A missing asset should cost a picture, not the fact."""
    from PyQt5 import QtGui, QtWidgets as W

    from ui import wiki_detail

    monkeypatch.setattr(wiki_detail, "demon_fire_pixmap",
                        lambda height: QtGui.QPixmap())

    badge = wiki_detail.cost_badge("3")

    assert "3" in badge.toolTip()
    assert [w for w in badge.findChildren(W.QLabel) if w.text() == "3"]
    assert not [w for w in badge.findChildren(W.QLabel) if w.pixmap() is not None]


def test_the_badge_colour_comes_from_the_artwork(qt_app):
    """It sits right beside the icon; a near-miss reads as a mistake."""
    import theme

    assert theme.DEMON_FIRE.lower() == "#2ea1da"


def test_the_icon_does_not_sit_in_a_darker_rectangle(qt_app):
    """The badge had a translucent fill, and it did not paint under the child
    holding the pixmap: Qt renders a stylesheet background behind styled
    widgets, and a child left transparent shows its ancestor's colour rather
    than its parent's. The icon sat in a visibly darker box — measured at
    (28,26,24) inside against (30,39,43) beside it.
    """
    from PyQt5 import QtCore, QtWidgets as W

    import theme
    from ui import wiki_detail

    host = W.QWidget()
    host.setStyleSheet("background: %s;" % theme.CARD)
    layout = W.QHBoxLayout(host)
    layout.setContentsMargins(20, 20, 20, 20)
    badge = wiki_detail.cost_badge("2")
    layout.addWidget(badge)
    layout.addStretch()
    host.resize(240, 70)
    host.show()
    drain()

    picture = [w for w in badge.findChildren(W.QLabel) if w.pixmap()][0]
    image = host.grab().toImage()
    corner = picture.mapTo(host, QtCore.QPoint(0, 0))
    inside = image.pixelColor(corner.x() + 1, corner.y() + 1)
    beside = image.pixelColor(corner.x() + picture.width() + 3, corner.y() + 1)
    host.close()

    assert (inside.red(), inside.green(), inside.blue()) ==            (beside.red(), beside.green(), beside.blue()),         "the icon is boxed: %s vs %s" % (inside.name(), beside.name())


# ── syncing on its own when the tab opens ───────────────────────────────────
#
# Asked for so that a user who opens Thức thần gets the current data without
# knowing there is a Đồng bộ button. It follows that the automatic path must
# behave differently from the button in two ways, and both matter more than the
# sync itself:
#
#   * it must never open a dialog. The button may ask for credentials and may
#     report a failure; something the user did not ask for may do neither.
#   * being offline is the ordinary case, not an error. A warning box every
#     time the app starts without a connection would be worse than never
#     syncing at all.


@pytest.fixture
def sync_spy(wiki, monkeypatch):
    """Records what a sync attempt did, without touching the network."""
    import ui.wiki_page as wiki_page

    state = {"started": 0, "warned": [], "asked": 0}

    class FakeWorker:
        def __init__(self, repository, config, resolver):
            self.failed = _Signal()
            self.succeeded = _Signal()
            self.progressed = _Signal()
            state["started"] += 1

        def isRunning(self):
            return False

        def start(self):
            pass

    monkeypatch.setattr(wiki_page, "SyncWorker", FakeWorker)
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning",
                        lambda *a, **k: state["warned"].append(a[1:]))

    class FakeDialog:
        def __init__(self, *a, **k):
            state["asked"] += 1

        def exec_(self):
            return QtWidgets.QDialog.Rejected

        def config(self):
            return None

    monkeypatch.setattr(wiki_page, "CredentialsDialog", FakeDialog)
    return state


class _Signal:
    def connect(self, *_a, **_k):
        pass

    def emit(self, *_a, **_k):
        pass


def configure(wiki):
    from wiki import config as wiki_config

    wiki._settings.setValue(wiki_config.URL_SETTING, "https://example.invalid")
    wiki._settings.setValue(wiki_config.ANON_SETTING, "anon-key")


def test_opening_the_tab_starts_a_sync(wiki, sync_spy):
    configure(wiki)

    wiki.sync_in_background()

    assert sync_spy["started"] == 1


def test_an_automatic_sync_never_asks_for_credentials(wiki, sync_spy,
                                                     monkeypatch):
    """Unconfigured is not a prompt. Opening a tab must not put a modal in
    front of somebody who was reading a list of shikigami.

    Clearing the stored settings is not enough to reach this state — `resolve`
    falls back to the URL and anon key built into the app, so in a real build
    there are always credentials. `resolve` itself is replaced here, because
    the guard still has to hold for a build shipped without them.
    """
    import ui.wiki_page as wiki_page
    from wiki.config import SupabaseConfig

    monkeypatch.setattr(wiki_page, "resolve",
                        lambda _stored: SupabaseConfig("", ""))

    wiki.sync_in_background()

    assert sync_spy["asked"] == 0
    assert sync_spy["started"] == 0


def test_an_automatic_sync_fails_silently(wiki, sync_spy):
    """No connection is the normal state on a laptop that has just woken up."""
    configure(wiki)
    wiki.sync_in_background()

    wiki._on_sync_failed("Không có mạng")

    assert sync_spy["warned"] == [], "interrupted the user over a failed sync"


def test_a_sync_the_user_asked_for_still_reports_failure(wiki, sync_spy):
    """The button keeps its manners: somebody who pressed it is owed an answer."""
    configure(wiki)
    wiki._on_sync()

    wiki._on_sync_failed("Máy chủ không trả lời")

    assert sync_spy["warned"], "a sync the user started failed without a word"


def test_the_automatic_sync_does_not_repeat(wiki, sync_spy):
    """Once a session. Every visit to the tab would be a request per click."""
    configure(wiki)

    wiki.sync_in_background()
    wiki.sync_in_background()
    wiki.sync_in_background()

    assert sync_spy["started"] == 1
