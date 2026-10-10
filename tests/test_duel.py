"""The Duel (Đấu PvP) loop, against screens from a real run.

The fixtures are frames of recordings/pvp — 18 ranked matches from Tier 1 to
Tier 5 — scaled to the reference client size and kept in grey, with everything
outside the areas the task looks at blacked out to keep them small. The "Prac."
lobby is the one built screen: a player's capture of that drum pasted over the
Battle drum, which it lines up with at 0.90.

``lobby_live`` is different: captured by the tool itself from a 1122x633 client,
exactly as a run sees the game, not resized from a recording. Its first run
stopped at once — the slash there is 4 px wide where every recorded one was 3,
and scored 0.66 against them. The recorded screens alone could not have caught
that.

``lobby_celebrity`` is a player's screenshot (1117x631, stretched to the
reference) of a Grand Celebrity lobby outside PvP hours: stars, "5/30", where
the tiers show a score, and the Prac. drum.

Nothing here posts input. The control is a real GameControl, so the real
matching runs, but its capture is a fixture and its clicks are a list.

The two things pinned hardest:

* **Every press is of a switch that is off.** Ready only while red, Auto Deploy
  only while it says so, Manual only while the battle is in Manual. Pressing
  any of them in the other state would undo what the task is there to do.
* **The score is read, or the run stops.** A misread number could carry the run
  past its target; an unreadable one ends it instead.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

import duel
import duel_score
import geometry
from conftest import bare_control
from duel import DuelWorker
from duel_score import ScoreReader

FIXTURES = Path(__file__).parent / "fixtures" / "duel"
REFERENCE = geometry.REFERENCE_CLIENT_SIZE


def load(name: str) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(FIXTURES / (name + ".png")), np.uint8),
                         cv2.IMREAD_GRAYSCALE)
    assert image is not None, name
    return image


def control_showing(frame: np.ndarray):
    """A GameControl whose window shows ``frame`` and whose clicks are kept."""
    made = bare_control(client=REFERENCE)
    colour = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    made.full_shot = lambda gray=False: frame if gray else colour
    made.clicks = []
    made.refused = 0     # clicks the real control would have withheld

    def click(point):
        if made.refusing:
            made.refused += 1
            return False
        made.clicks.append(tuple(point))
        return True

    made.click = click
    made.refusing = False
    made.holding = False
    made.withholding_clicks = lambda: made.holding
    made.close = lambda: None
    made.describe = lambda: "fixture"
    return made


@pytest.fixture(scope="module")
def reader():
    return ScoreReader()


@pytest.fixture
def worker(monkeypatch, reader):
    """A worker over one fixture screen, its waits cut to nothing."""
    for name in ("POLL_SECONDS", "AFTER_TAP_SECONDS", "AFTER_CLICK_SECONDS",
                 "AFTER_BATTLE_SECONDS", "CAPTURE_RETRY_SECONDS"):
        monkeypatch.setattr(duel, name, 0)

    def build(screen, target=0):
        frame = screen if isinstance(screen, np.ndarray) else load(screen)
        control = control_showing(frame)
        made = DuelWorker(hwnd=1, target=target, control=control, reader=reader)
        return made, control

    return build


def show(worker_and_control, screen):
    """Put another screen up in front of the same worker."""
    made, control = worker_and_control
    frame = load(screen)
    colour = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    control.full_shot = lambda gray=False: frame if gray else colour


def step(made) -> bool:
    made._control.begin_frame()
    try:
        return made._step()
    finally:
        made._control.end_frame()


def near(point, target, within=6) -> bool:
    return abs(point[0] - target[0]) <= within and abs(point[1] - target[1]) <= within


# ── reading the score ───────────────────────────────────────────────────────

SCORES = sorted(path.stem for path in (FIXTURES / "score").glob("*.png"))


def test_every_recorded_score_is_on_file():
    """Twenty recorded lobbies, Tier 1 to Tier 5, and one live capture."""
    assert len(SCORES) == 21
    assert set("".join(SCORES)) >= set("0123456789")


@pytest.mark.parametrize("name", SCORES)
def test_each_lobby_score_reads_exactly(reader, name):
    band = cv2.imdecode(np.fromfile(str(FIXTURES / "score" / (name + ".png")),
                                    np.uint8), cv2.IMREAD_GRAYSCALE)
    score, ceiling = (int(part) for part in name.split("-"))
    assert reader.read_band(band) == (score, ceiling)


def test_the_score_reads_off_a_whole_lobby(reader):
    assert reader.read(load("lobby")) == (1958, 2000)


def test_a_star_count_means_danh_si(reader):
    """Short of four digits is the player's own rule for "Danh sĩ reached"."""
    assert reader.read(load("lobby_celebrity")) == duel_score.CELEBRITY


