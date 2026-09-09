"""Worker lifecycle and handler-priority tests.

A stubbed GameControl stands in for the real one, so nothing is captured and no
input is ever posted to a window.
"""
from __future__ import annotations

import inspect
import threading
import time

import numpy as np
import pytest

import geometry
import realm_raid
import task_worker
from realm_raid import RealmRaidWorker

REFERENCE = geometry.REFERENCE_CLIENT_SIZE
SETTLE = 0.35
# How long to wait before believing something did *not* happen. The waits below
# are negative assertions, so each one burns its whole timeout — four seconds of
# it, in the slowest case, to prove a run had not ended.
#
# Half a second is plenty now the fixture shrinks the loop's own waits to
# hundredths: the worker gets through its entire three-reading confirmation in
# well under 50 ms, so this is a margin of ten times over, not a guess. Raise it
# if the fixture ever stops shrinking those.
NEVER = 0.5
# Long enough for the loop to press the attack button past its refusal limit.
SOON = 6.0


class StubControl:
    """Records clicks and returns whichever template matches the caller set up.

    Also tracks the frame-cache calls, so the tests can assert the loop opens
    and closes exactly one cached frame per pass.
    """

    def __init__(self, hwnd, matches=None, raises=None, match_score=0.42,
                 brightness=0, many=None):
        # The attack button is looked up with match() rather than find(), so its
        # score decides whether it is clicked at all. See ATTACK_FLOOR.
        self.match_score = match_score
        self.client_width, self.client_height = REFERENCE
        self.clicks: list[tuple[int, int]] = []
        self.closed = False
        self.matches = dict(matches or {})
        # template -> several points, for a board carrying nine cards.
        self.many = dict(many or {})
        self.raises = raises
        # Grey, so hue and saturation are zero and only the value moves — which
        # is what tells the two raid tabs apart. See geometry.GUILD_TAB_PATCH.
        # An int for a uniform screen, or {region: value} when a test needs
        # the two raid tabs to differ — which is how the board is told apart.
        self.brightness = brightness
        self.regions_read: list = []
        self.clicking = True
        # Where match() says its best hit is.
        self.match_point = (11, 22)
        self.frames_begun = 0
        self.frames_ended = 0
        self.invalidations = 0

    def part_shot(self, region, gray=False):
        """A strip of the screen. Its contents are mostly irrelevant here — the
        reading itself is covered by the ticket_counter tests — but `brightness`
        lets a test say which raid board is showing, which is read from how
        bright the Guild tab is."""
        if self.raises is not None:
            raise self.raises
        self.regions_read.append(region)
        (x1, y1), (x2, y2) = region
        shape = (y2 - y1, x2 - x1) if gray else (y2 - y1, x2 - x1, 3)
        level = self.brightness
        if isinstance(level, dict):
            level = level.get(region, 0)
        return np.full(shape, level, dtype=np.uint8)

    def describe(self):
        return "stub control"

    def find_all(self, template_path, threshold=0.9, gray=True, delay=0.1,
                 spacing=40):
        """Every copy of a template. `many` overrides; otherwise the one match."""
        if self.raises is not None:
            raise self.raises
        if template_path in self.many:
            return list(self.many[template_path])
        one = self.matches.get(template_path)
        return [one] if one else []

    def find(self, template_path, threshold=0.9, region=None, gray=True, delay=0.1):
        if self.raises is not None:
            raise self.raises
        time.sleep(0.001)  # keep the loop from spinning the CPU flat out
        return self.matches.get(template_path)

    def match(self, template_path, region=None, gray=True, delay=0.1):
        # match() answers with a single global best over the whole screen, with
        # no regard for what the caller was looking at — which is the point of
        # match_point: a test can put the attack button where a *different*
        # card's popup would put it.
        return (self.match_score, self.match_point)

    def withholding_clicks(self):
        """Whether the real control would refuse to click right now.

        `clicking = False` stands for the player's own cursor resting over the
        game window. The loops ask this before a pass, so a stub that cannot
        answer it makes every loop run passes the real one would skip.
        """
        return not self.clicking

    def click(self, point):
        # False stands in for the real control refusing to click because the
        # player's own cursor is over the game window.
        if not self.clicking:
            return False
        self.clicks.append(tuple(point))
        self.invalidations += 1
        return True

    def close(self):
        self.closed = True

    # ── frame cache ──
    def begin_frame(self):
        self.frames_begun += 1

    def end_frame(self):
        self.frames_ended += 1

    def invalidate_frame(self):
        self.invalidations += 1

    def last_frame(self):
        return None


@pytest.fixture
def stub_control(monkeypatch):
    """Builds workers backed by StubControl and tears them down afterwards.

    ``tickets_zero`` stands in for the counter reading; segmenting the real
    counter image is covered by the ticket_counter tests.
    """
    created: list[RealmRaidWorker] = []

    # The loop's real waits are seconds long each, and a test that only needs to
    # see a decision made should not pay for them: before this the 44 tests here
    # took 67s against 4s for the same number in test_souls_dungeon, which does
    # exactly this. Shrunk, not zeroed, and the ordering between them is kept —
    # a couple of tests do depend on one wait outlasting another.
    for name, value in (
        # Safe to shrink: the verdict counts *readings*, not elapsed time —
        # TICKET_ZERO_CONFIRMATIONS is what decides, and this is only the
        # pacing between them. It was the single biggest cost here, three
        # one-second waits on every call.
        ("TICKET_RECHECK_SECONDS", 0.01),
        ("BATTLE_POLL_SECONDS", 0.02),
        ("ATTACK_HANDOVER_SECONDS", 0.05),
        ("ATTACK_HANDOVER_POLL", 0.01),
        ("READY_SETTLE_SECONDS", 0.01),
        ("REFRESH_SETTLE_SECONDS", 0.01),
        ("POPUP_SETTLE_SECONDS", 0.01),
        ("CAPTURE_RETRY_SECONDS", 0.01),
        ("REWARD_CLICK_GAP_SECONDS", 0.01),
        ("RESIZE_SETTLE_SECONDS", 0.0),
    ):
        monkeypatch.setattr(realm_raid, name, value)

    def build(matches=None, raises=None, tickets_zero=False,
              match_score=0.42, brightness=0, many=None, **kwargs):
        # Patched on task_worker, not on realm_raid: the control is built in
        # the shared base class now, so that is where the substitution has to
        # happen. Patching the name realm_raid no longer calls would look right
        # and do nothing.
        monkeypatch.setattr(
            task_worker, "GameControl",
            lambda hwnd: StubControl(hwnd, matches, raises, match_score,
                                     brightness, many),
        )
        # A callable lets a test vary the reading between passes; a bool is the
        # common case of "always this".
        reading = tickets_zero if callable(tickets_zero) else (lambda: tickets_zero)
        monkeypatch.setattr(
            realm_raid.ticket_counter, "is_zero", lambda *_args: reading()
        )
        worker = RealmRaidWorker(hwnd=1, **kwargs)
        created.append(worker)
        return worker

    yield build

    for worker in created:
        worker.stop()
        if worker.ident is not None:  # never started -> join() would raise
            worker.join(3)


