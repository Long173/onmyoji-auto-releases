"""Reading the Realm Raid ticket counter on the chapter panel.

The whole feature turns on one question — does the counter say 30/30 — and the
cost of getting it wrong is lopsided: a missed 30/30 wastes a lap, a false 30/30
walks off the map to raid with no tickets. So the values that could be mistaken
for 30/30 are enumerated here rather than sampled.

Everything is built from **real glyphs**, harvested out of one live capture of
the top bar (`recordings/ticket/topbar.png` — the gold counter, the sushi
counter and the ticket counter, same font, same size, 8 KB). Counters other than
the one that was photographed are composed from those glyphs: that exercises the
reading, and it is not a photograph of the game rendering them. The one reading
that has never been photographed is 30/30 itself, which is stated in the module
under test and is the reason these tests lean on the impostors instead.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

import geometry
import raid_tickets
from raid_tickets import TicketReader, runs_of_lit_columns

TOPBAR = Path(__file__).resolve().parents[1] / "recordings" / "ticket" / "topbar.png"
# The strip was cut from the full frame at this offset, so a coordinate measured
# on the frame maps into it by subtracting these.
STRIP_ORIGIN = (480, 16)

pytestmark = pytest.mark.skipif(
    not TOPBAR.is_file(), reason="the top-bar capture is not present"
)


@pytest.fixture(scope="module")
def strip():
    image = cv2.imdecode(np.fromfile(str(TOPBAR), np.uint8), cv2.IMREAD_GRAYSCALE)
    assert image is not None
    return image


@pytest.fixture(scope="module")
def live_band(strip):
    """The ticket counter exactly as it was captured, reading 0/30."""
    (x1, _y1), (x2, _y2) = geometry.RAID_TICKET_BOX
    return strip[:, x1 - STRIP_ORIGIN[0]:x2 - STRIP_ORIGIN[0]]


@pytest.fixture(scope="module")
def glyphs(strip, live_band):
    """One real example of every digit that can appear in this counter.

    Harvested from the other numbers in the same bar. Only 0, 1, 2, 3 and 6 are
    needed: the counter tops out at 30, so a two-digit numerator is 10-29 or 30
    and its first glyph can only be 1, 2 or 3.
    """
    def runs(x1, x2):
        band = strip[:, x1 - STRIP_ORIGIN[0]:x2 - STRIP_ORIGIN[0]]
        return [band[:, a:b] for a, b in runs_of_lit_columns(band)]

    found = {
        "1": runs(683, 693)[0],      # from the sushi count, 61.1K
        "2": runs(528, 541)[0],      # from the gold count, 3,882
        "6": runs(670, 684)[0],      # from the sushi count
    }
    parts = runs_of_lit_columns(live_band)
    found["0"] = live_band[:, parts[-1][0]:parts[-1][1]]
    found["3"] = live_band[:, parts[-2][0]:parts[-2][1]]
    found["/"] = live_band[:, parts[-3][0]:parts[-3][1]]
    return found


@pytest.fixture(scope="module")
def reader(strip):
    class Frame:
        def reference_shot(self, gray=True):
            raise AssertionError("these tests read a band directly")

    return TicketReader(Frame())


def compose(glyphs, text, live_band, gap=2):
    """A counter reading ``text``, laid out from real glyphs on the real plaque."""
    blank = np.tile(live_band[:, 0:40], (1, 3))[:, :live_band.shape[1]].copy()
    picked = [glyphs[ch] for ch in text]
    width = sum(g.shape[1] for g in picked) + gap * (len(picked) - 1)
    x = (blank.shape[1] - width) // 2
    for glyph in picked:
        blank[:, x:x + glyph.shape[1]] = np.maximum(
            blank[:, x:x + glyph.shape[1]], glyph
        )
        x += glyph.shape[1] + gap
    return blank


# ── the capture itself ──────────────────────────────────────────────────────


def test_the_counter_that_was_photographed_reads_as_not_full(reader, live_band):
    """It said 0/30. Everything else here is composed; this one is real."""
    assert reader.read_band(live_band) is False


def test_the_capture_separates_into_the_four_glyphs_of_0_slash_30(live_band):
    """The segmentation the whole reading rests on, on real pixels."""
    widths = [b - a for a, b in runs_of_lit_columns(live_band)]

    assert widths == [8, 5, 8, 8], "0, /, 3, 0 — got %s" % widths


# ── the readings ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", ["30/30"])
def test_a_full_counter_reads_as_full(reader, glyphs, live_band, text):
    assert reader.read_band(compose(glyphs, text, live_band)) is True


@pytest.mark.parametrize("text", [
    "0/30",     # the everyday reading, and the one named as must-not-confuse
    "6/30",     # likewise named
    "3/30",     # a bare 3 — the numerator's digit is right, the count is not
    "10/30",    # two digits, first is a 1
    "20/30",    # two digits, first is a 2 — the closest impostor that can occur
    "13/30",
    "23/30",
    "26/30",
])
def test_every_other_reading_is_not_full(reader, glyphs, live_band, text):
    assert reader.read_band(compose(glyphs, text, live_band)) is False


def test_the_two_readings_the_user_called_out_are_rejected_on_the_glyph_count(
    reader, glyphs, live_band
):
    """0/30 and 6/30 never reach a digit comparison at all.

    Their numerator is one glyph where a full counter's is two, so they are out
    before anything is matched. Worth its own test because it is the barrier
    that does not depend on a threshold.
    """
    for text in ("0/30", "6/30"):
        band = compose(glyphs, text, live_band)
        assert len(runs_of_lit_columns(band)) == 4
    assert len(runs_of_lit_columns(compose(glyphs, "30/30", live_band))) == 5


# ── refusing to answer ──────────────────────────────────────────────────────


def test_an_empty_box_is_unreadable_rather_than_not_full(reader, live_band):
    """The distinction the caller depends on. Blank is not evidence of 0."""
    assert reader.read_band(np.zeros_like(live_band)) is raid_tickets.UNREADABLE


def test_a_counter_that_is_not_out_of_30_is_unreadable(reader, glyphs, live_band):
    """The denominator doubles as an assertion that this is the right box.

    If the bar shifts or another panel is on screen, the read must fail loudly
    rather than answer "not full" forever and quietly never raid.
    """
    assert reader.read_band(compose(glyphs, "3/16", live_band)) is raid_tickets.UNREADABLE


def test_a_band_of_noise_is_unreadable(reader, live_band):
    rng = np.random.default_rng(11)
    noise = rng.integers(0, 255, live_band.shape, dtype=np.uint8)

    assert reader.read_band(noise) is not True, "noise read as a full counter"


# ── the separation the thresholds sit in ────────────────────────────────────


def test_a_three_beats_every_digit_it_could_be_confused_with(reader, glyphs):
    """The measurement the threshold was chosen from, kept as a test.

    A first digit can only be 1, 2 or 3, so those are what matter; 6 is included
    because it is the nearest thing to a "0" and guards the second slot.
    """
    real = raid_tickets.looks_like(glyphs["3"], reader._digit3)
    impostors = {
        name: raid_tickets.looks_like(glyphs[name], reader._digit3)
        for name in ("1", "2", "0", "6")
    }

    assert real > raid_tickets.GLYPH_THRESHOLD
    worst = max(impostors.values())
    assert worst < raid_tickets.GLYPH_THRESHOLD, impostors
    assert real - worst > 0.2, "the gap has closed: real %.3f, %s" % (real, impostors)


def test_a_zero_beats_every_digit_it_could_be_confused_with(reader, glyphs):
    real = raid_tickets.looks_like(glyphs["0"], reader._digit0)
    impostors = {
        name: raid_tickets.looks_like(glyphs[name], reader._digit0)
        for name in ("1", "2", "3", "6")
    }

    assert real > raid_tickets.GLYPH_THRESHOLD
    assert max(impostors.values()) < raid_tickets.GLYPH_THRESHOLD, impostors
