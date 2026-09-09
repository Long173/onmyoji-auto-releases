"""Telling parading shikigami apart by colour.

Driven against the sprites actually cut from live rounds and labelled by hand,
because the question is whether real pixels off a real screen sort themselves
into the right buckets. A synthetic figure would prove nothing.
"""
from __future__ import annotations

import os

import cv2
import numpy as np
import pytest

import parade_figures


@pytest.fixture(autouse=True)
def fresh_library():
    parade_figures.reload_library()
    yield
    parade_figures.reload_library()


def labelled():
    """(rarity, path) for every sprite filed under a rarity.

    Asks the module where the pictures are rather than assuming: they are bulky
    enough to be moved to another drive, and a test that hardcoded the old path
    would quietly find nothing and pass.
    """
    root = str(parade_figures.raw_library_dir())
    out = []
    for rank in parade_figures.RANKS:
        folder = os.path.join(root, rank)
        if not os.path.isdir(folder):
            continue
        for entry in sorted(os.listdir(folder)):
            if entry.lower().endswith(".png"):
                out.append((rank, os.path.join(folder, entry)))
    return out


def read(path):
    return cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)


# ── the signature ───────────────────────────────────────────────────────────


def test_a_figure_has_a_signature():
    sprite = np.zeros((60, 40, 3), dtype=np.uint8)
    sprite[10:50, 5:35] = (30, 180, 220)

    assert parade_figures.signature(sprite) is not None


def test_an_empty_cut_out_has_none():
    """All background and no figure says nothing about who is there."""
    assert parade_figures.signature(np.zeros((60, 40, 3), dtype=np.uint8)) is None


def test_a_sliver_of_a_figure_has_none():
    """Too few pixels to tell one palette from another."""
    sprite = np.zeros((60, 40, 3), dtype=np.uint8)
    sprite[0:4, 0:4] = (30, 180, 220)

    assert parade_figures.signature(sprite) is None


def test_two_colours_are_told_apart():
    blue, red = (np.zeros((60, 40, 3), np.uint8), np.zeros((60, 40, 3), np.uint8))
    blue[10:50, 5:35] = (200, 60, 40)
    red[10:50, 5:35] = (40, 60, 200)

    score = parade_figures.alike(
        parade_figures.signature(blue), parade_figures.signature(red)
    )

    assert score < parade_figures.MATCH_ACCURACY


# ── against the real, labelled sprites ──────────────────────────────────────


def test_every_labelled_sprite_reads_back_as_its_own_rarity():
    """Whatever else the matcher does, it must not disagree with the labels.

    Weak on its own — a sprite is in the library, so it matches itself at 1.0.
    It earns its place by catching the case where some *other* rank scores
    higher still, which is what a rank mix-up would look like.
    """
    wrong = []
    for rank, path in labelled():
        got = parade_figures.rarity_of(read(path))
        if got != rank:
            wrong.append((os.path.basename(path), rank, got))

    assert not wrong, "sprites filed under one rarity but read as another: %s" % wrong[:5]


def test_no_rare_figure_looks_like_a_common_one():
    """The failure that would empty the round quietly.

    A rare figure scoring above the threshold against something in the common
    library reads as common, and the loop passes it over — the one figure the
    whole run exists to hit. Nothing else about a mix-up costs anything: SR
    against R against COMMON are all commons, and confusing them changes no
    decision, which is why only the rare-versus-common pairs are checked here.
    """
    rare, common = [], []
    for rank, path in labelled():
        mark = parade_figures.signature(read(path))
        if mark is None:
            continue
        name = "%s/%s" % (rank, os.path.basename(path))
        if rank in parade_figures.TARGET_RANKS:
            rare.append((name, mark))
        else:
            common.append((name, mark))

    assert rare and common, "need both kinds on disk for this to mean anything"

    worst, pair = 0.0, None
    for rare_name, rare_mark in rare:
        for common_name, common_mark in common:
            score = parade_figures.alike(rare_mark, common_mark)
            if score > worst:
                worst, pair = score, (rare_name, common_name)

    assert worst < parade_figures.MATCH_ACCURACY, (
        "a rare figure matches a common one at %.3f, at or above the %.2f "
        "threshold — the loop will pass it over: %s"
        % (worst, parade_figures.MATCH_ACCURACY, pair)
    )