def test_the_ready_prompt_presses_ready_and_nothing_else(stub_control):
    """One press, at the fixed Ready coordinate.

    It used to press Ready and then tap a configurable slot on the deployment
    screen. Measured against the live game, that tap opened the shikigami
    picker — a screen no template here matches at all (0.803 at best) — so on
    the rare pass where it fired it swapped one screen the loop understood for
    one it did not. The slot is gone; what is left must be the single press.
    """
    worker = stub_control(matches={realm_raid.TPL_READY_TAP: (560, 616)})
    worker.start()
    time.sleep(SETTLE)
    worker.stop()
    worker.join(3)

    clicks = worker._control.clicks
    assert clicks, "the Ready button was never pressed"
    assert set(clicks) == {geometry.TAP_READY_BUTTON},         "pressed something other than Ready: %s" % sorted(set(clicks))


def test_the_ready_prompt_never_clicks_where_the_glyph_matched(stub_control):
    """click.png is a 41x24 crop of one letter "e", not a button.

    It stays as a *detector* of the prompt — dropping it would narrow detection
    for no reason — but its position is the middle of a sentence, so the press
    has to go to the Ready button either way. Measured on a live deployment
    screen: the glyph scored 0.526 and the banner 0.999.
    """
    glyph = (385, 357)
    worker = stub_control(matches={realm_raid.TPL_READY_CLICK: glyph})
    worker.start()
    time.sleep(SETTLE)
    worker.stop()
    worker.join(3)

    assert glyph not in worker._control.clicks,         "clicked the letter the template was cut from"
    assert geometry.TAP_READY_BUTTON in worker._control.clicks


REFRESH_AT = (916, 526)
ENEMY_AT = (46, 24)
LOST_AT = (965, 141)
OK_AT = (664, 377)


def test_a_dialog_is_answered_before_the_board_is_judged(stub_control):
    """Pressing Refresh opens a confirmation, and the board shows through it.

    "Raid log progress will be reset if you refresh. Continue?" — Cancel and OK.
    The lost marker is still matchable behind that dialog, so a loop that judges
    the board before answering dialogs presses Refresh, sees the marker again,
    and presses Refresh again. A live run did exactly that for 2200 passes,
    roughly one press every 2.2 seconds, until it was stopped by hand.
    """
    worker = stub_control(matches={realm_raid.TPL_REFRESH: REFRESH_AT,
                                   realm_raid.TPL_LOST: LOST_AT,
                                   realm_raid.TPL_SECTION: ENEMY_AT,
                                   realm_raid.TPL_OK: OK_AT},
                          auto_refresh=True)

    worker._step()

    assert worker._control.clicks == [OK_AT], (
        "answered something other than the dialog: %s" % worker._control.clicks
    )


def test_refresh_is_not_pressed_for_ever_when_the_board_will_not_change(
    stub_control,
):
    """A cap for whatever sits on the board next.

    Answering the dialog is the fix; this is the net under it. Nothing here
    recognises the thing in the way, and the loop still has to stop pressing.
    """
    worker = stub_control(matches={realm_raid.TPL_REFRESH: REFRESH_AT,
                                   realm_raid.TPL_LOST: LOST_AT,
                                   realm_raid.TPL_SECTION: ENEMY_AT},
                          auto_refresh=True)

    for _ in range(realm_raid.REFRESH_PRESS_LIMIT + 6):
        worker._step()

    presses = [c for c in worker._control.clicks if c == REFRESH_AT]
    assert len(presses) <= realm_raid.REFRESH_PRESS_LIMIT, (
        "pressed Refresh %d times while nothing changed" % len(presses)
    )


def test_presses_that_were_never_sent_are_not_counted_as_refusals(stub_control):
    """The loop stops clicking while the player's cursor is over the game.

    Those presses never reach it, so counting them would mark an opponent as
    refusing for no better reason than somebody resting the mouse on the window
    for a few seconds.
    """
    worker = stub_control(matches={realm_raid.TPL_START: (875, 452)})
    worker._control.clicking = False

    for _ in range(realm_raid.START_REFUSAL_LIMIT + 5):
        worker._handle_start_button()

    assert worker._start_clicks == 0, "counted presses that were never sent"
    assert worker._refused == [], "blamed an opponent for the player's mouse"


def test_an_opponent_that_refuses_is_left_alone_afterwards(stub_control):
    """Dismissing the card was never enough on its own.

    That card is the board's best match, so the next pass opened it again. A
    live log shows the cycle running for as long as the task did — attack nine
    times, "the game is refusing it", dismiss, reopen — on a barrier somebody
    else had already broken. The card is now put on a list and skipped.
    """
    refuses, spare = (929, 252), (633, 134)
    worker = stub_control(many={realm_raid.TPL_SECTION: [refuses, spare]})
    worker._last_enemy = refuses

    worker._give_up_on_attacking()

    assert worker._pick_enemy() == spare, "went back to the card that refused"


def test_a_withheld_refresh_keeps_the_defeat_owed(stub_control):
    """A press that never left the app has changed nothing.

    Clicks are withheld while the player's cursor is over the game. Spending the
    queued re-roll on one of those would lose it exactly as the original bug
    did — the flag cleared before anything had happened.
    """
    worker = stub_control(matches={realm_raid.TPL_REFRESH: REFRESH_AT},
                          auto_refresh=True)
    worker._refresh_pending = True
    worker._control.clicking = False

    worker._handle_pending_refresh()

    assert worker._refresh_pending, "spent the re-roll on a press never sent"


def test_a_withheld_refresh_keeps_the_refused_list(stub_control):
    """The list is only meaningless once a *new* board has been dealt."""
    only = (929, 252)
    worker = stub_control(matches={realm_raid.TPL_REFRESH: REFRESH_AT},
                          many={realm_raid.TPL_SECTION: [only]})
    worker._last_enemy = only
    worker._give_up_on_attacking()
    worker._control.clicking = False

    worker._press_refresh(REFRESH_AT)

    assert worker._pick_enemy() is None, (
        "forgot the broken barrier without getting a new board"
    )


