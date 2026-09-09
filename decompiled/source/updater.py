"""In-app updates for the packaged build.

The owner publishes two things to any public HTTPS location — a small JSON
manifest and the new build as a .zip. The app reads the manifest, and if it
names a newer version, downloads the .zip, checks its SHA-256 against the
manifest, then swaps the build in and restarts.

A .zip rather than an .exe because the app is packaged one-dir: what ships is
a folder holding the .exe and `_internal/`. See the spec file for why one-file
was abandoned.

Manifest shape::

    {
      "version": "3.1",
      "url": "https://.../OnmyojiTool-3.1.zip",
      "sha256": "a1b2…",
      "size": 107000000,
      "published": "2026-08-20",
      "notes": "Sửa nhận diện hết vé"
    }

Security, stated plainly: the download is verified against the hash in the
manifest, so a corrupted or truncated transfer is caught, and both are fetched
over HTTPS. But the manifest is the only authority — nothing is code-signed, so
whoever can write to that URL can run code on every machine that updates from
it. Keep write access to it as tightly held as the app itself.

Nothing here imports Qt; the UI drives it from a worker thread.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

import paths

logger = logging.getLogger(__name__)

# Where releases are published: a GitHub repository whose latest release
# carries `latest.json` and the .exe as attachments. GitHub serves release
# assets of a *public* repo without any login and without a size limit worth
# worrying about, which is the whole reason for choosing it.
#
# Fill in the account name and rebuild — the packaged app has no other way to
# find updates, so this must already be right in the build you hand out. Left
# blank, the feature simply stays off rather than nagging about a bad address.
GITHUB_OWNER = "Long173"
# Keeps its original spelling after the app was renamed. This is the address
# already baked into every copy handed out; renaming the repo would leave those
# installs depending on a GitHub redirect that anyone could later break by
# creating a repo under the old name. A URL is not branding.
GITHUB_REPO = "onmyoji-auto-releases"

DEFAULT_MANIFEST_URL = ""

TIMEOUT_SECONDS = 30
CHUNK = 256 * 1024
STAGED_NAME = "update.zip"
USER_AGENT = "OnmyojiTool-Updater"

# Deliberately *not* `latest.json`.
#
# Builds up to 3.0 were one-file and their updater reads `latest.json`, expects
# a bare .exe behind it, and moves that file straight over its own .exe. Publish
# a .zip there and every one of those installs renames a zip to .exe and dies at
# the next launch. Their code is already out in the world and cannot be fixed.
#
# So the old name stays frozen at 3.0 forever: an old build reads it, sees
# nothing newer, and stays quiet instead of bricking itself. Builds from 3.1 on
# read the name below, where the .zip is published. The one cost is that old
# installs never update themselves again — they have to be replaced by hand,
# once. See `publish_release.py`, which writes both.
MANIFEST_NAME = "latest-v2.json"

# The page a person can open, as opposed to the manifest a program reads. Built
# from the same two names so the address exists in one place: a link in the app
# that pointed somewhere the updater does not would be worse than no link.
REPO_URL = ""

if GITHUB_OWNER:
    DEFAULT_MANIFEST_URL = (
        "https://github.com/%s/%s/releases/latest/download/%s"
        % (GITHUB_OWNER, GITHUB_REPO, MANIFEST_NAME)
    )
    REPO_URL = "https://github.com/%s/%s" % (GITHUB_OWNER, GITHUB_REPO)


class UpdateError(RuntimeError):
    """Something went wrong; the message is safe to show a user."""


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    sha256: str = ""
    size: int = 0
    published: str = ""
    notes: str = ""

    @property
    def size_mb(self) -> float:
        return self.size / (1024 * 1024) if self.size else 0.0


# ── versions ────────────────────────────────────────────────────────────────


def parse_version(text: str) -> Tuple[int, ...]:
    """``"2.10.1"`` -> ``(2, 10, 1)``. Unparsable parts count as 0."""
    parts = []
    for chunk in str(text or "").strip().lstrip("vV").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(candidate: str, current: str) -> bool:
    """Compare with equal length, so 2.2 beats 2.1.9 and 2.1 does not beat 2.1."""
    left, right = parse_version(candidate), parse_version(current)
    length = max(len(left), len(right))
    left += (0,) * (length - len(left))
    right += (0,) * (length - len(right))
    return left > right


# ── configuration ───────────────────────────────────────────────────────────


def manifest_url() -> str:
    """The manifest location, with an environment override for testing."""
    return (os.environ.get("ONMYOJI_UPDATE_URL") or DEFAULT_MANIFEST_URL).strip()


def can_update() -> bool:
    """Only a packaged build can replace itself, and only if a URL is set."""
    return bool(paths.FROZEN and manifest_url())


# ── fetching ────────────────────────────────────────────────────────────────


def _open(url: str):
    if not url.lower().startswith("https://"):
        raise UpdateError("Địa chỉ cập nhật phải dùng HTTPS.")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS)


def fetch_manifest(url: Optional[str] = None) -> Release:
    """Read the published manifest. Raises :class:`UpdateError`."""
    target = (url or manifest_url()).strip()
    if not target:
        raise UpdateError("Chưa cấu hình địa chỉ cập nhật.")
    try:
        with _open(target) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Nothing published yet is the normal state before the first release,
        # and object stores answer that with a 404 — or a 400 wrapping one.
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        if exc.code == 404 or "not_found" in detail or "NoSuchKey" in detail:
            raise UpdateError("Chưa có bản phát hành nào.") from exc
        raise UpdateError("Máy chủ trả về lỗi %s." % exc.code) from exc
    except urllib.error.URLError as exc:
        raise UpdateError("Không kết nối được: %s" % exc.reason) from exc
    except json.JSONDecodeError as exc:
        raise UpdateError("Thông tin phiên bản không hợp lệ.") from exc

    if not isinstance(payload, dict):
        raise UpdateError("Thông tin phiên bản không hợp lệ.")
    version = str(payload.get("version") or "").strip()
    download_url = str(payload.get("url") or "").strip()
    if not version or not download_url:
        raise UpdateError("Thông tin phiên bản thiếu 'version' hoặc 'url'.")

    return Release(
        version=version,
        url=download_url,
        sha256=str(payload.get("sha256") or "").strip().lower(),
        size=int(payload.get("size") or 0),
        published=str(payload.get("published") or ""),
        notes=str(payload.get("notes") or ""),
    )


def check(current_version: str, url: Optional[str] = None) -> Optional[Release]:
    """The published release if it is newer than ``current_version``."""
    release = fetch_manifest(url)
    if is_newer(release.version, current_version):
        logger.info("Update available: %s (running %s)", release.version, current_version)
        return release
    logger.info("Already up to date (%s)", current_version)
    return None


# ── downloading ─────────────────────────────────────────────────────────────

Progress = Optional[Callable[[int, int], None]]
Cancelled = Optional[Callable[[], bool]]


def download(release: Release, target: Path, progress: Progress = None,
             cancelled: Cancelled = None) -> Path:
    """Fetch the release to ``target``, verifying its hash. Returns the path.

    A partial file is removed rather than left to be mistaken for a good one.
    """
    digest = hashlib.sha256()
    received = 0
    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        with _open(release.url) as response:
            total = release.size or int(response.headers.get("Content-Length") or 0)
            with open(target, "wb") as handle:
                while True:
                    if cancelled is not None and cancelled():
                        raise UpdateError("Đã huỷ tải.")
                    block = response.read(CHUNK)
                    if not block:
                        break
                    handle.write(block)
                    digest.update(block)
                    received += len(block)
                    if progress is not None:
                        progress(received, total)
    except UpdateError:
        target.unlink(missing_ok=True)
        raise
    except urllib.error.HTTPError as exc:
        target.unlink(missing_ok=True)
        raise UpdateError("Tải thất bại, máy chủ trả về %s." % exc.code) from exc
    except (urllib.error.URLError, OSError) as exc:
        target.unlink(missing_ok=True)
        raise UpdateError("Tải thất bại: %s" % exc) from exc

    if release.sha256:
        actual = digest.hexdigest()
        if actual != release.sha256:
            target.unlink(missing_ok=True)
            raise UpdateError(
                "File tải về không khớp mã kiểm tra — đã bỏ. Thử lại sau."
            )
    else:
        logger.warning("Manifest carries no sha256; the download was not verified")

    logger.info("Downloaded %s (%d bytes) to %s", release.version, received, target)
    return target


def staged_path() -> Path:
    """Where the downloaded .zip waits, beside the running .exe."""
    return Path(sys.executable).with_name(STAGED_NAME)


# ── swapping ────────────────────────────────────────────────────────────────

# PowerShell rather than a .bat: cmd's batch parser mangles non-ASCII paths,
# and this app is routinely installed under folders like 陰陽師Onmyoji.
#
# What the app owns and what the user owns share one folder:
#
#     Onmyoji Tool\
#         Onmyoji Tool.exe     replaced
#         _internal\           replaced
#         logs\  cache\  .env  wiki\      left alone
#
# So this does not wipe the folder and unpack over it. It copies in only the
# entries the .zip actually carries, and every one it is about to overwrite is
# moved into a backup folder first. If anything fails halfway — a locked file,
# a full disk, a truncated archive — the backup goes back and the old build is
# started again. Replacing a directory has far more ways to fail partway than
# moving a single file did, and a half-replaced app is one that never opens.
_SWAP_SCRIPT = """\
$ErrorActionPreference = 'Stop'
$target = {target}
$appdir = {appdir}
$zip    = {staged}
$owner  = {pid}

