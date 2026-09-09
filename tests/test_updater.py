"""In-app updates.

This code downloads an executable and arranges for it to replace the running
one, so the parts that matter are: never accept a file whose hash does not
match, never leave a partial download where it could be mistaken for a good
one, and never touch anything unless the build is actually packaged.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
from pathlib import Path

import pytest

import updater

SAMPLE = b"pretend this is a 100 MB executable" * 40
SAMPLE_SHA = hashlib.sha256(SAMPLE).hexdigest()


def manifest_bytes(**overrides) -> bytes:
    payload = {
        "version": "2.2",
        "url": "https://example.test/Onmyoji%20Auto-2.2.exe",
        "sha256": SAMPLE_SHA,
        "size": len(SAMPLE),
        "published": "2026-08-20",
        "notes": "Sửa nhận diện hết vé",
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


class FakeResponse(io.BytesIO):
    """Enough of an HTTP response for urlopen's context-manager use."""

    def __init__(self, payload: bytes, headers=None):
        super().__init__(payload)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


@pytest.fixture
def served(monkeypatch):
    """Serve canned bytes per URL, and record what was requested."""
    routes = {}
    asked = []

    def fake_open(url):
        asked.append(url)
        if url not in routes:
            raise updater.UpdateError("khong co route cho %s" % url)
        return FakeResponse(routes[url])

    monkeypatch.setattr(updater, "_open", fake_open)
    return routes, asked


# ── versions ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text, expected",
    [("2.1", (2, 1)), ("v2.1", (2, 1)), ("2.10.1", (2, 10, 1)),
     ("2.1-beta", (2, 1)), ("", (0,)), ("abc", (0,))],
)
def test_version_parsing(text, expected):
    assert updater.parse_version(text) == expected


@pytest.mark.parametrize(
    "candidate, current, newer",
    [
        ("2.2", "2.1", True),
        ("2.10", "2.9", True),      # not a string comparison
        ("2.1.1", "2.1", True),
        ("2.1", "2.1", False),      # same version is not an update
        ("2.0", "2.1", False),
        ("2.1", "2.1.1", False),
        ("3.0", "2.99.99", True),
    ],
)
def test_newer_comparison(candidate, current, newer):
    assert updater.is_newer(candidate, current) is newer


# ── configuration ───────────────────────────────────────────────────────────


def test_updates_are_off_when_running_from_source(monkeypatch):
    """Only a packaged build can replace its own executable."""
    monkeypatch.setattr(updater.paths, "FROZEN", False)
    monkeypatch.setenv("ONMYOJI_UPDATE_URL", "https://example.test/latest.json")
    assert not updater.can_update()


def test_updates_are_off_without_a_url(monkeypatch):
    monkeypatch.setattr(updater.paths, "FROZEN", True)
    monkeypatch.delenv("ONMYOJI_UPDATE_URL", raising=False)
    monkeypatch.setattr(updater, "DEFAULT_MANIFEST_URL", "")
    assert not updater.can_update()


def test_updates_are_on_when_packaged_and_configured(monkeypatch):
    monkeypatch.setattr(updater.paths, "FROZEN", True)
    monkeypatch.setenv("ONMYOJI_UPDATE_URL", "https://example.test/latest.json")
    assert updater.can_update()


def test_plain_http_is_refused(monkeypatch):
    monkeypatch.setattr(updater, "DEFAULT_MANIFEST_URL", "http://example.test/x.json")
    monkeypatch.delenv("ONMYOJI_UPDATE_URL", raising=False)
    with pytest.raises(updater.UpdateError, match="HTTPS"):
        updater.fetch_manifest()


# ── the manifest ────────────────────────────────────────────────────────────


def test_a_manifest_is_read(served):
    routes, _asked = served
    routes["https://example.test/latest.json"] = manifest_bytes()

    release = updater.fetch_manifest("https://example.test/latest.json")

    assert release.version == "2.2"
    assert release.sha256 == SAMPLE_SHA
    assert release.size == len(SAMPLE)
    assert release.notes.startswith("Sửa")
    assert round(release.size_mb, 4) == round(len(SAMPLE) / 1024 / 1024, 4)


def test_a_manifest_without_a_url_is_rejected(served):
    routes, _ = served
    routes["https://example.test/latest.json"] = manifest_bytes(url="")

    with pytest.raises(updater.UpdateError, match="thiếu"):
        updater.fetch_manifest("https://example.test/latest.json")


