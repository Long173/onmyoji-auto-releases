"""Path resolution, in a checkout and in a packaged build.

A frozen build splits what a checkout keeps together: assets are extracted to a
temporary read-only folder, while logs, caches and ``.env`` belong beside the
.exe. Getting that wrong shows up only after packaging, so it is pinned here.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

import paths


def reload_paths(monkeypatch, *, frozen=False, executable=None, meipass=None,
                 environ=None):
    """Re-import paths with sys/os patched to look like another environment."""
    if frozen:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(executable))
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    else:
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    for key, value in (environ or {}).items():
        monkeypatch.setenv(key, value)
    return importlib.reload(paths)


@pytest.fixture(autouse=True)
def restore_paths():
    yield
    importlib.reload(paths)


# ── in a checkout ───────────────────────────────────────────────────────────


def test_a_checkout_keeps_one_root():
    assert not paths.FROZEN
    assert paths.APP_ROOT == paths.BUNDLE_ROOT
    assert paths.APP_ROOT.name == "auto_ads"


def test_assets_resolve_under_the_bundle_root():
    assert paths.FONT_DIR.is_relative_to(paths.BUNDLE_ROOT)
    assert paths.SCREENSHOT_DIR.is_relative_to(paths.BUNDLE_ROOT)
    assert paths.template("RealmRaid", "start.png").endswith("start.png")


def test_caches_resolve_under_the_writable_root():
    assert paths.LOG_DIR.is_relative_to(paths.DATA_ROOT)
    assert paths.WIKI_CACHE_DIR.is_relative_to(paths.CACHE_DIR)


# ── packaged ────────────────────────────────────────────────────────────────


def test_frozen_splits_the_writable_side_from_the_bundle(monkeypatch, tmp_path):
    exe_dir = tmp_path / "shipped"
    exe_dir.mkdir()
    bundle = tmp_path / "_MEI12345"
    (bundle / "wiki" / "assets" / "data").mkdir(parents=True)

    reloaded = reload_paths(
        monkeypatch, frozen=True, executable=exe_dir / "app.exe", meipass=bundle
    )

    assert reloaded.FROZEN
    assert reloaded.APP_ROOT == exe_dir, "writable side must sit beside the .exe"
    assert reloaded.BUNDLE_ROOT == bundle
    assert reloaded.FONT_DIR.is_relative_to(bundle), "assets must come from the bundle"
    assert reloaded.LOG_DIR.is_relative_to(exe_dir), "logs must not go in the bundle"


def test_frozen_prefers_the_packaged_wiki(monkeypatch, tmp_path):
    exe_dir = tmp_path / "shipped"
    exe_dir.mkdir()
    bundle = tmp_path / "_MEI12345"
    (bundle / "wiki" / "assets" / "data").mkdir(parents=True)

    reloaded = reload_paths(
        monkeypatch, frozen=True, executable=exe_dir / "app.exe", meipass=bundle
    )

    assert reloaded.WIKI_ROOT == bundle / "wiki"
    assert reloaded.DEFAULT_WIKI_DATA_DIR == bundle / "wiki" / "assets" / "data"


def test_a_wiki_folder_beside_the_exe_is_picked_up(monkeypatch, tmp_path):
    """So the dataset can be dropped in later without a rebuild."""
    exe_dir = tmp_path / "shipped"
    (exe_dir / "wiki" / "assets" / "data").mkdir(parents=True)
    bundle = tmp_path / "_MEI12345"
    bundle.mkdir()

    reloaded = reload_paths(
        monkeypatch, frozen=True, executable=exe_dir / "app.exe", meipass=bundle
    )

    assert reloaded.WIKI_ROOT == exe_dir / "wiki"


def test_a_read_only_folder_falls_back_to_localappdata(monkeypatch, tmp_path):
    """Someone will put the .exe in Program Files."""
    exe_dir = tmp_path / "program files" / "shipped"
    exe_dir.mkdir(parents=True)
    local = tmp_path / "localappdata"
    local.mkdir()

    monkeypatch.setattr(paths, "_is_writable", lambda directory: False)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    # _writable_root is what the module runs at import; call it directly so the
    # patched probe is the one in play.
    root = paths._writable_root()

    assert root == local / "OnmyojiAuto"


def test_the_probe_reports_a_usable_folder(tmp_path):
    assert paths._is_writable(tmp_path)
    assert not (tmp_path / ".write-probe").exists(), "the probe left a file behind"


def test_describe_names_every_root():
    line = paths.describe()
    for key in ("frozen=", "app=", "data=", "bundle=", "wiki="):
        assert key in line
