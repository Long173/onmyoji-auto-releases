"""Screen coordinates for the Realm Raid flow, and scaling between client sizes.

All coordinates below were recorded against a client area of
``REFERENCE_CLIENT_SIZE``, which every task resizes the game window to before
looking at it.

They used to be hard-coded integers scattered through the raid loop, so any
other window size silently clicked the wrong pixels. ``Geometry`` scales them
to whatever the window actually reports.

Caveat worth knowing: the template images under ``screenshots/RealmRaid`` are
also captured at the reference size and ``cv2.matchTemplate`` does not scale.
So a non-reference client size still degrades detection — scaling the fixed
coordinates only keeps the blind clicks (Ready button, popup dismiss) aligned.
``Geometry.is_reference_size`` exists so callers can warn about that.
"""
from __future__ import annotations

from typing import Tuple

Point = Tuple[int, int]
Region = Tuple[Point, Point]

# The client area every template was captured against, and what the game window
# is resized to before any task looks at it.
#
# There used to be a TARGET_WINDOW_SIZE of (1138, 672) beside this — the *outer*
# size to ask for. It was measured on one machine, whose window frame eats 16px
# across and 39px down, so 1122x633 of client fell out of it. That frame is not
# a constant: at 125% display scaling it is 21x50, and asking for the same outer
# size left a client of 1117x623 — every template 10px out. `resize_game_window`
# now measures the frame it is actually dealing with and adds it to this.
REFERENCE_CLIENT_SIZE: Point = (1122, 633)

# How far the real client may drift from the reference before it is worth
# warning about. Asking for a 1138px window does not reliably give 1122px of
# client: measured on this machine, GetWindowRect came back 1140 and the client
# 1124, because the game nudges its own window to hold an aspect ratio and
# Windows reports the invisible DWM resize border. Without a tolerance,
# is_reference_size was permanently False and the warning meant nothing.
# Measured cost of that drift: a template cut at 1124 still scored 0.94 at 1136
# (12px out), so a couple of pixels is comfortably inside the noise.
SIZE_TOLERANCE = 6

# There is deliberately no table of deployment slots here, and the reason is
# written down so nobody fills the gap back in. It used to hold five points on
# the screen reading "Tap the shikigami areas to deploy.", offered in the UI as
# "Vị trí target" — the player's own positions, not the enemy's, whatever the
# comment here claimed for years.
#
# Measured against the live game before removing it: a tap there deploys
# nothing, it opens the shikigami picker, which scores at most 0.803 against
# every template in this app and so is a screen the raid loop cannot see. And
# the handler that used it fired on 30 of 11,244 attacks (0.27%), always *after*
# pressing Ready, by which point the tap was too late to place anything. It
# promised something the app could not do. Making it real needs the picker
# recognised and a rule for which shikigami to place.

# "Ready" button, bottom-right. Clicked blind after the tap banner matches.
TAP_READY_BUTTON: Point = (1033, 547)
# Empty top-left area, used to dismiss modal popups such as
# "Cooldown time is not yet up!".
POPUP_DISMISS_POINT: Point = (10, 10)
# The "N/30" ticket counter, top right. This box covers the text only — it
# starts right of the ticket icon, whose white highlight would otherwise be
# picked up as the first glyph.
TICKET_TEXT_REGION: Region = ((1000, 12), (1105, 45))

# A co-op Wanted Quest invite stacks Refuse directly under Accept. Requiring
# that arrangement is what stops a lone green tick elsewhere in the game from
# being mistaken for this dialog.
WANTED_BUTTON_GAP = 90       # Accept centre to Refuse centre, vertically
WANTED_GAP_TOLERANCE = 22
WANTED_ALIGN_TOLERANCE = 16  # how far the two may drift apart horizontally


# ── Souls dungeon (Phụ bản ngự hồn) ─────────────────────────────────────────
# Recorded from a live co-op room at a client area of 1124x633.

# Centre of the "Fight" button, bottom right.
SOULS_FIGHT_BUTTON: Point = (1072, 562)
# A patch inside that button. Its *colour* is what says whether the button is
# live: gold when the room can start, grey when it cannot. Shape alone cannot
# tell — both states share the same lettering, so a greyscale template matches
# either at 0.94, and matching in colour barely separates them (0.04) because
# TM_CCOEFF_NORMED subtracts the mean and cancels a uniform colour shift.
# Measured mean HSV saturation over this patch: 149 lit, 4.5 dead.
SOULS_FIGHT_PATCH: Region = ((1026, 540), (1103, 579))
SOULS_FIGHT_LIT_SATURATION = 80.0   # midway between 4.5 and 149

