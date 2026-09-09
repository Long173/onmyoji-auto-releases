"""Publishing a release to GitHub.

This is the other half of the update path, and its mistakes are the expensive
kind: a manifest that names a file nobody uploaded, or one that names the wrong
file, is shipped to every machine that updates. So the invariants under test
are ordering (the .exe lands before the manifest that points at it) and
provenance (the URL comes from GitHub's own answer, never from a guess).
"""
from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import publish_release as publisher  # noqa: E402

MANIFEST = "https://github.com/someone/onmyoji-auto-releases/releases/latest/download/latest.json"

# What the app actually ships and polls from 3.1 on. `latest.json` still goes
# out with every release, but frozen at 3.0 for the one-file builds that are
# already installed — see LEGACY_MANIFEST_NAME in the publisher.
MANIFEST_ASSET = "OnmyojiTool-2.2.zip"
LIVE_MANIFEST = "latest-v2.json"


# ── where to publish ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url, expected",
    [
        (MANIFEST, ("someone", "onmyoji-auto-releases")),
        ("https://github.com/a-b/c.d/releases/latest/download/latest.json", ("a-b", "c.d")),
        ("https://www.github.com/o/r/releases/download/v2.2/latest.json", ("o", "r")),
        # not GitHub Releases
        ("https://example.test/latest.json", None),
        ("https://github.com/o/r/raw/main/latest.json", None),
        ("https://github.com/o", None),
        ("", None),
    ],
)
def test_the_repository_is_read_off_the_manifest_url(url, expected):
    """The URL in `updater` is the single place the repository is named."""
    assert publisher.github_target(url) == expected