@pytest.mark.parametrize("text, stars", [
    ("5/30", True), ("0/30", True), ("12/30", True), ("120/150", True),
    ("1958/2000", False), ("5", False), ("5/", False), ("", False),
])
def test_what_counts_as_a_star_count(text, stars):
    assert duel_score.is_star_count(text) is stars


def test_no_tier_lobby_is_taken_for_danh_si(reader):
    for screen in ("lobby", "lobby_live", "lobby_achievement", "tier_up"):
        assert reader.read(load(screen)) != duel_score.CELEBRITY, screen


def test_the_score_reads_off_a_live_capture(reader):
    """The first live run: its 4 px slash went unread and the run stopped."""
    assert reader.read(load("lobby_live")) == (1938, 2000)


@pytest.mark.parametrize("screen", ["matching", "pick_ready", "draft_auto_off",
                                    "battle_manual", "battle_auto", "result"])
def test_no_score_is_read_off_any_other_screen(reader, screen):
    """Not a wrong number: no number. A misread could end a run early or late."""
    assert reader.read(load(screen)) is None


def test_the_six_is_not_read_as_a_five(reader):
    """The case that sent the glyphs to normalised comparison.

    Slid across a padded glyph, as the ticket reader does, this "6" scored 0.90
    as a 5 and 0.84 as itself.
    """
    band = cv2.imdecode(np.fromfile(str(FIXTURES / "score" / "1760-1800.png"),
                                    np.uint8), cv2.IMREAD_GRAYSCALE)
    assert reader.read_band(band) == (1760, 1800)


@pytest.mark.parametrize("text, expected", [
    ("1958/2000", (1958, 2000)),
    ("2000/2000", (2000, 2000)),
    ("2001/2000", None),     # past the bar: a misread
    ("1958", None),          # no slash
    ("19/2000", None),       # too short to be a Duel score
    ("1958/", None),
    ("/2000", None),
])
def test_parse_accepts_only_a_plausible_score(text, expected):
    assert duel_score.parse(text) == expected


def test_a_smudge_among_the_digits_makes_it_unreadable(reader):
    band = cv2.imdecode(np.fromfile(str(FIXTURES / "score" / "1958-2000.png"),
                                    np.uint8), cv2.IMREAD_GRAYSCALE).copy()
    band[3:16, 22:30] = 255          # the second digit, now a solid block
    assert reader.read_band(band) is None


def test_missing_glyph_examples_fail_loudly(monkeypatch, tmp_path):
    (tmp_path / "Duel" / "digits").mkdir(parents=True)
    monkeypatch.setattr(duel_score, "template",
                        lambda *parts: str(tmp_path.joinpath(*parts)))
    with pytest.raises(ValueError, match="No glyph examples"):
        duel_score.load_examples()


# ── which screen is which ───────────────────────────────────────────────────

LOOKS = {
    "battle": (duel.TPL_BATTLE, duel.BATTLE_REGION, duel.DEFAULT_ACCURACY),
    "prac": (duel.TPL_PRAC, duel.BATTLE_REGION, duel.DEFAULT_ACCURACY),
    "ready": (duel.TPL_READY, duel.READY_REGION, duel.READY_ACCURACY),
    "manual": (duel.TPL_MANUAL, duel.MANUAL_REGION, duel.MANUAL_ACCURACY),
    "autoDeploy": (duel.TPL_AUTO_DEPLOY, duel.AUTO_DEPLOY_REGION,
                   duel.DEFAULT_ACCURACY),
    "tapContinue": (duel.TPL_TAP_CONTINUE, duel.PROMPT_REGION,
                    duel.DEFAULT_ACCURACY),
    "tapSkip": (duel.TPL_TAP_SKIP, duel.PROMPT_REGION, duel.DEFAULT_ACCURACY),
    "achievement": (duel.TPL_ACHIEVEMENT, duel.ACHIEVEMENT_REGION,
                    duel.DEFAULT_ACCURACY),
}

