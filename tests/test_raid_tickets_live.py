"""The ticket counter at a real 30/30, photographed off the chapter panel.

Until 2026-10-06 the reader had only ever seen "0/30": every full counter in
`test_raid_tickets.py` is composed from glyphs. The first real one it met was
never read as full, and the map farm walked past a full ticket stack lap after
lap. The digits were not the problem — "3" scored 0.973 and 0.996, "0" 0.963 and
0.980, "/" 0.933. The box was: it starts at x=805, and the ticket icon to the
left of the text ends at 811, so its last few columns were cut into the band as
a sixth glyph. "30/30" then had three glyphs before the slash, which the reader
rejects as "not this counter at all". At "0/30" the same stray glyph happened to
give the right answer, which is why nothing noticed.

The fixture is the top bar around the counter, cut from that live frame at
(760, 0). Unlike the composed tests' source capture it is committed, so these
run everywhere.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

import geometry
from raid_tickets import TicketReader, runs_of_lit_columns

FIXTURE = Path(__file__).parent / "fixtures" / "ticket" / "full-30-30.png"
ORIGIN = (760, 0)
FRAME_SIZE = (633, 1122)


@pytest.fixture(scope="module")
def topbar() -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(FIXTURE), np.uint8), cv2.IMREAD_GRAYSCALE)
    assert image is not None
    return image


def frame_with(topbar: np.ndarray) -> np.ndarray:
    frame = np.zeros(FRAME_SIZE, np.uint8)
    height, width = topbar.shape
    frame[ORIGIN[1]:ORIGIN[1] + height, ORIGIN[0]:ORIGIN[0] + width] = topbar
    return frame


def band_of(topbar: np.ndarray) -> np.ndarray:
    (x1, y1), (x2, y2) = geometry.RAID_TICKET_BOX
    return topbar[y1 - ORIGIN[1]:y2 - ORIGIN[1], x1 - ORIGIN[0]:x2 - ORIGIN[0]]


class Shot:
    def __init__(self, frame: np.ndarray) -> None:
        self._frame = frame

    def reference_shot(self, gray: bool = True) -> np.ndarray:
        return self._frame


def test_a_real_full_counter_reads_as_full(topbar):
    assert TicketReader(Shot(frame_with(topbar))).is_full() is True


def test_the_icon_cut_by_the_box_edge_is_not_a_glyph(topbar):
    band = band_of(topbar)
    assert runs_of_lit_columns(band)[0][0] == 0, (
        "the fixture no longer shows the icon's edge inside the box — this "
        "test is not testing anything")
    reader = TicketReader(Shot(frame_with(topbar)))
    assert reader.read_band(band) is True


def test_a_counter_with_its_first_digit_blanked_is_not_full(topbar):
    """The stray-glyph fix must not turn "0/30" into "30/30"."""
    blanked = topbar.copy()
    (x1, y1), (_x2, y2) = geometry.RAID_TICKET_BOX
    # The "3" of the numerator sits 17-26 columns into the box.
    blanked[y1:y2, x1 + 16 - ORIGIN[0]:x1 + 27 - ORIGIN[0]] = 7
    assert TicketReader(Shot(frame_with(blanked))).is_full() is False