def test_a_re_roll_forgets_which_opponents_refused(stub_control):
    """Every card changes with the list, so the old names mean nothing."""
    only = (929, 252)
    worker = stub_control(many={realm_raid.TPL_SECTION: [only]})
    worker._last_enemy = only
    worker._give_up_on_attacking()
    assert worker._pick_enemy() is None, "the refusal did not take"

    worker._press_refresh(REFRESH_AT)

    assert worker._pick_enemy() == only, "still avoiding a card from the old list"


def test_a_board_where_every_opponent_refused_counts_as_empty(stub_control):
    """And an empty board is re-rolled, which is the way out of the loop.

    Without this the loop would sit on a full board with nothing it was willing
    to open, which reads as busy and is not.
    """
    only = (929, 252)
    worker = stub_control(matches={realm_raid.TPL_REFRESH: REFRESH_AT},
                          many={realm_raid.TPL_SECTION: [only]},
                          auto_refresh=True)
    worker._last_enemy = only
    worker._give_up_on_attacking()
    worker._control.clicks.clear()

    for _ in range(realm_raid.EMPTY_BOARD_CONFIRMATIONS):
        worker._step()

    assert REFRESH_AT in worker._control.clicks, "sat on a board it would not touch"


def test_a_lost_opponent_on_the_board_re_rolls_the_list(stub_control):
    """A loss does not clear a barrier, so the board never renews on its own.

    The game hands out a new board once every barrier is broken. A card that
    beat the player stops being attackable without counting as broken — measured
    on a live board, the four template hits on that card dropped to zero and
    stayed there over ten seconds — so a board holding one loss would otherwise
    be worked down and then sat on.
    """
    worker = stub_control(matches={realm_raid.TPL_REFRESH: REFRESH_AT,
                                   realm_raid.TPL_LOST: LOST_AT,
                                   realm_raid.TPL_SECTION: ENEMY_AT},
                          auto_refresh=True)

    worker._step()

    assert REFRESH_AT in worker._control.clicks, "left the board as it was"


def test_a_lost_opponent_is_ignored_when_the_option_is_off(stub_control):
    worker = stub_control(matches={realm_raid.TPL_REFRESH: REFRESH_AT,
                                   realm_raid.TPL_LOST: LOST_AT,
                                   realm_raid.TPL_SECTION: ENEMY_AT},
                          auto_refresh=False)

    worker._step()

    assert REFRESH_AT not in worker._control.clicks


def test_an_empty_board_is_re_rolled_but_only_once_confirmed(stub_control):
    """Absence needs confirming in a way presence does not.

    A board caught mid-render has nothing attackable on it either, and
    re-rolling then throws away opponents nobody has fought.
    """
    worker = stub_control(matches={realm_raid.TPL_REFRESH: REFRESH_AT},
                          auto_refresh=True)

    for _ in range(realm_raid.EMPTY_BOARD_CONFIRMATIONS - 1):
        worker._step()
        assert REFRESH_AT not in worker._control.clicks, "re-rolled on one reading"

    worker._step()

    assert REFRESH_AT in worker._control.clicks


def test_a_board_with_enemies_left_is_never_re_rolled(stub_control):
    """Re-rolling a board still worth attacking throws the rest of it away."""
    worker = stub_control(matches={realm_raid.TPL_REFRESH: REFRESH_AT,
                                   realm_raid.TPL_SECTION: ENEMY_AT},
                          auto_refresh=True)

    for _ in range(realm_raid.EMPTY_BOARD_CONFIRMATIONS + 2):
        worker._step()

    assert REFRESH_AT not in worker._control.clicks


def test_a_guild_board_is_left_alone(stub_control):
    """A guild raid has no Refresh button, so there is nothing to press.

    Gating on the button rather than on the mode is what keeps this honest: the
    only board with a Refresh is the one where re-rolling is possible.
    """
    worker = stub_control(matches={realm_raid.TPL_LOST: LOST_AT},
                          auto_refresh=True)

    for _ in range(realm_raid.EMPTY_BOARD_CONFIRMATIONS + 2):
        worker._step()

    assert worker._control.clicks == [],         "clicked something on a board with no Refresh: %s" % worker._control.clicks


def test_refresh_is_only_pressed_after_a_defeat(stub_control):
    """Clearing the board is not a reason to press it — the game re-rolls itself.

    Once all nine opponents are beaten the game hands out a new board on its
    own, so a loss is the only thing Refresh is for. A second branch used to
    press it whenever the button was on screen with the board up. It never
    actually fired — its first gate, rank.PNG, was cut from a window about 20%
    larger and scores 0.599 against the live board against a 0.9 threshold — and
    firing would have thrown away a board still being worked through.
    """
    worker = stub_control(matches={realm_raid.TPL_REFRESH: (916, 526),
                                   realm_raid.TPL_SECTION: (46, 24)},
                          auto_refresh=True)

    worker._step()
    worker._step()

    assert (916, 526) not in worker._control.clicks, "pressed Refresh unprompted"


def test_a_defeat_still_refreshes_when_the_button_arrives_a_pass_later(stub_control):
    """The queued re-roll must outlive the passes before the board comes back.

    The old version cleared the flag *before* looking for the button, so a
    defeat only refreshed if the button happened to be on screen in that very
    frame. It never was: measured on the one defeat in the logs, the board took
    six seconds to return, and by the next line the flag was already gone and
    the bot had attacked the same list again.

    Driven a pass at a time so the assertion is about the decision, not about
    how many passes fitted inside a sleep.
    """
    worker = stub_control(matches={realm_raid.TPL_FAILED: (379, 174)},
                          auto_refresh=True)

    worker._step()                                  # the defeat queues a re-roll
    assert worker._refresh_pending, "the defeat queued nothing"

    del worker._control.matches[realm_raid.TPL_FAILED]   # panel gone, board not back
    worker._step()
    assert worker._refresh_pending, "the re-roll was dropped while waiting"

    worker._control.matches[realm_raid.TPL_REFRESH] = (916, 526)
    worker._step()

    assert (916, 526) in worker._control.clicks, "never pressed Refresh"
    assert not worker._refresh_pending, "the re-roll was not spent"


