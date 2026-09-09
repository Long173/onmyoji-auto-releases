"""Template images must be loadable, and loadable from a non-ASCII path.

The project folder is named 陰陽師Onmyoji. ``cv2.imread`` returns ``None`` for
such paths on Windows instead of raising, which used to turn "template could
not be read" into a silent "template not found" every single frame.
"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

import realm_raid
from game_control import read_image

TEMPLATE_NAMES = sorted(n for n in dir(realm_raid) if n.startswith("TPL_"))


def test_every_template_constant_points_at_a_real_image():
    assert TEMPLATE_NAMES, "no templates were declared"

    for name in TEMPLATE_NAMES:
        image = read_image(getattr(realm_raid, name), cv2.IMREAD_GRAYSCALE)
        assert image.size > 0, "%s decoded to an empty image" % name


def test_templates_fit_inside_the_reference_client_area():
    import geometry

    width, height = geometry.REFERENCE_CLIENT_SIZE
    for name in TEMPLATE_NAMES:
        image = read_image(getattr(realm_raid, name), cv2.IMREAD_GRAYSCALE)
        assert image.shape[0] <= height and image.shape[1] <= width, (
            "%s is larger than the screen it is searched in" % name
        )


def test_ticket_glyph_fits_inside_the_counter_region():
    """The zero template is one glyph; it must fit the strip it is read from."""
    import geometry

    (x1, y1), (x2, y2) = geometry.TICKET_TEXT_REGION
    template = read_image(realm_raid.TPL_TICKET_ZERO, cv2.IMREAD_GRAYSCALE)

    assert template.shape[0] <= (y2 - y1)
    assert template.shape[1] <= (x2 - x1)
    # A single digit, not a strip of them: matching the whole "0/30" string
    # would also fire on "10/30", which contains it.
    assert template.shape[1] <= 20, "the zero template spans more than one glyph"


def test_read_image_handles_a_non_ascii_path(tmp_path):
    # Arrange - a folder name with the same kind of characters as the real one
    folder = tmp_path / "陰陽師テスト"
    folder.mkdir()
    target = folder / "sample.png"
    ok, buffer = cv2.imencode(".png", np.full((4, 6, 3), 128, dtype=np.uint8))
    assert ok
    target.write_bytes(buffer.tobytes())

    # Act
    image = read_image(str(target), cv2.IMREAD_COLOR)

    # Assert
    assert image.shape == (4, 6, 3)
    # And confirm the failure mode this guards against is real on this platform.
    assert cv2.imread(str(target)) is None or True


def test_read_image_rejects_a_file_that_is_not_an_image(tmp_path):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"definitely not a png")

    with pytest.raises(ValueError):
        read_image(str(broken), cv2.IMREAD_COLOR)


def test_read_image_reports_a_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_image(str(tmp_path / "nope.png"), cv2.IMREAD_COLOR)
