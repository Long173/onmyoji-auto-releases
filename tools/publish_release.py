"""Prepare — and optionally publish — a release on GitHub Releases.

    python tools/publish_release.py 2.2 --notes "Sửa nhận diện hết vé"
    python tools/publish_release.py 2.2 --notes "..." --upload

Keep `--notes` short: a handful of lines saying what somebody gets, not how it
was built. The notes drifted from 157 characters at 3.6 to 1936 at 3.8, and the
owner asked for them back: "người dùng ko cần biết chi tiết". The reasoning
belongs in CHANGELOG.md, which is where whoever maintains this looks.

Zips `dist/Onmyoji Tool/`, hashes the archive, and writes into `dist/release/`:

    OnmyojiTool-3.1.zip     the build to publish
    latest-v2.json          the manifest builds from 3.1 poll
    latest.json             frozen at 3.0, so pre-3.1 installs stay quiet

With `--upload` all three are pushed to the GitHub repository named in
`updater.DEFAULT_MANIFEST_URL`, as one release tagged `v<version>`, and
`CHANGELOG.md` is written to that repository's root. That needs a token with
write access to the repository's contents, as `GITHUB_TOKEN` in `.env` or the
environment. Without it, create the release by hand on GitHub and attach the
three files from `dist/release/`.

Order matters: the .zip is uploaded first and the manifest is written from the
URL GitHub gives back, so the manifest can never point at a file that is not
there yet — and never at a guessed name (GitHub rewrites spaces in asset names).

The version here must match `theme.APP_VERSION` in the build you are shipping,
or the app will keep offering an update it already has.
"""
from __future__ import annotations

import argparse
import base64
import re
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import date
from pathlib import Path
from typing import Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "decompiled" / "source"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

BUILD = ROOT / "dist" / "Onmyoji Tool"      # one-dir: a folder, not a file
OUTPUT = ROOT / "dist" / "release"
CHANGELOG = ROOT / "CHANGELOG.md"
CHUNK = 1024 * 1024
API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
ZIP_TYPE = "application/zip"

# GitHub turns spaces in an asset name into dots, so ship a name that survives
# the round trip unchanged.
ASSET_STEM = "OnmyojiTool"

# ── the frozen manifest for builds up to 3.0 ────────────────────────────────
#
# Those builds are one-file, read `latest.json`, and move whatever it points at
# straight over their own .exe. Hand them the new .zip and they rename it to
# .exe and never start again. They are already out in the world.
#
# So `latest.json` is republished unchanged with every release, permanently
# describing 3.0 — the last one-file build. An old install reads it, sees
# nothing newer than what it is running, and stays quiet. Someone still on 2.x
# is offered 3.0 and gets a real one-file .exe, which works.
#
# The hashes below are the real, published 3.0 asset: fetched back from GitHub
# and verified byte for byte, not copied from a build log.
LEGACY_MANIFEST_NAME = "latest.json"
LEGACY_VERSION = "3.0"
LEGACY_ASSET = "OnmyojiTool-3.0.exe"
LEGACY_SHA256 = "b98c209a99f5bf0519424fe77bc41e7e6f4f8e1c12c49908b2f0eac2ac5fd80b"
LEGACY_SIZE = 107083362
LEGACY_PUBLISHED = "2026-08-14"
LEGACY_NOTES = (
    "Trung tâm tác vụ mới, wiki trong cùng cửa sổ, sửa lỗi tự dừng khi còn vé"
)


class PublishError(RuntimeError):
    """Something went wrong that the operator needs to read and act on."""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


# ── where to publish ────────────────────────────────────────────────────────


def github_target(manifest_url: str) -> Optional[Tuple[str, str]]:
    """``(owner, repo)`` from a GitHub Releases manifest URL, else ``None``.

    Recognises the ``…/releases/latest/download/latest.json`` form the app
    polls, which is what makes the URL in ``updater`` the single place the
    repository is named.
    """
    parsed = urllib.parse.urlparse(manifest_url)
    if parsed.netloc.lower() not in ("github.com", "www.github.com"):
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 3 or parts[2] != "releases":
        return None
    return parts[0], parts[1]