for ($i = 0; $i -lt 150; $i++) {{
    if (-not (Get-Process -Id $owner -ErrorAction SilentlyContinue)) {{ break }}
    Start-Sleep -Milliseconds 400
}}

$stage  = Join-Path $appdir '.update-stage'
$backup = Join-Path $appdir '.update-backup'

try {{
    foreach ($dir in @($stage, $backup)) {{
        if (Test-Path -LiteralPath $dir) {{
            Remove-Item -LiteralPath $dir -Recurse -Force
        }}
    }}
    Expand-Archive -LiteralPath $zip -DestinationPath $stage -Force

    # The archive carries one top folder ("Onmyoji Tool\\"); take what is inside
    # it. Tolerate an archive packed without that wrapper, too.
    $payload = $stage
    $top = @(Get-ChildItem -LiteralPath $stage)
    if ($top.Count -eq 1 -and $top[0].PSIsContainer) {{ $payload = $top[0].FullName }}

    $items = @(Get-ChildItem -LiteralPath $payload)
    if ($items.Count -eq 0) {{ throw 'Ban tai ve rong.' }}

    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    foreach ($item in $items) {{
        $dest = Join-Path $appdir $item.Name
        if (Test-Path -LiteralPath $dest) {{
            Move-Item -LiteralPath $dest -Destination $backup -Force
        }}
    }}
    foreach ($item in $items) {{
        Move-Item -LiteralPath $item.FullName -Destination $appdir -Force
    }}

    Remove-Item -LiteralPath $backup -Recurse -Force
    Remove-Item -LiteralPath $stage -Recurse -Force
    Remove-Item -LiteralPath $zip -Force
    Start-Process -FilePath $target
}} catch {{
    # Unconditional: the backup folder is created before anything is moved into
    # it, so failing on the very first entry still leaves an empty one behind.
    if (Test-Path -LiteralPath $backup) {{
        foreach ($item in @(Get-ChildItem -LiteralPath $backup)) {{
            $dest = Join-Path $appdir $item.Name
            if (Test-Path -LiteralPath $dest) {{
                Remove-Item -LiteralPath $dest -Recurse -Force
            }}
            Move-Item -LiteralPath $item.FullName -Destination $appdir -Force
        }}
        Remove-Item -LiteralPath $backup -Recurse -Force
    }}
    if (Test-Path -LiteralPath $stage) {{
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    }}
    # Put the user back in a working app rather than nothing at all. The .zip is
    # left where it is so the attempt can be retried.
    if (Test-Path -LiteralPath $target) {{ Start-Process -FilePath $target }}
    exit 1
}}
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
"""


def _quote(value: Path) -> str:
    """PowerShell single-quoted literal."""
    return "'%s'" % str(value).replace("'", "''")


def write_swap_script(target: Path, staged: Path, pid: int,
                      directory: Optional[Path] = None) -> Path:
    """Write the helper that waits for us to exit, then swaps the build in."""
    folder = directory or Path(tempfile.gettempdir())
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "onmyoji-tool-update.ps1"
    script.write_text(
        _SWAP_SCRIPT.format(
            target=_quote(target),
            appdir=_quote(target.parent),
            staged=_quote(staged),
            pid=pid,
        ),
        encoding="utf-8-sig",  # PowerShell wants the BOM to read UTF-8 reliably
    )
    return script


def apply_and_restart(staged: Path) -> None:
    """Hand over to the swap helper. The caller must quit straight after."""
    if not staged.is_file():
        raise UpdateError("Không tìm thấy bản đã tải.")
    target = Path(sys.executable)
    script = write_swap_script(target, staged, os.getpid())
    logger.info("Handing over to %s to replace %s", script, target)
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-WindowStyle", "Hidden",
            "-File", str(script),
        ],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
