"""Run one slow call off the UI thread.

The wiki's submission and review dialogs each talk to Supabase two or three
times, and every one of those calls can hang for the full twenty-second
timeout. Doing them inline froze the window — including the button that had just
been pressed, so the only feedback was that the app had stopped repainting.

Deliberately not a thread pool. Each dialog owns its worker and waits for it in
``closeEvent``; a shared pool would outlive the widget whose slot it is about to
call, which is the one failure mode a dialog cannot recover from.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from PyQt5 import QtCore, QtWidgets

logger = logging.getLogger(__name__)


class CallWorker(QtCore.QThread):
    """Calls one function, then emits either :attr:`done` or :attr:`failed`.

    Exactly one of the two is emitted, always. A dialog that has disabled its
    buttons while waiting has no other way back to a usable state.
    """

    done = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, call: Callable[[], Any],
                 parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self._call = call

    def run(self) -> None:
        try:
            result = self._call()
        except Exception as exc:  # noqa: BLE001 - a thread boundary
            # Anything escaping here would end the thread with no signal, and
            # the dialog would wait for a reply that is never coming. The
            # message is shown to the user, so the traceback goes to the log
            # where it is useful without being frightening.
            logger.exception("Background call failed")
            self.failed.emit(str(exc) or exc.__class__.__name__)
            return
        self.done.emit(result)


class Busy:
    """Holds a dialog's one in-flight worker, and cleans up after it.

    Starting a second call while the first is still running is what happens when
    somebody double-clicks. The old worker is not killed — a half-finished POST
    to the database is worse than a slow one — it is simply disowned, so its
    result is ignored.
    """

    def __init__(self, owner: QtWidgets.QWidget) -> None:
        self._owner = owner
        self._worker: Optional[CallWorker] = None

    def run(self, call: Callable[[], Any],
            on_done: Callable[[Any], None],
            on_failed: Callable[[str], None]) -> None:
        self.forget()
        worker = CallWorker(call, self._owner)
        self._worker = worker

        def guard(handler: Callable[[Any], None]) -> Callable[[Any], None]:
            def fire(payload: Any) -> None:
                if self._worker is not worker:
                    return  # superseded; its answer is no longer wanted
                self._worker = None
                handler(payload)
            return fire

        worker.done.connect(guard(on_done))
        worker.failed.connect(guard(on_failed))
        worker.start()

    @property
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def forget(self) -> None:
        """Stop caring about the current worker, without stopping it."""
        self._worker = None

    def wait(self, milliseconds: int = 3000) -> None:
        """Let an in-flight call finish before the owner goes away."""
        worker = self._worker
        self._worker = None
        if worker is not None and worker.isRunning():
            worker.wait(milliseconds)
