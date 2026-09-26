"""The attack must land on the card the loop opened, and be blamed on it.

`match` answers with a single global best over the whole screen. `_click_attack`
took that answer and pressed it without ever asking whose card it belonged to,
so whenever a popup was already open the loop pressed *that* one — and then
recorded the refusal against the card it had merely been looking at.

From the run that found this, on the guild board:

    08:34:44  Enemy found (section) at (929, 490)
    08:34:45  Attack button score=0.984 at (579, 452) — clicked
    08:34:59  Pressed attack 8 times ... leaving (929, 490) alone

Every one of those presses hit the button at (579, 452), which belongs to the
card at (633, 252). So the barrier that was actually refusing never made it
onto the skip list and was attacked forever, while an innocent card was struck
off. The user saw exactly that: one slot attacked over and over.

The popup opens over its own card, at a fixed offset — see
geometry.ATTACK_BUTTON_OFFSET — so which card a button belongs to is a question
with an answer, and both of those bugs come from never asking it.
"""
from __future__ import annotations

import pytest

pytest.importorskip("win32con")

import geometry  # noqa: E402
import realm_raid  # noqa: E402

DX, DY = geometry.ATTACK_BUTTON_OFFSET

# Two cards on the live board, and where each one's Attack button sits.
OPENED_CARD = (633, 252)
ITS_BUTTON = (OPENED_CARD[0] + DX, OPENED_CARD[1] + DY)
OTHER_CARD = (929, 490)


@pytest.fixture
def raid(monkeypatch):
    """A raid worker on a board whose popup belongs to OPENED_CARD."""
    import task_worker
    from test_realm_raid import StubControl

    control = StubControl(1, match_score=0.984)
    control.match_point = ITS_BUTTON
    monkeypatch.setattr(task_worker, "GameControl", lambda hwnd: control)
    monkeypatch.setattr(realm_raid.ticket_counter, "is_zero", lambda *_a: False)

    worker = realm_raid.RealmRaidWorker(hwnd=1)
    monkeypatch.setattr(worker, "_wait_for_battle_to_take_over", lambda: None)
    yield worker
    worker.stop()


def test_the_button_belonging_to_the_opened_card_is_pressed(raid):
    """The ordinary case still works: open a card, press its own button."""
    raid._handle_enemy_section(OPENED_CARD)

    assert ITS_BUTTON in raid._control.clicks


def test_another_card_s_button_is_not_pressed(raid):
    """The click that opens a card does nothing while a popup is up.

    So the popup on screen is still the old one, and pressing it attacks a card
    the loop never chose — the one it has already been refused by.
    """
    raid._handle_enemy_section(OTHER_CARD)

    assert ITS_BUTTON not in raid._control.clicks, (
        "attacked a popup belonging to a different card"
    )


def test_a_refusal_names_the_card_that_was_actually_attacked(raid):
    """The half that made this permanent.

    Blaming the wrong card is worse than not blaming one: the card that really
    refuses stays eligible forever, and a good card is struck off the board.
    """
    raid._last_enemy = OTHER_CARD          # what the loop had been looking at
    raid._start_clicks = realm_raid.START_REFUSAL_LIMIT
    raid._control.matches[realm_raid.TPL_START] = ITS_BUTTON

    raid._handle_start_button()

    assert raid._has_refused(OPENED_CARD), "the refusing card was not skipped"
    assert not raid._has_refused(OTHER_CARD), "struck off a card never attacked"


def test_a_card_the_loop_gave_up_on_is_not_opened_again(raid):
    """What the skip list is for, end to end."""
    raid._control.many[realm_raid.TPL_SECTION] = [OPENED_CARD, OTHER_CARD]

    assert raid._pick_enemy() == OPENED_CARD
    raid._refused.append(OPENED_CARD)
    assert raid._pick_enemy() == OTHER_CARD