SEEN_ON = {
    "lobby": {"battle"},
    "lobby_live": {"battle"},
    "lobby_celebrity": {"prac"},
    "lobby_prac": {"prac"},
    "lobby_achievement": {"battle", "achievement"},
    "tier_up": {"tapSkip"},
    "matching": set(),
    "pick_ready": {"ready"},
    "pick_readied": set(),          # Ready gone grey: pressed already
    "draft_auto_off": {"autoDeploy"},
    "draft_auto_on": set(),         # reads "Cancel Auto"
    "battle_manual": {"manual"},
    "battle_auto": set(),
    "result": {"tapContinue"},
}


@pytest.mark.parametrize("screen", sorted(SEEN_ON))
def test_each_screen_shows_exactly_what_it_should(screen):
    control = control_showing(load(screen))
    found = {name for name, (path, region, accuracy) in LOOKS.items()
             if control.find(path, accuracy, region=region, delay=0) is not None}
    assert found == SEEN_ON[screen]


# ── what the loop does on each screen ───────────────────────────────────────

def test_the_lobby_queues_a_match(worker):
    made, control = worker("lobby")
    assert step(made) is False
    assert len(control.clicks) == 1
    assert near(control.clicks[0], (1049, 539), within=12)


@pytest.mark.parametrize("screen, button", [
    ("pick_ready", "ready"),
    ("draft_auto_off", "autoDeploy"),
    ("battle_manual", "manual"),
])
def test_a_switch_that_is_off_is_pressed_where_it_is(worker, screen, button):
    made, control = worker(screen)
    step(made)
    expected = control_showing(load(screen)).find(
        LOOKS[button][0], 0.5, region=LOOKS[button][1], delay=0)
    assert control.clicks == [expected]


@pytest.mark.parametrize("screen", ["pick_readied", "draft_auto_on",
                                    "battle_auto", "matching"])
def test_a_switch_that_is_on_is_left_alone(worker, screen):
    made, control = worker(screen)
    for _ in range(3):
        step(made)
    assert control.clicks == []


@pytest.mark.parametrize("screen", ["result", "tier_up", "lobby_achievement"])
def test_screens_in_the_way_are_tapped_at_the_bottom(worker, screen):
    """The achievement first, though the Battle drum shows through it."""
    made, control = worker(screen)
    step(made)
    assert control.clicks == [geometry.DUEL_TAP]


def test_ready_is_not_pressed_again_while_it_fades(worker):
    made, control = worker("pick_ready")
    for _ in range(4):
        step(made)
    assert len(control.clicks) == 1


def test_ready_is_pressed_again_once_the_wait_is_over(worker, monkeypatch):
    """A press the game missed is not given up on."""
    monkeypatch.setattr(duel, "READY_REPEAT_SECONDS", 0)
    made, control = worker("pick_ready")
    step(made)
    step(made)
    assert len(control.clicks) == 2


def test_a_withheld_press_does_not_start_the_wait(worker):
    """Refused for the cursor, nothing changed on screen; try again next pass."""
    made, control = worker("pick_ready")
    control.refusing = True
    step(made)
    control.refusing = False
    step(made)
    assert control.refused == 1 and len(control.clicks) == 1


def test_battle_is_not_pressed_again_while_the_lobby_lingers(worker):
    made, control = worker("lobby")
    for _ in range(4):
        step(made)
    assert len(control.clicks) == 1


# ── counting ────────────────────────────────────────────────────────────────

def test_a_result_screen_counts_once_however_long_it_stays(worker):
    made, control = worker("lobby")
    step(made)
    show((made, control), "result")
    for _ in range(5):
        step(made)
    assert made.progress == 1


