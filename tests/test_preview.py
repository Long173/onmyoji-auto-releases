"""The live thumbnail of a game window.

Two things are worth pinning. The conversion, because both of its failure modes
are silent — a sheared picture from a mis-stated stride, and swapped colour
channels — and neither raises. And the throttle, because an idle window costs a
real screen grab per card per tick, which is why the preview was expensive
enough to need throttling in the first place.
"""
from __future__ import annotations

import numpy as np
import pytest

QtGui = pytest.importorskip("PyQt5.QtGui")

from ui import preview  # noqa: E402

RAID = "realm_raid"


def bgr_frame(width=64, height=36, colour=(10, 20, 200)):
    """A solid frame in OpenCV's channel order (blue, green, red)."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :] = colour
    return frame


# ── conversion ──────────────────────────────────────────────────────────────


def test_a_frame_becomes_a_pixmap_of_the_same_size(qt_app):
    pixmap = preview.to_pixmap(bgr_frame(width=100, height=56))

    assert pixmap is not None
    assert (pixmap.width(), pixmap.height()) == (100, 56)


def test_channels_are_reordered_not_just_copied(qt_app):
    """OpenCV hands back BGR. Skip the swap and the game looks blue-tinted."""
    pixmap = preview.to_pixmap(bgr_frame(colour=(10, 20, 200)))   # mostly red

    colour = pixmap.toImage().pixelColor(5, 5)
    assert (colour.red(), colour.green(), colour.blue()) == (200, 20, 10)


@pytest.mark.parametrize("width", [61, 62, 63, 65, 101])
def test_an_awkward_width_is_not_sheared(qt_app, width):
    """A width that is not a multiple of four is where a bad stride shows up.

    The frame is a solid colour, so every pixel must match; a mis-stated
    bytes-per-line walks the read head and leaves a diagonal seam.
    """
    pixmap = preview.to_pixmap(bgr_frame(width=width, height=20))
    image = pixmap.toImage()

    corners = [(0, 0), (width - 1, 0), (0, 19), (width - 1, 19), (width // 2, 10)]
    seen = {image.pixelColor(x, y).getRgb()[:3] for x, y in corners}
    assert seen == {(200, 20, 10)}, "the picture is sheared: %s" % seen


def test_a_four_channel_frame_also_works(qt_app):
    """part_shot and raw grabs can carry an alpha channel."""
    frame = np.zeros((10, 10, 4), dtype=np.uint8)
    frame[:, :] = (10, 20, 200, 255)

    pixmap = preview.to_pixmap(frame)

    assert pixmap is not None
    assert pixmap.toImage().pixelColor(1, 1).getRgb()[:3] == (200, 20, 10)


@pytest.mark.parametrize(
    "bad",
    [None, np.zeros((0, 0, 3), dtype=np.uint8), np.zeros((4, 4), dtype=np.uint8),
     np.zeros((4, 4, 2), dtype=np.uint8)],
)
def test_nothing_usable_yields_nothing(qt_app, bad):
    """A failed capture must not raise inside a repaint."""
    assert preview.to_pixmap(bad) is None


def test_the_box_keeps_the_games_aspect_ratio():
    assert preview.height_for(320) == 180
    assert preview.height_for(0) == 1, "a zero-width box must not be zero-height"


# ── the card ────────────────────────────────────────────────────────────────


class StubSession:
    """Enough of a GameSession for the card, counting its captures."""

    def __init__(self, running=False, hwnd=101):
        from auto.window_scanner import GameWindow

        self.window = GameWindow(hwnd, "陰陽師Onmyoji", 1136, 640)
        self.hwnd = hwnd
        self.title = self.window.title
        self.selected = RAID
        self.status = "running" if running else "idle"
        self.message = ""
        self.is_running = running
        self.task_id = RAID if running else RAID
        self.progress = 0
        self.elapsed_seconds = 0.0
        self.captures = 0

    def preview_frame(self):
        self.captures += 1
        return bgr_frame()

    def stats_for(self, task_id):
        return 0, 0.0


@pytest.fixture
def card(qt_app):
    import tasks
    from ui.task_view import TaskWindowCard

    session = StubSession()
    return TaskWindowCard(session, tasks.BY_ID[RAID]), session


def test_the_card_shows_the_frame(card):
    made, session = card

    made.update_from(session)

    assert session.captures == 1
    assert made._thumbnail._pixmap is not None


def test_the_first_refresh_always_captures_even_on_a_throttled_tick(card):
    """Otherwise a card sits blank for a second after it appears."""
    made, session = card

    made.update_from(session, capture=False)

    assert session.captures == 1


def test_an_idle_window_is_not_grabbed_on_every_tick(card):
    """Each grab is real GDI work, once per card per tick."""
    made, session = card
    made.update_from(session)          # the mandatory first one
    before = session.captures

    for _ in range(4):
        made.update_from(session, capture=False)

    assert session.captures == before, "an idle window was grabbed while throttled"


def test_a_running_window_updates_every_tick(qt_app):
    """Free: it reads the frame the raid loop already captured."""
    import tasks
    from ui.task_view import TaskWindowCard

    session = StubSession(running=True)
    made = TaskWindowCard(session, tasks.BY_ID[RAID])

    for _ in range(3):
        made.update_from(session, capture=False)

    assert session.captures == 3


def test_a_failed_capture_leaves_a_message_not_a_crash(qt_app):
    import tasks
    from ui.task_view import TaskWindowCard

    session = StubSession()
    session.preview_frame = lambda: None
    made = TaskWindowCard(session, tasks.BY_ID[RAID])

    made.update_from(session)

    assert made._thumbnail._pixmap is None
    assert "KHÔNG CHỤP" in made._thumbnail._text


# ── wiring ──────────────────────────────────────────────────────────────────


def test_the_overview_page_never_grabs_anything(dashboard, monkeypatch):
    """No thumbnails there, so idle windows should cost nothing on that page."""
    grabs = []
    for session in dashboard._manager.sessions:
        monkeypatch.setattr(
            session, "preview_frame", lambda s=session: grabs.append(s.hwnd)
        )

    for _ in range(6):
        dashboard._refresh()

    assert grabs == []


def test_a_task_page_that_is_not_open_never_grabs_anything(dashboard, monkeypatch):
    dashboard._show_page(RAID)
    grabs = []
    for session in dashboard._manager.sessions:
        monkeypatch.setattr(
            session, "preview_frame", lambda s=session: grabs.append(s.hwnd)
        )
    dashboard._show_page("__home__")

    for _ in range(6):
        dashboard._refresh()

    assert grabs == []


def test_leaving_a_task_page_releases_the_capture_handles(dashboard, monkeypatch):
    """Otherwise every previewed window keeps its device contexts for good."""
    released = []
    for session in dashboard._manager.sessions:
        monkeypatch.setattr(
            session, "release", lambda s=session: released.append(s.hwnd)
        )

    dashboard._show_page(RAID)
    dashboard._show_page("__home__")

    assert set(released) == {s.hwnd for s in dashboard._manager.sessions}
