"""Each task page links its YouTube tutorial from the header."""
from __future__ import annotations

import re

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")

import tasks  # noqa: E402
from ui import page_header  # noqa: E402
from ui.task_sidebar import HOME  # noqa: E402

YOUTUBE = re.compile(r"^https://youtu\.be/[\w-]{11}$")


# Built, but the tutorial has not been recorded yet. Taking a task off this list
# is what the test below then asks for.
AWAITING_VIDEO: set = set()


def test_every_built_task_has_a_tutorial():
    for spec in tasks.available():
        if spec.id in AWAITING_VIDEO:
            assert not spec.video, "%s has a video now: drop it from the list" % spec.id
            continue
        assert YOUTUBE.match(spec.video), "%s has no tutorial link" % spec.id


def test_the_header_offers_the_task_video(dashboard):
    dashboard._show_page("realm_raid")
    button = dashboard._header._video

    assert button.isVisibleTo(dashboard)


def test_pressing_it_opens_that_tasks_video(dashboard, monkeypatch):
    opened = []
    monkeypatch.setattr(page_header, "open_url", opened.append)
    dashboard._show_page("souls")

    dashboard._header._video.click()

    assert opened == [tasks.BY_ID["souls"].video]


def test_the_overview_has_no_video_button(dashboard):
    dashboard._show_page(HOME)

    assert not dashboard._header._video.isVisibleTo(dashboard)


def test_a_task_without_a_video_shows_no_button(dashboard, monkeypatch):
    import dataclasses

    monkeypatch.setitem(tasks.BY_ID, "event",
                        dataclasses.replace(tasks.BY_ID["event"], video=""))
    dashboard._show_page("event")

    assert not dashboard._header._video.isVisibleTo(dashboard)