def test_no_new_fight_starts_while_a_defeat_is_owed_a_new_list(stub_control):
    """Otherwise the re-roll is pointless — the bot re-enters the list it lost to.

    On the individual raid board the enemy list and the Refresh button share one
    screen (measured 0.959 and 0.921 on a live frame), so a pass that attacked
    before refreshing would be racing its own re-roll.
    """
    worker = stub_control(matches={realm_raid.TPL_SECTION: (46, 24),
                                   realm_raid.TPL_START: (875, 452)},
                          auto_refresh=True)
    worker._refresh_pending = True

    worker._step()

    assert worker._control.clicks == [], (
        "started a fight while a re-roll was still owed: %s" % worker._control.clicks
    )


def test_waiting_for_the_refresh_button_gives_up_rather_than_holding_for_ever(
    stub_control,
):
    """Guild raids have no Refresh button at all, so the wait has to end."""
    worker = stub_control(matches={}, auto_refresh=True)
    worker._refresh_pending = True

    for _ in range(realm_raid.REFRESH_WAIT_PASSES):
        worker._step()

    assert not worker._refresh_pending, "still holding out for a button"


def test_a_defeat_queues_nothing_when_the_option_is_off(stub_control):
    worker = stub_control(matches={realm_raid.TPL_FAILED: (379, 174),
                                   realm_raid.TPL_REFRESH: (916, 526)},
                          auto_refresh=False)

    worker._step()
    worker._step()

    assert (916, 526) not in worker._control.clicks, "re-rolled with the option off"


def test_the_leave_battle_dialog_is_cancelled_before_anything_else(stub_control):
    """Confirm here throws the fight away, and the ticket that paid for it.

    "Sure you want to leave the battle?" covers a fight in progress. Everything
    underneath still matches through it — the board, the attack button — so a
    loop that judges those first acts on a screen it cannot reach, and leaves
    the fight parked behind a modal.
    """
    worker = stub_control(matches={realm_raid.TPL_LEAVE_BATTLE: (560, 281),
                                   realm_raid.TPL_SECTION: ENEMY_AT,
                                   realm_raid.TPL_START: (875, 452),
                                   realm_raid.TPL_REFRESH: REFRESH_AT})

    worker._step()

    assert worker._control.clicks == [worker._leave_cancel], (
        "answered something other than the dialog: %s" % worker._control.clicks
    )


def test_the_leave_battle_dialog_is_never_confirmed(stub_control):
    """The Confirm button has no coordinate in this app, and must not gain one."""
    worker = stub_control(matches={realm_raid.TPL_LEAVE_BATTLE: (560, 281)})

    for _ in range(5):
        worker._step()

    assert set(worker._control.clicks) == {worker._leave_cancel}
    assert not hasattr(geometry, "RAID_LEAVE_CONFIRM"), (
        "a coordinate for Confirm was added; nothing should be able to press it"
    )


def test_the_escape_only_ever_clicks_an_empty_corner(stub_control):
    """Blind navigation is withdrawn.

    The escape used to press the top-left back arrow as a last resort. During a
    fight that opens "Sure you want to leave the battle?" — a dialog a loop
    which cannot read the screen must never be one stray press away from
    confirming. The empty corner is the only place left that it presses.
    """
    worker = stub_control(matches={})

    for _ in range(realm_raid.UNKNOWN_SCREEN_LIMIT * 5):
        worker._step()

    assert set(worker._control.clicks) <= {worker._popup_dismiss}, (
        "clicked somewhere other than the empty corner: %s"
        % sorted(set(worker._control.clicks))
    )


def test_an_ordinary_battle_does_not_trip_the_escape(stub_control):
    """A raid fight matches nothing at all, and that is the normal case.

    `battle.png` scored 0.780 against a live fight, under the 0.9 threshold, and
    "Battle in progress" has never once been logged on this account — so the
    loop is blind for the whole fight. Fights run 15-25 seconds. An escape tuned
    tighter than that fires in the middle of one, which is how the back arrow
    came to be pressed during battles.
    """
    worker = stub_control(matches={})

    for _ in range(100):                      # comfortably longer than a fight
        worker._step()

    assert worker._control.clicks == [], (
        "escaped during what could be an ordinary battle: %s"
        % worker._control.clicks
    )


def test_an_unrecognised_screen_is_escaped_instead_of_spun_on(stub_control):
    """Nothing matches, so the loop must not sit there in silence.

    A live log holds 2340 consecutive passes — 12.5 minutes — with no action of
    any kind, ended only by the user pressing Stop. The cause was in `_step`:
    when nothing matched it reset `_stuck_count` to 0, so the stuck counter
    could never reach its limit and no escape ever fired. The screen that
    provoked it needs no guessing either — the shikigami picker scores at most
    0.803 against every template here, well under the 0.9 threshold.
    """
    worker = stub_control(matches={})          # nothing on screen at all

    for _ in range(realm_raid.UNKNOWN_SCREEN_LIMIT + 1):
        worker._step()

    assert worker._control.clicks == [worker._popup_dismiss], (
        "%d passes with nothing recognised and the loop never tried to escape"
        % realm_raid.UNKNOWN_SCREEN_LIMIT
    )


def test_a_screen_the_loop_understands_never_triggers_the_escape(stub_control):
    """The escape must not fire while the loop is working normally.

    The in-battle banner is the case that matters, and the reason this is not
    simply "no clicks for a while": it matches, it acts, and it clicks nothing
    at all. A loop that escaped on quiet alone would walk out of every battle.
    """
    worker = stub_control(matches={realm_raid.TPL_IN_BATTLE: (1077, 617)})

    for _ in range(20):
        worker._step()

    # The counter is what would drive the escape, so that is what is checked —
    # cheaper and more direct than running past the limit itself.
    assert worker._unknown_passes == 0, (
        "a screen the loop acted on still counted as adrift"
    )
    assert not worker._control.clicks, (
        "escaped from a screen it recognised: %s" % worker._control.clicks
    )


def test_stop_ends_the_thread_promptly(stub_control):
    # Arrange
    worker = stub_control()
    worker.start()
    time.sleep(SETTLE)
    assert worker._iteration > 0, "the loop never ran"

    # Act
    started = time.time()
    worker.stop()
    worker.join(3)
    elapsed = time.time() - started

    # Assert
    assert not worker.is_alive()
    assert elapsed < 1.0, "stop took %.2fs" % elapsed
    assert worker._control.closed, "GDI handles were not released"


def test_pause_freezes_the_loop_and_resume_restarts_it(stub_control):
    worker = stub_control()
    worker.start()
    time.sleep(SETTLE)

    worker.pause()
    time.sleep(0.1)
    frozen_at = worker._iteration
    time.sleep(SETTLE)

    assert worker.is_paused
    assert worker._iteration == frozen_at, "the loop kept running while paused"

    worker.resume()
    time.sleep(SETTLE)
    assert not worker.is_paused
    assert worker._iteration > frozen_at, "the loop did not resume"


