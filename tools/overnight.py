"""Collect all night, lay the results out to label, then shut the machine down.

    python tools/overnight.py --cycles 7 --rounds 10 --hwnd 0x1901d8

Runs `grow_library.py`, rebuilds both audit sheets, writes a summary, and powers
the machine off. Everything lands in `cache/overnight.log` to read in the
morning.

Self-contained on purpose: nothing here waits on a person or on another program
staying alive. A run that needs someone watching it is not an overnight run.

The audit sheets are built **whatever the collection did**, including when it
gave up early. A morning with three cycles of work laid out ready to label
beats a morning spent finding out why nothing was laid out.

Shutdown is announced with a delay, so a person still at the keyboard can stop
it with `shutdown /a`.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "cache" / "overnight.log"
# Long enough for someone sitting at the machine to notice and cancel, short
# enough not to waste the night if nobody is.
SHUTDOWN_DELAY_SECONDS = 120


def say(handle, text):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), text)
    print(line, flush=True)
    handle.write(line + "\n")
    handle.flush()


def step(handle, command):
    """Run a step, copying its output into the log as it appears.

    Line by line, not gathered at the end. A step that runs for two hours and
    writes nothing until it finishes cannot be told apart from one that has
    hung, which is the single thing an unattended run must never be ambiguous
    about.

    PYTHONUNBUFFERED because that is not enough on its own: a child writing to
    a pipe holds its output in a 4 KB block regardless of how this end reads,
    and `flush=True` in the child only covers the lines that remember it.
    """
    say(handle, "$ " + " ".join(str(c) for c in command))
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    process = subprocess.Popen(
        [sys.executable] + [str(c) for c in command],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", bufsize=1, env=env,
    )
    for line in process.stdout:
        handle.write("    " + line.rstrip() + "\n")
        handle.flush()
    code = process.wait()
    say(handle, "   -> ma tra ve %d" % code)
    return code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Collect overnight, then shut down")
    parser.add_argument("--cycles", type=int, default=7)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--hwnd", default=None)
    parser.add_argument("--no-shutdown", action="store_true",
                        help="lam moi thu nhung khong tat may")
    args = parser.parse_args(argv)

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("w", encoding="utf-8") as handle:
        say(handle, "bat dau: %d chu ky x %d vong" % (args.cycles, args.rounds))

        grow = [ROOT / "tools" / "grow_library.py",
                "--cycles", args.cycles, "--rounds", args.rounds]
        if args.hwnd:
            grow += ["--hwnd", args.hwnd]
        collected = step(handle, grow)
        if collected != 0:
            say(handle, "thu thap khong hoan tat — van lap bang voi nhung gi da co")

        # Both sheets, and the packed library they read from, so the morning
        # starts with something to look at rather than a repair job.
        step(handle, [ROOT / "tools" / "pack_library.py"])
        step(handle, [ROOT / "tools" / "audit_library.py", "RARE"])
        step(handle, [ROOT / "tools" / "audit_library.py", "commons"])

        lots = sorted((ROOT / "cache" / "can-xem").glob("*.png"))
        say(handle, "co %d lo can gan nhan trong cache/can-xem/" % len(lots))
        say(handle, "hai bang ra soat: cache/ra_soat_rare.png, cache/ra_soat_common.png")

        if args.no_shutdown:
            say(handle, "xong. Khong tat may (--no-shutdown).")
            return 0

        say(handle, "tat may sau %d giay — huy bang: shutdown /a"
            % SHUTDOWN_DELAY_SECONDS)
        subprocess.run(["shutdown", "/s", "/t", str(SHUTDOWN_DELAY_SECONDS),
                        "/c", "Onmyoji: thu thap xong, tat may"], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
