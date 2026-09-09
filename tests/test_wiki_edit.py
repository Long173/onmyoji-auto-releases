"""Proposing a deletion, and the owner's review window.

Adding and editing are tested in ``test_wiki_page.py``, because they happen on
the detail page rather than in a dialog.

What is worth pinning here:

* **A delete says why, and says it somewhere that is not truncated.**
* **Review never reaches the live table without a service_role key**, and an
  anon key pasted by mistake is told apart locally rather than turning into a
  permission error that reads like a bug.
* **Approving asks first**, and **rejecting never writes the live table.**
"""
from __future__ import annotations

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")
from PyQt5 import QtCore  # noqa: E402

from ui import wiki_edit, wiki_review  # noqa: E402
from wiki import submissions  # noqa: E402
from wiki.config import SupabaseConfig  # noqa: E402
from wiki.submissions import DELETE, EDIT, Submission, SubmissionError  # noqa: E402

CONFIG = SupabaseConfig(url="https://example.supabase.co", anon_key="anon-key")


@pytest.fixture(autouse=True)
def _background(instant_background):
    """Every widget here talks to the server; none of them should wait."""


@pytest.fixture(autouse=True)
def _dialogs(quiet_dialogs):
    return quiet_dialogs


@pytest.fixture
def sent(monkeypatch):
    """Every proposal that would have been sent."""
    rows = []
    monkeypatch.setattr(submissions, "submit",
                        lambda config, row: rows.append(row))
    return rows


def a_service_key():
    import base64
    import json

    def seg(obj):
        return base64.urlsafe_b64encode(
            json.dumps(obj).encode("utf-8")).rstrip(b"=").decode("ascii")

    return "%s.%s.sig" % (seg({"alg": "HS256"}), seg({"role": "service_role"}))


def an_anon_key():
    import base64
    import json

    def seg(obj):
        return base64.urlsafe_b64encode(
            json.dumps(obj).encode("utf-8")).rstrip(b"=").decode("ascii")

    return "%s.%s.sig" % (seg({"alg": "HS256"}), seg({"role": "anon"}))


# ── proposing a deletion ────────────────────────────────────────────────────


def a_delete_dialog(qt_app):
    return wiki_edit.DeleteProposalDialog(CONFIG, "ootengu", "Đại Thiên Cẩu")


def test_a_delete_needs_a_reason(qt_app, sent):
    dialog = a_delete_dialog(qt_app)

    dialog._on_send()

    assert sent == []
    assert dialog._status.text()


def test_a_delete_puts_the_reason_where_it_is_not_truncated(qt_app, sent):
    """`author` is capped at 80 characters; a reason belongs in the payload."""
    dialog = a_delete_dialog(qt_app)
    dialog._reason.setPlainText("t" * 300)

    dialog._on_send()

    assert sent[0]["payload"]["reason"] == "t" * 300
    assert sent[0]["kind"] == DELETE
    assert sent[0]["target_id"] == "ootengu"


def test_a_delete_remembers_the_name_for_next_time(qt_app, sent):
    first = a_delete_dialog(qt_app)
    first._reason.setPlainText("trùng")
    first._author.setText("Ayu")
    first._on_send()

    assert a_delete_dialog(qt_app)._author.text() == "Ayu"


def test_a_failed_send_lets_it_be_tried_again(qt_app, monkeypatch):
    def boom(config, row):
        raise SubmissionError("mạng lỗi")

    monkeypatch.setattr(submissions, "submit", boom)
    dialog = a_delete_dialog(qt_app)
    dialog._reason.setPlainText("trùng")

    dialog._on_send()

    assert dialog._send.isEnabled(), "there is no way back from here"
    assert "mạng lỗi" in dialog._status.text()


def test_the_helper_refuses_to_open_this_for_an_edit(qt_app):
    """Add and edit live on the detail page; routing one here would open a
    deletion dialog for somebody who asked to edit."""
    with pytest.raises(ValueError):
        wiki_edit.propose(CONFIG, EDIT, None, target_id="ootengu")


# ── review ──────────────────────────────────────────────────────────────────


def a_queue(monkeypatch, rows):
    monkeypatch.setattr(submissions, "pending", lambda config, key: list(rows))