def test_stop_wakes_a_paused_worker(stub_control):
    worker = stub_control()
    worker.start()
    time.sleep(SETTLE)
    worker.pause()
    time.sleep(0.1)

    worker.stop()
    worker.join(3)

    assert not worker.is_alive()


def test_finishes_when_the_test_attack_starts_no_battle(stub_control):
    """On the board, counter reading zero, and attacking changes nothing.

    The counter alone does not end a run any more. It is only believed once an
    attack has been tried and no battle followed — the reading was wrong often
    enough to matter: a live counter showing six tickets scored 0.745 against
    the stored zero, over the 0.72 the reader used.
    """
    done = threading.Event()
    messages: list[str] = []

    worker = stub_control(
        matches={realm_raid.TPL_SECTION: (46, 24)},
        tickets_zero=True,
        on_finished=lambda msg: (messages.append(msg), done.set()),
    )
    worker.start()

    # Three test attacks, each preceded by its own re-readings, so this takes
    # noticeably longer than the old single-reading verdict.
    assert done.wait(30), "on_finished never fired"
    worker.join(3)
    assert not worker.is_alive()
    assert worker._control.clicks, "it gave up without trying to attack once"
    assert "Hết vé" in messages[0]


# ── when the counter may be read at all ─────────────────────────────────────
# The counter lives in a fixed rectangle on the raid board. Read anywhere else,
# the digit segmentation finds a "0" in whatever art happens to be there — which
# ended runs that still had tickets, mid-battle.


def test_a_battle_in_progress_is_never_read_as_out_of_tickets(stub_control):
    """The reported bug: it stopped mid-fight with tickets left.

    The enemy list is matched here as well, standing in for a loose match of it
    against battle artwork. Being in a battle has to win on its own, so that a
    false positive on the list is not enough to get the counter believed.
    """
    done = threading.Event()

    worker = stub_control(
        matches={
            realm_raid.TPL_IN_BATTLE: (560, 300),
            realm_raid.TPL_SECTION: (46, 24),
        },
        tickets_zero=True,          # the region reads "0" because it is not the counter
        on_finished=lambda _msg: done.set(),
    )
    worker.start()

    assert not done.wait(NEVER), "it ended the run while a battle was on screen"
    assert worker.is_alive()


def test_a_battle_screen_alone_is_not_the_board_either(stub_control):
    done = threading.Event()

    worker = stub_control(
        matches={realm_raid.TPL_IN_BATTLE: (560, 300)},
        tickets_zero=True,
        on_finished=lambda _msg: done.set(),
    )
    worker.start()

    assert not done.wait(NEVER), "it ended the run from the battle screen"


@pytest.mark.parametrize(
    "covering",
    # TPL_START is not in this list any more, and the reason is worth reading:
    # see the two tests below it. A single sighting of the attack button still
    # must not end a run — but nine presses of it that produce no battle is not
    # a covered counter, it is a dead end, and treating it as one cost a live
    # run 107 presses of the same button.
    ["TPL_COOLDOWN", "TPL_CLAIM_REWARD", "TPL_READY_CLICK", "TPL_RAID_ENTRY"],
)
def test_the_counter_is_not_read_behind_a_popup_or_prompt(stub_control, covering):
    done = threading.Event()

    worker = stub_control(
        matches={getattr(realm_raid, covering): (300, 450),
                 realm_raid.TPL_SECTION: (46, 24)},
        tickets_zero=True,
        on_finished=lambda _msg: done.set(),
    )
    worker.start()

    assert not done.wait(NEVER), "%s did not stop the counter being trusted" % covering


def test_an_attack_that_keeps_being_refused_ends_the_run(stub_control):
    """The button that was pressed 107 times.

    With an enemy card open the attack button is on screen, its handler claims
    every pass, and the branch that reads the ticket counter is never reached —
    so the run could not end however many times the press was refused. The
    refusal is only visible as a toast that is gone in about a second, and
    missing it left the loop hammering the card forever.
    """
    done = threading.Event()

    worker = stub_control(
        matches={realm_raid.TPL_START: (921, 339),
                 realm_raid.TPL_SECTION: (46, 24)},
        tickets_zero=True,
        on_finished=lambda _msg: done.set(),
    )
    worker.start()

    assert done.wait(SOON), "still pressing an attack the game keeps refusing"


def test_a_refused_attack_does_not_end_a_run_that_still_has_tickets(stub_control):
    """The counter still has the last word, which is what keeps this safe.

    A refusal can mean other things — a cooldown, a target that cannot be
    raided. Ending on the refusal alone would cut runs short.
    """
    done = threading.Event()

    worker = stub_control(
        matches={realm_raid.TPL_START: (921, 339),
                 realm_raid.TPL_SECTION: (46, 24)},
        tickets_zero=False,
        on_finished=lambda _msg: done.set(),
    )
    worker.start()

    assert not done.wait(NEVER), "ended a run that still had tickets"


def test_the_counter_is_not_read_off_the_board_at_all(stub_control):
    """Nothing matched — we are on some other screen, so the region is not the counter."""
    done = threading.Event()

    worker = stub_control(
        tickets_zero=True,
        on_finished=lambda _msg: done.set(),
    )
    worker.start()

    assert not done.wait(NEVER), "it stopped without ever seeing the raid board"


# ── one reading is not enough ───────────────────────────────────────────────


def tabs(guild, individual):
    """Brightness for the two raid tabs, at the reference client size."""
    return {geometry.GUILD_TAB_PATCH: guild,
            geometry.INDIVIDUAL_TAB_PATCH: individual}


def test_a_guild_board_at_zero_ends_the_run_without_probing(stub_control):
    """Attacking cannot disprove a guild count, so it is not tried.

    The individual board refuses an attack once the tickets are gone, which is
    what makes "attack and see whether a battle follows" a real test there. A
    guild board allows the fight anyway. On a live run the loop attacked at 0/6,
    the fight ran through to "Battle finished", and the probe took that battle as
    proof the count was wrong — then read zero again, attacked again, and kept
    that up for as long as the task was left running.
    """
    done = threading.Event()
    worker = stub_control(
        matches={realm_raid.TPL_SECTION: ENEMY_AT},
        brightness=tabs(143, 82),          # the guild tab is the lit one
        tickets_zero=True,
        on_finished=lambda _msg: done.set(),
    )
    worker.start()

    assert done.wait(SOON), "kept going with the guild count at zero"
    assert worker._failed_probes == 0, "it probed a board that cannot be probed"


