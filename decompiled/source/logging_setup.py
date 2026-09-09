"""Application logging.

Replaces the old ``printWithTime`` helper. The previous setup redirected
stdout into ``silent.log`` with ``>>``, so the file grew without bound (it
reached 86 MB). A ``RotatingFileHandler`` caps total log size instead.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from paths import LOG_DIR

LOG_FILE_NAME = "onmyoji_auto.log"
MAX_LOG_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3
LOG_FORMAT = "[%(asctime)s] %(levelname)-7s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure(verbose: bool = False) -> None:
    """Attach a rotating file handler and a console handler to the root logger.

    Safe to call twice: existing handlers are cleared first.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    file_handler = RotatingFileHandler(
        LOG_DIR / LOG_FILE_NAME,
        maxBytes=MAX_LOG_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.handlers.clear()
    root.addHandler(file_handler)

    # Under pythonw.exe there is no console and sys.stdout is None, so a stream
    # handler would blow up on the first record.
    if sys.stdout is not None:
        _tolerate_unencodable(sys.stdout)
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)


def _tolerate_unencodable(stream) -> None:
    """Stop the console handler from failing on characters it cannot draw.

    A Windows console defaults to the ANSI code page — cp1252 here — and any
    record carrying a character outside it raises ``UnicodeEncodeError`` inside
    the handler. Logging catches that and prints a "--- Logging error ---"
    traceback instead of the message, so the line is lost and replaced by
    something longer and less useful.

    Not hypothetical: this app's own checkout lives under ``…\\陰陽師Onmyoji\\…``,
    and the very first line it logs is the path it is running from. Vietnamese
    user folders hit it too.

    ``backslashreplace`` rather than ``replace``: ``\\u9670`` still says which
    character it was, where ``?`` throws that away. The file handler is already
    UTF-8 and is unaffected either way — it is only the console that cannot
    draw them.
    """
    try:
        stream.reconfigure(errors="backslashreplace")
    except (AttributeError, OSError, ValueError):
        # A stream that is not a text wrapper, or one already detached. The
        # handler may still fail on such a stream, but there is nothing here
        # that can help it, and failing to configure logging is worse.
        pass