def some_pending():
    return [
        Submission.from_row({"id": 1, "kind": EDIT, "target_id": "ootengu",
                             "payload": {"id": "ootengu", "name_vi": "Sửa"},
                             "author": "Ayu", "created_at": "2026-08-27T10:00:00"}),
        Submission.from_row({"id": 2, "kind": DELETE, "target_id": "kaguya",
                             "payload": {"reason": "trùng"},
                             "created_at": "2026-08-27T11:00:00"}),
    ]


def test_review_refuses_the_anon_key(qt_app, monkeypatch):
    reached = []
    monkeypatch.setattr(submissions, "pending",
                        lambda *a: reached.append(a) or [])

    assert wiki_review.review(CONFIG, an_anon_key(), None) is False
    assert reached == []


def test_review_refuses_no_key_at_all(qt_app, monkeypatch):
    monkeypatch.setattr(submissions, "pending",
                        lambda *a: pytest.fail("asked the server with no key"))

    assert wiki_review.review(CONFIG, "", None) is False


def test_review_lists_what_is_waiting(qt_app, monkeypatch):
    a_queue(monkeypatch, some_pending())

    dialog = wiki_review.ReviewDialog(CONFIG, "service", None)

    assert dialog._list.count() == 2
    assert "Sửa" in dialog._list.item(0).text()
    assert "Ayu" in dialog._list.item(0).text()


def test_review_spells_out_that_a_delete_deletes(qt_app, monkeypatch):
    a_queue(monkeypatch, some_pending())
    dialog = wiki_review.ReviewDialog(CONFIG, "service", None)

    dialog._list.setCurrentRow(1)

    shown = dialog._detail.toPlainText()
    assert "XOÁ" in shown
    assert "trùng" in shown, "the reason is the only thing to judge it on"


def test_review_spells_out_that_an_edit_overwrites(qt_app, monkeypatch):
    a_queue(monkeypatch, some_pending())
    dialog = wiki_review.ReviewDialog(CONFIG, "service", None)

    dialog._list.setCurrentRow(0)

    assert "GHI ĐÈ" in dialog._detail.toPlainText()


def test_approving_passes_the_note_and_the_key(qt_app, monkeypatch):
    a_queue(monkeypatch, some_pending())
    done = []
    monkeypatch.setattr(
        submissions, "approve",
        lambda config, key, row, note="": done.append((key, row.id, note)))
    dialog = wiki_review.ReviewDialog(CONFIG, "service", None)
    dialog._list.setCurrentRow(0)
    dialog._note.setText("ok rồi")

    dialog._on_approve()

    assert done == [("service", 1, "ok rồi")]
    assert dialog.approved_anything


def test_approving_asks_first(qt_app, monkeypatch):
    a_queue(monkeypatch, some_pending())
    asked = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        staticmethod(lambda *a, **k: asked.append(a[1])
                                     or QtWidgets.QMessageBox.No))
    monkeypatch.setattr(submissions, "approve",
                        lambda *a, **k: pytest.fail("approved without asking"))
    dialog = wiki_review.ReviewDialog(CONFIG, "service", None)
    dialog._list.setCurrentRow(0)

    dialog._on_approve()

    assert asked


def test_rejecting_asks_nothing_and_touches_nothing_live(qt_app, monkeypatch):
    a_queue(monkeypatch, some_pending())
    done = []
    monkeypatch.setattr(
        submissions, "reject",
        lambda config, key, row_id, note="": done.append(row_id))
    monkeypatch.setattr(
        submissions, "approve",
        lambda *a, **k: pytest.fail("a rejection wrote the live table"))
    dialog = wiki_review.ReviewDialog(CONFIG, "service", None)
    dialog._list.setCurrentRow(1)

    dialog._on_reject()

    assert done == [2]
    assert not dialog.approved_anything


def test_an_empty_queue_says_so_and_offers_no_buttons(qt_app, monkeypatch):
    a_queue(monkeypatch, [])

    dialog = wiki_review.ReviewDialog(CONFIG, "service", None)

    assert "Không có" in dialog._count.text()
    assert not dialog._approve.isEnabled()
    assert not dialog._reject.isEnabled()


def test_a_queue_that_will_not_load_leaves_the_buttons_off(qt_app, monkeypatch):
    def boom(config, key):
        raise SubmissionError("chưa có bảng")

    monkeypatch.setattr(submissions, "pending", boom)

    dialog = wiki_review.ReviewDialog(CONFIG, "service", None)

    assert "chưa có bảng" in dialog._status.text()
    assert not dialog._approve.isEnabled()