def test_every_rare_sprite_still_reads_as_rare():
    """Cheap, and it is the check that the common library has not swallowed
    the very figures it is there to leave behind."""
    swallowed = []
    for rank, path in labelled():
        if rank not in parade_figures.TARGET_RANKS:
            continue
        if not parade_figures.is_target(parade_figures.rarity_of(read(path))):
            swallowed.append(os.path.basename(path))

    assert not swallowed, "rare sprites now read as common: %s" % swallowed[:5]


def test_the_pictures_behind_the_library_can_be_found():
    """Several tests below walk the labelled pictures, and every one of them
    passes trivially if the folder cannot be found — which is easy to arrange
    by accident, since it is allowed to live on another drive."""
    found = labelled()

    assert found, (
        "no pictures under %s — set %s if they have been moved"
        % (parade_figures.raw_library_dir(), parade_figures.RAW_LIBRARY_VARIABLE)
    )


def test_the_library_is_not_empty():
    """A missing library is silent — every figure reads as unknown and aiming
    quietly degrades to a plain sweep."""
    library = parade_figures.library()

    assert library, "no rarity library on disk"
    assert sum(len(v) for v in library.values()) >= 20


# ── priority ────────────────────────────────────────────────────────────────


def test_the_two_ranks_worth_a_bean_are_targets():
    assert parade_figures.is_target("SP")
    assert parade_figures.is_target("SSR")


def test_the_common_ranks_are_not():
    for rank in ("SR", "R", "N"):
        assert not parade_figures.is_target(rank), rank


def test_an_unrecognised_figure_is_worth_a_bean():
    """The one that carries the whole design, so it gets the reasoning.

    Rare shikigami do not come back: all thirteen a player picked out of ten
    rounds appeared in exactly one round each, against 31% for groups at large.
    Commons repeat — 69% of them showed up in more than one round. So a library
    of rare figures cannot recognise the next rare figure, but a library of
    commons can rule one out, and whatever is left over is the prize.

    Flip this to False and the loop only ever throws at the handful of rare
    shikigami somebody has already labelled, which live measurement put at one
    throw in seventy-five.
    """
    assert parade_figures.is_target(None)


def test_the_common_grades_cover_the_folders_that_are_not_rare():
    for rank in parade_figures.RANKS:
        if rank in parade_figures.TARGET_RANKS:
            continue
        assert rank in parade_figures.COMMON_RANKS, (
            "%s is neither rare nor common, so is_target's answer for it is an "
            "accident" % rank
        )


def test_the_targets_are_ranks_that_exist():
    for rank in parade_figures.TARGET_RANKS:
        assert rank in parade_figures.RANKS


def test_the_ranks_the_user_is_hunting_are_present_in_the_library():
    """Not a hard failure — a note.

    SP and SSR are the whole reason for aiming, and a first pass of 106 groups
    came back with none of either: the collector was throwing away anything
    wider than 250 pixels, which is what the most elaborate artwork is.
    """
    library = parade_figures.library()
    missing = [r for r in ("SP", "SSR") if not library.get(r)]
    if missing:
        print("chua co mau cho hang: %s" % ", ".join(missing))


# ── the tools and the library must agree where the pictures live ─────────────


def test_the_labelling_tools_write_where_the_packer_reads():
    """A silent split loses whole cycles of work.

    The pictures are allowed to live on another drive, and two tools once had
    the original path spelled out in them. Moving the library left them filing
    into a stray folder on the old drive while the packer read the real one: a
    collection cycle filed 23 groups into nowhere and the library did not grow.

    Reading is already covered by test_the_pictures_behind_the_library_can_be_found;
    this is the writing side, which that test cannot see.
    """
    import sys
    tools = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"
    )
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import cluster_figures
    import promote_group  # noqa: F401 - imported for the path it resolves

    library = parade_figures.raw_library_dir()

    assert cluster_figures.common_dir().parent == library, (
        "cluster_figures files commons into %s but the library is %s"
        % (cluster_figures.common_dir().parent, library)
    )
