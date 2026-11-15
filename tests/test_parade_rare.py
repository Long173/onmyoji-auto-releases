"""Recognising an SSR/SP pick candidate from a picture of it lit up."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import parade_pick
import parade_rare
from game_control import read_image

FIXTURES = Path(__file__).parent / "fixtures" / "demon_parade"


def _lineup(label):
    dark = read_image(str(FIXTURES / ("lineup-%s-dark.jpg" % label)))
    lit = read_image(str(FIXTURES / ("lineup-%s-lit.jpg" % label)))
    left = next(c for c in parade_pick.candidates(dark) if c.column == 0)
    return lit, left


def _library_without(stem_part):
    return tuple(s for s in parade_rare.library() if stem_part not in s.name)


@pytest.fixture(autouse=True)
def fresh_library():
    parade_rare.reload_library()
    yield
    parade_rare.reload_library()


def test_the_shipped_library_loads():
    samples = parade_rare.library()

    assert len(samples) >= 19
    assert all(s.image.shape[:2] == s.mask.shape for s in samples)
    assert {s.column for s in samples} <= {0, 1, 2}


def test_an_ssr_is_recognised_from_a_picture_taken_on_another_client():
    """The emulator's picture of it, against the Steam client — its own
    Steam picture left out, or it would only be recognising itself."""
    lit, candidate = _lineup("rare")

    score, name = parade_rare.best_match(lit, candidate, _library_without("s037"))

    assert score >= parade_rare.MATCH_ACCURACY
    assert "b122" in name


def test_the_common_shikigami_nearest_an_ssr_is_not_taken_for_one():
    """The closest of 848 commons: 0.69 against the nearest SSR/SP picture."""
    lit, candidate = _lineup("common")

    score, _ = parade_rare.best_match(lit, candidate)

    assert score < parade_rare.MATCH_ACCURACY


def test_a_picture_only_counts_for_its_own_column():
    lit, candidate = _lineup("rare")
    elsewhere = candidate._replace(column=2)

    score, name = parade_rare.best_match(lit, elsewhere, _library_without("nothing"))

    assert name is None or "b122" not in name


def test_a_saved_candidate_reads_back_as_a_matching_picture(tmp_path):
    lit, candidate = _lineup("rare")

    path = parade_rare.save(lit, candidate, tmp_path, "check")
    sample = parade_rare._read(path)

    assert sample.column == candidate.column
    assert parade_rare.score(lit, sample) > 0.99


def test_a_file_without_a_position_in_its_name_is_ignored(tmp_path):
    (tmp_path / "notes.png").write_bytes(b"")

    assert parade_rare.library([tmp_path]) == ()


def test_an_empty_mask_scores_nothing():
    sample = parade_rare.Sample("x", 0, 10, 10, np.zeros((20, 20, 3), np.uint8),
                                np.zeros((20, 20), np.uint8))

    assert parade_rare.score(np.zeros((633, 1122, 3), np.uint8), sample) == 0.0