# Where both result screens are tapped: low and to the right, on bare ground.
#
# There used to be two spots, and the reward screen's was the middle of the
# screen. That is exactly where the game piles the loot and stands the shikigami
# line-up, and players reported runs sticking there — the tap opened a reward
# instead of dismissing the screen.
#
# Picked by measuring rather than by eye. Across the nine result frames in
# recordings/chu-phong, the worst-case standard deviation of a 28x28 patch was
# 56.5 at the old middle spot, 13.7 at the old Victory spot, and 3.8 here: flat
# ground on every one of them, on both screens.
#
# It also sits 50px above the top of the Fight button rather than on it. A tap
# that arrives one pass late — the result screen having just gone — then lands
# on nothing, instead of pressing Fight past the lit-check that exists to stop
# exactly that.
SOULS_RESULT_TAP: Point = (1054, 490)


# ── Demon Parade (Ném đậu) ──────────────────────────────────────────────────
# Measured live at a client of 1122x633.

# Entry screen: one ticket per press, and it commits — press it only when the
# run is actually going to be played out.
PARADE_ENTER: Point = (978, 528)
# Pick screen: a shikigami must be selected or Start does nothing at all.
#
# Not one point but several, tried in turn until the "Pick" banner shows.
# The line-up changes every round and the figures differ wildly in height: a
# single point at (560, 330) worked on a tall one standing on a pot and then,
# next round, landed in empty sky above a short one. Worse than missing —
# clicking empty ground *deselects*, so a fixed point can undo its own work.
# Measured on one line-up: (560, 480) and (560, 500) selected, (560, 440) and
# (555, 460) did not.
PARADE_PICK_POINTS = ((560, 490), (560, 450), (560, 520), (230, 480), (890, 470))
PARADE_START: Point = (1020, 525)
# The result scroll takes a tap anywhere; this corner is never a button.
PARADE_DISMISS: Point = (60, 600)

# Beans-per-throw slider, bottom left while a round is running.
#
# Calibrated by dragging the knob to a series of x positions and reading the
# number off the knob:
#
#     x    200  240  300  360  400  440  480  520
#     val    1    1    3    5    6    7    9   10
#
# So value = (x - 225) / 30, saturating at 1 and 10. Only 5 and 10 are offered
# to the user; the rest of the range is here to explain the two numbers.
PARADE_SLIDER_Y = 578
PARADE_SLIDER_X = {5: 360, 10: 520}
# Where to look along the track for the knob. The knob sits at the right-hand
# end of the gold fill, so the last gold pixel finds it.
PARADE_SLIDER_SCAN = (200, 545)
# Knob is within this many pixels of the target for the setting to count.
PARADE_SLIDER_TOLERANCE = 12

# Where anything in the parade can be, walking or flying. Used to ignore
# movement elsewhere on screen — the timer counting down, the bean counter.
PARADE_FIGURE_BAND = (110, 530)

# Fallback spray, for when nothing can be picked out of the frame. The parade
# walks the bridge along these rows.
PARADE_THROW_ROWS = (400, 445)
PARADE_THROW_X = (180, 1010)       # start, stop
PARADE_THROW_STEP = 95


# ── Event dungeon (Event) ───────────────────────────────────────────────────
# Measured on a live event screen ("Shadowed Sand City") at a client of
# 1122x633, by reading the brightness profile of the bottom-right corner: the
# start button is a parchment diamond centred at (1029, 548) with a
# half-diagonal of 53 px.
#
# The word printed across it is *not* part of the button's identity. It reads
# "Challenge" on this event and "Fight" on others, so nothing here matches the
# lettering — the loop clicks the point and never looks.
#
# The same point also lands on the Ready button of the deploy board, the Fight
# drum that confirms it, and the "Tap to continue" of all three reward screens.
# Verified on a live run: eleven complete runs in 150 seconds off this one
# coordinate. The game keeps its "next" button in this corner throughout, which
# is what makes a single point workable at all.
#
# This point is also the safest place on the screen to keep clicking, which is
# not a coincidence and is worth stating. Out of tickets, the game answers a
# press with a shop panel selling more, priced in jade. On the frame captured
# of that panel it spans x 170-930: a click here falls outside it and reads as
# a tap that closes it, where a point chosen nearer the middle would land on a
# purchase button. Anyone moving this point should stay out of that band.
EVENT_CLICK_POINT: Point = (1030, 549)

