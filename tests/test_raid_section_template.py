"""The opponent-card template against real pixels, not a stubbed match.

``section.png`` is the top-right corner of an unbroken card. It used to reach
far enough down to take in the end of the player's name on the card it was cut
from — a short one. A long name runs on into that corner, and on a live guild
board the two cards whose owners had long names scored 0.815 and 0.883 against
the 0.9 the loop needs. The loop broke the six other realms, then sat in front
of those two for an hour logging "Nothing recognised".

Every other test of the raid loop stubs ``find_all``, which is how a template
that misses real cards got through. These read the frame.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("win32con")

from conftest import bare_control  # noqa: E402
import game_control  # noqa: E402
import realm_raid  # noqa: E402

BOARD = Path(__file__).parent / "fixtures" / "raid_board"


def cards_in(fixture: str):
    """Where the raid loop would see opponent cards in this piece of board."""
    image = game_control.read_image(str(BOARD / fixture), game_control.cv2.IMREAD_GRAYSCALE)
    control = bare_control(client=(1122, 633))
    control.full_shot = lambda gray=True: image
    return control.find_all(realm_raid.TPL_SECTION,
                            threshold=realm_raid.DEFAULT_ACCURACY, delay=0)


@pytest.mark.parametrize("fixture", ["long_name_left.png", "long_name_right.png"])
def test_a_card_whose_name_runs_into_the_corner_is_still_found(fixture):
    assert len(cards_in(fixture)) == 1


def test_a_broken_card_is_not_taken_for_an_open_one():
    """The KO stamp sits on the very corner the template looks at."""
    assert cards_in("ko_corner.png") == []
