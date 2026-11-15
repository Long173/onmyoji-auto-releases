"""Following the picked boss through the Demon Parade, so beans go at it alone.

Hitting the boss picked before the round pays triple shards, and the boss is
the whole point of the pick: the pick chooses the biggest silhouette, which is
the SSR/SP when one is offered. Spraying beans at the parade spends them on
whoever walks by.

The game marks the boss itself. The word "Picked" orbits the chosen shikigami
for as long as it is on screen, and nothing else wears it. Matched on the frame
in greyscale over 3402 frames of five filmed rounds, it found the badge in as
many frames as matching in colour did (154 against 149 at 0.6) at a quarter of
the cost, about 9 ms a frame, and never scored above 0.55 where there was no
badge — on the pick screen, the result scroll, or a parade without the boss.

The badge is not where to throw, though:

* it orbits, so half the time it is edge-on and unreadable, and where it is
  read it may be beside the figure rather than on it;
* beans are in the air for a moment and the figure keeps walking left, so a
  bean aimed at the figure lands behind it.

So the badge only says *which* figure. The figure's own body — found the same
way the loop finds every figure, as what differs from the empty stage — is
followed from frame to frame, its speed is measured from its own track, and
each bean is aimed where it will be a moment from now. Through the moments the
badge cannot be read, the body is followed on its own. Measured live on 16
rounds, this hit the boss in 8, against 7 in 20 for beans paced across the
whole parade.

Two rules keep the follow from wandering onto someone else:

* a body counts only if it is near where the boss is, or should be by now;
* every figure walks left, so a body further right than the boss was is the
  next figure in line coming up behind it, not the boss.

Everything here works at the reference client size, 1122x633.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import cv2
import numpy as np

import parade_pick
from game_control import read_image
from paths import template

Point = Tuple[float, float]

TPL_BADGE = template("DemonParade", "pickedBadge.png")
BADGE_ACCURACY = 0.6
# The stage the parade walks on; the counter and the bean slider are outside.
BADGE_ROWS = (100, 540)
BODY_ROWS = (110, 530)

# A body is what differs from the empty stage by more than this, in one blob
# at least this big — beans in flight and sparkles are smaller.
BODY_DIFFERENCE = 40
BODY_MIN_AREA = 1500
BODY_MIN_HEIGHT = 70

# Figures walk at about 150 px/s at the reference size, slower under Slow. A
# measured speed outside this range is the follow having slipped, not the
# figure. The ceiling was 300 once: the body blob merged with the figure
# walking ahead, the speed hit it, and every bean landed on that figure.
DEFAULT_VELOCITY = -150.0
VELOCITY_RANGE = (-200.0, -40.0)
VELOCITY_WINDOW_SECONDS = 2.0
VELOCITY_MIN_SPAN_SECONDS = 0.4

# How far from the badge (or the prediction) a body may be and still be the
# boss, and how far right of its last place it may step — jitter in the blob,
# never actual walking.
MATCH_RADIUS = 120
MAX_STEP_BACK = 40
# How long the boss is followed on prediction alone before it counts as lost.
CHASE_SECONDS = 1.5
# How far ahead of the figure the bean is aimed. 0.4, 0.8 and 1.2 s were tried
# on the emulator and none was clearly better. On the Steam client 0.8 put the
# aim on the figure in front of the boss whenever the speed read high; 0.4 at
# the usual speed is 60 px, well inside the boss's own width either way.
LEAD_SECONDS = 0.4
# Within the client, with a little room for the frame's edge.
AIM_X_RANGE = (10, 1110)


def badge_at(frame: np.ndarray) -> Optional[Point]:
    """Where the "Picked" badge is, in reference units — or None."""
    small = parade_pick.at_reference(frame)
    badge = cv2.cvtColor(read_image(TPL_BADGE), cv2.COLOR_BGR2GRAY)
    top, bottom = BADGE_ROWS
    stage = cv2.cvtColor(small[top:bottom], cv2.COLOR_BGR2GRAY)
    result = cv2.matchTemplate(stage, badge, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(result)
    if score < BADGE_ACCURACY:
        return None
    return (x + badge.shape[1] / 2.0, y + top + badge.shape[0] / 2.0)


# Fliers that carry a label below them — "Assist Up" and "Got Beans" — are worth
# one bean each before the boss comes: the owner's rule. Cut from the Steam
# client and matched in colour over 557 parade frames: the labels scored 0.9 and
# up, the rest of the stage at most 0.6 for Assist Up and 0.8 for Got Beans.
HELPER_LABELS = (
    ("assist", template("DemonParade", "assistUp.png"), 0.8),
    ("beans", template("DemonParade", "gotBeans.png"), 0.88),
    ("chance", template("DemonParade", "chanceUp.png"), 0.8),
)
HELPER_ROWS = (100, 420)
# The flier's body hangs about 90 px above its label; a little to the left of
# it, because fliers drift left too.
HELPER_ABOVE_LABEL = 90
HELPER_LEAD_X = 30


# Found at half size first — a quarter of the work, about 15 ms for both labels
# where full size took 80, too slow beside a 0.3 s throw — and then confirmed at
# full size around the spot, since half size alone puts Got Beans' label and the
# stage within 0.05 of each other.
HELPER_SCOUT_SCALE = 0.5
HELPER_SCOUT_ACCURACY = 0.75
HELPER_CONFIRM_SLACK = 6


def _scaled(image: np.ndarray) -> np.ndarray:
    return cv2.resize(image, None, fx=HELPER_SCOUT_SCALE, fy=HELPER_SCOUT_SCALE,
                      interpolation=cv2.INTER_AREA)


def helpers(frame: np.ndarray) -> List[Tuple[str, Tuple[int, int]]]:
    """(kind, where to throw) for each labelled flier in sight, reference units."""
    small = parade_pick.at_reference(frame)
    top, bottom = HELPER_ROWS
    stage = small[top:bottom]
    scout = _scaled(stage)
    found = []
    for kind, path, accuracy in HELPER_LABELS:
        label = read_image(path)
        mini = _scaled(label)
        if mini.shape[0] > scout.shape[0] or mini.shape[1] > scout.shape[1]:
            continue
        _, rough, _, (sx, sy) = cv2.minMaxLoc(
            cv2.matchTemplate(scout, mini, cv2.TM_CCOEFF_NORMED))
        if rough < HELPER_SCOUT_ACCURACY:
            continue
        x0 = max(0, int(sx / HELPER_SCOUT_SCALE) - HELPER_CONFIRM_SLACK)
        y0 = max(0, int(sy / HELPER_SCOUT_SCALE) - HELPER_CONFIRM_SLACK)
        window = stage[y0:y0 + label.shape[0] + 2 * HELPER_CONFIRM_SLACK,
                       x0:x0 + label.shape[1] + 2 * HELPER_CONFIRM_SLACK]
        if window.shape[0] < label.shape[0] or window.shape[1] < label.shape[1]:
            continue
        _, score, _, (x, y) = cv2.minMaxLoc(
            cv2.matchTemplate(window, label, cv2.TM_CCOEFF_NORMED))
        if score < accuracy:
            continue
        cx = x0 + x + label.shape[1] // 2 - HELPER_LEAD_X
        cy = y0 + y + top + label.shape[0] // 2 - HELPER_ABOVE_LABEL
        found.append((kind, (int(max(cx, AIM_X_RANGE[0] + 1)), int(max(cy, 0)))))
    return found


def bodies(frame: np.ndarray, background: np.ndarray) -> List[Point]:
    """The centres of the figures on the stage. Both frames at reference size."""
    if frame is None or background is None or frame.shape != background.shape:
        return []
    moved = (cv2.absdiff(frame, background).max(axis=2) > BODY_DIFFERENCE).astype(np.uint8)
    top, bottom = BODY_ROWS
    moved[:top] = 0
    moved[bottom:] = 0
    moved = cv2.morphologyEx(moved, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    moved = cv2.morphologyEx(moved, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    total, _, stats, centres = cv2.connectedComponentsWithStats(moved, 8)
    return [
        (float(centres[i][0]), float(centres[i][1]))
        for i in range(1, total)
        if stats[i][cv2.CC_STAT_AREA] > BODY_MIN_AREA
        and stats[i][cv2.CC_STAT_HEIGHT] > BODY_MIN_HEIGHT
    ]


class BossChase:
    """The boss's track through one round: where it was, and when."""

    def __init__(self, lead_seconds: float = LEAD_SECONDS) -> None:
        self._lead = lead_seconds
        self._track: List[Tuple[float, float, float]] = []   # (t, x, y)

    def is_following(self, now: float) -> bool:
        """Whether the boss was seen recently enough to still be followed."""
        return bool(self._track) and now - self._track[-1][0] <= CHASE_SECONDS

    def velocity(self) -> float:
        """Pixels a second along x, from the last couple of seconds of track."""
        if not self._track:
            return DEFAULT_VELOCITY
        latest = self._track[-1][0]
        recent = [p for p in self._track if latest - p[0] <= VELOCITY_WINDOW_SECONDS]
        span = recent[-1][0] - recent[0][0]
        if len(recent) < 2 or span < VELOCITY_MIN_SPAN_SECONDS:
            return DEFAULT_VELOCITY
        # A straight line through every recent point, not the first and last
        # alone: one point taken off a neighbour then moves the line a little
        # instead of deciding it.
        times = np.array([p[0] for p in recent])
        xs = np.array([p[1] for p in recent])
        slope = float(np.polyfit(times - times[0], xs, 1)[0])
        low, high = VELOCITY_RANGE
        return max(low, min(high, slope))

    def _expected(self, now: float) -> Point:
        t, x, y = self._track[-1]
        return (x + self.velocity() * (now - t), y)

    def see(self, now: float, badge: Optional[Point], seen: List[Point]) -> bool:
        """Take in one frame. True when this frame (re)found a lost boss."""
        following = self.is_following(now)
        if badge is not None:
            anchor = badge
        elif following:
            anchor = self._expected(now)
        else:
            return False
        last_x = self._track[-1][1] if following else None
        near = [
            b for b in seen
            if abs(b[0] - anchor[0]) < MATCH_RADIUS
            and (last_x is None or b[0] <= last_x + MAX_STEP_BACK)
        ]
        if not near:
            return False
        body = min(near, key=lambda b: abs(b[0] - anchor[0]) + 0.5 * abs(b[1] - anchor[1]))
        if not following:
            # A boss found again is a new pass — it can walk by twice, and a
            # speed measured across both passes would point the wrong way.
            self._track = []
        self._track.append((now, body[0], body[1]))
        return not following

    def aim(self, now: float) -> Optional[Tuple[int, int]]:
        """Where a bean thrown now should go, in reference units — or None."""
        if not self.is_following(now):
            return None
        x, y = self._expected(now + self._lead)
        low, high = AIM_X_RANGE
        if not low < x < high:
            return None
        return (int(round(x)), int(round(y)))