def test_the_token_prefers_the_environment(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_from_env")
    assert publisher.token() == "ghp_from_env"


def test_the_token_falls_back_to_a_dotenv(monkeypatch, tmp_path):
    import wiki.config as wiki_config

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    env = tmp_path / ".env"
    env.write_text("GITHUB_TOKEN=ghp_from_file\n", encoding="utf-8")
    monkeypatch.setattr(wiki_config, "ENV_FILES", (env,))

    assert publisher.token() == "ghp_from_file"


def test_no_token_anywhere_reads_as_empty(monkeypatch, tmp_path):
    import wiki.config as wiki_config

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(wiki_config, "ENV_FILES", (tmp_path / "absent.env",))

    assert publisher.token() == ""


# ── the publish sequence ────────────────────────────────────────────────────


class FakeGitHub:
    """Records every call, and answers the way the real API does."""

    def __init__(self, private=False, existing_assets=()):
        self.calls = []
        self.private = private
        self.release = {"id": 77, "assets": list(existing_assets)}
        self.uploaded = {}

    def __call__(self, method, url, key, payload=None, content_type="application/json"):
        self.calls.append((method, url, payload))
        if url.endswith("/repos/o/r"):
            return {"private": self.private}
        if "/releases/tags/" in url:
            return self.release
        if method == "POST" and url.endswith("/releases"):
            return self.release
        if "/assets?name=" in url:
            name = url.split("name=", 1)[1]
            self.uploaded[name] = payload
            return {
                "browser_download_url":
                    "https://github.com/o/r/releases/download/v2.2/%s" % name
            }
        return None


@pytest.fixture
def staged(tmp_path, monkeypatch):
    """A stand-in build, staged where the publisher expects to find one."""
    monkeypatch.setattr(publisher, "OUTPUT", tmp_path)
    archive = tmp_path / "OnmyojiTool-2.2.zip"
    archive.write_bytes(b"PK pretend build")
    return archive


def run_publish(fake, staged, monkeypatch, **overrides):
    monkeypatch.setattr(publisher, "call", fake)
    fields = {
        "owner": "o", "repo": "r", "version": "2.2", "named": staged,
        "digest": hashlib.sha256(staged.read_bytes()).hexdigest(),
        "size": staged.stat().st_size, "notes": "Sửa nhận diện hết vé",
        "key": "ghp_x",
    }
    fields.update(overrides)
    publisher.publish(**fields)


def test_the_exe_is_uploaded_before_the_manifest_that_names_it(staged, monkeypatch):
    """Otherwise the manifest briefly advertises a download that 404s."""
    fake = FakeGitHub()

    run_publish(fake, staged, monkeypatch)

    uploads = [url for method, url, _ in fake.calls if "/assets?name=" in url]
    assert len(uploads) == 3
    assert MANIFEST_ASSET in uploads[0]
    assert LIVE_MANIFEST in uploads[1]
    assert "latest.json" in uploads[2]


def test_the_manifest_carries_the_url_github_gave_back(staged, monkeypatch):
    """Not a guessed one — GitHub rewrites asset names it does not like."""
    fake = FakeGitHub()

    run_publish(fake, staged, monkeypatch)

    manifest = json.loads(fake.uploaded[LIVE_MANIFEST].decode("utf-8"))
    assert manifest["url"] == (
        "https://github.com/o/r/releases/download/v2.2/OnmyojiTool-2.2.zip"
    )
    assert manifest["version"] == "2.2"
    assert manifest["notes"] == "Sửa nhận diện hết vé"


# ── the frozen manifest that keeps pre-3.1 installs safe ────────────────────


def test_the_legacy_manifest_still_describes_the_last_one_file_build(staged, monkeypatch):
    """A pre-3.1 install renames whatever this points at to .exe and runs it.

    Point it at the .zip and every one of those installs dies on next launch.
    """
    fake = FakeGitHub()

    run_publish(fake, staged, monkeypatch)

    legacy = json.loads(fake.uploaded["latest.json"].decode("utf-8"))
    assert legacy["version"] == publisher.LEGACY_VERSION
    assert legacy["url"].endswith(".exe"), "old builds would rename a .zip to .exe"
    assert legacy["sha256"] == publisher.LEGACY_SHA256
    assert legacy["size"] == publisher.LEGACY_SIZE


def test_the_legacy_manifest_never_advertises_the_version_being_published(
    staged, monkeypatch
):
    """It has to stay frozen, or an old build is offered a package it cannot use."""
    fake = FakeGitHub()

    run_publish(fake, staged, monkeypatch, version="9.9")

    legacy = json.loads(fake.uploaded["latest.json"].decode("utf-8"))
    assert legacy["version"] == "3.0" != "9.9"


def test_the_two_manifests_are_not_the_same_file(staged, monkeypatch):
    fake = FakeGitHub()

    run_publish(fake, staged, monkeypatch)

    assert fake.uploaded["latest.json"] != fake.uploaded[LIVE_MANIFEST]


def test_the_changelog_is_written_to_the_repository_root(staged, monkeypatch, tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## 3.1\n", encoding="utf-8")
    monkeypatch.setattr(publisher, "CHANGELOG", changelog)
    fake = FakeGitHub()

    run_publish(fake, staged, monkeypatch)

    puts = [(url, payload) for method, url, payload in fake.calls if method == "PUT"]
    assert len(puts) == 1
    url, payload = puts[0]
    assert url.endswith("/contents/CHANGELOG.md")
    # Bytes, not text: the file is uploaded verbatim, and comparing decoded
    # text would hide Windows turning \n into \r\n on the way to disk.
    assert base64.b64decode(payload["content"]) == changelog.read_bytes()


def test_a_missing_changelog_does_not_stop_the_release(staged, monkeypatch, tmp_path):
    """The build and manifests matter; the changelog is a nicety."""
    monkeypatch.setattr(publisher, "CHANGELOG", tmp_path / "nope.md")
    fake = FakeGitHub()

    run_publish(fake, staged, monkeypatch)

    assert not [c for c in fake.calls if c[0] == "PUT"]
    assert LIVE_MANIFEST in fake.uploaded


def test_the_manifest_hash_matches_the_file_actually_uploaded(staged, monkeypatch):
    """The app throws away a download whose hash disagrees, so these must agree."""
    fake = FakeGitHub()

    run_publish(fake, staged, monkeypatch)

    manifest = json.loads(fake.uploaded[LIVE_MANIFEST].decode("utf-8"))
    sent = fake.uploaded[MANIFEST_ASSET]
    assert manifest["sha256"] == hashlib.sha256(sent).hexdigest()
    assert manifest["size"] == len(sent)


def test_a_private_repository_is_refused(staged, monkeypatch):
    """Its release assets need a login, so the friend's app could never fetch them."""
    fake = FakeGitHub(private=True)

    with pytest.raises(publisher.PublishError, match="private"):
        run_publish(fake, staged, monkeypatch)

    assert not fake.uploaded, "nothing should have been uploaded"


def test_republishing_replaces_the_old_assets(staged, monkeypatch):
    """A re-run of the same version must not leave two files fighting."""
    fake = FakeGitHub(existing_assets=[
        {"id": 5, "name": MANIFEST_ASSET},
        {"id": 6, "name": "latest.json"},
    ])

    run_publish(fake, staged, monkeypatch)

    deleted = [url for method, url, _ in fake.calls if method == "DELETE"]
    assert any(url.endswith("/assets/5") for url in deleted)
    assert any(url.endswith("/assets/6") for url in deleted)


def test_the_banner_headline_and_the_release_body_are_separate(staged, monkeypatch):
    """The banner truncates at 80 characters; a changelog needs more room."""
    fake = FakeGitHub()
    fake.release = {"id": 77, "assets": []}

    def no_existing_tag(method, url, key, payload=None, content_type="application/json"):
        if "/releases/tags/" in url:
            raise publisher.PublishError("404")
        return FakeGitHub.__call__(fake, method, url, key, payload, content_type)

    run_publish(no_existing_tag, staged, monkeypatch,
                notes="Sửa nhận diện hết vé", body="- dòng một\n- dòng hai")

    created = [payload for method, url, payload in fake.calls
               if method == "POST" and url.endswith("/releases")]
    # startswith, not equality: the contact section is appended after it.
    assert created[0]["body"].startswith("- dòng một\n- dòng hai")
    manifest = json.loads(fake.uploaded[LIVE_MANIFEST].decode("utf-8"))
    assert manifest["notes"] == "Sửa nhận diện hết vé", "the banner got the changelog"


def test_the_release_page_carries_the_contact_details(staged, monkeypatch):
    """Every release page, not only the newest — an old tag is a permanent link."""
    import contact

    fake = FakeGitHub()
    fake.release = {"id": 77, "assets": []}

    def no_existing_tag(method, url, key, payload=None, content_type="application/json"):
        if "/releases/tags/" in url:
            raise publisher.PublishError("404")
        return FakeGitHub.__call__(fake, method, url, key, payload, content_type)

    monkeypatch.setattr(contact, "CONTACTS", (("Tên ingame", "A y u"),))
    run_publish(no_existing_tag, staged, monkeypatch, notes="Sửa lỗi")

    created = [payload for method, url, payload in fake.calls
               if method == "POST" and url.endswith("/releases")]
    assert "A y u" in created[0]["body"]
    # The banner is a one-liner and must stay clean of it.
    manifest = json.loads(fake.uploaded[LIVE_MANIFEST].decode("utf-8"))
    assert manifest["notes"] == "Sửa lỗi"


def test_without_a_body_the_release_page_falls_back_to_the_headline(staged, monkeypatch):
    fake = FakeGitHub()
    fake.release = {"id": 77, "assets": []}

    def no_existing_tag(method, url, key, payload=None, content_type="application/json"):
        if "/releases/tags/" in url:
            raise publisher.PublishError("404")
        return FakeGitHub.__call__(fake, method, url, key, payload, content_type)

    run_publish(no_existing_tag, staged, monkeypatch, notes="Chỉ một dòng")

    created = [payload for method, url, payload in fake.calls
               if method == "POST" and url.endswith("/releases")]
    assert created[0]["body"].startswith("Chỉ một dòng")


def test_the_release_is_not_a_draft(staged, monkeypatch):
    """`/releases/latest/download/` skips drafts, so the app would see nothing."""
    fake = FakeGitHub()
    fake.release = {"id": 77, "assets": []}

    def no_existing_tag(method, url, key, payload=None, content_type="application/json"):
        if "/releases/tags/" in url:
            raise publisher.PublishError("404")
        return FakeGitHub.__call__(fake, method, url, key, payload, content_type)

    run_publish(no_existing_tag, staged, monkeypatch)

    created = [payload for method, url, payload in fake.calls
               if method == "POST" and url.endswith("/releases")]
    assert created and created[0]["draft"] is False
    assert created[0]["tag_name"] == "v2.2"


# ── error messages ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "code, fragment",
    [(401, "token"), (403, "Contents"), (404, "repo"), (422, "422"), (500, "500")],
)
def test_failures_say_what_to_do(code, fragment):
    assert fragment in publisher.explain(code, "detail", "https://api.test/x")


# ── what goes into the archive ──────────────────────────────────────────────


@pytest.fixture
def built(tmp_path, monkeypatch):
    """A build folder that has been *run*, so it carries runtime droppings."""
    build = tmp_path / "Onmyoji Tool"
    (build / "_internal").mkdir(parents=True)
    (build / "Onmyoji Tool.exe").write_bytes(b"MZ build")
    (build / "_internal" / "python312.dll").write_bytes(b"dll")
    # None of the following belongs to anyone but the developer.
    (build / "logs").mkdir()
    (build / "logs" / "onmyoji_auto.log").write_text("nhat ky may build", encoding="utf-8")
    (build / "cache").mkdir()
    (build / "cache" / "wiki.json").write_text("{}", encoding="utf-8")
    (build / ".env").write_text("SUPABASE_ANON_KEY=bi-mat", encoding="utf-8")
    monkeypatch.setattr(publisher, "BUILD", build)
    monkeypatch.setattr(publisher, "OUTPUT", tmp_path / "release")
    return build


def names_in(archive_path):
    import zipfile

    with zipfile.ZipFile(archive_path) as archive:
        return archive.namelist()


def test_the_archive_carries_the_build(built):
    named, digest, size = publisher.stage("3.1")

    names = names_in(named)
    assert "Onmyoji Tool/Onmyoji Tool.exe" in names
    assert "Onmyoji Tool/_internal/python312.dll" in names
    assert size == named.stat().st_size
    assert len(digest) == 64


def test_the_developers_dotenv_is_never_published(built):
    """Zipping the folder wholesale would ship the build machine's secrets."""
    named, _, _ = publisher.stage("3.1")

    assert not [n for n in names_in(named) if ".env" in n]


def test_the_developers_logs_and_cache_are_not_published(built):
    """They would also overwrite the user's own on the next update."""
    named, _, _ = publisher.stage("3.1")

    names = names_in(named)
    assert not [n for n in names if "/logs/" in n]
    assert not [n for n in names if "/cache/" in n]


def test_the_archive_keeps_one_top_level_folder(built):
    """So extracting it by hand does not strew files across the download dir."""
    named, _, _ = publisher.stage("3.1")

    roots = {n.split("/")[0] for n in names_in(named)}
    assert roots == {"Onmyoji Tool"}


def test_a_build_missing_its_internals_is_refused(built):
    import shutil

    shutil.rmtree(built / "_internal")

    with pytest.raises(publisher.PublishError, match="_internal"):
        publisher.stage("3.1")


# ── a changelog that has quietly stopped ────────────────────────────────────
#
# `push_changelog` uploads the local file as it stands, and says so. That is
# truthful and was still misleading: the local file's newest entry was 3.6 while
# 3.7, 3.8, 3.9 and 3.10 were published, so four releases reported "CHANGELOG.md
# -> <url>" while pushing a file that did not mention them.
#
# The push is not the thing to change — uploading whatever is written is exactly
# its job. What was missing is anyone noticing the file had been left behind.


def a_changelog(tmp_path, newest="3.6"):
    path = tmp_path / "CHANGELOG.md"
    path.write_text("# Changelog\n\n## %s\n\nchuyện cũ\n" % newest,
                    encoding="utf-8")
    return path


def test_a_changelog_without_this_version_is_flagged(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(publisher, "CHANGELOG", a_changelog(tmp_path))

    assert publisher.changelog_covers("3.10") is False


def test_a_changelog_with_this_version_is_not_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(publisher, "CHANGELOG",
                        a_changelog(tmp_path, newest="3.10"))

    assert publisher.changelog_covers("3.10") is True


def test_a_version_that_is_a_prefix_of_another_does_not_count(tmp_path, monkeypatch):
    """"## 3.1" must not satisfy a release of 3.10, nor the other way round."""
    monkeypatch.setattr(publisher, "CHANGELOG",
                        a_changelog(tmp_path, newest="3.1"))

    assert publisher.changelog_covers("3.10") is False


def test_no_changelog_at_all_is_not_a_false_reassurance(tmp_path, monkeypatch):
    monkeypatch.setattr(publisher, "CHANGELOG", tmp_path / "nope.md")

    assert publisher.changelog_covers("3.10") is False