def test_nothing_published_yet_says_so(monkeypatch):
    """Before the first release the object simply is not there."""
    import urllib.error

    def not_found(url):
        raise urllib.error.HTTPError(
            url, 400, "Bad Request", {},
            io.BytesIO(b'{"statusCode":"404","error":"not_found"}'),
        )

    monkeypatch.setattr(updater, "_open", not_found)

    with pytest.raises(updater.UpdateError, match="Chưa có bản phát hành"):
        updater.fetch_manifest("https://example.test/latest.json")


def test_a_real_server_error_is_reported_as_one(monkeypatch):
    import urllib.error

    def boom(url):
        raise urllib.error.HTTPError(url, 500, "Server Error", {}, io.BytesIO(b"oops"))

    monkeypatch.setattr(updater, "_open", boom)

    with pytest.raises(updater.UpdateError, match="500"):
        updater.fetch_manifest("https://example.test/latest.json")


def test_junk_instead_of_a_manifest_is_rejected(served):
    routes, _ = served
    routes["https://example.test/latest.json"] = b"<html>404</html>"

    with pytest.raises(updater.UpdateError, match="không hợp lệ"):
        updater.fetch_manifest("https://example.test/latest.json")


def test_check_returns_nothing_when_already_current(served):
    routes, _ = served
    routes["https://example.test/latest.json"] = manifest_bytes(version="2.1")

    assert updater.check("2.1", "https://example.test/latest.json") is None


def test_check_returns_the_release_when_newer(served):
    routes, _ = served
    routes["https://example.test/latest.json"] = manifest_bytes(version="2.5")

    release = updater.check("2.1", "https://example.test/latest.json")
    assert release is not None and release.version == "2.5"


# ── downloading ─────────────────────────────────────────────────────────────


def release_for(url="https://example.test/app.exe", **overrides):
    fields = {"version": "2.2", "url": url, "sha256": SAMPLE_SHA, "size": len(SAMPLE)}
    fields.update(overrides)
    return updater.Release(**fields)


def test_a_good_download_is_kept(served, tmp_path):
    routes, _ = served
    routes["https://example.test/app.exe"] = SAMPLE
    target = tmp_path / "staged.exe"

    result = updater.download(release_for(), target)

    assert result == target
    assert target.read_bytes() == SAMPLE


def test_progress_is_reported(served, tmp_path):
    routes, _ = served
    routes["https://example.test/app.exe"] = SAMPLE
    seen = []

    updater.download(release_for(), tmp_path / "staged.exe",
                     progress=lambda got, total: seen.append((got, total)))

    assert seen, "no progress was reported"
    assert seen[-1][0] == len(SAMPLE)
    assert all(total == len(SAMPLE) for _got, total in seen)


def test_a_mismatched_hash_is_thrown_away(served, tmp_path):
    """The whole point: a tampered or truncated file must not survive."""
    routes, _ = served
    routes["https://example.test/app.exe"] = SAMPLE + b"tampered"
    target = tmp_path / "staged.exe"

    with pytest.raises(updater.UpdateError, match="mã kiểm tra"):
        updater.download(release_for(), target)

    assert not target.exists(), "a bad download was left on disk"


def test_a_cancelled_download_leaves_nothing_behind(served, tmp_path):
    routes, _ = served
    routes["https://example.test/app.exe"] = SAMPLE
    target = tmp_path / "staged.exe"

    with pytest.raises(updater.UpdateError, match="huỷ"):
        updater.download(release_for(), target, cancelled=lambda: True)

    assert not target.exists()


def test_a_manifest_without_a_hash_still_downloads(served, tmp_path, caplog):
    """Unverified, and said so in the log."""
    routes, _ = served
    routes["https://example.test/app.exe"] = SAMPLE
    target = tmp_path / "staged.exe"

    with caplog.at_level("WARNING"):
        updater.download(release_for(sha256=""), target)

    assert target.read_bytes() == SAMPLE
    assert any("not verified" in record.message for record in caplog.records)


# ── the swap ────────────────────────────────────────────────────────────────


def test_the_staged_file_sits_beside_the_running_one(monkeypatch, tmp_path):
    exe = tmp_path / "Onmyoji Tool.exe"
    monkeypatch.setattr(sys, "executable", str(exe))

    staged = updater.staged_path()

    assert staged.parent == exe.parent
    assert staged.name == updater.STAGED_NAME
    assert staged.suffix == ".zip", "one-dir builds ship as an archive"


def test_the_manifest_name_is_not_the_one_old_builds_read():
    """Builds up to 3.0 rename whatever `latest.json` names to .exe and run it.

    Publishing the .zip under that name bricks every one of them, so the live
    manifest has to live somewhere they never look.
    """
    assert updater.MANIFEST_NAME != "latest.json"
    assert updater.DEFAULT_MANIFEST_URL.endswith(updater.MANIFEST_NAME)


