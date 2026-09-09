"""The souls dungeon loop.

Nothing here touches Windows: the capture and the clicks are stubbed, so these
run headless and never post input anywhere.

The two things worth pinning hardest:

* **Counting on the rising edge.** The result screen sits there for several
  seconds while the loop looks every second, so counting per pass would score
  one battle as four or five — and with a round limit, that ends the run early.
* **Not pressing a dead Fight button.** Three seconds after a battle the room is
  back but the teammate has not rejoined, so the button is grey. Shape alone
  cannot tell; the colour can.
"""
from __future__ import annotations

import threading
import time

import numpy as np
import pytest

import geometry
import souls_dungeon
from souls_dungeon import ROLE_LEADER, ROLE_MEMBER, SoulsDungeonWorker

REFERENCE = geometry.REFERENCE_CLIENT_SIZE
SETTLE = 0.4


class StubControl:
    """Returns whichever templates the test set up, and records clicks."""

    def __init__(self, hwnd, matches=None, saturation=200.0):
        self.client_width, self.client_height = REFERENCE
        self.clicks: list = []
        # False stands in for the real control refusing to click
        # because the player's own cursor is over the game window.
        self.clicking = True
        self.closed = False
        self.matches = dict(matches or {})
        self.saturation = saturation
        self.frames_begun = 0
        self.frames_ended = 0

    def describe(self):
        return "stub control"

    def find(self, template_path, threshold=0.9, region=None, gray=True, delay=0.1):
        time.sleep(0.001)  # keep the loop from spinning the CPU flat out
        return self.matches.get(template_path)

    def part_shot(self, region, gray=False):
        """A patch whose mean HSV saturation is exactly what the test asked for.

        Built in BGR directly rather than via cvtColor(HSV2BGR): that round trip
        is lossy by a unit or two, which is invisible against the real 4.5-vs-149
        gap but enough to flip a value sitting on the threshold.

        OpenCV defines saturation as (max - min) / max * 255. With max pinned at
        255, a channel minimum of 255 - s gives exactly s.
        """
        (x1, y1), (x2, y2) = region
        height, width = max(1, y2 - y1), max(1, x2 - x1)
        low = max(0, 255 - int(round(self.saturation)))
        patch = np.zeros((height, width, 3), dtype=np.uint8)
        patch[:, :, 0] = low     # blue
        patch[:, :, 1] = low     # green
        patch[:, :, 2] = 255     # red — the max channel
        return patch

    def withholding_clicks(self):
        """Whether the real control would refuse to click right now.

        `clicking = False` stands for the player's own cursor resting over the
        game window. The loops ask this before a pass, so a stub that cannot
        answer it makes every loop run passes the real one would skip.
        """
        return not self.clicking

    def click(self, point):
        self.clicks.append(tuple(point))

    def close(self):
        self.closed = True

    def begin_frame(self):
        self.frames_begun += 1

    def end_frame(self):
        self.frames_ended += 1

    def invalidate_frame(self):
        pass

    def last_frame(self):
        return None


@pytest.fixture
def worker(monkeypatch):
    """Builds workers backed by StubControl and tears them down afterwards."""
    created: list = []

    def build(matches=None, saturation=200.0, armed=True, **kwargs):
        control = StubControl(1, matches, saturation)
        made = SoulsDungeonWorker(hwnd=1, control=control, **kwargs)
        if armed:
            # Most tests here are about what happens *during* a run, so they
            # skip past the start-up guard and begin as a worker does once the
            # screen it started on has cleared. The guard itself is covered by
            # the two tests named for it, which pass armed=False.
            made._in_result = False
            made._quiet_passes = souls_dungeon.RESULT_CLEAR_PASSES
        created.append(made)
        return made

    # Keep the loop brisk: the real waits are seconds long.
    monkeypatch.setattr(souls_dungeon, "BATTLE_POLL_SECONDS", 0.01)
    monkeypatch.setattr(souls_dungeon, "AFTER_FIGHT_SECONDS", 0.01)
    monkeypatch.setattr(souls_dungeon, "AFTER_TAP_SECONDS", 0.01)
    monkeypatch.setattr(souls_dungeon, "POPUP_SETTLE_SECONDS", 0.01)
    yield build

    for made in created:
        made.stop()
        if made.ident is not None:
            made.join(3)


