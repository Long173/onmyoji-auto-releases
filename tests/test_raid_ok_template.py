"""The OK-button template against real pixels, not a stubbed match.

``ok.png`` was cut from a plain OK button. The dialog Refresh opens — "Raid log
progress will be reset if you refresh. Continue?" — draws its OK with a diamond
at each end and a rule along the top, and against that button the whole
template scored 0.872, under the 0.9 the loop needs. Usually some frame
squeaked over; once none did, and the loop clicked the board under the dialog
for six minutes. Then Exploration took the window back and pressed the board's
close button — also under the dialog — for three hours.

Cut to the face of the button, it carries what both kinds share and nothing of
what they don't.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("win32con")

from conftest import bare_control  # noqa: E402
import game_control  # noqa: E402
import realm_raid  # noqa: E402

BOARD = Path(__file__).parent / "fixtures" / "raid_board"


def ok_in(fixture: str):
    """Where the raid loop would press OK in this piece of screen."""
    image = game_control.read_image(str(BOARD / fixture), game_control.cv2.IMREAD_GRAYSCALE)
    control = bare_control(client=(1122, 633))
    control.full_shot = lambda gray=True: image
    return control.find(realm_raid.TPL_OK,
                        threshold=realm_raid.DEFAULT_ACCURACY, delay=0)


def test_the_ok_on_the_refresh_confirmation_is_found():
    """Cancel sits on the left half of this crop, OK on the right."""
    found = ok_in("refresh_confirm_buttons.png")
    assert found is not None
    assert found[0] > 200, "matched Cancel, not OK"


def test_a_plain_ok_button_is_still_found():
    assert ok_in("ok_plain.png") is not None
