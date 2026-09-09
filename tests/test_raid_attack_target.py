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
