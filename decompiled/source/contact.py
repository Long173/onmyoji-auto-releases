"""Who to reach about this app.

One place, because the same details go two ways: the Cài đặt chung dialog inside
the app, and the README of the public releases repository that
``tools/publish_release.py`` writes.

Left empty, both surfaces simply omit the section rather than showing blank
rows — so an unfilled build never advertises a contact that does not exist.

Anything here is **public**: the releases repo is a public GitHub page, and the
.exe goes to whoever it is handed to. Put in what you would put on a poster.
"""
from __future__ import annotations

from typing import Tuple

# (label, value). Order is the order shown.
CONTACTS: Tuple[Tuple[str, str], ...] = (
    ("Tên ingame", "A y u"),
    ("Code", "3055324"),
)

# One line above the list, shown only when there is a list.
INTRO = "Tìm mình trong game để hỏi hoặc góp ý:"

# The licence, and the sentence that says out loud what it is for.
#
# Kept here for the same reason as the contacts: the app and the releases page
# want the same words. But do not mistake the copy inside the app for a defence.
# It compiles into the .exe along with everything else, and anybody repackaging
# this to sell will delete it first — the module `contact` was pulled straight
# out of a shipped build during development, contact details and all, in three
# lines and without a decompiler. The copy that matters is the one on the public
# release page, where a reseller cannot reach it.
LICENCE_NAME = "PolyForm Noncommercial 1.0.0"
FREE_NOTICE = (
    "Tool này miễn phí. Nếu bạn phải trả tiền cho ai để có nó thì bạn đã bị lừa."
)
LICENCE_NOTE = (
    "Được dùng và chia sẻ lại thoải mái, nhưng không được dùng cho mục đích "
    "thương mại — không bán, không cho thuê, không gói kèm dịch vụ có thu phí."
)


def licence_markdown(repo_url: str) -> str:
    """The licence section for the releases README."""
    lines = [
        "## Giấy phép",
        "",
        "**%s**" % FREE_NOTICE,
        "",
        "Bản chính thức luôn miễn phí tại <%s>." % repo_url,
        "",
        LICENCE_NOTE,
        "",
        "Giấy phép đầy đủ: [%s](LICENSE)." % LICENCE_NAME,
    ]
    return "\n".join(lines) + "\n"


def has_any() -> bool:
    return bool([pair for pair in CONTACTS if pair[1].strip()])


def rows() -> Tuple[Tuple[str, str], ...]:
    """The entries worth showing — blanks are dropped rather than rendered."""
    return tuple((label, value.strip()) for label, value in CONTACTS if value.strip())


def as_markdown() -> str:
    """The same details as a section for the releases README."""
    if not has_any():
        return ""
    lines = ["## Liên hệ", "", INTRO, ""]
    lines += ["- **%s:** %s" % (label, value) for label, value in rows()]
    return "\n".join(lines) + "\n"