def test_an_individual_board_at_zero_still_probes(stub_control):
    """The probe stays where it earns its place.

    A live account with six tickets had the "6" of "6/30" score 0.745 against
    the stored "0", over the 0.72 the reader trusts — so on that board a zero
    reading alone is not enough to end a run.
    """
    worker = stub_control(
        matches={realm_raid.TPL_SECTION: ENEMY_AT},
        brightness=tabs(79, 136),          # the individual tab is the lit one
        tickets_zero=True,
    )
    worker.start()
    time.sleep(SETTLE)
    worker.stop()
    worker.join(3)

    assert worker._probing or worker._failed_probes, "it never tried an attack"


@pytest.mark.parametrize(
    "guild, individual, expected, what",
    # Measured on live frames, dimmed and not. The dimming halves both, which is
    # exactly why the pair is compared rather than either being thresholded.
    [(143.7, 82.8, True, "guild board"),
     (59.1, 34.1, True, "guild board behind an open enemy card"),
     (79.4, 136.3, False, "individual board")],
)
def test_the_brighter_tab_says_which_board_is_showing(
    stub_control, guild, individual, expected, what
):
    """A fixed cut-off was tried first and failed in use.

    An open enemy card dims the board behind it, and the lit Guild tab fell from
    143.7 to 59.1 — under any line drawn for the undimmed screen. The tool then
    read the individual board's ticket pill, which on a guild board is bare
    background, and kept attacking at 0/6.
    """
    worker = stub_control(brightness=tabs(int(guild), int(individual)))

    assert worker._on_guild_board() is expected, what


def test_each_board_has_its_own_counter_read(stub_control):
    """They count different things in different places.

    Individual counts tickets, "0/30", top right. Guild counts attempts left,
    "4/6", in the left panel — and reading the individual spot on a guild board
    reads bare background, which is why "tự dừng khi hết vé" could never fire
    there.
    """
    on_guild = stub_control(brightness=tabs(143, 82))
    on_guild._tickets_exhausted()

    assert on_guild._guild_attempts in on_guild._control.regions_read
    assert on_guild._ticket_region not in on_guild._control.regions_read

    on_individual = stub_control(brightness=tabs(79, 136))
    on_individual._tickets_exhausted()

    assert on_individual._ticket_region in on_individual._control.regions_read
    assert on_individual._guild_attempts not in on_individual._control.regions_read


def test_a_single_zero_reading_does_not_end_the_run(stub_control):
    """A screen sliding in can cover the counter for one frame."""
    done = threading.Event()
    readings = iter([True])

    worker = stub_control(
        matches={realm_raid.TPL_SECTION: (46, 24)},
        tickets_zero=lambda: next(readings, False),
        on_finished=lambda _msg: done.set(),
    )
    worker.start()

    assert not done.wait(NEVER), "one zero reading was taken as final"
    assert worker._zero_reads == 0, "the counter never went back to normal"


def test_it_holds_still_instead_of_attacking_while_re_checking(stub_control,
                                                              monkeypatch):
    """Clicking would start a battle, putting the next reading on the wrong screen.

    This is the one test here that needs the re-check interval *not* shrunk to
    nothing: it has to catch the worker mid-count, and the fixture's global
    speedup would let it finish counting and get to the probe — which attacks on
    purpose — before the assertion ever ran. So the interval is set here, and
    the wait is derived from it rather than being a number that happened to work.
    """
    interval = 0.25
    monkeypatch.setattr(realm_raid, "TICKET_RECHECK_SECONDS", interval)
    worker = stub_control(
        matches={realm_raid.TPL_SECTION: (46, 24)},
        tickets_zero=lambda: True,
    )
    worker.start()
    # Strictly fewer than the readings it takes to finish counting, so the
    # worker is still undecided when this looks.
    time.sleep(interval * (realm_raid.TICKET_ZERO_CONFIRMATIONS - 1))
    worker.stop()
    worker.join(3)

    assert not worker._control.clicks, "it attacked while the reading was unconfirmed"


def test_a_normal_reading_clears_the_count(stub_control):
    worker = stub_control(matches={realm_raid.TPL_SECTION: (46, 24)})
    worker._zero_reads = 2

    assert worker._ticket_verdict() == realm_raid.TICKETS_LEFT
    assert worker._zero_reads == 0


def test_the_verdict_needs_the_configured_number_of_readings(stub_control):
    """Repeated readings first, then an attack to test them, only then gone."""
    worker = stub_control(
        matches={realm_raid.TPL_SECTION: (46, 24)}, tickets_zero=True
    )

    seen = [worker._ticket_verdict()
            for _ in range(realm_raid.TICKET_ZERO_CONFIRMATIONS)]

    assert seen[:-1] == [realm_raid.TICKETS_PENDING] * (len(seen) - 1)
    assert seen[-1] == realm_raid.TICKETS_PROBE, "ended a run on a reading alone"

    # Every probe after the first also has to fail before the account is
    # called empty: one silent probe can just be a click that missed.
    verdicts = [worker._ticket_verdict() for _ in range(20)]
    assert verdicts.count(realm_raid.TICKETS_PROBE) ==         realm_raid.TICKET_PROBE_ATTEMPTS - 1, "gave up after a single probe"
    assert realm_raid.TICKETS_GONE in verdicts


def test_the_games_own_refusal_ends_the_run_without_probing(stub_control):
    """"Not enough Realm Challenge Passes" is the answer, not a hint.

    Reading the counter is guesswork — a live "6/30" scored 0.745 against the
    stored "0" — and a probe that starts no battle only says something did not
    happen. The message says why, so it needs no confirming and no repeat
    attacks.
    """
    import realm_raid as rr

    worker = stub_control(
        matches={rr.TPL_START: (60, 60), rr.TPL_NO_PASSES: (500, 210),
                 rr.TPL_SECTION: (46, 24)},
        match_score=0.95,
        tickets_zero=True,
    )

    worker._click_attack()
    assert worker._passes_refused, "ignored the game saying why the attack failed"

    assert worker._ticket_verdict() == rr.TICKETS_GONE
    assert worker._failed_probes == 0, "probed anyway after a definite answer"


def test_the_refusal_is_forgotten_once_tickets_are_back(stub_control):
    """Passes refill. A run left believing otherwise would never attack again."""
    import realm_raid as rr

    worker = stub_control(matches={rr.TPL_SECTION: (46, 24)}, tickets_zero=False)
    worker._passes_refused = True

    assert worker._ticket_verdict() == rr.TICKETS_LEFT
    assert not worker._passes_refused