# ── configuration ───────────────────────────────────────────────────────────


def test_rejects_an_unknown_role(worker):
    with pytest.raises(ValueError):
        worker(role="khan gia")


def test_rejects_a_negative_round_count(worker):
    with pytest.raises(ValueError):
        worker(rounds=-1)


# ── counting ────────────────────────────────────────────────────────────────


def test_a_result_screen_already_up_at_the_start_is_not_counted(worker):
    """It belongs to a battle this run did not fight.

    Starting the task moments after stopping it — with the last battle's screen
    still on display — used to score that screen immediately. A live log has
    both windows writing "Battle 1/9 finished" in the same second their workers
    started, before a single Fight press; the run went on to fight two battles
    and reported three.
    """
    made = worker(matches={souls_dungeon.TPL_TAP_CONTINUE: (561, 610)},
                  role=ROLE_MEMBER, armed=False)

    made._step()
    made._step()

    assert made.progress == 0, "counted a battle it never fought"
    assert made._control.clicks, "it should still tap the leftover screen away"


def test_the_first_real_battle_after_that_start_is_counted(worker):
    """The guard must delay the count, not lose it."""
    made = worker(matches={souls_dungeon.TPL_TAP_CONTINUE: (561, 610)},
                  role=ROLE_MEMBER, armed=False)

    made._step()                                   # the leftover screen
    made._control.matches.clear()                  # it clears; the room is back
    for _ in range(souls_dungeon.RESULT_CLEAR_PASSES):
        made._step()
    made._control.matches[souls_dungeon.TPL_TAP_CONTINUE] = (561, 610)
    made._step()                                   # a battle this run fought

    assert made.progress == 1


def test_a_result_screen_counts_once_however_long_it_lingers(worker):
    """It sits there for seconds; the loop looks every second."""
    made = worker(matches={souls_dungeon.TPL_TAP_CONTINUE: (561, 610)},
                  role=ROLE_MEMBER)
    made.start()
    time.sleep(SETTLE)
    made.stop()
    made.join(3)

    assert made._iteration > 3, "the loop barely ran; the test proves nothing"
    assert made.progress == 1, (
        "counted %d battles from one result screen over %d passes"
        % (made.progress, made._iteration)
    )


def test_one_quiet_pass_is_not_enough_to_count_again(worker):
    """A gap of one pass is the seam between a battle's two result screens."""
    made = worker(matches={souls_dungeon.TPL_TAP_CONTINUE: (561, 610)},
                  role=ROLE_MEMBER)

    made._step()                       # sees the result, counts 1
    assert made.progress == 1
    made._control.matches.clear()      # one pass with nothing matching
    made._step()
    assert made.progress == 1, "counted again while nothing was on screen"

    made._control.matches[souls_dungeon.TPL_TAP_CONTINUE] = (561, 610)
    made._step()
    assert made.progress == 1, "one quiet pass was taken as a new battle"


def test_both_result_screens_are_tapped_in_the_same_bare_spot(worker):
    """One spot serves both, and the point is which spot, not how many.

    They used to differ, and the reward screen's was the middle of the screen —
    where the loot and the line-up are drawn. Players reported runs sticking
    there: the tap opened a reward instead of dismissing the screen.
    """
    made = worker(matches={souls_dungeon.TPL_VICTORY: (840, 512)}, role=ROLE_MEMBER)
    made._step()
    assert made._control.clicks == [made._result_tap]

    made._control.clicks.clear()
    made._control.matches = {souls_dungeon.TPL_TAP_CONTINUE: (561, 610)}
    made._step()
    assert made._control.clicks == [made._result_tap], "the two screens diverged"