def token() -> str:
    """The publish token, from the environment or a .env beside the project."""
    import wiki.config as wiki_config

    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    for path in wiki_config.ENV_FILES:
        values = wiki_config.read_env_file(path)
        for name in ("GITHUB_TOKEN", "GH_TOKEN"):
            value = values.get(name, "").strip()
            if value:
                return value
    return ""


# ── the GitHub API ──────────────────────────────────────────────────────────


def call(method: str, url: str, key: str, payload=None, content_type="application/json"):
    """One authenticated request. Returns the decoded body, or ``None``."""
    body = payload
    if payload is not None and not isinstance(payload, (bytes, bytearray)):
        body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": "Bearer " + key,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "OnmyojiTool-Publisher",
            **({"Content-Type": content_type} if body is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=900) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode("utf-8", "replace")
        raise PublishError(explain(exc.code, detail, url)) from exc
    except urllib.error.URLError as exc:
        raise PublishError("Khong ket noi duoc GitHub: %s" % exc.reason) from exc


def explain(code: int, detail: str, url: str) -> str:
    """Turn the common failures into something actionable."""
    if code == 401:
        return "GitHub tu choi token (401). Token sai hoac da het han."
    if code == 403:
        return (
            "GitHub tu choi (403): %s\n"
            "Token can quyen ghi Contents cua repo nay." % detail
        )
    if code == 404:
        return (
            "Khong thay repo (404): %s\n"
            "Kiem tra ten repo trong updater.DEFAULT_MANIFEST_URL, va token co\n"
            "nhin thay repo do khong." % url
        )
    if code == 422:
        return "GitHub tu choi du lieu (422): %s" % detail
    return "GitHub tra ve %s: %s" % (code, detail)


def repository(owner: str, repo: str, key: str) -> dict:
    return call("GET", "%s/repos/%s/%s" % (API, owner, repo), key) or {}


def ensure_release(owner: str, repo: str, tag: str, notes: str, key: str) -> dict:
    """The release for ``tag``, created if it is not there yet."""
    base = "%s/repos/%s/%s/releases" % (API, owner, repo)
    try:
        existing = call("GET", "%s/tags/%s" % (base, tag), key)
    except PublishError:
        existing = None
    if existing:
        print("  dung lai release da co: %s" % tag)
        return existing
    print("  tao release moi: %s" % tag)
    return call("POST", base, key, {
        "tag_name": tag,
        "name": tag,
        "body": notes,
        "draft": False,        # a draft is not served by /releases/latest/
        "prerelease": False,
        "make_latest": "true",
    })


def replace_asset(owner: str, repo: str, release: dict, name: str,
                  payload: bytes, content_type: str, key: str) -> str:
    """Attach one asset, replacing any of the same name. Returns its URL."""
    for asset in release.get("assets") or []:
        if asset.get("name") == name:
            print("  thay the asset cu: %s" % name)
            call("DELETE", "%s/repos/%s/%s/releases/assets/%s"
                 % (API, owner, repo, asset["id"]), key)

    url = "%s/repos/%s/%s/releases/%s/assets?name=%s" % (
        UPLOADS, owner, repo, release["id"], urllib.parse.quote(name)
    )
    print("  dang tai len %-22s %6.1f MB ..." % (name, len(payload) / 1024 / 1024))
    result = call("POST", url, key, payload, content_type) or {}
    download = result.get("browser_download_url", "")
    if not download:
        raise PublishError("GitHub khong tra ve dia chi tai cho %s." % name)
    return download


# ── the local artefacts ─────────────────────────────────────────────────────


# Exactly what PyInstaller's COLLECT produces, and exactly what the updater
# replaces. Anything else in dist\Onmyoji Tool\ got there by *running* the build
# — logs\, cache\, and, worst of all, a .env. Zipping the folder wholesale
# published the developer's log over every user's, and would have published
# their Supabase keys the first time they tested a build with a .env beside it.
SHIPPED = ("Onmyoji Tool.exe", "_internal")