def test_the_swap_script_quotes_paths_and_waits_for_us(tmp_path):
    target = tmp_path / "Onmyoji Tool.exe"
    staged = tmp_path / "Onmyoji Tool.exe.new"

    script = updater.write_swap_script(target, staged, 4242, directory=tmp_path)
    body = script.read_text(encoding="utf-8-sig")

    assert script.suffix == ".ps1"
    assert "'%s'" % target in body, "the target path is not a quoted literal"
    assert "'%s'" % staged in body
    assert "4242" in body, "the script does not wait for this process"
    assert "Move-Item" in body and "Start-Process" in body


def test_the_swap_script_survives_quotes_in_the_path(tmp_path):
    odd = tmp_path / "it's here"
    odd.mkdir()
    target = odd / "app.exe"

    body = updater.write_swap_script(
        target, odd / "app.exe.new", 1, directory=tmp_path
    ).read_text(encoding="utf-8-sig")

    assert "it''s here" in body, "a quote in the path was not escaped"


def test_the_script_is_written_with_a_bom(tmp_path):
    """PowerShell needs the BOM to read a UTF-8 script reliably."""
    script = updater.write_swap_script(
        tmp_path / "a.exe", tmp_path / "a.exe.new", 1, directory=tmp_path
    )
    assert script.read_bytes().startswith(b"\xef\xbb\xbf")


def test_applying_without_a_staged_file_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app.exe"))

    with pytest.raises(updater.UpdateError, match="Không tìm thấy"):
        updater.apply_and_restart(tmp_path / "missing.exe.new")


def test_apply_hands_over_and_does_not_swap_itself(tmp_path, monkeypatch):
    """The running .exe is locked, so the helper must do the move, not us."""
    target = tmp_path / "app.exe"
    target.write_bytes(b"old")
    staged = tmp_path / "app.exe.new"
    staged.write_bytes(b"new")
    monkeypatch.setattr(sys, "executable", str(target))
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))

    launched = []
    monkeypatch.setattr(
        updater.subprocess, "Popen",
        lambda args, **kwargs: launched.append(args) or None,
    )

    updater.apply_and_restart(staged)

    assert launched, "the swap helper was never started"
    assert "powershell.exe" in launched[0][0]
    assert target.read_bytes() == b"old", "the running file must not be replaced here"
    assert staged.exists(), "the staged file must survive for the helper"


# ── the swap, run for real ──────────────────────────────────────────────────
#
# These drive the actual PowerShell helper against a fake install. They are the
# only tests that prove the thing this code exists to do, and the failure they
# guard against is the worst one available: a half-replaced app that never
# opens again. Asserting on the script's *text* would not have caught any of it.

windows_only = pytest.mark.skipif(
    os.name != "nt", reason="the swap helper is PowerShell on Windows"
)

DEAD_PID = 999999  # nothing is running under this, so the wait loop falls through


def build_install(root: Path) -> Path:
    """A fake install: what we ship, plus what the user owns."""
    appdir = root / "Onmyoji Tool"
    (appdir / "_internal").mkdir(parents=True)
    (appdir / "Onmyoji Tool.exe").write_bytes(b"old exe")
    (appdir / "_internal" / "python312.dll").write_bytes(b"old dll")
    # The user's, and none of it is in the archive.
    (appdir / "logs").mkdir()
    (appdir / "logs" / "run.log").write_text("dong nhat ky cu", encoding="utf-8")
    (appdir / "cache").mkdir()
    (appdir / "cache" / "wiki.json").write_text("{}", encoding="utf-8")
    (appdir / ".env").write_text("SUPABASE_URL=x", encoding="utf-8")
    return appdir


def build_zip(path: Path, exe: bytes = b"new exe", dll: bytes = b"new dll") -> Path:
    """An archive shaped the way `publish_release.stage` writes one."""
    import zipfile

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Onmyoji Tool/Onmyoji Tool.exe", exe)
        archive.writestr("Onmyoji Tool/_internal/python312.dll", dll)
    return path


def run_swap(tmp_path: Path, appdir: Path, staged: Path, pid: int = DEAD_PID):
    """Run the helper, with the final relaunch stubbed out.

    A PowerShell *function* shadows the cmdlet of the same name, so dot-sourcing
    the real script under this wrapper records the relaunch instead of starting
    a window we would then have to hunt down.
    """
    import subprocess

    script = updater.write_swap_script(
        appdir / "Onmyoji Tool.exe", staged, pid, directory=tmp_path
    )
    marker = tmp_path / "launched.txt"
    wrapper = tmp_path / "wrapper.ps1"
    wrapper.write_text(
        "function Start-Process { param([string]$FilePath) "
        "Add-Content -LiteralPath '%s' -Value $FilePath }\n. '%s'\n"
        % (marker, script),
        encoding="utf-8-sig",
    )
    done = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(wrapper)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120,
    )
    launched = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
    return done, launched


