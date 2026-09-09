"""Logging that survives the path it is running from.

The app's own checkout lives under a folder named 陰陽師Onmyoji, and the first
line it logs is that path. On a Windows console — cp1252 here — the stream
handler raised ``UnicodeEncodeError`` on it, so logging swallowed the record and
printed a "--- Logging error ---" traceback in its place. Found by running the
packaged build and reading what it actually wrote, not by reasoning about it.

The file handler was always UTF-8 and always fine. It is the console half that
had to be made tolerant, and the point of these tests is that it stays that way.
"""
from __future__ import annotations

import io
import logging

import pytest

import logging_setup

AWKWARD = "陰陽師Onmyoji"


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    """Keep the log file out of the real logs folder."""
    folder = tmp_path / "logs"
    monkeypatch.setattr(logging_setup, "LOG_DIR", folder)
    yield folder
    logging.getLogger().handlers.clear()


def a_console(encoding: str = "cp1252"):
    """A stdout that behaves like a Windows console."""
    return io.TextIOWrapper(io.BytesIO(), encoding=encoding, newline="")


@pytest.fixture
def complaints(monkeypatch):
    """Whatever the logging machinery could not write.

    ``Handler.handleError`` is the hook that fires when ``emit`` raises; logging
    never re-raises, so without watching it a broken handler looks like success.
    """
    caught = []
    monkeypatch.setattr(logging.Handler, "handleError",
                        lambda self, record: caught.append(record.getMessage()))
    return caught


def test_a_path_the_console_cannot_draw_is_still_logged(log_dir, monkeypatch,
                                                        complaints):
    monkeypatch.setattr(logging_setup.sys, "stdout", a_console())
    logging_setup.configure()

    logging.getLogger(__name__).info("Paths: %s", AWKWARD)

    assert complaints == [], "the record was dropped: %s" % complaints


def test_the_file_still_gets_the_real_characters(log_dir, monkeypatch):
    """Tolerating them on the console must not mangle them on disk."""
    monkeypatch.setattr(logging_setup.sys, "stdout", a_console())
    logging_setup.configure()

    logging.getLogger(__name__).info("Paths: %s", AWKWARD)
    logging.getLogger().handlers[0].flush()

    written = (log_dir / logging_setup.LOG_FILE_NAME).read_text(encoding="utf-8")
    assert AWKWARD in written


def test_the_console_keeps_a_hint_of_what_it_could_not_draw(log_dir, monkeypatch):
    """``backslashreplace`` over ``replace``: ``\\u9670`` still identifies the
    character, where ``?`` throws that away."""
    console = a_console()
    monkeypatch.setattr(logging_setup.sys, "stdout", console)
    logging_setup.configure()

    logging.getLogger(__name__).info("Paths: %s", AWKWARD)
    console.flush()

    shown = console.buffer.getvalue().decode("cp1252")
    assert "u9670" in shown
    assert "?" not in shown


def test_a_utf8_console_is_left_alone(log_dir, monkeypatch, complaints):
    console = a_console("utf-8")
    monkeypatch.setattr(logging_setup.sys, "stdout", console)
    logging_setup.configure()

    logging.getLogger(__name__).info("Paths: %s", AWKWARD)
    console.flush()

    assert complaints == []
    assert AWKWARD in console.buffer.getvalue().decode("utf-8")


def test_no_console_at_all_is_fine(log_dir, monkeypatch):
    """Under pythonw.exe ``sys.stdout`` is None, which is the shipped case."""
    monkeypatch.setattr(logging_setup.sys, "stdout", None)

    logging_setup.configure()

    logging.getLogger(__name__).info("Paths: %s", AWKWARD)
    assert len(logging.getLogger().handlers) == 1


def test_a_stream_that_cannot_be_reconfigured_does_not_stop_logging(log_dir,
                                                                    monkeypatch):
    """Failing to set up logging is worse than a console that garbles a path."""
    class Stubborn(io.StringIO):
        def reconfigure(self, **_kwargs):
            raise OSError("no")

    monkeypatch.setattr(logging_setup.sys, "stdout", Stubborn())

    logging_setup.configure()

    assert len(logging.getLogger().handlers) == 2


def test_configuring_twice_does_not_double_the_handlers(log_dir, monkeypatch):
    monkeypatch.setattr(logging_setup.sys, "stdout", a_console())

    logging_setup.configure()
    logging_setup.configure()

    assert len(logging.getLogger().handlers) == 2
