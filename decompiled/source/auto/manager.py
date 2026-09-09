"""Owns every :class:`GameSession` and the per-task settings they share."""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence

import tasks
from auto import window_scanner
from auto.session import GameSession
from auto.window_scanner import GameWindow

logger = logging.getLogger(__name__)

Notify = Optional[Callable[[str, int], None]]


class SessionManager:
    """Keeps the set of known windows in step with what is actually open.

    Rescanning preserves each window's chosen task and running worker; only
    genuinely new windows get a fresh session, and only windows that
    disappeared while idle are dropped.

    Task settings live here rather than on the session because they are shared:
    changing the raid target changes it for every window running that task.
    """

    def __init__(
        self,
        configs: Optional[Dict[str, Dict[str, Any]]] = None,
        app_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._app: Dict[str, Any] = tasks.coerce_app(app_config)
        self._configs: Dict[str, Dict[str, Any]] = {}
        for spec in tasks.TASKS:
            self._configs[spec.id] = spec.coerce((configs or {}).get(spec.id))
        self._sessions: Dict[int, GameSession] = {}
        self._order: List[int] = []

    # ── settings ────────────────────────────────────────────────────────────

    def config_for(
        self, task_id: str, session: Optional[GameSession] = None
    ) -> Dict[str, Any]:
        """Everything a worker for this task on this window should see.

        Three layers, each one narrower than the last: app-wide, then the
        task's own, then whatever this particular window overrides.
        """
        merged = tasks.merge_layers(self._app, self._configs.get(task_id, {}))
        if session is not None:
            merged.update(session.options_for(task_id))
        return merged

    @property
    def app_config(self) -> Dict[str, Any]:
        return dict(self._app)

    def set_option(self, task_id: str, key: str, value: Any) -> None:
        if task_id in self._configs:
            self._configs[task_id][key] = value

    def set_app_option(self, key: str, value: Any) -> None:
        if key in self._app:
            self._app[key] = value

    # ── collection ──────────────────────────────────────────────────────────

    @property
    def sessions(self) -> List[GameSession]:
        return [self._sessions[hwnd] for hwnd in self._order if hwnd in self._sessions]

    def get(self, hwnd: int) -> Optional[GameSession]:
        return self._sessions.get(hwnd)

    @property
    def running_count(self) -> int:
        return sum(1 for session in self.sessions if session.is_running)

    def sessions_for(self, task_id: str) -> List[GameSession]:
        """Windows set to this task — running it now, or next time they start."""
        return [s for s in self.sessions if s.task_id == task_id]

    def running_count_for(self, task_id: str) -> int:
        return sum(
            1 for s in self.sessions if s.is_running and s.task_id == task_id
        )

    def scan(
        self, patterns: Sequence[str] = window_scanner.DEFAULT_PATTERNS
    ) -> List[GameSession]:
        """Re-enumerate game windows and reconcile the session list."""
        found = window_scanner.scan(patterns)
        self._merge(found)
        return self.sessions

    def _merge(self, found: Sequence[GameWindow]) -> None:
        found_by_hwnd = {window.hwnd: window for window in found}

        for hwnd, window in found_by_hwnd.items():
            existing = self._sessions.get(hwnd)
            if existing is None:
                self._sessions[hwnd] = GameSession(window)
                self._order.append(hwnd)
            else:
                # The title or client size may have changed since the last scan.
                existing.window = window

        for hwnd in list(self._sessions):
            if hwnd in found_by_hwnd:
                continue
            session = self._sessions[hwnd]
            if session.is_running:
                # Keep it visible so the user sees it failing rather than
                # having a card silently vanish mid-run.
                session.sync_status()
                continue
            session.release()
            del self._sessions[hwnd]
            self._order.remove(hwnd)

    def forget(self, hwnd: int) -> None:
        session = self._sessions.pop(hwnd, None)
        if session is None:
            return
        session.stop()
        session.release()
        if hwnd in self._order:
            self._order.remove(hwnd)

    # ── choosing ────────────────────────────────────────────────────────────

    def select(self, hwnd: int, task_id: str) -> None:
        """Set which task a window will run."""
        session = self._sessions.get(hwnd)
        if session is not None:
            session.select(task_id)

    # ── control ─────────────────────────────────────────────────────────────

    def start(self, hwnd: int, on_finished: Notify = None, on_error: Notify = None,
              task_id: Optional[str] = None) -> None:
        """Start one window.

        ``task_id`` selects that task first, so "start" on a task's own page
        starts *that* task. Left as None — which is what the home page wants —
        the window runs whatever it is already set to.
        """
        session = self._sessions.get(hwnd)
        if session is None:
            return
        if task_id is not None:
            session.select(task_id)
        session.start(
            self.config_for(session.task_id or "", session), on_finished, on_error
        )

    def stop(self, hwnd: int) -> None:
        session = self._sessions.get(hwnd)
        if session is not None:
            session.stop()

    def start_all(
        self,
        on_finished: Notify = None,
        on_error: Notify = None,
        task_id: Optional[str] = None,
    ) -> List[str]:
        """Start every idle window. Returns the errors that stopped any of them.

        ``task_id`` limits the sweep to windows already set to that task —
        the ones a task's own page is showing. It deliberately does not switch
        windows over: a sweep from one page must not take a window away from
        the job it is set to do.
        """
        errors: List[str] = []
        for session in self.sessions:
            if session.is_running:
                continue
            if task_id is not None and session.task_id != task_id:
                continue
            if not tasks.is_available(session.task_id or ""):
                # Its start button is disabled for the same reason; a sweep
                # should skip it quietly rather than raise a dialog per window.
                continue
            try:
                session.start(
                    self.config_for(session.task_id or "", session),
                    on_finished, on_error,
                )
            except Exception as exc:  # noqa: BLE001 - reported to the caller
                logger.warning("Could not start 0x%08x: %s", session.hwnd, exc)
                errors.append("%s: %s" % (session.title, exc))
        return errors

    def stop_all(self, task_id: Optional[str] = None) -> None:
        for session in self.sessions:
            if task_id is not None and session.task_id != task_id:
                continue
            session.stop()

    def pause_all(self) -> None:
        for session in self.sessions:
            if session.is_running:
                session.toggle_pause()

    def sync(self) -> None:
        for session in self.sessions:
            session.sync_status()

    def drop_closed_windows(self) -> List[GameSession]:
        """Stop and forget every session whose window has been closed.

        Returns them, so the caller can say which were in the middle of
        something. Only handles Windows has actually destroyed — see
        ``window_scanner.is_gone``; a hidden window keeps its card, and with it
        the task the user chose for it.

        Left to the next scan, a dead window went on being counted as a game
        window and its worker went on capturing it, which on a live instance
        meant "Invalid window handle" once a second for half an hour and a
        screenshot hotkey that could not tell which of "two" games was meant.
        """
        dead = [s for s in self.sessions if window_scanner.is_gone(s.hwnd)]
        for session in dead:
            session.note_running_before_close()
            self.forget(session.hwnd)
        return dead

    def shutdown(self) -> None:
        for session in self.sessions:
            session.stop()
            session.release()
        self._sessions.clear()
        self._order.clear()