def stage(version: str) -> Tuple[Path, str, int]:
    """Zip the build under its release name. Returns (path, sha256, size).

    The archive keeps a single top-level ``Onmyoji Tool/`` folder, so someone
    installing by hand can extract it anywhere without strewing files about.
    The updater looks through that wrapper.
    """
    OUTPUT.mkdir(parents=True, exist_ok=True)
    named = OUTPUT / ("%s-%s.zip" % (ASSET_STEM, version))
    if named.exists():
        named.unlink()

    sources = []
    for entry in SHIPPED:
        item = BUILD / entry
        if not item.exists():
            raise PublishError("Build thieu %s — chay lai pyinstaller." % entry)
        sources.extend(sorted(item.rglob("*")) if item.is_dir() else [item])

    skipped = sorted(
        p.name for p in BUILD.iterdir() if p.name not in SHIPPED
    )
    if skipped:
        print("  bo qua (khong phai thu ship): %s" % ", ".join(skipped))

    print("  dang nen %d file ..." % sum(1 for p in sources if p.is_file()))
    with zipfile.ZipFile(named, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for item in sources:
            if item.is_file():
                archive.write(item, Path(BUILD.name) / item.relative_to(BUILD))
        # The licence, lifted to the top of the archive.
        #
        # PyInstaller can only put a data file inside `_internal`, where nobody
        # unzipping this will ever look. The terms are meant to be found by the
        # person holding the copy, so the same file is written again beside the
        # .exe. Both copies are the same bytes; the buried one is what the app
        # itself would read if it ever needed to.
        licence = ROOT / "LICENSE"
        if licence.is_file():
            archive.write(licence, Path(BUILD.name) / "LICENSE")
        else:
            print("  canh bao: khong co LICENSE de kem theo")
    return named, sha256_of(named), named.stat().st_size


def write_manifest(version: str, url: str, digest: str, size: int, notes: str) -> Path:
    manifest = {
        "version": version,
        "url": url,
        "sha256": digest,
        "size": size,
        "published": date.today().isoformat(),
        "notes": notes,
    }
    path = OUTPUT / updater_module().MANIFEST_NAME
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def write_legacy_manifest(owner: str, repo: str) -> Path:
    """The unchanging manifest that keeps pre-3.1 installs quiet. See the top."""
    manifest = {
        "version": LEGACY_VERSION,
        "url": "https://github.com/%s/%s/releases/download/v%s/%s"
               % (owner, repo, LEGACY_VERSION, LEGACY_ASSET),
        "sha256": LEGACY_SHA256,
        "size": LEGACY_SIZE,
        "published": LEGACY_PUBLISHED,
        "notes": LEGACY_NOTES,
    }
    path = OUTPUT / LEGACY_MANIFEST_NAME
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def updater_module():
    import updater

    return updater


def notes_from_changelog(version: str, path: Optional[Path] = None) -> str:
    """The changelog's own section for ``version``, without its heading.

    The notes used to be typed on the command line. That is one place for them
    to be wrong and another for them to be mangled: passing Vietnamese through
    argv under Git Bash on Windows hands Python the bytes read back through the
    ANSI codepage, so "Cửa sổ" reaches the release as "Cá»­a sá»•". Reading the
    file the text already lives in has no such step — and it stops the release
    notes and the changelog from saying different things, which is the failure
    that actually costs something.

    Exits rather than returning empty. A release published with no notes is one
    the in-app banner has nothing to show for, and that is worse than a build
    that stops and asks for a changelog entry.
    """
    path = path or CHANGELOG
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        sys.exit("Khong doc duoc %s: %s" % (path, exc))

    # The heading of the section wanted, up to the heading of the next one —
    # any "## ", not this version's successor, because there is no way to know
    # what that is called.
    match = re.search(
        r"^##\s+%s\s*$(.*?)(?=^##\s|\Z)" % re.escape(version),
        text, re.MULTILINE | re.DOTALL,
    )
    if match is None:
        sys.exit("CHANGELOG.md chua co muc cho %s — viet no truoc khi phat hanh."
                 % version)
    # The horizontal rule belongs to the layout of the file, not to the notes.
    body = re.sub(r"^-{3,}\s*$", "", match.group(1), flags=re.MULTILINE)
    notes = body.strip()
    if not notes:
        sys.exit("Muc %s trong CHANGELOG.md dang rong." % version)
    return notes


def changelog_covers(version: str) -> bool:
    """Whether CHANGELOG.md has an entry for the version being released.

    `push_changelog` uploads the local file as it stands and reports that it
    did, which is true and was still misleading: the file's newest entry sat at
    3.6 while 3.7, 3.8, 3.9 and 3.10 went out, so four releases printed
    "CHANGELOG.md -> <url>" while pushing a file that mentioned none of them.

    The heading is matched whole. "## 3.1" must not satisfy a release of 3.10.
    """
    if not CHANGELOG.is_file():
        return False
    headings = re.findall(r"(?m)^##\s+(\S+)\s*$",
                          CHANGELOG.read_text(encoding="utf-8"))
    return version in headings


def push_changelog(owner: str, repo: str, key: str) -> bool:
    """Put CHANGELOG.md at the root of the releases repo. Returns True if sent.

    A release page only shows one version's notes. The changelog is the whole
    history in one place, so someone can see what changed across several
    versions without clicking through every tag.
    """
    if not CHANGELOG.is_file():
        print("  bo qua CHANGELOG.md — khong tim thay")
        return False

    url = "%s/repos/%s/%s/contents/CHANGELOG.md" % (API, owner, repo)
    try:
        existing = call("GET", url, key) or {}
    except PublishError:
        existing = {}

    body = CHANGELOG.read_bytes()
    payload = {
        "message": "docs: cap nhat changelog",
        "content": base64.b64encode(body).decode("ascii"),
    }
    # Without the blob sha GitHub refuses to overwrite an existing file.
    if existing.get("sha"):
        payload["sha"] = existing["sha"]

    call("PUT", url, key, payload)
    print("  CHANGELOG.md -> https://github.com/%s/%s/blob/main/CHANGELOG.md"
          % (owner, repo))
    return True


def warn_if_changelog_is_behind(version: str) -> None:
    """Say plainly that the changelog does not mention this release."""
    if changelog_covers(version):
        return
    print("  CANH BAO: CHANGELOG.md khong co muc '%s'." % version)
    print("            File van duoc day len, nhung no khong noi gi ve ban nay.")


def release_body(body: str, notes: str) -> str:
    """The changelog for the release page, with the contact details appended.

    It goes on every release rather than only the newest, because a release page
    is a permanent link — someone landing on an old tag should still be able to
    tell who to ask. ``contact.as_markdown`` is empty when nothing is filled in,
    and then this is just the changelog.
    """
    import contact

    text = (body or notes).rstrip()
    section = contact.as_markdown()
    if not section:
        return text
    return (text + "\n\n---\n\n" + section) if text else section


def guessed_url(owner: str, repo: str, tag: str, name: str) -> str:
    """Where the asset will land — used only for the dry run, never to publish."""
    return "https://github.com/%s/%s/releases/download/%s/%s" % (
        owner, repo, urllib.parse.quote(tag), urllib.parse.quote(name)
    )


# ── driver ──────────────────────────────────────────────────────────────────


def publish(owner: str, repo: str, version: str, named: Path, digest: str,
            size: int, notes: str, key: str, body: str = "") -> None:
    """Create the release, attach the .exe, then the manifest that names it.

    ``notes`` is the one-line headline the in-app banner shows; ``body`` is the
    full changelog on the release page. They are separate because the banner
    truncates at 80 characters, and a changelog worth reading is longer.
    """
    info = repository(owner, repo, key)
    if info.get("private"):
        raise PublishError(
            "Repo %s/%s dang o che do private.\n"
            "File trong release cua repo private can dang nhap moi tai duoc,\n"
            "nen app cua ban be se khong tai duoc. Doi repo sang public\n"
            "(Settings > General > Change visibility)." % (owner, repo)
        )

    tag = "v%s" % version
    release = ensure_release(owner, repo, tag, release_body(body, notes), key)

    download = replace_asset(owner, repo, release, named.name,
                             named.read_bytes(), ZIP_TYPE, key)
    manifest = write_manifest(version, download, digest, size, notes)
    replace_asset(owner, repo, release, manifest.name,
                  manifest.read_bytes(), "application/json", key)

    # Republished with every release so a pre-3.1 install keeps reading a
    # manifest that offers it nothing, instead of a .zip it would rename to
    # .exe and die on. See LEGACY_MANIFEST_NAME.
    legacy = write_legacy_manifest(owner, repo)
    replace_asset(owner, repo, release, legacy.name,
                  legacy.read_bytes(), "application/json", key)

    push_changelog(owner, repo, key)
    warn_if_changelog_is_behind(version)

    print("\nXong. App se thay ban %s o lan khoi dong sau." % version)
    print("  release: https://github.com/%s/%s/releases/tag/%s" % (owner, repo, tag))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Publish an update to GitHub Releases")
    parser.add_argument("version", help="e.g. 2.2 — must match theme.APP_VERSION")
    parser.add_argument(
        "--notes", default="",
        help="one line for the in-app banner — it shows the first 80 characters",
    )
    parser.add_argument(
        "--from-changelog", action="store_true",
        help="take the notes from CHANGELOG.md's section for this version",
    )
    parser.add_argument(
        "--body", default="",
        help="the full changelog for the GitHub release page; defaults to --notes",
    )
    parser.add_argument("--upload", action="store_true",
                        help="create the release on GitHub (needs GITHUB_TOKEN)")
    args = parser.parse_args(argv)
    if args.from_changelog:
        if args.notes:
            print("Chi duoc chon mot: --notes hoac --from-changelog.")
            return 1
        args.notes = notes_from_changelog(args.version)

    import theme
    import updater

    if not BUILD.is_dir():
        print("Chua co thu muc %s — chay pyinstaller truoc." % BUILD)
        return 1
    if not (BUILD / "Onmyoji Tool.exe").is_file():
        print("%s khong co Onmyoji Tool.exe — build hong?" % BUILD)
        return 1

    if args.version != theme.APP_VERSION:
        message = ("theme.APP_VERSION la %r nhung ban phat hanh %r. "
                   "App se moi cap nhat lai chinh no."
                   % (theme.APP_VERSION, args.version))
        if args.from_changelog:
            # Nothing watches an automated run closely enough for a
            # warning to be read, and a mismatch ships an update that
            # re-offers itself for ever. Stop instead.
            print("Loi: " + message)
            return 1
        print("Canh bao: " + message)

    target = github_target(updater.DEFAULT_MANIFEST_URL)
    if target is None:
        print("Chua biet phat hanh len repo nao.\n"
              "  updater.DEFAULT_MANIFEST_URL = %r\n"
              "Dien ten tai khoan vao decompiled/source/updater.py:\n"
              "  GITHUB_OWNER = \"ten-tai-khoan\"\n"
              "  GITHUB_REPO  = %r\n"
              "roi build lai truoc khi phat hanh."
              % (updater.DEFAULT_MANIFEST_URL, updater.GITHUB_REPO))
        return 1
    owner, repo = target

    named, digest, size = stage(args.version)
    print("%-24s %8.1f MB" % (named.name, size / 1024 / 1024))
    print("%-24s sha256 %s" % ("", digest))

    if not args.upload:
        manifest = write_manifest(
            args.version,
            guessed_url(owner, repo, "v" + args.version, named.name),
            digest, size, args.notes,
        )
        legacy = write_legacy_manifest(owner, repo)
        for path in (manifest, legacy):
            print("%-24s -> %s" % (path.name, path))
        print("\nTao release 'v%s' tai https://github.com/%s/%s/releases/new\n"
              "roi dinh kem ca 3 file trong dist/release/.\n"
              "Hoac chay lai voi --upload (can GITHUB_TOKEN)."
              % (args.version, owner, repo))
        return 0

    key = token()
    if not key:
        print("\nKhong tim thay GITHUB_TOKEN (trong .env hoac bien moi truong).\n"
              "Tao o https://github.com/settings/tokens ,\n"
              "quyen can: Contents (read and write) cho repo %s/%s." % (owner, repo))
        return 1

    try:
        publish(owner, repo, args.version, named, digest, size, args.notes, key,
                args.body)
    except PublishError as exc:
        print("\n%s" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
