"""Answering a co-op Wanted Quest invite.

Another player's invite opens a modal that swallows every click underneath it.
That stalls *any* automation, not just Realm Raid, which is why the reply is an
app-wide setting and why this lives in its own module rather than inside one
worker.

The dialog is always answered — leaving it up is the stall — so the only choice
is which button.

Detection requires **both** buttons, stacked and aligned. Matching a lone green
tick would fire on any other confirmation dialog in the game; the pair only
occurs here. The two are matched in colour: the green tick and the red cross are
near-identical once greyscaled.
"""
from __future__ import annotations

import logging
from typing import Optional

import geometry
from geometry import Geometry, Point
from paths import template

logger = logging.getLogger(__name__)

TPL_ACCEPT = template("RealmRaid", "wantedAccept.png")
TPL_REFUSE = template("RealmRaid", "wantedRefuse.png")

# Measured separation on real frames was 1.00 on the dialog against 0.58
# anywhere else, so 0.75 has room either way.
ACCURACY = 0.75


def find_reply(control, layout: Geometry, accept: bool) -> Optional[Point]:
    """Where to click to answer an invite, or ``None`` when there is no invite.

    ``control`` is a GameControl with a frame already captured for this pass, so
    this costs no extra screen grab.
    """
    tick = control.find(TPL_ACCEPT, threshold=ACCURACY, gray=False, delay=0)
    if tick is None:
        return None
    cross = control.find(TPL_REFUSE, threshold=ACCURACY, gray=False, delay=0)
    if cross is None:
        return None

    if abs(cross[0] - tick[0]) > geometry.WANTED_ALIGN_TOLERANCE:
        logger.debug("Invite buttons not aligned: %s vs %s", tick, cross)
        return None

    expected_gap = layout.point((0, geometry.WANTED_BUTTON_GAP))[1]
    if abs((cross[1] - tick[1]) - expected_gap) > geometry.WANTED_GAP_TOLERANCE:
        logger.debug(
            "Invite button gap %d, expected ~%d", cross[1] - tick[1], expected_gap
        )
        return None

    return tick if accept else cross
