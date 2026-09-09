"""Reading the Demon Parade result scroll.

Driven against the real captures the templates were cut from, because the whole
question is whether pixels off a live screen turn into the right names and
numbers. A stub frame would prove nothing here.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

import parade_results

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "demon_parade"

# What is actually on the scroll in `seven-shikigami.png`, read by eye.
SEVEN = {
    "Koi": 3,
    "Blue Imp": 4,
    "Lantern Soul": 4,
    "Nurikabe": 4,
    "Kusa": 3,
    "Hahakigami": 4,
    "Grave Digger": 4,
}


def load(name: str) -> np.ndarray:
    path = FIXTURES / name
    if not path.is_file():
        pytest.skip("missing capture: %s" % path)
    return cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)


@pytest.fixture(autouse=True)
def fresh_libraries():
    parade_results.reload_libraries()
    yield
    parade_results.reload_libraries()


def test_every_shikigami_on_the_scroll_is_named():
    cards = parade_results.read_scroll(load("seven-shikigami.png"))

    assert {name for name, _count in cards} == set(SEVEN)


def test_every_shard_count_is_read_and_right():
    """All seven, once the library holds more than one picture per digit.

    With a single picture each, one card's `3` would not lift off its
    background and read as unknown — correct behaviour, but a line of the tally
    lost. Digits are shaded like the ribbon, so they need variants for the same
    reason names do.
    """
    cards = parade_results.read_scroll(load("seven-shikigami.png"))

    assert dict(cards) == SEVEN


def test_among_the_digits_it_knows_the_right_one_wins():
    """What the floor can and cannot do.

    It cannot promise that a digit missing from the library reads as unknown:
    a plain block scores 0.562 against `2`, while a real `3` on a busy portrait
    can score as low as 0.51. The two ranges overlap, so no floor separates
    them, and a card showing a 5 may well be read as some other digit.

    The remedy is the library, not the threshold — every digit that turns up
    should be added. What *is* guaranteed is this: whenever the right digit is
    available, it wins.
    """
    library = parade_results.counts()
    for label, pictures in library.items():
        for picture in pictures:
            got, _score = parade_results._best_digit(picture)
            assert got == label, "%r read as %r" % (label, got)


def test_the_digits_still_missing_are_worth_knowing_about():
    """Not a failure — a note. 1, 5, 7, 8 and 9 have not turned up yet, and
    until they do a card showing one of them may be read as something else."""
    have = set(parade_results.counts())
    missing = sorted({str(d) for d in range(1, 10)} - have)
    if missing:
        print("chu so chua co mau: %s" % ", ".join(missing))


def test_a_gold_digit_reads_the_same_as_a_white_one():
    """The glyph is white on some cards and gold on others. Matched as a
    picture, a gold 3 came out as a 6; matched as a shape, colour drops out."""
    import cv2
    import numpy as np

    white = parade_results.counts().get("3", [None])[0]
    assert white is not None
    gold = white.copy()
    gold[:, :, 0] = (gold[:, :, 0] * 0.35).astype(np.uint8)   # strip the blue

    assert parade_results.overlap(
        parade_results.glyph(white), parade_results.glyph(gold)
    ) > 0.95


def test_a_scroll_with_no_shards_reads_as_nothing_won():
    """"Pact shards not received yet." — an ordinary outcome after a round that
    hit nothing, and not to be confused with a scroll full of cards."""
    assert parade_results.read_scroll(load("no-shards.png")) == []


def test_the_empty_scroll_is_recognised_outright():
    """Not inferred from finding no cards: the chibi on that screen has enough
    dark pixels in one grid slot to look like an occupied one, and did produce
    a phantom card before this check existed."""
    assert parade_results.says_no_shards(load("no-shards.png"))
    assert not parade_results.says_no_shards(load("seven-shikigami.png"))


def test_screens_that_are_not_the_scroll_yield_nothing_confidently():
    """A misread here would invent shards out of the entry screen."""
    for name in ("entry.png", "pick.png"):
        cards = parade_results.read_scroll(load(name))
        named = [c for c in cards if c[0] is not None]
        assert named == [], "%s produced %r" % (name, named)


def test_an_unknown_name_is_reported_rather_than_guessed():
    """A shikigami with no template must not be filed under the nearest one."""
    frame = load("seven-shikigami.png")
    parade_results.reload_libraries()
    only_koi = {"Koi": parade_results.names()["Koi"]}
    parade_results._names = only_koi

    cards = parade_results.read_scroll(frame)

    assert ("Koi", 3) in cards
    assert sum(1 for name, _c in cards if name is None) == 6


def test_unreadable_cards_are_handed_back_for_labelling():
    frame = load("seven-shikigami.png")
    parade_results.reload_libraries()
    parade_results._names = {}

    crops = parade_results.unknown_crops(frame)

    assert len(crops) >= 7
    assert all(patch.size > 0 for patch in crops.values())


def test_the_library_reads_the_names_it_was_built_from():
    """Contains, not equals: the library is meant to grow. Every real run meets
    shikigami it has never seen, keeps their crops, and they get added."""
    assert set(SEVEN) <= set(parade_results.names())


def test_no_two_different_names_look_alike_enough_to_be_confused():
    """Two names matching above the threshold means one shikigami's shards get
    filed under another's.

    Driven through the real matcher rather than a bare correlation, because
    what protects the tally is the whole rule: crop to the lettering, rule out
    anything of a different pixel width, then compare. Whole-strip matching had
    `Kanko` and `Kappa` at 0.938 against a threshold of 0.95 — twelve
    thousandths. The closest pair now is `Kyonshi Imoto` and `Kyonshi Ototo`,
    which differ by a single letter, at 0.787.
    """
    library = parade_results.names()
    worst, pair = 0.0, None
    for name, pictures in library.items():
        for picture in pictures:
            for other, others in library.items():
                if other == name:
                    continue
                for template in others:
                    cut = parade_results.text_crop(picture)
                    reference = parade_results.text_crop(template)
                    if cut is None or reference is None:
                        continue
                    if abs(reference.shape[1] - cut.shape[1]) > parade_results.TEXT_WIDTH_SLACK:
                        continue
                    if (reference.shape[0] > cut.shape[0]
                            or reference.shape[1] > cut.shape[1]):
                        continue
                    score = float(
                        cv2.matchTemplate(cut, reference, cv2.TM_CCOEFF_NORMED).max()
                    )
                    if score > worst:
                        worst, pair = score, (name, other)

    assert worst < parade_results.NAME_ACCURACY, (
        "%r and %r match at %.3f, at or above the threshold of %.2f"
        % (pair[0], pair[1], worst, parade_results.NAME_ACCURACY)
    )


def test_every_template_still_recognises_itself():
    """The threshold has to leave room underneath as well as above."""
    wrong = []
    for name, pictures in parade_results.names().items():
        for picture in pictures:
            label, score = parade_results._best_name(picture)
            if label != name or score < parade_results.NAME_ACCURACY:
                wrong.append((name, label, round(score, 3)))

    assert not wrong, "templates that do not read as themselves: %s" % wrong[:5]


def test_the_lettering_is_cropped_away_from_the_ribbon():
    """The ribbon is identical on every card. Left in, it is most of what the
    two pictures agree about, and the margin between a right and a wrong answer
    collapses from 0.072 to 0.012."""
    for pictures in parade_results.names().values():
        picture = pictures[0]
        cut = parade_results.text_crop(picture)
        assert cut is not None
        assert cut.shape[1] < picture.shape[1], "nothing was cropped away"
        assert cut.shape[1] > 5, "cropped down to nothing"
        break


def test_several_pictures_can_share_one_name():
    """The ribbon is shaded by rarity, so the same name on an SR card and an R
    card are different pictures. One picture per name left a run reporting
    names that were already in the library as unknown."""
    assert parade_results.label_of("Koi (2).png") == "Koi"
    assert parade_results.label_of("Koi.png") == "Koi"
    assert parade_results.label_of("Ushi no Toki (3).png") == "Ushi no Toki"

    multiples = [n for n, pictures in parade_results.names().items() if len(pictures) > 1]
    assert multiples, "no name has a second picture; variants are not being loaded"


def test_count_templates_are_named_after_the_number_they_show():
    for label in parade_results.counts():
        assert label.isdigit(), "count template %r is not a number" % label


# ── where the library is read from ──────────────────────────────────────────


def test_names_are_read_from_beside_the_exe_as_well_as_the_build(monkeypatch, tmp_path):
    """A user cannot add to the shipped folder and keep it.

    The templates ship inside `_internal/`, and the updater replaces
    `_internal/` wholesale — so a name added there survives exactly until the
    next update. Beside the .exe is where logs, cache and .env already live,
    and the updater leaves all of that alone.
    """
    import paths as paths_module

    extra = tmp_path / "DemonParade" / "names"
    extra.mkdir(parents=True)
    borrowed = parade_results.names()["Koi"][0]
    cv2.imencode(".png", borrowed)[1].tofile(str(extra / "Nguoi Dung Them.png"))
    monkeypatch.setattr(paths_module, "DATA_ROOT", tmp_path)
    parade_results.reload_libraries()

    library = parade_results.names()

    assert "Nguoi Dung Them" in library, "the folder beside the exe was not read"
    assert "Koi" in library, "the shipped names were dropped"


def test_the_shipped_names_are_still_there_without_a_user_folder(monkeypatch, tmp_path):
    import paths as paths_module

    monkeypatch.setattr(paths_module, "DATA_ROOT", tmp_path / "khong-co")
    parade_results.reload_libraries()

    assert len(parade_results.names()) > 50


def test_no_two_digits_look_alike_enough_to_be_confused():
    """The floor has to sit above the confusion between digits, not just above
    the noise. The library does not hold every digit — a card showing a 5 has
    no right answer available, and with the floor underneath the confusion
    ceiling it would be read as whichever wrong digit scored best."""
    library = parade_results.counts()
    worst, pair = 0.0, None
    for label, pictures in library.items():
        for picture in pictures:
            for other, others in library.items():
                if other == label:
                    continue
                for template in others:
                    score = parade_results.overlap(
                        parade_results.glyph(picture), parade_results.glyph(template)
                    )
                    if score > worst:
                        worst, pair = score, (label, other)

    assert worst < parade_results.COUNT_ACCURACY, (
        "digits %r and %r overlap at %.3f, at or above the floor of %.2f"
        % (pair[0], pair[1], worst, parade_results.COUNT_ACCURACY)
    )


def test_every_digit_template_reads_as_itself():
    wrong = []
    for label, pictures in parade_results.counts().items():
        for picture in pictures:
            got, score = parade_results._best_digit(picture)
            if got != label or score < parade_results.COUNT_ACCURACY:
                wrong.append((label, got, round(score, 3)))

    assert not wrong, "digit templates that do not read as themselves: %s" % wrong