@windows_only
def test_the_swap_replaces_the_build(tmp_path):
    appdir = build_install(tmp_path)
    staged = build_zip(appdir / updater.STAGED_NAME)

    done, launched = run_swap(tmp_path, appdir, staged)

    assert done.returncode == 0, done.stderr or done.stdout
    assert (appdir / "Onmyoji Tool.exe").read_bytes() == b"new exe"
    assert (appdir / "_internal" / "python312.dll").read_bytes() == b"new dll"
    assert launched.endswith("Onmyoji Tool.exe"), "the app was not started again"


@windows_only
def test_the_swap_leaves_everything_the_user_owns_alone(tmp_path):
    """logs, cache and .env live in the same folder as the .exe it replaces."""
    appdir = build_install(tmp_path)
    staged = build_zip(appdir / updater.STAGED_NAME)

    run_swap(tmp_path, appdir, staged)

    assert (appdir / "logs" / "run.log").read_text(encoding="utf-8") == "dong nhat ky cu"
    assert (appdir / "cache" / "wiki.json").exists()
    assert (appdir / ".env").read_text(encoding="utf-8") == "SUPABASE_URL=x"


@windows_only
def test_the_swap_tidies_up_after_itself(tmp_path):
    appdir = build_install(tmp_path)
    staged = build_zip(appdir / updater.STAGED_NAME)

    run_swap(tmp_path, appdir, staged)

    assert not staged.exists(), "the archive was left behind"
    assert not (appdir / ".update-stage").exists()
    assert not (appdir / ".update-backup").exists()


@windows_only
def test_a_corrupt_archive_leaves_the_old_build_running(tmp_path):
    """Better the version they had than no working app at all."""
    appdir = build_install(tmp_path)
    staged = appdir / updater.STAGED_NAME
    staged.write_bytes(b"this is not a zip file")

    _done, launched = run_swap(tmp_path, appdir, staged)

    assert (appdir / "Onmyoji Tool.exe").read_bytes() == b"old exe"
    assert (appdir / "_internal" / "python312.dll").read_bytes() == b"old dll"
    assert launched.endswith("Onmyoji Tool.exe"), "the user was left with nothing open"
    # The success path deletes the archive and the failure path keeps it, so
    # this is what says which one ran. The script's exit code cannot say: these
    # tests dot-source it to stub the relaunch, and `exit` does not carry
    # through that. Nothing reads the code in production anyway — by the time
    # the helper runs, the app that launched it has already quit.
    assert staged.exists(), "the download was thrown away, so it cannot be retried"


@windows_only
def test_an_empty_archive_is_refused(tmp_path):
    """An archive that unpacks to nothing must not blank the install."""
    import zipfile

    appdir = build_install(tmp_path)
    staged = appdir / updater.STAGED_NAME
    with zipfile.ZipFile(staged, "w"):
        pass

    run_swap(tmp_path, appdir, staged)

    assert (appdir / "Onmyoji Tool.exe").read_bytes() == b"old exe"
    assert staged.exists(), "an empty archive was treated as a good build"


@windows_only
def test_a_failure_partway_puts_the_old_build_back(tmp_path):
    """The dangerous case: some entries moved aside, then something jams.

    A process whose working directory is `_internal` makes that folder
    unmovable, which is exactly how a real one fails — antivirus or Explorer
    holding something open. Whatever order the entries are processed in, the
    install has to end up as it started.
    """
    import subprocess

    appdir = build_install(tmp_path)
    staged = build_zip(appdir / updater.STAGED_NAME)

    holder = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-Command", "Start-Sleep -Seconds 90"],
        cwd=str(appdir / "_internal"),
    )
    try:
        _done, launched = run_swap(tmp_path, appdir, staged)
    finally:
        holder.kill()
        holder.wait(timeout=30)

    assert (appdir / "Onmyoji Tool.exe").read_bytes() == b"old exe", (
        "the .exe was moved aside and never put back — the app is gone"
    )
    assert (appdir / "_internal" / "python312.dll").read_bytes() == b"old dll"
    assert not (appdir / ".update-backup").exists(), "backup left lying around"
    assert launched.endswith("Onmyoji Tool.exe")