def test_the_result_back_after_an_achievement_is_the_same_match(worker):
    """Tapping the achievement away uncovers the same result (293.9 s)."""
    made, control = worker("lobby")
    step(made)
    for screen in ("result", "lobby_achievement", "lobby_achievement",
                   "lobby_achievement", "lobby_achievement", "result",
                   "tier_up", "tier_up", "tier_up"):
        show((made, control), screen)
        step(made)
    assert made.progress == 1


def test_each_match_of_a_run_is_counted(worker):
    made, control = worker("lobby")
    for screen in ("pick_ready", "battle_manual", "battle_auto", "result",
                   "lobby", "matching", "draft_auto_off", "battle_auto",
                   "result", "result"):
        show((made, control), screen)
        step(made)
    assert made.progress == 2


def test_a_result_left_over_from_before_the_run_is_not_counted(worker):
    made, _ = worker("result")
    step(made)
    assert made.progress == 0


def test_a_result_under_the_cursor_is_counted_but_not_tapped(worker):
    made, control = worker("battle_manual")
    step(made)
    taps_before = len(control.clicks)
    control.holding = True
    show((made, control), "result")
    step(made)
    assert made.progress == 1
    assert len(control.clicks) == taps_before


# ── when the run ends ───────────────────────────────────────────────────────

def test_with_no_target_the_score_is_not_even_read(worker, monkeypatch):
    made, control = worker("lobby")
    monkeypatch.setattr(made._reader, "read",
                        lambda frame: pytest.fail("read the score"))
    assert step(made) is False
    assert len(control.clicks) == 1


@pytest.mark.parametrize("screen", ["lobby", "lobby_live"])
def test_below_the_target_it_queues_again(worker, screen):
    made, control = worker(screen, target=2400)
    assert step(made) is False
    assert len(control.clicks) == 1


def test_at_the_target_it_stops_without_queueing(worker):
    made, control = worker("lobby", target=1958)
    assert step(made) is True
    assert control.clicks == []
    assert "1958" in made._finish_message


def test_closing_time_ends_the_run(worker):
    """Outside PvP hours the drum says "Prac." and is never pressed."""
    made, control = worker("lobby_prac", target=2400)
    assert step(made) is True
    assert control.clicks == []
    assert "Prac." in made._finish_message


def test_reaching_danh_si_ends_the_run(worker):
    """The live lobby with the Celebrity star line in place of its score."""
    frame = load("lobby_live").copy()
    celebrity = load("lobby_celebrity")
    (x1, y1), (x2, y2) = geometry.DUEL_SCORE_BOX
    frame[y1:y2, x1:x2] = 0
    (x1, y1), (x2, y2) = geometry.DUEL_STARS_BOX
    frame[y1:y2, x1:x2] = celebrity[y1:y2, x1:x2]
    made, control = worker(frame, target=2700)
    assert step(made) is True
    assert control.clicks == []
    assert "Danh sĩ" in made._finish_message


def test_a_lobby_that_will_not_read_stops_the_run(worker):
    """Better to stop than to queue past a target the task cannot see."""
    frame = load("lobby").copy()
    (x1, y1), (x2, y2) = geometry.DUEL_SCORE_BOX
    frame[y1:y2, x1:x2] = 0
    made, control = worker(frame, target=3000)
    results = [step(made) for _ in range(duel.UNREADABLE_LOBBY_LIMIT)]
    assert results[-1] is True and not any(results[:-1])
    assert control.clicks == []
    assert "Không đọc được" in made._finish_message


def test_one_unreadable_glance_is_forgiven(worker):
    """A popup fading over the lobby costs a pass, not the run."""
    blank = load("lobby").copy()
    (x1, y1), (x2, y2) = geometry.DUEL_SCORE_BOX
    blank[y1:y2, x1:x2] = 0
    made, control = worker(blank, target=2400)
    for _ in range(duel.UNREADABLE_LOBBY_LIMIT - 1):
        assert step(made) is False
    show((made, control), "lobby")
    assert step(made) is False
    assert len(control.clicks) == 1
    assert made._unreadable_lobbies == 0


def test_a_negative_target_is_refused():
    with pytest.raises(ValueError):
        DuelWorker(hwnd=1, target=-1, control=control_showing(load("lobby")),
                   reader=object())
