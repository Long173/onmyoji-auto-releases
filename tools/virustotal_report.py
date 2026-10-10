"""Scan a release's .exe on VirusTotal and put the result in the release notes.

    python tools/virustotal_report.py "dist/Onmyoji Tool/Onmyoji Tool.exe" v3.22 \
        Long173/onmyoji-auto-releases

Needs VT_API_KEY (a free VirusTotal account's key) and GITHUB_TOKEN in the
environment. Without VT_API_KEY it says so and does nothing: the scan is a
courtesy to players, never a reason for a release to fail.

Why it exists: 3.21 was scanned by a player, came back 3/71, and was posted in
a group as "Virus nhé" with nothing beside it. Every flag on that scan was a
heuristic one — a packer the malware also uses, a behaviour guess, a bare
"Malicious" — but that explanation arrived after the post, not with the file.
Now each release carries its own scan and, for every engine that flags it, a
line saying what kind of flag it is. The explanations come from a fixed table of
label patterns below, so an engine flagging something new is reported as having
no explanation rather than being explained away.

Uploading puts the file on VirusTotal, where anyone can look it up; it is a
public download already, so nothing is disclosed that was not.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

VT = "https://www.virustotal.com/api/v3"
GITHUB = "https://api.github.com"
GUI = "https://www.virustotal.com/gui/file/"

# The free API allows 4 requests a minute; one look every 30 s stays well under.
POLL_SECONDS = 30
POLL_LIMIT_SECONDS = 20 * 60

START = "<!-- virustotal:start -->"
END = "<!-- virustotal:end -->"

# Label patterns, checked in order: the first match explains the label. Lower
# case, matched anywhere in the label.
EXPLANATIONS: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("blank",),
     "Nhận nhầm theo cách đóng gói: \"Blank\" là một mã độc viết bằng Python, "
     "đóng gói bằng PyInstaller giống tool này."),
    (("pyinstaller", "pyinst"),
     "Gắn nhãn theo bộ đóng gói PyInstaller, không theo nội dung chương trình."),
    (("behaveslike",),
     "Phỏng đoán theo hành vi: tool gửi thao tác chuột vào cửa sổ khác, chụp "
     "cửa sổ game, có mục khởi động cùng Windows và tự cập nhật."),
    (("!ml", "static ai", "static ml", "(ml)", ".ml", "ai -", "deepinstinct"),
     "Phỏng đoán bằng học máy, không nhận ra mã độc cụ thể nào."),
    (("malicious", "generic", "heur", "suspicious", "unsafe", "confidence",
      "riskware", "susgen"),
     "Nhãn chung chung, không chỉ ra mã độc cụ thể nào — kiểu báo các phần "
     "mềm này dùng cho file .exe không có chữ ký số."),
)
UNEXPLAINED = ("Chưa có giải thích cho nhãn này — cần kiểm tra lại trước khi "
               "trả lời người dùng.")

CONTEXT = ("Tool đóng gói bằng PyInstaller và chưa có chữ ký số; nó gửi thao "
           "tác chuột vào cửa sổ game, chụp cửa sổ game, có mục khởi động cùng "
           "Windows và tự cập nhật — những việc phần mềm quét theo phỏng đoán "
           "hay gắn nhầm. Mã nguồn công khai trong repo này, và bản build do "
           "GitHub Actions dựng từ đúng mã nguồn đó.")


def explain(label: str) -> str:
    lowered = (label or "").lower()
    for patterns, text in EXPLANATIONS:
        if any(pattern in lowered for pattern in patterns):
            return text
    return UNEXPLAINED


def flagged(report: dict) -> List[Tuple[str, str]]:
    """(engine, label) for every engine that called the file malicious or suspicious."""
    results = report["data"]["attributes"].get("last_analysis_results", {})
    return sorted((engine, (entry.get("result") or entry["category"]))
                  for engine, entry in results.items()
                  if entry.get("category") in ("malicious", "suspicious"))


def counts(report: dict) -> Tuple[int, int]:
    """(flagged, engines that gave a verdict). Timeouts and unsupported excluded."""
    stats = report["data"]["attributes"]["last_analysis_stats"]
    bad = stats.get("malicious", 0) + stats.get("suspicious", 0)
    total = bad + stats.get("undetected", 0) + stats.get("harmless", 0)
    return bad, total


def section(report: dict, sha256: str) -> str:
    """The markdown block for the release notes, between START and END."""
    bad, total = counts(report)
    lines = [START, "### Kiểm tra virus", "",
             "VirusTotal: **%d/%d** phần mềm diệt virus báo — [xem kết quả](%s%s)"
             % (bad, total, GUI, sha256)]
    hits = flagged(report)
    if hits:
        lines += ["", "| Phần mềm | Nhãn | Vì sao |", "| --- | --- | --- |"]
        for engine, label in hits:
            lines.append("| %s | `%s` | %s |" % (engine, label.replace("|", "/"),
                                                 explain(label)))
        lines += ["", CONTEXT]
    lines.append(END)
    return "\n".join(lines)


def with_section(body: str, block: str) -> str:
    """``body`` with ``block`` in place of any earlier scan section, or appended."""
    pattern = re.compile(re.escape(START) + ".*?" + re.escape(END), re.S)
    if pattern.search(body or ""):
        return pattern.sub(lambda _m: block, body)
    return (body or "").rstrip() + "\n\n" + block + "\n"


# ── network ────────────────────────────────────────────────────────────────


def _call(method: str, url: str, headers: dict, data: Optional[bytes] = None) -> dict:
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def upload(path: Path, key: str) -> str:
    """Send the file for analysis; the analysis id comes back."""
    boundary = uuid.uuid4().hex
    body = b"".join([
        b"--" + boundary.encode() + b"\r\n",
        b'Content-Disposition: form-data; name="file"; filename="'
        + path.name.encode("utf-8") + b'"\r\n',
        b"Content-Type: application/octet-stream\r\n\r\n",
        path.read_bytes(), b"\r\n",
        b"--" + boundary.encode() + b"--\r\n",
    ])
    answer = _call("POST", VT + "/files",
                   {"x-apikey": key,
                    "Content-Type": "multipart/form-data; boundary=" + boundary},
                   body)
    return answer["data"]["id"]


def wait_for(analysis: str, key: str) -> dict:
    deadline = time.monotonic() + POLL_LIMIT_SECONDS
    while True:
        answer = _call("GET", VT + "/analyses/" + analysis, {"x-apikey": key})
        status = answer["data"]["attributes"]["status"]
        print("VirusTotal analysis:", status, flush=True)
        if status == "completed":
            return answer
        if time.monotonic() > deadline:
            raise TimeoutError("VirusTotal did not finish in %d minutes"
                               % (POLL_LIMIT_SECONDS // 60))
        time.sleep(POLL_SECONDS)


def file_report(sha256: str, key: str) -> dict:
    return _call("GET", VT + "/files/" + sha256, {"x-apikey": key})


def update_release(repo: str, tag: str, block: str, token: str) -> None:
    headers = {"Authorization": "Bearer " + token,
               "Accept": "application/vnd.github+json"}
    release = _call("GET", "%s/repos/%s/releases/tags/%s" % (GITHUB, repo, tag), headers)
    body = with_section(release.get("body") or "", block)
    _call("PATCH", "%s/repos/%s/releases/%d" % (GITHUB, repo, release["id"]),
          dict(headers, **{"Content-Type": "application/json"}),
          json.dumps({"body": body}).encode("utf-8"))


def main(argv: List[str]) -> int:
    if len(argv) != 4:
        print(__doc__)
        return 2
    path, tag, repo = Path(argv[1]), argv[2], argv[3]
    key = os.environ.get("VT_API_KEY", "").strip()
    if not key:
        print("VT_API_KEY is not set — skipping the VirusTotal scan.")
        return 0
    import hashlib
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    print("Uploading %s (%s) to VirusTotal" % (path.name, sha256), flush=True)
    wait_for(upload(path, key), key)
    block = section(file_report(sha256, key), sha256)
    print(block)
    update_release(repo, tag, block, os.environ["GITHUB_TOKEN"])
    print("Release %s notes updated." % tag)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
