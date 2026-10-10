"""The VirusTotal section CI adds to each release.

3.21 was scanned by a player, came back 3/71, and was posted as "Virus nhé".
Every release now carries its own scan, and an explanation for each engine
that flags it, written before anyone has to ask.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import virustotal_report as vt  # noqa: E402

SHA = "f150404d895509e0ea9fc47e6df04159bed4fa81ab843e6f4ca8d621d957e44b"


def report(flagged=None, clean=68):
    """The parts of a VirusTotal /files/{sha} answer the script reads."""
    results = {"Engine%d" % i: {"category": "undetected", "result": None}
               for i in range(clean)}
    for engine, label in (flagged or {}).items():
        results[engine] = {"category": "malicious", "result": label}
    malicious = len(flagged or {})
    return {"data": {"attributes": {
        "last_analysis_stats": {"malicious": malicious, "suspicious": 0,
                                "undetected": clean, "harmless": 0},
        "last_analysis_results": results,
    }}}


# The three detections 3.21 actually drew.
SEEN_ON_3_21 = {
    "SecureAge": "Malicious",
    "Skyhigh (SWG)": "BehavesLike.Win64.Backdoor.rc",
    "Zillya": "Trojan.Blank.Script.2228",
}


def test_a_clean_scan_is_one_line_with_the_link():
    text = vt.section(report(), SHA)
    assert "0/68" in text
    assert "https://www.virustotal.com/gui/file/" + SHA in text
    assert "| " not in text, "a clean scan needs no table"


def test_each_flagging_engine_is_listed_with_its_label():
    text = vt.section(report(SEEN_ON_3_21), SHA)
    assert "3/71" in text
    for engine, label in SEEN_ON_3_21.items():
        assert engine in text and label in text


@pytest.mark.parametrize("label, words", [
    ("Trojan.Blank.Script.2228", "Blank"),
    ("BehavesLike.Win64.Backdoor.rc", "hành vi"),
    ("Malicious", "chung chung"),
    ("Static AI - Malicious PE", "học máy"),
    ("Trojan:Win32/Wacatac.B!ml", "học máy"),
    ("Gen:Variant.Pyinstaller.12", "PyInstaller"),
    ("HEUR:Trojan.Win32.Generic", "chung chung"),
])
def test_known_kinds_of_label_get_their_explanation(label, words):
    assert words in vt.explain(label)


def test_an_unfamiliar_label_is_said_to_be_unexplained():
    assert "Chưa có giải thích" in vt.explain("Trojan.Ransom.Lockbit")


def test_the_section_replaces_an_earlier_one_instead_of_stacking():
    body = "Ghi chú bản này.\n\n" + vt.section(report(SEEN_ON_3_21), SHA)
    again = vt.with_section(body, vt.section(report(), SHA))
    assert again.count(vt.START) == 1
    assert "0/68" in again and "3/71" not in again
    assert again.startswith("Ghi chú bản này.")


def test_the_section_is_added_to_a_body_that_has_none():
    body = vt.with_section("Ghi chú.", vt.section(report(), SHA))
    assert body.startswith("Ghi chú.") and vt.START in body and vt.END in body


def test_suspicious_counts_as_flagged():
    data = report()
    data["data"]["attributes"]["last_analysis_stats"]["suspicious"] = 2
    assert "2/70" in vt.section(data, SHA)


def test_without_a_key_the_scan_is_skipped_quietly(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("VT_API_KEY", raising=False)
    monkeypatch.setattr(vt, "_call", lambda *a, **k: pytest.fail("went online"))
    exe = tmp_path / "Onmyoji Tool.exe"
    exe.write_bytes(b"MZ")

    assert vt.main(["x", str(exe), "v3.22", "Long173/onmyoji-auto-releases"]) == 0
    assert "skipping" in capsys.readouterr().out
