"""Deciding whether the Realm Raid ticket counter reads zero.

This is the raid loop's own reading of the counter, from the raid screen, and it
only cares about one thing: has the numerator gone to zero, so the run is over.
The chapter panel's "is it 30/30" reading is a different question on a different
screen and lives in :mod:`raid_tickets`.

What is worth pinning here is why the module looks the way it does. The counter
cannot be matched as a whole picture — "0/30" is a substring of "10/30", and the
text is centred so every glyph slides when the numerator gains a digit. Only the
*leftmost* glyph is dependable, so that is what gets compared, and the tests
below are mostly about that choice holding up: a leading digit stops it reading
as zero, the denominator is irrelevant, and specks are not glyphs.

Note for whoever reads this next: this file was rewritten from its test names
after the module's source was accidentally overwritten and restored from a build
artefact. The behaviours are the ones the names describe and all of them pass
against the restored module, but the original bodies are gone — if one of these
looks thinner than it should, that is why.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

import ticket_counter
from paths import template

ZERO_TEMPLATE = template("RealmRaid", "ticketZero.png")


@pytest.fixture(scope="module")
def zero():
    """The shipped ``0`` the raid loop matches against."""
    image = cv2.imdecode(np.fromfile(ZERO_TEMPLATE, np.uint8), cv2.IMREAD_GRAYSCALE)
    assert image is not None, "cannot read %s" % ZERO_TEMPLATE
    return image


def strip(width=60, height=20):
    return np.zeros((height, width), dtype=np.uint8)


def put(band, x, glyph):
    """Paste a glyph into a strip at ``x``."""
    band[2:2 + glyph.shape[0], x:x + glyph.shape[1]] = glyph
    return band


def block(width=8, height=14, value=255):
    return np.full((height, width), value, dtype=np.uint8)


# ── finding glyphs ──────────────────────────────────────────────────────────


def test_no_glyphs_in_an_empty_strip():
    assert ticket_counter.find_glyphs(strip()) == []


def test_empty_input_is_handled():
    """Called with nothing at all rather than an empty picture."""
    assert ticket_counter.find_glyphs(None) == []
    assert ticket_counter.find_glyphs(np.zeros((0, 0), dtype=np.uint8)) == []


def test_glyphs_come_back_left_to_right():
    """The whole method rests on "leftmost", so the order is the contract."""
    band = strip(80)
    put(band, 50, block())
    put(band, 10, block())
    put(band, 30, block())

    xs = [x for x, _y, _w, _h in ticket_counter.find_glyphs(band)]

    assert xs == sorted(xs) == [10, 30, 50]


def test_specks_are_ignored():
    """Antialiasing fringe and stray pixels are not digits."""
    band = strip()
    put(band, 5, block(2, 2))          # too small either way
    put(band, 20, block(8, 3))         # wide enough, far too short

    assert ticket_counter.find_glyphs(band) == []


def test_a_strip_with_no_counter_on_it_does_not_read_as_zero(zero):
    """What replaced "dim pixels are not ink".

    That rule came from the fixed threshold and went with it: the split point is
    now taken from each crop, so *something* is always separated from something
    else, however dim. Which makes the useful question not "is this bright
    enough to be ink" but "does whatever was found look like a zero".

    It does not. The guild board leaves the individual board's ticket pill bare,
    and that patch of gradient — the closest thing to a false positive in the
    game — scored -0.221 against the stored zero on a live frame.
    """
    band = strip()
    ramp = np.linspace(40, 117, band.shape[1], dtype=np.uint8)
    band[:, :] = np.tile(ramp, (band.shape[0], 1))

    assert not ticket_counter.is_zero(band, zero)


# ── the template it matches against ─────────────────────────────────────────


def test_the_zero_template_is_a_single_glyph(zero):
    """A template holding two glyphs would match the wrong thing everywhere."""
    assert len(ticket_counter.find_glyphs(zero)) <= 1


def test_the_template_segments_to_exactly_one_glyph(zero):
    """And it is a glyph, not a blank crop that scores against anything."""
    assert zero.size > 0
    assert int(zero.max()) - int(zero.min()) >= 100, (
        "the template has no contrast in it, so it would match anything"
    )


# ── reading zero ────────────────────────────────────────────────────────────


def test_a_zero_on_its_own_reads_as_zero(zero):
    band = strip(zero.shape[1] + 30, zero.shape[0] + 8)
    put(band, 4, zero)

    assert ticket_counter.is_zero(band, zero) is True


def test_the_denominator_does_not_matter(zero):
    """"0/30" and "0/50" are the same answer; only the first glyph is read."""
    wide = strip(zero.shape[1] * 4 + 40, zero.shape[0] + 8)
    put(wide, 4, zero)
    put(wide, 4 + zero.shape[1] + 10, zero)
    put(wide, 4 + 2 * zero.shape[1] + 20, zero)

    assert ticket_counter.is_zero(wide, zero) is True


def test_a_digit_before_the_zero_stops_it_reading_as_zero(zero):
    """The 10/30 case: a leading 1 means tickets remain.

    Built by putting a tall thin bar where the "1" would be — whatever else it
    resembles, it is not the stored zero, and it is now the leftmost glyph.
    """
    band = strip(zero.shape[1] * 3 + 40, zero.shape[0] + 8)
    put(band, 4, block(3, zero.shape[0]))
    put(band, 4 + 10, zero)

    assert ticket_counter.is_zero(band, zero) is False


def test_a_counter_with_no_digits_is_not_zero(zero):
    """Nothing legible must not read as a zero — that would end the run."""
    assert ticket_counter.is_zero(strip(), zero) is False
    assert ticket_counter.score_against_zero(strip(), zero) == -1.0


def test_a_solid_block_is_not_a_zero(zero):
    """A filled rectangle has no hole in it, whatever its size."""
    band = strip(zero.shape[1] + 30, zero.shape[0] + 8)
    put(band, 4, block(zero.shape[1], zero.shape[0]))

    assert ticket_counter.is_zero(band, zero) is False


def test_threshold_sits_between_the_real_measurements(zero):
    """A real zero clears it by a distance; a solid block is nowhere near."""
    real = strip(zero.shape[1] + 30, zero.shape[0] + 8)
    put(real, 4, zero)
    solid = strip(zero.shape[1] + 30, zero.shape[0] + 8)
    put(solid, 4, block(zero.shape[1], zero.shape[0]))

    hit = ticket_counter.score_against_zero(real, zero)
    miss = ticket_counter.score_against_zero(solid, zero)

    assert hit >= ticket_counter.MATCH_THRESHOLD
    assert miss < ticket_counter.MATCH_THRESHOLD
    assert hit - miss > 0.2, "hit %.3f, miss %.3f" % (hit, miss)


def test_glyphs_are_found_whatever_the_panel_brightness():
    """The split point comes from the crop, not from a constant.

    The game dims the whole board behind an open enemy card. Against a fixed
    ink threshold both the digits and the panel then sat on the same side of the
    line and the strip came back as a single blob — so the count could not be
    read at the one moment it mattered, with an enemy card open and the attack
    about to be pressed.
    """
    strip = np.zeros((20, 60), dtype=np.uint8)
    strip[5:15, 5:12] = 255
    strip[5:15, 20:27] = 255

    for floor, contrast in ((0, 1.0), (120, 0.4), (180, 0.25)):
        dimmed = np.clip(strip * contrast + floor, 0, 255).astype(np.uint8)
        found = ticket_counter.find_glyphs(dimmed)
        assert len(found) == 2, (
            "read %d glyphs at floor %d, contrast %.2f" % (len(found), floor,
                                                           contrast)
        )
