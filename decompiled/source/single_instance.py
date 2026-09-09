"""One copy of the app at a time; a second launch wakes the first.

This matters more than it looks, and it matters *because* the window now hides
to the tray. Hidden, there is no taskbar button and no window to alt-tab to, so
the natural thing to do is double-click the shortcut again — and without this,
that starts a whole second copy. Two copies fighting over the same game windows
is not a cosmetic problem: both would click into the same client, each undoing
the other's screen reading. It has already happened during development, where a
window scan turned up two "Onmyoji Tool" windows nobody meant to open.

Two pieces, and it needs both. A shared-memory segment is the lock; a local
socket carries the "come back" message.

Listening on the socket alone looked like it would do — the name is either taken
or it is not — and it does not. On Windows a Qt local socket is a named pipe, and
Windows lets a second process create another *instance* of a pipe that already
exists, so ``listen()`` cheerfully succeeded twice and both copies believed they
were first. It took a test to notice: nothing about the running app looks wrong
until two copies are clicking into the same game. The shared-memory segment is
the part that really only one process can hold.

The name includes the user, because on Windows a local socket is a named pipe
and those are machine-wide: two people signed into the same machine would
otherwise block each other.

**When the first copy cannot be woken, the second one takes over.** A pipe whose
owner has died or wedged would otherwise leave the app unstartable, with nothing
on screen to explain why — the worst possible failure. Refusing to start is only
correct while there is genuinely somebody there to show instead.
"""
from __future__ import annotations

import getpass
import logging

from PyQt5 import QtCore, QtNetwork

logger = logging.getLogger(__name__)

# How long to wait for the running copy to answer. Generous: it may be busy
# matching templates when the socket arrives, and being wrong here means
# starting a second copy.
CONNECT_TIMEOUT_MS = 2000
WRITE_TIMEOUT_MS = 1000
WAKE = b"show"


def key_for(name: str) -> str:
    """The socket name, scoped to this user."""
    try:
        who = getpass.getuser()
    except Exception:  # noqa: BLE001 - a nameless account still needs a key
        who = "user"
    return "%s-%s" % (name, who)


class SingleInstance(QtCore.QObject):
    """Holds the "I am the running copy" claim, and hears later launches."""

    woken = QtCore.pyqtSignal()

    def __init__(self, name: str, parent=None) -> None:
        super().__init__(parent)
        self._key = key_for(name)
        # The lock. Held for the life of the process; Windows frees the segment
        # when the last holder exits, including a holder that crashed.
        self._lock = QtCore.QSharedMemory(self._key + "-lock", self)
        self._server: QtNetwork.QLocalServer = QtNetwork.QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        # Set only in the copy that is exiting; see wake_the_running_copy.
        self._waker: object = None

    @property
    def key(self) -> str:
        return self._key

    def claim(self) -> bool:
        """True if this process is the one and only copy.

        False means another copy holds the lock *and* answered when asked. A
        lock held by something that does not answer is taken over — see the
        module docstring.
        """
        if self._lock.create(1):
            self._start_listening()
            logger.info("Holding the single-instance claim on %r", self._key)
            return True

        if self._lock.error() != QtCore.QSharedMemory.AlreadyExists:
            logger.warning(
                "Could not take the single-instance lock (%s) — starting anyway",
                self._lock.errorString(),
            )
            self._start_listening()
            return True

        if self.wake_the_running_copy():
            logger.info("Another copy is already running; asked it to show")
            return False

        # Held by something that is not answering: a copy that wedged, or a
        # segment left behind on a platform that does not reclaim them.
        logger.warning(
            "The lock on %r is held but nothing answered — taking it over",
            self._key,
        )
        self._lock.attach()
        self._lock.detach()
        QtNetwork.QLocalServer.removeServer(self._key)
        if not self._lock.create(1):
            logger.error(
                "Could not clear the lock on %r: %s",
                self._key, self._lock.errorString(),
            )
        # Starting is better than not starting: the user asked for the app, and
        # refusing leaves nothing on screen to explain why.
        self._start_listening()
        return True

    def _start_listening(self) -> None:
        """Open the channel later launches use to ask for the window."""
        if self._server.isListening():
            return
        if not self._server.listen(self._key):
            # Stale on platforms where the socket outlives its process.
            QtNetwork.QLocalServer.removeServer(self._key)
            if not self._server.listen(self._key):
                logger.warning(
                    "Not listening for later launches on %r: %s",
                    self._key, self._server.errorString(),
                )

    def wake_the_running_copy(self) -> bool:
        """Ask the copy that holds the lock to show itself.

        True means *somebody answered the door* — which is the question the
        caller is really asking, since the alternative is deciding the holder is
        dead and taking its lock.

        Connecting is what proves that, not the write. ``waitForBytesWritten``
        returns false when there is nothing left pending, which is exactly what
        happens when the write already went through — reading it as "not
        delivered" had every second launch conclude the first was dead and start
        a second copy anyway.
        """
        # Kept on self, and not disconnected here. A socket left as a local
        # goes out of scope the moment this returns, and the pipe can be torn
        # down before the running copy's event loop has accepted it — the bytes
        # are already waiting on the other side, but the connection carrying
        # them is gone. Held instead until this process exits.
        socket = QtNetwork.QLocalSocket(self)
        self._waker = socket
        socket.connectToServer(self._key)
        if not socket.waitForConnected(CONNECT_TIMEOUT_MS):
            return False
        socket.write(WAKE)
        socket.flush()
        # Best effort, and it must not gate the answer: a false here means
        # nothing was left pending, not that nothing arrived.
        socket.waitForBytesWritten(WRITE_TIMEOUT_MS)
        return True

    def _on_connection(self) -> None:
        """A later launch is asking for the window."""
        socket = self._server.nextPendingConnection()
        if socket is None:
            return
        socket.disconnected.connect(socket.deleteLater)
        socket.readyRead.connect(lambda: self._read(socket))
        # And read straight away, which is the part that was missing. Measured:
        # an accepted connection already has all four bytes waiting on it, so
        # ``readyRead`` has often been and gone before this handler runs and
        # waiting only for it means waiting forever.
        self._read(socket)

    def _read(self, socket) -> None:
        """Collect what has arrived, and act once the word is complete.

        Accumulated rather than read in one go. Four bytes do arrive together in
        practice, but a channel that only works when they do is a channel that
        breaks under load for no visible reason.
        """
        seen = bytes(socket.property("seen") or b"") + bytes(socket.readAll())
        if WAKE not in seen:
            socket.setProperty("seen", seen[-len(WAKE):])
            return
        socket.setProperty("seen", b"")
        logger.info("A second launch asked for the window")
        self.woken.emit()

    def release(self) -> None:
        if self._server.isListening():
            self._server.close()
        if self._lock.isAttached():
            self._lock.detach()