# ── the skip list has to name a card the board actually has ─────────────────
#
# Attributing the button to its own card fixed the wrong half being struck off.
# What it left behind is that the attributed point is an *estimate*: the offset
# is good to about 3px, but a button is accepted as belonging to a card up to
# ATTACK_BUTTON_TOLERANCE away, while two points only count as the same card
# within the tighter SAME_ENEMY_WITHIN. Anything landing in the gap between
# those two numbers is struck off at a position the board does not have, and
# `_pick_enemy` goes on offering the real card for ever.
#
# From the run that found it — 514 of these in one morning, every one naming
# the same phantom:
#
#     find_all(section) -> (633, 134), (930, 134), (633, 252), (930, 252)
#     WARNING Pressed attack 8 times ... leaving (633, 189) alone
#
# 189 is 55 from the card at 134: inside the 60 that accepted the button,
# outside the 50 that remembers it. The loop spent the morning on one barrier.

REAL_CARD = (633, 134)
# A button sitting 55px below where REAL_CARD's own button would be: still
# close enough to be accepted as this card's, far enough that the position it
# implies is not recognised as this card afterwards.
DRIFTED_BUTTON = (REAL_CARD[0] + DX, REAL_CARD[1] + DY + 55)


def test_the_two_tolerances_leave_a_gap():
    """The arithmetic the bug lives in, stated so it cannot drift back."""
    assert geometry.ATTACK_BUTTON_TOLERANCE > realm_raid.SAME_ENEMY_WITHIN, (
        "no gap any more — this test and the snapping it guards can go")


def test_a_refused_card_is_not_offered_again(monkeypatch):
    """The whole point of the skip list, at the offset that defeated it."""
    import task_worker
    from test_realm_raid import StubControl

    control = StubControl(
        1,
        match_score=0.984,
        matches={realm_raid.TPL_START: DRIFTED_BUTTON},
        many={realm_raid.TPL_SECTION: [REAL_CARD, (930, 134)]},
    )
    control.match_point = DRIFTED_BUTTON
    monkeypatch.setattr(task_worker, "GameControl", lambda hwnd: control)
    monkeypatch.setattr(realm_raid.ticket_counter, "is_zero", lambda *_a: False)
    worker = realm_raid.RealmRaidWorker(hwnd=1)
    monkeypatch.setattr(worker, "_wait_for_battle_to_take_over", lambda: None)
    try:
        worker._handle_start_button()
        worker._give_up_on_attacking()

        assert worker._has_refused(REAL_CARD), (
            "struck off %s, which is not a card on this board" % (worker._last_enemy,)
        )
        assert worker._pick_enemy() != REAL_CARD, "offered the refused card again"
    finally:
        worker.stop()


def test_a_button_belonging_to_no_visible_card_is_not_blamed_on_one(monkeypatch):
    """Snapping must not reach across the board.

    Without a distance limit the nearest card wins however far away it is, and
    an innocent barrier is struck off — which is the bug the whole of this file
    exists to keep fixed, arriving by the other door.
    """
    import task_worker
    from test_realm_raid import StubControl

    stray = (200, 600)              # nothing on the board is near this
    control = StubControl(
        1,
        match_score=0.984,
        matches={realm_raid.TPL_START: (stray[0] + DX, stray[1] + DY)},
        many={realm_raid.TPL_SECTION: [REAL_CARD, (930, 134)]},
    )
    monkeypatch.setattr(task_worker, "GameControl", lambda hwnd: control)
    monkeypatch.setattr(realm_raid.ticket_counter, "is_zero", lambda *_a: False)
    worker = realm_raid.RealmRaidWorker(hwnd=1)
    monkeypatch.setattr(worker, "_wait_for_battle_to_take_over", lambda: None)
    try:
        worker._handle_start_button()

        assert worker._last_enemy == stray, (
            "blamed %s, a card nowhere near the button" % (worker._last_enemy,))
        worker._give_up_on_attacking()
        assert not worker._has_refused(REAL_CARD), "struck off an innocent card"
    finally:
        worker.stop()
