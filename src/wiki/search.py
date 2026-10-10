"""Diacritic-insensitive matching for Vietnamese.

Typing "ibaraki dong tu" has to find "Ibaraki Đồng Tử". Unicode NFD splits a
letter from its accents so the combining marks can be dropped, but Đ/đ is a
letter in its own right — it has no decomposition — so it is mapped explicitly.

This mirrors what the Flutter app does with the `diacritic` package and what
Postgres does in the generated ``*_unaccent`` columns, so local search and
server-side search agree.
"""
from __future__ import annotations

import re
import unicodedata

_COMBINING = re.compile(r"[̀-ͯ]")
_SPECIAL = str.maketrans({"đ": "d", "Đ": "D", "ð": "d", "Ð": "D"})
_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lowercase, strip accents, collapse whitespace."""
    if not text:
        return ""
    folded = text.translate(_SPECIAL)
    decomposed = unicodedata.normalize("NFD", folded)
    return _WHITESPACE.sub(" ", _COMBINING.sub("", decomposed)).strip().lower()


def matches(query: str, haystack: str) -> bool:
    """True when every whitespace-separated term appears in ``haystack``.

    Terms are matched independently so word order does not matter — "dong tu
    ibaraki" finds the same record as "ibaraki dong tu".
    """
    normalized_query = normalize(query)
    if not normalized_query:
        return True
    normalized_hay = normalize(haystack)
    return all(term in normalized_hay for term in normalized_query.split(" "))