def test_the_attack_waits_for_the_board_to_leave_before_carrying_on(stub_control):
    """Otherwise the next pass clicks into a screen already on its way out.

    Measured in a live log: every second attack failed with "the enemy card did
    not open", because the loop came back a second after the attack, found the
    board still painted mid-transition, and clicked an enemy that was gone by
    the time the click landed. Tickets sat unspent while the loop looked busy.
    """
    import realm_raid as rr

    # StubControl.match always answers (11, 22) — the attack click goes there.
    worker = stub_control(match_score=0.95)
    looks = []
    real_find = worker._find

    def counting_find(template, *args, **kwargs):
        looks.append(template)
        return real_find(template, *args, **kwargs)

    worker._find = counting_find
    worker._click_attack()

    assert (11, 22) in worker._control.clicks, "never clicked the attack button"
    assert rr.TPL_SECTION in looks, (
        "clicked and returned without checking the board had gone"
    )


def test_a_board_that_never_clears_does_not_hang_the_loop(stub_control, monkeypatch):
    """A stuck board must cost one short wait, not the run."""
    import realm_raid as rr

    monkeypatch.setattr(rr, "ATTACK_HANDOVER_SECONDS", 0.5)
    monkeypatch.setattr(rr, "ATTACK_HANDOVER_POLL", 0.1)
    worker = stub_control(
        matches={rr.TPL_SECTION: (40, 40)},   # board never clears
        match_score=0.95,
    )

    worker._click_attack()          # returns once the deadline passes

    assert (11, 22) in worker._control.clicks


def test_every_screen_that_proves_a_battle_clears_the_zero_verdict(stub_control):
    """The probe is only as good as what counts as proof of a battle.

    The first version watched the in-battle banner alone. On a live account
    that banner matched **zero** times across 281 finished battles, so the
    probe always concluded the tickets were gone — a fix that shipped and did
    nothing. Setting the flag by hand in a test hid it, because the test never
    asked which handler sets it.
    """
    import realm_raid as rr

    provers = [
        (rr.TPL_FINISHED_BATTLE, "_handle_battle_finished"),
        (rr.TPL_CLAIM_REWARD, "_handle_claim_reward"),
        (rr.TPL_IN_BATTLE, "_handle_in_battle"),
    ]
    for template, handler_name in provers:
        worker = stub_control(matches={template: (40, 40)})
        assert not worker._saw_battle
        handled = getattr(worker, handler_name)()
        assert handled, "%s did not fire on its own template" % handler_name
        assert worker._saw_battle, (
            "%s ran but left no proof a battle happened, so the ticket probe "
            "would read it as no battle" % handler_name
        )


def test_a_battle_after_the_test_attack_means_the_reading_was_wrong(stub_control):
    """The case this exists for: the counter says zero and it is not true.

    Six tickets read as zero on a live game, because the leftmost glyph of
    "6/30" scored 0.745 against the stored "0" and the reader believed anything
    over 0.72. A battle starting is proof a ticket was there to spend, and it
    outranks any reading of the counter.
    """
    worker = stub_control(
        matches={realm_raid.TPL_SECTION: (46, 24)}, tickets_zero=True
    )
    for _ in range(realm_raid.TICKET_ZERO_CONFIRMATIONS):
        worker._ticket_verdict()

    worker._saw_battle = True          # the test attack started a fight

    assert worker._ticket_verdict() == realm_raid.TICKETS_LEFT
    assert worker._zero_reads == 0, "kept counting towards a verdict it withdrew"
    assert worker._failed_probes == 0, "kept a strike against an account with tickets"


def test_with_auto_stop_off_it_never_reports_gone(stub_control):
    worker = stub_control(
        matches={realm_raid.TPL_SECTION: (46, 24)},
        tickets_zero=True,
        stop_when_out_of_tickets=False,
    )

    seen = [worker._ticket_verdict()
            for _ in range(realm_raid.TICKET_ZERO_CONFIRMATIONS + 2)]

    assert realm_raid.TICKETS_GONE not in seen
    assert seen[realm_raid.TICKET_ZERO_CONFIRMATIONS - 1] == realm_raid.TICKETS_PROBE


def test_an_unexpected_error_is_reported_and_handles_released(stub_control):
    failed = threading.Event()
    messages: list[str] = []

    worker = stub_control(
        raises=RuntimeError("boom"),
        on_error=lambda msg: (messages.append(msg), failed.set()),
    )
    worker.start()

    assert failed.wait(3), "on_error never fired"
    worker.join(3)
    assert "boom" in messages[0]
    assert worker._control.closed


def test_capture_errors_do_not_kill_the_loop(stub_control):
    from game_control import CaptureError

    worker = stub_control(raises=CaptureError("window went away"))
    worker.start()
    # Each failure backs off by CAPTURE_RETRY_SECONDS, so allow two of them.
    time.sleep(realm_raid.CAPTURE_RETRY_SECONDS * 2 + 0.3)

    assert worker.is_alive(), "a transient capture failure ended the run"
    assert worker._iteration > 1, "the loop did not retry after a capture failure"


def test_cooldown_popup_is_dismissed_before_anything_is_attacked(stub_control):
    """Both templates match; the cooldown popup must win."""
    worker = stub_control(
        matches={
            realm_raid.TPL_COOLDOWN: (300, 450),
            realm_raid.TPL_SECTION: (46, 24),
        }
    )
    worker.start()
    time.sleep(SETTLE)
    worker.stop()
    worker.join(3)

    assert worker._control.clicks, "nothing was clicked"
    assert set(worker._control.clicks) == {geometry.POPUP_DISMISS_POINT}, (
        "it clicked something other than the popup dismiss point"
    )


def test_a_reward_panel_is_clicked_through(stub_control):
    worker = stub_control(matches={realm_raid.TPL_CLAIM_REWARD: (554, 476)})
    worker.start()
    time.sleep(SETTLE)
    worker.stop()
    worker.join(3)

    assert worker._control.clicks.count((554, 476)) >= 2, "the reward needs two clicks"


def test_the_loop_reports_no_battle_count(stub_control):
    """It could only be inferred from reward panels, so it drifted. Gone on purpose."""
    worker = stub_control()

    assert not hasattr(worker, "progress"), "a count came back"
    assert not hasattr(worker, "completed_raids")


