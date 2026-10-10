"""Text size, set as a percentage in Cài đặt chung.

Players reported the text as too small. Every font in the app is made by
``theme._font``, so one factor there scales all of it; changing the setting
rescales the widgets already built, so it applies without a restart.
"""
from __future__ import annotations

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")

import tasks  # noqa: E402
import theme  # noqa: E402


@pytest.fixture(autouse=True)
def normal_size():
    theme.set_text_scale(1.0)
    yield
    theme.set_text_scale(1.0)


def test_the_setting_is_offered_in_the_app_settings():
    field = next(f for f in tasks.APP_FIELDS if f.key == "text_size")
    assert field.default == "100%"
    assert "125%" in field.options and "150%" in field.options


@pytest.mark.parametrize("text, scale", [
    ("100%", 1.0), ("125%", 1.25), ("150%", 1.5), (" 110 % ", 1.1),
    ("", 1.0), (None, 1.0), ("nhiều", 1.0), ("10%", 1.0), ("900%", 1.0),
])
def test_a_percentage_reads_as_a_scale(text, scale):
    assert tasks.text_scale(text) == pytest.approx(scale)


def test_every_font_follows_the_scale(qt_app):
    theme.set_text_scale(1.5)
    assert theme.body(12).pixelSize() == 18
    assert theme.display(36).pixelSize() == 54
    assert theme.mono(10).pixelSize() == 15
    assert theme.tabular(17).pixelSize() == 26


def test_changing_it_rescales_what_is_already_on_screen(dashboard):
    title = dashboard._header._title
    before = title.font().pixelSize()

    dashboard._on_app_setting("text_size", "150%")

    assert title.font().pixelSize() == round(before * 1.5)


def test_going_back_restores_the_exact_size(dashboard):
    title = dashboard._header._title
    before = title.font().pixelSize()

    for value in ("125%", "160%", "110%", "100%"):
        dashboard._on_app_setting("text_size", value)

    assert title.font().pixelSize() == before


def test_widgets_built_after_the_change_use_it(dashboard):
    dashboard._on_app_setting("text_size", "125%")
    dashboard._show_page("event")        # a page not built before

    assert dashboard._header._title.font().pixelSize() == round(36 * 1.25)


def test_the_choice_is_saved(dashboard, isolated_settings):
    dashboard._on_app_setting("text_size", "125%")
    dashboard._settings.sync()

    assert "125%" in isolated_settings.read_text(encoding="utf-8")


@pytest.fixture
def saved_125(isolated_settings):
    """Written before ``dashboard`` builds the window — request it first."""
    import app_settings

    store = app_settings.open_store()
    store.setValue("text_size", "125%")
    store.sync()


def test_a_saved_size_is_used_from_the_first_frame(saved_125, dashboard):
    assert theme.text_scale() == pytest.approx(1.25)
    assert dashboard._header._title.font().pixelSize() == round(36 * 1.25)


def test_columns_that_hold_text_widen_with_it(dashboard):
    from ui import task_sidebar

    dashboard._show_page("exploration")
    sidebar = dashboard._sidebar
    config = dashboard._views["exploration"]._config_scroll

    dashboard._on_app_setting("text_size", "150%")

    assert sidebar.width() == round(task_sidebar.WIDTH * 1.5)
    from ui import task_view
    assert config.width() == round(task_view.CONFIG_WIDTH * 1.5)


def test_column_widths_come_back_exactly(dashboard):
    from ui import task_sidebar

    for value in ("125%", "150%", "110%", "100%"):
        dashboard._on_app_setting("text_size", value)

    assert dashboard._sidebar.width() == task_sidebar.WIDTH


def test_a_page_built_at_a_larger_size_starts_wide(dashboard):
    from ui import task_view

    dashboard._on_app_setting("text_size", "125%")
    dashboard._show_page("souls")

    assert dashboard._views["souls"]._config_scroll.width() == round(
        task_view.CONFIG_WIDTH * 1.25)


def test_header_buttons_keep_their_words_at_a_large_size(dashboard):
    """At 150% the header row runs short; the title wraps, the buttons do not shrink.

    Checked as the layout rule rather than measured: the offscreen platform the
    suite runs on falls back to other fonts, whose widths say nothing about the
    real ones. Measured on the real platform at 1340px and 150%: both buttons at
    their full width, the title on two lines.
    """
    header = dashboard._header
    for button in (header._video, header._toggle):
        assert button.sizePolicy().horizontalPolicy() == QtWidgets.QSizePolicy.Minimum
    assert header._title.wordWrap()