# ── reaching review from where the key is pasted ────────────────────────────


@pytest.fixture
def settings_page(qt_app, monkeypatch, tmp_path):
    import app_settings
    from ui.settings_page import SettingsPage

    store = QtCore.QSettings(str(tmp_path / "s.ini"), QtCore.QSettings.IniFormat)
    monkeypatch.setattr(app_settings, "open_store", lambda scope=None: store)
    return lambda: SettingsPage({})


def _review_button(page):
    from ui import controls

    return [b for b in page.findChildren(controls.OutlineButton)
            if b.text() == "Mở mục duyệt"][0]


def test_the_review_button_is_dead_without_a_key(settings_page, monkeypatch):
    from wiki import config as wiki_config

    monkeypatch.setattr(wiki_config, "load_service_key", lambda: "")

    assert not _review_button(settings_page()).isEnabled()


def test_the_review_button_is_dead_with_an_anon_key(settings_page, monkeypatch):
    from wiki import config as wiki_config

    monkeypatch.setattr(wiki_config, "load_service_key", an_anon_key)

    assert not _review_button(settings_page()).isEnabled()


def test_the_review_button_wakes_up_with_a_service_key(settings_page, monkeypatch):
    from wiki import config as wiki_config

    monkeypatch.setattr(wiki_config, "load_service_key", a_service_key)

    assert _review_button(settings_page()).isEnabled()


def test_pressing_it_opens_review_with_the_stored_key(settings_page, monkeypatch):
    from wiki import config as wiki_config

    key = a_service_key()
    monkeypatch.setattr(wiki_config, "load_service_key", lambda: key)
    monkeypatch.setattr(wiki_config, "load_config", lambda: CONFIG)
    opened = []
    monkeypatch.setattr(wiki_review, "review",
                        lambda config, service_key, parent: opened.append(
                            (config.url, service_key)) or False)
    page = settings_page()

    _review_button(page).click()

    assert opened == [(CONFIG.url, key)]


# ── the proposal, drawn rather than dumped ──────────────────────────────────
#
# The pane was a JSON dump, which shows the shape of the data and hides the
# thing being decided: whether the text is right. A reviewer reading
# `"levels": [{"level": 2, ...}]` is doing the parser's job.


def a_full_proposal():
    return Submission.from_row({
        "id": 11, "kind": EDIT, "target_id": "ootengu", "author": "Ayu",
        "created_at": "2026-08-28T09:00:00",
        "payload": {
            "id": "ootengu", "name_vi": "Đại Thiên Cẩu", "name_en": "Ootengu",
            "rarity": "SSR", "description": "Sát thương diện rộng.",
            "recommended_souls": ["ban_nguyet", "kinh_ho"],
            "countered_by": ["shinigami"],
            "obtain": ["Hộp quà"], "lore": "Truyền thuyết.",
            "skills": [{"name": "PHONG NHẬN", "description": "Gây sát thương.",
                        "levels": [{"level": 1, "description": "Gây sát thương."},
                                   {"level": 2, "description": "105%"}]}],
            "stats": {"hp": {"value": 11000}},
        },
    })


def a_review(monkeypatch, rows):
    a_queue(monkeypatch, rows)
    return wiki_review.ReviewDialog(CONFIG, "service", None)


def test_the_page_view_is_what_shows_first(qt_app, monkeypatch):
    dialog = a_review(monkeypatch, [a_full_proposal()])

    assert dialog._views.currentIndex() == 0, "it opened on the JSON"


def test_the_proposal_is_drawn_with_the_wiki_view(qt_app, monkeypatch):
    dialog = a_review(monkeypatch, [a_full_proposal()])
    dialog._list.setCurrentRow(0)

    drawn = _text_of(dialog._rendered)
    assert "Đại Thiên Cẩu" in drawn
    assert "PHONG NHẬN" in drawn
    assert "Sát thương diện rộng." in drawn


def test_the_skill_levels_are_drawn_as_a_table_not_json(qt_app, monkeypatch):
    dialog = a_review(monkeypatch, [a_full_proposal()])
    dialog._list.setCurrentRow(0)

    drawn = _text_of(dialog._rendered)
    assert "105%" in drawn
    assert '"level"' not in drawn