def test_a_stuck_screen_eventually_dismisses_a_popup(stub_control):
    """The START button matching forever means an invisible modal is in the way."""
    worker = stub_control(matches={realm_raid.TPL_START: (804, 190)})
    worker.start()

    deadline = time.time() + 5
    while time.time() < deadline:
        if geometry.POPUP_DISMISS_POINT in worker._control.clicks:
            break
        time.sleep(0.05)
    worker.stop()
    worker.join(3)

    assert geometry.POPUP_DISMISS_POINT in worker._control.clicks, (
        "never tried to dismiss a popup after %d stuck frames" % realm_raid.STUCK_LIMIT
    )


def test_defeat_queues_a_refresh_only_when_enabled(stub_control):
    worker = stub_control(
        matches={realm_raid.TPL_FAILED: (379, 174)}, auto_refresh=True
    )
    worker.start()
    time.sleep(SETTLE)
    worker.stop()
    worker.join(3)

    assert worker._control.clicks, "the defeat dialog was never dismissed"


def test_fixed_points_are_resolved_from_geometry(stub_control):
    """No deployment slot among them any more — see geometry for why.

    Checked on the signature and on the module, not on an attribute: the line
    that went was `self._target = ...`, and `threading.Thread` already owns
    `self._target`. So it was quietly shadowing a base-class attribute the whole
    time — harmless only because this class overrides `run()` — which is the
    same trap as the `_stop` one written up in test_recorder.
    """
    worker = stub_control()

    assert "slot" not in inspect.signature(RealmRaidWorker.__init__).parameters
    assert not hasattr(geometry, "TARGET_SLOTS"), "the slot table came back"
    assert worker._ready_button == geometry.TAP_READY_BUTTON
    assert worker._popup_dismiss == geometry.POPUP_DISMISS_POINT


def test_each_pass_opens_and_closes_exactly_one_cached_frame(stub_control):
    """The frame cache is what keeps N windows from doing N×14 captures."""
    worker = stub_control()
    worker.start()
    time.sleep(SETTLE)
    worker.stop()
    worker.join(3)

    control = worker._control
    assert control.frames_begun > 0, "the loop never opened a frame"
    assert control.frames_begun == control.frames_ended, (
        "a pass left the frame cache open: %d begun, %d ended"
        % (control.frames_begun, control.frames_ended)
    )
    assert control.frames_begun == worker._iteration


def test_out_of_tickets_keeps_running_when_auto_stop_is_off(stub_control):
    finished = threading.Event()

    worker = stub_control(
        tickets_zero=True,
        stop_when_out_of_tickets=False,
        on_finished=lambda _msg: finished.set(),
    )
    worker.start()
    time.sleep(SETTLE)

    assert worker.is_alive(), "it stopped even though auto-stop was disabled"
    assert not finished.is_set(), "it reported finishing with auto-stop disabled"


# ── co-op Wanted Quest invites ──────────────────────────────────────────────
# The dialog stacks Refuse directly under Accept. Both must be seen, aligned
# and correctly spaced before anything is clicked.

ACCEPT_AT = (747, 367)
REFUSE_AT = (747, 457)


def invite(accept=ACCEPT_AT, refuse=REFUSE_AT):
    return {
        realm_raid.TPL_WANTED_ACCEPT: accept,
        realm_raid.TPL_WANTED_REFUSE: refuse,
    }


def run_briefly(worker):
    worker.start()
    time.sleep(SETTLE)
    worker.stop()
    worker.join(3)
    return worker._control.clicks


def test_invite_is_refused_by_default(stub_control):
    clicks = run_briefly(stub_control(matches=invite()))
    assert REFUSE_AT in clicks
    assert ACCEPT_AT not in clicks


def test_invite_can_be_accepted(stub_control):
    clicks = run_briefly(stub_control(matches=invite(), accept_wanted_quest=True))
    assert ACCEPT_AT in clicks
    assert REFUSE_AT not in clicks


def test_a_lone_accept_button_is_not_treated_as_an_invite(stub_control):
    """Other dialogs show a green tick; only this one pairs it with a red cross."""
    clicks = run_briefly(
        stub_control(matches={realm_raid.TPL_WANTED_ACCEPT: ACCEPT_AT})
    )
    assert not clicks


def test_misaligned_buttons_are_rejected(stub_control):
    clicks = run_briefly(stub_control(matches=invite(refuse=(900, 457))))
    assert not clicks


def test_wrongly_spaced_buttons_are_rejected(stub_control):
    clicks = run_briefly(stub_control(matches=invite(refuse=(747, 600))))
    assert not clicks


def test_invite_is_answered_before_anything_else_is_clicked(stub_control):
    """The dialog covers the board, so every other handler must wait."""
    matches = invite()
    matches[realm_raid.TPL_SECTION] = (46, 24)
    matches[realm_raid.TPL_COOLDOWN] = (300, 450)

    clicks = run_briefly(stub_control(matches=matches))

    assert clicks, "nothing was clicked"
    assert set(clicks) == {REFUSE_AT}, "it clicked past the invite dialog"


def test_elapsed_time_advances_and_pauses(stub_control):
    worker = stub_control()
    worker.start()
    time.sleep(SETTLE)

    running = worker.elapsed_seconds
    assert running > 0, "elapsed time never started"

    worker.pause()
    frozen = worker.elapsed_seconds
    time.sleep(0.3)
    assert abs(worker.elapsed_seconds - frozen) < 0.05, "the clock ran while paused"

    worker.resume()
    time.sleep(0.2)
    assert worker.elapsed_seconds > frozen, "the clock did not restart"


# ── clicking the attack button ──────────────────────────────────────────────


def test_the_attack_button_is_clicked_while_it_is_still_animating_in(stub_control):
    """It rarely clears the usual threshold right after the card opens.

    Holding it to 0.9 here would stall every raid, which is why the low score
    is tolerated at all.
    """
    worker = stub_control(match_score=0.62)

    worker._click_attack()

    assert worker._control.clicks == [(11, 22)]


def test_an_absent_attack_button_is_not_clicked(stub_control, caplog):
    """0.44 is not a button fading in — it is no button on screen.

    A real run on a 125% laptop logged 0.32 to 0.44 over and over while the
    enemy card never opened. Clicking the best match then means clicking
    whatever noise scored highest, somewhere unrelated.
    """
    worker = stub_control(match_score=0.44)

    with caplog.at_level("WARNING"):
        worker._click_attack()

    assert worker._control.clicks == [], "clicked at noise"
    assert "did not open" in caplog.text


def test_the_floor_sits_below_anything_that_might_be_the_button(stub_control):
    """Set too high it would stall working raids, so it only blocks the absent."""
    assert realm_raid.ATTACK_FLOOR < realm_raid.DEFAULT_ACCURACY
    assert realm_raid.ATTACK_FLOOR > 0.44, "an absent button scored 0.44 in the wild"