# Where the out-of-tickets shop panel sits, from a capture of it: two panels
# side by side with "buy" buttons priced in jade. The picker warns when the
# chosen point falls inside this box, because a point in here spends money the
# first time a run is attempted with an empty ticket count.
#
# Measured on one event only — treat it as "known to be dangerous here", not as
# the full extent of what a stray click can reach.
EVENT_SHOP_PANEL: Region = ((170, 120), (930, 600))

# --- Exploration (Tham hiem chuong) ------------------------------------------------
# Where to click on the world map to open a chapter. The default is the row of
# the chapter recorded being farmed, Chapter 28, in the list down the right of
# the world map. It is a *setting* rather than a template per chapter because
# the list scrolls: whatever the user picks is where it clicks, so a different
# chapter needs no new artwork.
EXPLORATION_CHAPTER_POINT: Point = (990, 417)

# The two ends of a horizontal sweep across the exploration map, and the patch
# of it that is compared before and after to tell whether the view moved.
#
# Horizontal only, and that is measured rather than assumed: phase correlation
# over all 77 recorded frames gave dy about 0 on every consecutive pair, with dx
# between 40 and 184 px whenever the map was being dragged and about 0.5 px when
# it was not. So "dragged and the picture did not move" is a reliable edge
# signal, and there is no vertical axis to sweep.
#
# The compared patch deliberately excludes the top and bottom strips, which
# carry fixed UI — the sushi cost, the Auto Rotation pill, the back arrow. Left
# in, that furniture is identical between the two captures and drags the
# correlation towards "nothing moved" even when the map did.
EXPLORATION_DRAG_LEFT: Point = (300, 300)
EXPLORATION_DRAG_RIGHT: Point = (850, 300)
EXPLORATION_MAP_AREA: Region = ((60, 100), (1060, 470))

# Where to tap to close the "Claim Reward" scroll that a reward node opens.
# Outside the panel, which is the whole point: tapping the panel itself — even
# its decorative title — leaves it open, and tapping here closes it. Measured
# live, both ways round.
#
# Chosen to miss everything else on the screen as well: it is left of centre and
# below the panel, clear of the Auto Rotation pill and the Settings owl along the
# bottom, the Lineup/Shikigami/Auto row beside them, and the back arrow up in the
# corner. It can land on the map underneath, which at worst starts a battle the
# loop was going to start anyway.
EXPLORATION_CLAIM_DISMISS_POINT: Point = (300, 500)

# The Realm Raid ticket counter in the top bar of the chapter panel, reading
# "N/30". Bounds cover the inside of its plaque and nothing else: the ticket
# icon sits to the left of 805 and the plaque's notched right edge past 900, and
# either one would be segmented as a glyph.
#
# Measured on a live capture at reference size: inside this box the counter
# "0/30" separates into four runs of lit columns 8, 5, 8 and 8 px wide — the
# digits, then the slash. That segmentation is what :mod:`ticket_counter` reads.
RAID_TICKET_BOX: Region = ((805, 16), (900, 36))

# Getting from the chapter panel to the Realm Raid board and back, for the map
# farm's detour when tickets are full. All three measured live, and none of them
# is the one that looks obvious:
#
# * the chapter panel leaves by the arrow in the top-left corner;
# * the Realm Raid board is entered from the world map's bottom strip, not from
#   the town screen — the strip reads Evo Material / Soul / Realm Raid / Totem…;
# * the board does **not** leave by that same top-left arrow. Pressing it there
#   does nothing at all. The way out is the red X on its right-hand edge.
#
# The back arrow is only ever pressed while the chapter panel is confirmed on
# screen. One press further back is the town screen, where the same coordinate
# is the player's portrait and opens Settings over everything — which is exactly
# what happened while these were being measured.
EXPLORATION_BACK_ARROW: Point = (45, 32)
# ── Guild raid ──────────────────────────────────────────────────────────────
# The two raid boards count different things, in different places, in opposite
# colours. Individual counts tickets — "0/30", light on dark, top right. Guild
# counts attempts left — "4/6", dark on light, in the left panel. Reading the
# individual spot on a guild board reads bare background, which is why stopping
# on an empty account never fired there.