def test_the_result_tap_stays_off_the_loot_and_the_line_up(worker):
    """The avatars sit at (680, 320) and (790, 320) on a 1124x633 client."""
    made = worker()
    x, y = made._result_tap

    for avatar in ((680, 320), (790, 320)):
        assert abs(x - avatar[0]) > 120 or abs(y - avatar[1]) > 80, (
            "the tap at %s sits on the avatar at %s" % ((x, y), avatar))
    middle = (geometry.REFERENCE_CLIENT_SIZE[0] // 2,
              geometry.REFERENCE_CLIENT_SIZE[1] // 2)
    assert abs(x - middle[0]) > 200, "back in the middle, where the loot is"


def test_the_result_tap_does_not_land_on_the_fight_button(worker):
    """A tap arriving one pass late would otherwise press Fight blind.

    Fight is gated on the button being lit, because for a few seconds after a
    battle the room is back but the teammates are not. A tap that fell on the
    button would walk straight past that check.
    """
    made = worker()
    x, y = made._result_tap
    (bx1, by1), (bx2, by2) = made._fight_patch

    assert not (bx1 <= x <= bx2 and by1 <= y <= by2), "the tap is on the button"
    assert y < by1 - 20, "only %dpx above the Fight button" % (by1 - y)


def test_one_battle_showing_both_result_screens_counts_once(worker):
    """The gap between Victory and the reward screen used to reset the edge.

    A real run logged three battles in 44 seconds — two of them 6 and 16
    seconds apart, which no fight takes.
    """
    made = worker(matches={souls_dungeon.TPL_VICTORY: (840, 512)}, role=ROLE_MEMBER)

    made._step()                                   # Victory
    assert made.progress == 1
    made._control.matches.clear()                  # the gap between the two
    made._step()
    made._control.matches = {souls_dungeon.TPL_TAP_CONTINUE: (561, 610)}
    made._step()                                   # reward screen

    assert made.progress == 1, "the two screens of one battle counted twice"


def test_a_genuinely_new_battle_still_counts(worker):
    """The debounce must not swallow the next battle."""
    made = worker(matches={souls_dungeon.TPL_TAP_CONTINUE: (561, 610)},
                  role=ROLE_MEMBER)

    made._step()
    assert made.progress == 1
    made._control.matches.clear()
    for _ in range(souls_dungeon.RESULT_CLEAR_PASSES):
        made._step()
    made._control.matches = {souls_dungeon.TPL_TAP_CONTINUE: (561, 610)}
    made._step()

    assert made.progress == 2


def test_the_victory_banner_counts_as_the_same_battle(worker):
    """Victory then the reward screen is one battle, not two."""
    made = worker(matches={souls_dungeon.TPL_VICTORY: (840, 512)},
                  role=ROLE_MEMBER)

    made._step()
    assert made.progress == 1
    # The banner gives way to the reward screen without returning to the room.
    made._control.matches = {souls_dungeon.TPL_TAP_CONTINUE: (561, 610)}
    made._step()

    assert made.progress == 1, "the same battle was counted twice"


def test_the_run_ends_at_the_requested_round_count(worker):
    done = threading.Event()
    messages: list = []

    made = worker(
        matches={souls_dungeon.TPL_TAP_CONTINUE: (561, 610)},
        role=ROLE_MEMBER, rounds=1,
        on_finished=lambda msg: (messages.append(msg), done.set()),
    )
    made.start()

    assert done.wait(3), "on_finished never fired"
    made.join(3)
    assert not made.is_alive()
    assert made.progress == 1
    assert "1 trận" in messages[0]


def test_zero_rounds_means_it_keeps_going(worker):
    done = threading.Event()
    made = worker(
        matches={souls_dungeon.TPL_TAP_CONTINUE: (561, 610)},
        role=ROLE_MEMBER, rounds=0,
        on_finished=lambda _msg: done.set(),
    )
    made.start()

    assert not done.wait(1.0), "it stopped even though no limit was set"
    assert made.is_alive()
    # Still on the same result screen, so still one battle — the loop running on
    # is what "no limit" means, not the count climbing.
    assert made.progress == 1
    assert made._iteration > 3, "the loop stalled rather than kept going"


# ── the Fight button ────────────────────────────────────────────────────────


def test_a_lit_button_is_pressed(worker):
    made = worker(matches={souls_dungeon.TPL_FIGHT: (1072, 562)}, saturation=149)

    assert made._step() is False
    assert made._control.clicks == [made._fight_button]


def test_a_dead_button_is_left_alone(worker):
    """Right after a battle the room is back but the teammate is not."""
    made = worker(matches={souls_dungeon.TPL_FIGHT: (1072, 562)}, saturation=4.5)

    made._step()
    made._step()

    assert made._control.clicks == [], "it pressed a Fight button that was greyed out"


@pytest.mark.parametrize(
    "saturation, pressed",
    [(4.5, False), (40, False), (79, False), (81, True), (149, True), (200, True)],
)
def test_the_saturation_threshold(worker, saturation, pressed):
    """Measured on real frames: 4.5 when dead, 149 when lit."""
    made = worker(matches={souls_dungeon.TPL_FIGHT: (1072, 562)}, saturation=saturation)

    made._step()

    assert bool(made._control.clicks) is pressed


def test_a_member_never_presses_fight(worker):
    """There is no Fight button on a member's screen; pressing would be a stray click."""
    made = worker(matches={souls_dungeon.TPL_FIGHT: (1072, 562)},
                  saturation=200, role=ROLE_MEMBER)

    made._step()
    made._step()

    assert made._control.clicks == []


# ── the invite, which blocks every task ─────────────────────────────────────


def test_an_invite_is_answered_before_anything_else(worker, monkeypatch):
    """The modal swallows clicks underneath, so nothing else can progress."""
    monkeypatch.setattr(
        souls_dungeon.wanted_invite, "find_reply",
        lambda control, layout, accept: (500, 400),
    )
    made = worker(matches={souls_dungeon.TPL_FIGHT: (1072, 562)}, saturation=200)

    made._step()

    assert made._control.clicks == [(500, 400)], "it acted on the board under a modal"


def test_the_reply_follows_the_app_wide_setting(worker, monkeypatch):
    seen = []
    monkeypatch.setattr(
        souls_dungeon.wanted_invite, "find_reply",
        lambda control, layout, accept: seen.append(accept) or None,
    )
    made = worker(accept_wanted_quest=True)

    made._step()

    assert seen == [True]


# ── lifecycle ───────────────────────────────────────────────────────────────


def test_stop_ends_the_thread_promptly(worker):
    made = worker()
    made.start()
    time.sleep(SETTLE)
    assert made._iteration > 0, "the loop never ran"

    started = time.time()
    made.stop()
    made.join(3)

    assert not made.is_alive()
    assert time.time() - started < 1.0
    assert made._control.closed, "GDI handles were not released"


def test_pause_freezes_the_loop(worker):
    made = worker()
    made.start()
    time.sleep(SETTLE)
    made.pause()
    time.sleep(0.1)
    before = made._iteration
    time.sleep(SETTLE)

    assert made._iteration == before, "the loop kept running while paused"
    assert made.is_paused

    made.resume()
    time.sleep(SETTLE)
    assert made._iteration > before


def test_one_cached_frame_per_pass(worker):
    made = worker()
    made.start()
    time.sleep(SETTLE)
    made.stop()
    made.join(3)

    assert made._control.frames_begun == made._control.frames_ended
    assert made._control.frames_begun >= made._iteration - 1
