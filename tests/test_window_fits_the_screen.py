"""The window has to fit on the screen it opens on.

Reported at 200% display scaling: the lower part of the app was off-screen and
its controls could not be reached. The numbers say why — the window declared a
minimum of 1120x700, and a 2560x1440 monitor at 200% offers 1280x672 of
*logical* room. The width fits; the height is 28 short, and a minimum is a
floor Qt will not go under, so the window stayed taller than the screen.

Every page inside already scrolls, so a shorter window loses nothing. What it
must not do is insist on a height the screen does not have.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from ui.auto_window import DESIGN_MINIMUM, fit_to_screen  # noqa: E402


def test_a_roomy_screen_keeps_the_designed_minimum():
    assert fit_to_screen(DESIGN_MINIMUM, (1920, 1032)) == DESIGN_MINIMUM


def test_the_reported_screen_gets_a_shorter_window():
    """2560x1440 at 200%, which is where this was found."""
    assert fit_to_screen(DESIGN_MINIMUM, (1280, 672)) == (1120, 672)


def test_a_narrow_screen_gives_up_width_too():
    assert fit_to_screen(DESIGN_MINIMUM, (1000, 1032)) == (1000, 700)


def test_nothing_is_ever_asked_for_beyond_the_screen():
    """The property that matters, over a spread of real screen sizes."""
    screens = [(3840, 2112), (1920, 1032), (1536, 824), (1280, 672),
               (1024, 560), (800, 450)]
    for available in screens:
        width, height = fit_to_screen(DESIGN_MINIMUM, available)
        assert width <= available[0], "%s too wide for %s" % (width, available)
        assert height <= available[1], "%s too tall for %s" % (height, available)


def test_a_screen_size_that_cannot_be_read_falls_back_to_the_design():
    """Qt answers 0x0 when there is no screen — a headless run, a race at
    start-up. Clamping to that would leave a window of nothing."""
    assert fit_to_screen(DESIGN_MINIMUM, (0, 0)) == DESIGN_MINIMUM


def test_the_window_itself_fits(dashboard):
    """The wiring, not just the arithmetic."""
    from PyQt5 import QtWidgets

    available = QtWidgets.QApplication.primaryScreen().availableGeometry()
    minimum = dashboard.minimumSize()

    assert minimum.width() <= available.width()
    assert minimum.height() <= available.height()


@pytest.mark.parametrize("task_id", [spec.id for spec in __import__("tasks").TASKS])
def test_no_page_holds_the_window_taller_than_the_design(dashboard, task_id):
    """The window could not be dragged shorter at all, at 100% scaling.

    The settings column on a task page did not scroll, so its explanatory notes
    set a floor under the whole window — 937 px for Thám hiểm chương alone, and
    the page stack takes the tallest floor of all its pages. With the title bar
    and header on top, the window could not go under about 1200 px: on a
    1392 px desktop that left the bottom edge nowhere to go.
    """
    from PyQt5 import QtWidgets

    dashboard._show_page(task_id)
    QtWidgets.QApplication.processEvents()

    assert dashboard.minimumSizeHint().height() <= DESIGN_MINIMUM[1], (
        "a page's content sets a floor taller than the window's own minimum")