# Matching patches inside the two tabs on the right rail. The brighter of the
# pair is the board that is open — a comparison, not a threshold, and that
# distinction is the whole point.
#
# An absolute cut-off was tried first and failed in use: an open enemy card dims
# the board behind it, and the lit Guild tab fell from 143.7 to 59.1, under any
# line drawn for the undimmed screen. The dimming hits both tabs alike, so their
# order survives it. Measured: 143.7/82.8 undimmed and 59.1/34.1 dimmed on the
# guild board, 79.4/136.3 on the individual one.
#
# Saturation is no use here (164.7 against 147.6) and neither is a template of
# the tab (1.000 against 0.773): same shape, same word, lit differently.
GUILD_TAB_PATCH: Region = ((1046, 363), (1111, 372))
INDIVIDUAL_TAB_PATCH: Region = ((1046, 255), (1111, 264))

# The "N/6" of "Win(s): N/6", bounded clear of both neighbours: the glyphs of
# "n(s):" end at x=208 and the warning icon starts at x=293, with the digits
# themselves at 246 and 264.
GUILD_ATTEMPTS_REGION: Region = ((232, 492), (288, 522))

# Cancel on "Sure you want to leave the battle?". Confirm sits at (652, 376) and
# is deliberately *not* recorded: pressing it throws the fight away along with
# the ticket that paid for it, so nothing in this app should be able to reach it.
RAID_LEAVE_CANCEL: Point = (470, 376)

# There is deliberately no raid back-arrow coordinate. One was added so the raid
# loop could leave a screen it did not recognise, and withdrawn the next day: a
# raid battle matches no template at all, so "unrecognised" is the ordinary state
# during every fight, and the press landed mid-battle on "Sure you want to leave
# the battle?". A loop that cannot read the screen has no business navigating it.
# Where a card's Attack button sits relative to the card itself.
#
# The popup opens over its own card rather than in a fixed place, so this is
# constant and it is what says which card a button belongs to. Measured live on
# the guild board, all at reference size:
#
#     card (633, 133) -> button (579, 333)
#     card (929, 134) -> button (875, 333)
#     card (633, 252) -> button (579, 452) and (580, 454)
#
# Every sample gave (-54, +199) to within 3px.
#
# Worth having because ``match`` answers with one global best over the whole
# screen: without this the raid pressed whichever popup happened to be open and
# then blamed the card it had merely been looking at, so the barrier that was
# really refusing was never skipped. See realm_raid._card_owning.
ATTACK_BUTTON_OFFSET: Point = (-54, 199)

# How far a button may sit from where the opened card puts it before it is
# taken to belong to a different card. Columns are 296px apart and rows 119px,
# so this separates neighbours with room to spare while absorbing the few px
# the popup animation leaves behind.
ATTACK_BUTTON_TOLERANCE: int = 60

RAID_ENTRY_POINT: Point = (248, 584)
RAID_CLOSE_POINT: Point = (1058, 118)


class Geometry:
    """Maps reference-size coordinates onto the window's actual client area."""

    def __init__(self, client_width: int, client_height: int) -> None:
        ref_w, ref_h = REFERENCE_CLIENT_SIZE
        self.client_width = client_width
        self.client_height = client_height
        self._scale_x = client_width / ref_w
        self._scale_y = client_height / ref_h

    @property
    def is_reference_size(self) -> bool:
        """Close enough to the size the templates were captured at.

        Not an equality test — see :data:`SIZE_TOLERANCE` for why the client
        never lands exactly on the reference.
        """
        return (
            abs(self.client_width - REFERENCE_CLIENT_SIZE[0]) <= SIZE_TOLERANCE
            and abs(self.client_height - REFERENCE_CLIENT_SIZE[1]) <= SIZE_TOLERANCE
        )

    @property
    def scale(self) -> Tuple[float, float]:
        return (self._scale_x, self._scale_y)

    def point(self, point: Point) -> Point:
        return (round(point[0] * self._scale_x), round(point[1] * self._scale_y))

    def region(self, region: Region) -> Region:
        return (self.point(region[0]), self.point(region[1]))