def test_the_referenced_ids_are_shown_as_they_stand(qt_app, monkeypatch):
    """This window has no dataset to resolve them against, and an id a reviewer
    can read beats a blank."""
    dialog = a_review(monkeypatch, [a_full_proposal()])
    dialog._list.setCurrentRow(0)

    drawn = _text_of(dialog._rendered)
    assert "ban_nguyet" in drawn
    assert "shinigami" in drawn


def test_the_banner_says_what_approving_does(qt_app, monkeypatch):
    dialog = a_review(monkeypatch, [a_full_proposal()])
    dialog._list.setCurrentRow(0)

    assert "GHI ĐÈ" in dialog._banner.text()
    assert "ootengu" in dialog._banner.text()
    assert "Ayu" in dialog._banner.text()


def test_a_deletion_says_so_and_gives_the_reason(qt_app, monkeypatch):
    row = Submission.from_row({"id": 12, "kind": DELETE, "target_id": "kaguya",
                               "payload": {"reason": "trùng bản ghi khác"},
                               "created_at": "2026-08-28T09:00:00"})
    dialog = a_review(monkeypatch, [row])
    dialog._list.setCurrentRow(0)

    assert "SẼ XOÁ" in dialog._banner.text()
    assert "trùng bản ghi khác" in dialog._banner.text()


def test_a_deletion_draws_the_record_that_would_go(qt_app, monkeypatch):
    """There is nothing proposed to draw, so what is drawn is what would be
    lost — which is the thing actually being decided."""
    row = Submission.from_row({"id": 12, "kind": DELETE, "target_id": "kaguya",
                               "payload": {"reason": "x"},
                               "created_at": "2026-08-28T09:00:00"})
    monkeypatch.setattr(submissions, "fetch_live",
                        lambda config, target: {"id": "kaguya",
                                                "name_vi": "Huy Dạ Cơ",
                                                "rarity": "SSR"})
    dialog = a_review(monkeypatch, [row])
    dialog._list.setCurrentRow(0)

    assert "Huy Dạ Cơ" in _text_of(dialog._rendered)


def test_a_record_that_cannot_be_fetched_does_not_block_the_decision(
        qt_app, monkeypatch):
    row = Submission.from_row({"id": 12, "kind": DELETE, "target_id": "kaguya",
                               "payload": {"reason": "x"},
                               "created_at": "2026-08-28T09:00:00"})

    def boom(config, target):
        raise SubmissionError("mạng lỗi")

    monkeypatch.setattr(submissions, "fetch_live", boom)
    dialog = a_review(monkeypatch, [row])
    dialog._list.setCurrentRow(0)

    assert dialog._approve.isEnabled()
    assert "SẼ XOÁ" in dialog._banner.text()


def test_the_raw_form_is_still_reachable(qt_app, monkeypatch):
    """Some columns have no place on the page — image, source_url, sort_index,
    a skill's cost — and approving means being able to see all of it."""
    dialog = a_review(monkeypatch, [a_full_proposal()])
    dialog._list.setCurrentRow(0)

    dialog._as_json.setChecked(True)

    assert dialog._views.currentIndex() == 1
    assert '"name_vi"' in dialog._detail.toPlainText()


def test_selecting_nothing_leaves_an_empty_page(qt_app, monkeypatch):
    dialog = a_review(monkeypatch, [a_full_proposal()])
    dialog._list.setCurrentRow(0)

    dialog._list.setCurrentRow(-1)

    assert dialog._banner.text() == ""


def _text_of(widget) -> str:
    """Every piece of text the view is showing, however deeply nested."""
    from PyQt5 import QtWidgets as W

    parts = []
    for child in widget.findChildren(W.QWidget):
        for reader in ("text", "toPlainText"):
            if hasattr(child, reader):
                try:
                    parts.append(str(getattr(child, reader)()))
                except TypeError:
                    pass
                break
    return "\n".join(parts)


# ── settling several from the window ────────────────────────────────────────


def many_pending(count=4):
    return [Submission.from_row(
        {"id": n, "kind": EDIT, "target_id": "r%d" % n,
         "payload": {"id": "r%d" % n, "name_vi": "Tên %d" % n},
         "author": "Ayu", "created_at": "2026-08-28T10:0%d:00" % n})
        for n in range(1, count + 1)]


