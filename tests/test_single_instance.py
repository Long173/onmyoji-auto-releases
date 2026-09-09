"""One copy of the app at a time.

The reason this is not cosmetic: two copies both drive the same game windows,
each clicking into a client the other is reading, and neither knows the other is
there. It became reachable the moment the window learned to hide to the tray —
hidden, there is nothing to alt-tab to, so double-clicking the shortcut again is
the obvious move.

The awkward case is the one worth the most care, and it is the third test group:
a name held by a copy that has died or wedged. Refusing to start there would
leave the app unstartable with nothing on screen to explain why, so the second
copy takes the name over. Getting that backwards is the difference between a
minor annoyance and an app that cannot be opened at all.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtNetwork")
from PyQt5 import QtCore, QtNetwork  # noqa: E402

import single_instance  # noqa: E402
from single_instance import SingleInstance  # noqa: E402

# A name of its own per test run, so a real app running on this machine is
# neither disturbed by these tests nor able to disturb them.
BASE = "OnmyojiToolTests"


@pytest.fixture
def name(request):
    """A socket name unique to this test, cleaned up afterwards."""
    made = "%s-%s" % (BASE, request.node.name[-40:])
    yield made
    QtNetwork.QLocalServer.removeServer(single_instance.key_for(made))


def pump(app, ms=250):
    """Let Qt deliver socket events — there is no event loop in a test."""
    end = QtCore.QTime.currentTime().addMSecs(ms)
    while QtCore.QTime.currentTime() < end:
        app.processEvents()


# ── the claim ───────────────────────────────────────────────────────────────


def test_the_first_copy_gets_the_claim(qt_app, name):
    first = SingleInstance(name)
    try:
        assert first.claim() is True
    finally:
        first.release()


def test_a_second_copy_is_turned_away(qt_app, name):
    first = SingleInstance(name)
    second = SingleInstance(name)
    try:
        assert first.claim() is True

        assert second.claim() is False, "two copies both thought they were first"
    finally:
        second.release()
        first.release()


def test_the_claim_is_scoped_to_the_user(qt_app):
    """A local socket on Windows is a machine-wide named pipe.

    Two people signed into the same machine would otherwise lock each other
    out of an app neither of them is running.
    """
    import getpass

    assert getpass.getuser() in single_instance.key_for("whatever")


def test_two_different_names_do_not_collide(qt_app, name):
    other = SingleInstance(name + "-other")
    first = SingleInstance(name)
    try:
        assert first.claim() is True
        assert other.claim() is True
    finally:
        other.release()
        first.release()
        QtNetwork.QLocalServer.removeServer(
            single_instance.key_for(name + "-other")
        )


# ── waking the first copy ───────────────────────────────────────────────────


def test_the_second_launch_wakes_the_first(qt_app, name):
    first = SingleInstance(name)
    woken = []
    first.woken.connect(lambda: woken.append(True))
    try:
        assert first.claim() is True

        # Held in a local, the way the real one is parented to the QApplication.
        # Dropped straight after claim() its socket is collected with it, and
        # the pipe can be torn down before the running copy accepts.
        second = SingleInstance(name)
        second.claim()
        pump(qt_app)

        assert woken == [True], "the running copy was never told"
    finally:
        first.release()


def test_waking_a_name_nobody_holds_reports_failure(qt_app, name):
    """What tells the guard the holder is gone rather than busy."""
    lonely = SingleInstance(name)

    assert lonely.wake_the_running_copy() is False


def test_the_wake_is_ignored_if_it_says_something_else(qt_app, name):
    """The socket is the app's own, but it should still not act on noise."""
    first = SingleInstance(name)
    woken = []
    first.woken.connect(lambda: woken.append(True))
    try:
        assert first.claim() is True

        socket = QtNetwork.QLocalSocket()
        socket.connectToServer(first.key)
        assert socket.waitForConnected(2000)
        socket.write(b"something else entirely")
        socket.flush()
        socket.waitForBytesWritten(1000)
        pump(qt_app)
        socket.disconnectFromServer()

        assert woken == []
    finally:
        first.release()


# ── the name held by nobody ─────────────────────────────────────────────────


def test_a_name_held_by_a_dead_copy_is_taken_over(qt_app, name, monkeypatch):
    """Otherwise the app becomes unstartable, silently.

    Simulated by making the wake fail while the name is still held: exactly what
    a crashed copy leaves behind on a platform whose socket outlives it.
    """
    holder = SingleInstance(name)
    taker = SingleInstance(name)
    try:
        assert holder.claim() is True
        monkeypatch.setattr(taker, "wake_the_running_copy", lambda: False)

        assert taker.claim() is True, "refused to start with nobody to show"
    finally:
        taker.release()
        holder.release()


def test_it_starts_anyway_when_the_name_cannot_be_claimed_at_all(qt_app, name, monkeypatch):
    """The user asked for the app. Starting beats a silent nothing."""
    guard = SingleInstance(name)
    monkeypatch.setattr(guard, "wake_the_running_copy", lambda: False)
    monkeypatch.setattr(guard._server, "listen", lambda _key: False)

    assert guard.claim() is True


# ── released on the way out ─────────────────────────────────────────────────


def test_releasing_lets_the_next_copy_claim_it(qt_app, name):
    first = SingleInstance(name)
    assert first.claim() is True
    first.release()

    second = SingleInstance(name)
    try:
        assert second.claim() is True
    finally:
        second.release()
