"""Reading the world map's chapter list.

The fixtures are the list band, cut at the reference size from a live list at
four scroll positions: the bottom (26-28), the middle (13-15, 8-10) and the top
(1-4). Each row must read as its own number, and only that.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

import chapter_list
import geometry
from game_control import read_image

LISTS = Path(__file__).parent / "fixtures" / "exploration" / "chapters"
SHOWN = {
    "list_00.png": [26, 27, 28],
    "list_05.png": [13, 14, 15],
    "list_07.png": [8, 9, 10],
    "list_10.png": [1, 2, 3, 4],
}


def frame_showing(name):
    """A reference-size grey frame with the list band where the game draws it."""
    band = read_image(str(LISTS / name), cv2.IMREAD_GRAYSCALE)
    assert band is not None, name
    frame = np.zeros(tuple(reversed(geometry.REFERENCE_CLIENT_SIZE)), np.uint8)
    (x, y), _ = geometry.EXPLORATION_CHAPTER_LIST
    frame[y:y + band.shape[0], x:x + band.shape[1]] = band
    return frame


class FrameControl:
    def __init__(self, frame):
        self.frame = frame

    def reference_shot(self, gray=True):
        return self.frame


def reader(frame, size=geometry.REFERENCE_CLIENT_SIZE):
    return chapter_list.ChapterList(FrameControl(frame), geometry.Geometry(*size))


@pytest.mark.parametrize("name,expected", sorted(SHOWN.items()))
def test_every_row_in_view_reads_as_its_own_number(name, expected):
    rows = reader(frame_showing(name)).read()

    assert [n for n, _ in rows] == expected


def test_a_row_is_clicked_on_its_label():
    """The label is what opens a chapter; Chapter 28 used to be (990, 417)."""
    rows = dict(reader(frame_showing("list_00.png")).read())

    x, y = rows[28]
    assert abs(x - 990) <= 25 and abs(y - 412) <= 10, rows[28]


def test_points_are_given_in_the_windows_own_pixels():
    size = (geometry.REFERENCE_CLIENT_SIZE[0] * 2, geometry.REFERENCE_CLIENT_SIZE[1] * 2)
    at_reference = dict(reader(frame_showing("list_00.png")).read())
    doubled = dict(reader(frame_showing("list_00.png"), size).read())

    assert doubled[28] == (at_reference[28][0] * 2, at_reference[28][1] * 2)


def test_one_digit_is_not_read_as_two():
    """"Chapter 1" sits inside "Chapter 12"; the blank after the 1 tells them apart."""
    rows = reader(frame_showing("list_10.png")).read()

    assert rows[0][0] == 1


def test_a_reading_that_does_not_hold_together_is_thrown_away(monkeypatch):
    monkeypatch.setattr(chapter_list, "read_rows",
                        lambda frame, word, numbers: [(13, (0, 0)), (19, (0, 1))])

    assert reader(frame_showing("list_05.png")).read() == []


def test_a_screen_without_the_list_reads_nothing():
    blank = np.zeros(tuple(reversed(geometry.REFERENCE_CLIENT_SIZE)), np.uint8)

    assert reader(blank).read() == []


@pytest.mark.parametrize("numbers,expected", [
    ([], True), ([7], True), ([3, 4, 5], True), ([3, 5], False), ([5, 4], False),
])
def test_consecutive(numbers, expected):
    assert chapter_list.consecutive(numbers) is expected


def test_every_chapter_has_its_template():
    folder = Path(chapter_list.CHAPTER_DIR)
    assert sorted(p.name for p in folder.glob("*.png")) == [
        "%02d.png" % n for n in range(1, chapter_list.CHAPTERS + 1)]


# ── the list as a world-map signal ──────────────────────────────────────────
#
# On a live map over green countryside the tab strip read 0.794 and the Realm
# Raid icon 0.74, both under their cut-offs, and the loop stood on a world map
# it could not see. The list is the third signal.

RECORDED = Path(__file__).resolve().parents[1] / "recordings" / "map-w1"


def worker_seeing(frame):
    import exploration
    from conftest import bare_control

    control = bare_control(client=geometry.REFERENCE_CLIENT_SIZE)
    colour = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR) if frame.ndim == 2 else frame
    control.full_shot = lambda gray=False: (
        cv2.cvtColor(colour, cv2.COLOR_BGR2GRAY) if gray else colour)
    return exploration.ExplorationWorker(hwnd=1, control=control)


@pytest.mark.parametrize("name", sorted(SHOWN))
def test_the_list_alone_says_world_map(name):
    """No tab strip and no Realm Raid icon in these frames: only the list."""
    assert worker_seeing(frame_showing(name))._on_world_map()


def test_a_screen_without_the_list_is_not_the_world_map():
    blank = np.zeros(tuple(reversed(geometry.REFERENCE_CLIENT_SIZE)), np.uint8)
    assert not worker_seeing(blank)._on_world_map()


@pytest.mark.skipif(not RECORDED.is_dir(), reason="the recorded laps are not present")
def test_the_fade_into_a_chapter_panel_is_not_taken_for_the_world_map():
    """The list shows through the cross-fade at 0.886; the cut-off is above it."""
    image = read_image(str(RECORDED / "27_0085.2s.png"))
    frame = cv2.resize(image, geometry.REFERENCE_CLIENT_SIZE, interpolation=cv2.INTER_CUBIC)
    import exploration
    worker = worker_seeing(frame)

    found = worker._control.find(exploration.TPL_CHAPTER_WORD,
                                 exploration.CHAPTER_LIST_THRESHOLD,
                                 region=worker._chapter_list, delay=0)
    assert found is None
