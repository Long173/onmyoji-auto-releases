"""One game window, the task chosen for it, and the worker driving that task.

A session no longer knows what Realm Raid is. It holds one task id and asks
:mod:`tasks` to build a worker for it, so a new automation reaches every window
without this file changing.

One task, not a queue. An earlier version held a list per window and started
the next one when the first finished, which made pressing Bắt đầu on a task's
own page start something else and leave that page reading "Trong hàng chờ".
Nobody was chaining tasks; they were opening the one they wanted and running
it.

Deliberately Qt-free so it can be tested without a display.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

import realm_raid
import tasks
from auto.window_scanner import GameWindow, is_alive
from game_control import CaptureError, GameControl

logger = logging.getLogger(__name__)

IDLE = "idle"
RUNNING = "running"
PAUSED = "paused"
DONE = "done"
ERROR = "error"


class GameSession:
    """Tracks one window's chosen task, worker and last-known status."""

    def __init__(
        self,
        window: GameWindow,
        task_id: Optional[str] = None,
    ) -> None:
        self.window = window
        self.selected: str = tasks.clean_task(task_id) or tasks.DEFAULT_TASK_ID
        # Settings that belong to this window rather than to the task, keyed by
        # task id. A co-op room has one leader, so "which role" cannot be a
        # single value shared by every window running the task.
        self.window_options: Dict[str, Dict[str, Any]] = {}
        self.status = IDLE
        self.message = ""
        self._worker: Optional[Any] = None
        # Whether there was work in flight when the window was closed out. Read
        # after stop(), when is_running can no longer answer it.
        self._was_running = False
        self._control: Optional[GameControl] = None
        # Which task the live worker is running. Not always the selected one:
        # the selection can be changed while a worker runs, and the stats below
        # belong to the task that produced them.
        self._active_task: Optional[str] = None
        # Which task the cached figures below belong to, so another task's page
        # does not display a count this window earned somewhere else.
        self._stats_task: Optional[str] = None
        self._progress = 0
        self._elapsed = 0.0
        self._shards: Dict[str, int] = {}

    # ── identity ────────────────────────────────────────────────────────────

    @property
    def hwnd(self) -> int:
        return self.window.hwnd

    @property
    def title(self) -> str:
        return self.window.title

    @property
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    @property
    def task_id(self) -> Optional[str]:
        """The task running now, or the one chosen for this window."""
        if self._active_task is not None and self.is_running:
            return self._active_task
        return self.selected

    @property
    def task(self) -> Optional[tasks.TaskSpec]:
        task_id = self.task_id
        return tasks.get(task_id) if task_id else None

    # ── choosing ────────────────────────────────────────────────────────────

    def select(self, task_id: str) -> None:
        """Choose the task this window will run. Ignores an unknown id.

        Allowed while a worker runs: the running task is tracked separately, so
        changing the selection sets up what the next Bắt đầu will do without
        disturbing what is happening now.
        """
        if task_id in tasks.BY_ID:
            self.selected = task_id

    # ── per-window settings ─────────────────────────────────────────────────

    def options_for(self, task_id: str) -> Dict[str, Any]:
        """This window's own settings for a task, defaults filled in."""
        spec = tasks.get(task_id)
        if spec is None:
            return {}
        return tasks.coerce_fields(
            spec.window_fields, self.window_options.get(task_id)
        )

    def set_option(self, task_id: str, key: str, value: Any) -> None:
        spec = tasks.get(task_id)
        if spec is None or key not in {f.key for f in spec.window_fields}:
            return
        self.window_options.setdefault(task_id, {})[key] = value

    def load_options(self, stored: Optional[Dict[str, Dict[str, Any]]]) -> None:
        """Restore what was saved for this window title, dropping the rest."""
        for task_id, values in (stored or {}).items():
            spec = tasks.get(task_id)
            if spec is None or not spec.window_fields:
                continue
            keys = {f.key for f in spec.window_fields}
            kept = {k: v for k, v in (values or {}).items() if k in keys}
            if kept:
                self.window_options[task_id] = kept

    # ── stats ───────────────────────────────────────────────────────────────
    # Cached on every read so the numbers survive the worker being torn down.

    @property
    def progress(self) -> int:
        """Units of work the live worker reports, or 0 if it reports none.

        ``progress`` is optional in the worker protocol — see :mod:`tasks` — so
        this reads it defensively rather than requiring every task to invent a
        number it cannot count honestly.
        """
        if self._worker is not None:
            self._progress = getattr(self._worker, "progress", 0)
        return self._progress

    @property
    def elapsed_seconds(self) -> float:
        if self._worker is not None:
            self._elapsed = self._worker.elapsed_seconds
        return self._elapsed

    @property
    def shards(self) -> Dict[str, int]:
        """What the task collected, if it collects anything countable by name.

        Optional in the worker protocol, like ``progress``: only Ném đậu reads
        a result screen listing names and amounts, and a task that cannot count
        honestly should not be made to invent a number.
        """
        if self._worker is not None:
            self._shards = dict(getattr(self._worker, "shards", {}) or {})
        return self._shards

    def stats_for(self, task_id: str) -> "tuple[int, float]":
        """Progress and elapsed time, but only if this task earned them."""
        if self._stats_task != task_id:
            return 0, 0.0
        return self.progress, self.elapsed_seconds

    def shards_for(self, task_id: str) -> Dict[str, int]:
        """What this task collected — nothing, if the haul belongs elsewhere."""
        if self._stats_task != task_id:
            return {}
        return self.shards

    @staticmethod
    def format_elapsed(seconds: float) -> str:
        total = int(seconds)
        if total >= 3600:
            return "%d:%02d:%02d" % (total // 3600, (total % 3600) // 60, total % 60)
        return "%02d:%02d" % (total // 60, total % 60)

    # ── lifecycle ───────────────────────────────────────────────────────────

    def start(
        self,
        config: Dict[str, Any],
        on_finished: Optional[Callable[[str, int], None]] = None,
        on_error: Optional[Callable[[str, int], None]] = None,
    ) -> None:
        """Run the chosen task. No-op if one is already running."""
        if self.is_running:
            return
        spec = self.task
        if spec is None:
            raise RuntimeError("Cửa sổ này chưa được gán tác vụ nào")
        if not spec.is_available:
            raise RuntimeError("Tác vụ “%s” chưa được cài đặt" % spec.name)
        if not is_alive(self.hwnd):
            self.status = ERROR
            self.message = "Cửa sổ game đã đóng"
            raise RuntimeError(self.message)

        control = self._ensure_control()
        # Every task drives the same client area, so the window is put at the
        # size the templates were captured at before any of them looks at it.
        realm_raid.resize_game_window(self.hwnd)
        control.refresh_metrics()

        self._worker = spec.build(
            hwnd=self.hwnd,
            control=control,
            config=config,
            on_finished=lambda msg: on_finished and on_finished(msg, self.hwnd),
            on_error=lambda msg: on_error and on_error(msg, self.hwnd),
        )
        self._active_task = spec.id
        self._stats_task = spec.id
        self._progress = 0
        self._elapsed = 0.0
        self.status = RUNNING
        self.message = ""
        self._worker.start()
        logger.info("Session started for %s — %s", self.window.descriptor, spec.id)

    def stop(self, timeout: float = 3.0) -> None:
        worker = self._worker
        if worker is None:
            self.status = IDLE
            return
        # Read the stats through before the worker goes away. getattr because
        # `progress` is optional — Realm Raid has none.
        self._progress = getattr(worker, "progress", 0)
        self._elapsed = worker.elapsed_seconds
        worker.stop()
        worker.join(timeout)
        if worker.is_alive():
            logger.warning("Worker for 0x%08x did not stop in %.0fs", self.hwnd, timeout)
        self._worker = None
        self._active_task = None
        # The worker closes the shared control on its way out; drop our handle
        # so the next preview rebuilds it.
        self._control = None
        if self.status in (RUNNING, PAUSED):
            self.status = IDLE
        logger.info("Session stopped for 0x%08x", self.hwnd)

    def toggle_pause(self) -> None:
        if not self.is_running or self._worker is None:
            return
        if self._worker.is_paused:
            self._worker.resume()
            self.status = RUNNING
        else:
            self._worker.pause()
            self.status = PAUSED

    def mark_finished(self, message: str) -> str:
        """Record a completed run. Returns the id of the task that finished."""
        finished = self._active_task or self.selected
        if self._worker is not None:
            self._progress = getattr(self._worker, "progress", 0)
            self._elapsed = self._worker.elapsed_seconds
        self._worker = None
        self._active_task = None
        self._control = None
        self.status = DONE
        self.message = message
        return finished

    def mark_failed(self, message: str) -> None:
        self._worker = None
        self._active_task = None
        self._control = None
        self.status = ERROR
        self.message = message

    def note_running_before_close(self) -> None:
        """Take the reading that stopping is about to destroy."""
        self._was_running = self.is_running

    @property
    def was_running(self) -> bool:
        """Whether this session had work in flight when it was closed out.

        Read after the session has been stopped, so ``is_running`` no longer
        answers it — and it is the only part worth telling the user about: a
        run that ended is news, an idle card disappearing is not.
        """
        return self._was_running

    def sync_status(self) -> None:
        """Reconcile status with reality — called from the dashboard's timer."""
        if self.status in (DONE, ERROR):
            return
        if not is_alive(self.hwnd):
            self.status = ERROR
            self.message = "Mất cửa sổ"
            return
        if self._worker is not None and not self._worker.is_alive():
            # Ended without a callback (stopped externally).
            self._worker = None
            self._active_task = None
            self._control = None
            self.status = IDLE

    # ── preview ─────────────────────────────────────────────────────────────

    def preview_frame(self) -> Optional[Any]:
        """Latest colour frame of the game window, or ``None``.

        While a worker owns the device contexts we read the frame it already
        captured; capturing here too would use the same GDI handles from a
        second thread.
        """
        if self.is_running and self._worker is not None:
            return self._worker.latest_frame()
        try:
            return self._ensure_control().full_shot()
        except CaptureError:
            return None
        except Exception:
            logger.debug("Preview capture failed for 0x%08x", self.hwnd, exc_info=True)
            return None

    def release(self) -> None:
        """Drop GDI handles held for previews. Safe while a worker runs."""
        if self._control is not None and not self.is_running:
            self._control.close()
            self._control = None

    def _ensure_control(self) -> GameControl:
        if self._control is None:
            self._control = GameControl(self.hwnd)
        return self._control