def select(dialog, rows):
    from PyQt5 import QtCore

    dialog._list.clearSelection()
    for row in rows:
        dialog._list.item(row).setSelected(True)
    dialog._list.setCurrentRow(rows[0], QtCore.QItemSelectionModel.NoUpdate)
    return dialog


def test_the_buttons_act_on_the_selection_not_on_everything(qt_app, monkeypatch):
    """There is no "approve everything" button on purpose: choosing what to
    apply stays a deliberate act."""
    a_queue(monkeypatch, many_pending())
    applied = []
    monkeypatch.setattr(submissions, "apply_many",
                        lambda config, key, rows, note="":
                        applied.append([r.id for r in rows])
                        or submissions.BatchResult(list(rows), []))
    dialog = wiki_review.ReviewDialog(CONFIG, "service", None)

    select(dialog, [0, 2])._on_approve()

    assert applied == [[1, 3]]


def test_the_selection_is_applied_in_list_order(qt_app, monkeypatch):
    """Two proposals for one record must land oldest first, or the older wins."""
    a_queue(monkeypatch, many_pending())
    applied = []
    monkeypatch.setattr(submissions, "apply_many",
                        lambda config, key, rows, note="":
                        applied.append([r.id for r in rows])
                        or submissions.BatchResult(list(rows), []))
    dialog = wiki_review.ReviewDialog(CONFIG, "service", None)

    select(dialog, [3, 1, 2])._on_approve()

    assert applied == [[2, 3, 4]]


def test_approving_several_asks_first_and_names_them(qt_app, monkeypatch):
    a_queue(monkeypatch, many_pending())
    asked = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        staticmethod(lambda *a, **k: asked.append(a[2])
                                     or QtWidgets.QMessageBox.No))
    monkeypatch.setattr(submissions, "apply_many",
                        lambda *a, **k: pytest.fail("applied without asking"))
    dialog = wiki_review.ReviewDialog(CONFIG, "service", None)

    select(dialog, [0, 1])._on_approve()

    assert asked, "it did not ask"
    assert "Tên 1" in asked[0] and "Tên 2" in asked[0],         "a confirmation that only counts is one nobody can check"


def test_the_buttons_say_how_many_are_selected(qt_app, monkeypatch):
    a_queue(monkeypatch, many_pending())
    dialog = wiki_review.ReviewDialog(CONFIG, "service", None)

    select(dialog, [0, 1, 2])

    assert "(3)" in dialog._approve.text()
    assert "(3)" in dialog._reject.text()


def test_one_selected_reads_as_one(qt_app, monkeypatch):
    a_queue(monkeypatch, many_pending())
    dialog = wiki_review.ReviewDialog(CONFIG, "service", None)

    select(dialog, [1])

    assert dialog._approve.text() == "Chấp nhận"


def test_a_partly_failed_batch_says_which_failed(qt_app, monkeypatch):
    """Reporting only the successes leaves nobody able to say which rows are
    still waiting."""
    rows = many_pending()
    a_queue(monkeypatch, rows)
    monkeypatch.setattr(
        submissions, "apply_many",
        lambda config, key, chosen, note="": submissions.BatchResult(
            [chosen[0]], [(chosen[1], "server bận")]))
    dialog = wiki_review.ReviewDialog(CONFIG, "service", None)

    select(dialog, [0, 1])._on_approve()

    assert "lỗi" in dialog._status.text()
    assert "server bận" in dialog._status.text()


def test_a_batch_that_applied_nothing_does_not_offer_a_resync(qt_app, monkeypatch):
    a_queue(monkeypatch, many_pending())
    monkeypatch.setattr(
        submissions, "apply_many",
        lambda config, key, chosen, note="": submissions.BatchResult(
            [], [(row, "hỏng") for row in chosen]))
    dialog = wiki_review.ReviewDialog(CONFIG, "service", None)

    select(dialog, [0, 1])._on_approve()

    assert not dialog.approved_anything


def test_rejecting_several_never_asks_but_still_reports(qt_app, monkeypatch):
    a_queue(monkeypatch, many_pending())
    rejected = []
    monkeypatch.setattr(submissions, "reject_many",
                        lambda config, key, rows, note="":
                        rejected.append([r.id for r in rows])
                        or submissions.BatchResult(list(rows), []))
    dialog = wiki_review.ReviewDialog(CONFIG, "service", None)

    select(dialog, [0, 3])._on_reject()

    assert rejected == [[1, 4]]
    assert "2" in dialog._status.text()
