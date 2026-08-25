"""In-process fair worker scheduler for 47313 web tasks.

The workbench keeps its SSE protocol (the request thread is the streaming
thread), so this scheduler bounds *concurrency* rather than moving turns to a
separate pool of threads: at most ``max_active`` executions are admitted at
once, one per ``(task_id, execution_id)`` claim, and everything else waits in
a FIFO queue.

Admission semantics mirror 47314's ``ModelingRunManager``:

- FIFO admission order by enqueue time, skipping a user who is already at
  their per-user active cap so one busy user cannot starve the queue;
- global active cap, per-user active cap, per-user queued cap and global
  queued cap;
- provider/database ``BoundedSemaphore`` pairs that callers hold around the
  actual turn so LLM and database concurrency are bounded independently of
  the number of waiting tasks.

The module is intentionally server-agnostic: it has no access to task stores,
repositories or workspaces.  47313 wires it up in ``oc_codex_server``; 47314
keeps its own ``ModelingRunManager`` so its behaviour does not regress.
"""
from __future__ import annotations

import threading
import time
from collections import Counter, deque
from typing import Any, Callable, Optional

DEFAULT_MAX_ACTIVE = 10
DEFAULT_MAX_ACTIVE_PER_USER = 3
DEFAULT_MAX_QUEUED_PER_USER = 3
DEFAULT_MAX_QUEUED = 50
MAX_ACTIVE_LIMIT = 32
MAX_QUEUED_LIMIT = 1000


class SchedulerLimitError(RuntimeError):
    """Raised when a new execution cannot even enter the bounded queue."""

    def __init__(self, code: str, message: str, *, details: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


class _Waiter:
    __slots__ = ("task_id", "user_id", "execution_id", "queued_at", "admitted", "wakeup")

    def __init__(self, task_id: str, user_id: str, execution_id: str, now: float):
        self.task_id = task_id
        self.user_id = user_id
        self.execution_id = execution_id
        self.queued_at = now
        self.admitted = False
        self.wakeup = threading.Event()


class TaskScheduler:
    """Bounded, fair, in-process execution admission gate.

    ``enqueue`` is non-blocking: it either admits the execution immediately
    (when capacity allows) or places it in the FIFO queue.  The waiting thread
    then blocks in ``wait_for_slot`` until the scheduler admits it; the same
    thread continues as the execution worker, preserving the 47313 SSE
    contract.  ``release`` is idempotent and is safe to call from ``finally``
    whether or not the waiter was admitted.
    """

    def __init__(self, max_active: Optional[int] = None,
                 max_active_per_user: Optional[int] = None,
                 max_queued_per_user: Optional[int] = None,
                 max_queued: Optional[int] = None,
                 provider_concurrency: Optional[int] = None,
                 database_concurrency: Optional[int] = None):
        def configured(value: Optional[int], env_name: str, default: int, limit: int) -> int:
            raw = value if value is not None else _env_int(env_name, default)
            if not 1 <= raw <= limit:
                raise ValueError(f"{env_name} must be between 1 and {limit}")
            return raw

        self.max_active = configured(max_active, "TASKS_MAX_ACTIVE",
                                     DEFAULT_MAX_ACTIVE, MAX_ACTIVE_LIMIT)
        self.max_active_per_user = min(
            configured(max_active_per_user, "TASKS_MAX_ACTIVE_PER_USER",
                       DEFAULT_MAX_ACTIVE_PER_USER, MAX_ACTIVE_LIMIT),
            self.max_active)
        self.max_queued_per_user = configured(
            max_queued_per_user, "TASKS_MAX_QUEUED_PER_USER",
            DEFAULT_MAX_QUEUED_PER_USER, MAX_QUEUED_LIMIT)
        self.max_queued = configured(max_queued, "TASKS_MAX_QUEUED",
                                     DEFAULT_MAX_QUEUED, MAX_QUEUED_LIMIT)
        provider_limit = (provider_concurrency if provider_concurrency is not None
                          else _env_int("TASKS_PROVIDER_CONCURRENCY", self.max_active))
        database_limit = (database_concurrency if database_concurrency is not None
                          else _env_int("TASKS_DATABASE_CONCURRENCY", self.max_active))
        if provider_limit < 1 or database_limit < 1:
            raise ValueError("provider/database concurrency must be positive")
        self.provider_concurrency = provider_limit
        self.database_concurrency = database_limit
        self.provider_slots = threading.BoundedSemaphore(provider_limit)
        self.database_slots = threading.BoundedSemaphore(database_limit)
        self._lock = threading.RLock()
        self._queue: deque[_Waiter] = deque()
        self._active: set[str] = set()
        self._active_users: Counter[str] = Counter()

    def enqueue(self, task_id: str, user_id: str, execution_id: str) -> _Waiter:
        """Admit immediately or enqueue in FIFO order.

        Raises :class:`SchedulerLimitError` when the per-user or global queued
        cap is already reached; the caller must then release its execution
        claim and surface the limit to the client.
        """
        with self._lock:
            queued_user = sum(1 for waiter in self._queue if waiter.user_id == user_id)
            if queued_user >= self.max_queued_per_user:
                raise SchedulerLimitError(
                    "USER_QUEUE_LIMIT_REACHED", "该用户排队任务已达到上限",
                    details={"maxQueuedPerUser": self.max_queued_per_user})
            if len(self._queue) >= self.max_queued:
                raise SchedulerLimitError(
                    "GLOBAL_QUEUE_FULL", "全局排队任务已达到上限",
                    details={"maxQueued": self.max_queued})
            waiter = _Waiter(task_id, user_id, execution_id, time.time())
            self._queue.append(waiter)
            self._admit_locked()
            return waiter

    def wait_for_slot(self, waiter: _Waiter) -> bool:
        """Block until ``waiter`` is admitted.

        Returns ``True`` once admitted.  The scheduler admits in FIFO order
        and skips users already at their active cap, mirroring 47314's
        dispatch so one busy user cannot starve other users.
        """
        while not waiter.admitted:
            waiter.wakeup.wait()
        return True

    def release(self, waiter: _Waiter) -> None:
        """Release an admitted execution or remove a still-queued waiter."""
        with self._lock:
            if waiter.admitted:
                self._active.discard(waiter.execution_id)
                if waiter.user_id:
                    remaining = self._active_users[waiter.user_id] - 1
                    if remaining <= 0:
                        self._active_users.pop(waiter.user_id, None)
                    else:
                        self._active_users[waiter.user_id] = remaining
                waiter.admitted = False
                self._admit_locked()
            else:
                try:
                    self._queue.remove(waiter)
                except ValueError:
                    pass
            waiter.wakeup.set()

    def position(self, waiter: _Waiter) -> tuple[int, int]:
        """Return ``(1-based queue position, queue length)`` for a waiter."""
        with self._lock:
            try:
                return self._queue.index(waiter) + 1, len(self._queue)
            except ValueError:
                return 0, len(self._queue)

    def snapshot(self) -> dict[str, Any]:
        """Transient scheduling state for observability/status endpoints."""
        with self._lock:
            return {
                "active": len(self._active),
                "queued": len(self._queue),
                "maxActive": self.max_active,
                "maxActivePerUser": self.max_active_per_user,
                "maxQueuedPerUser": self.max_queued_per_user,
                "maxQueued": self.max_queued,
                "providerConcurrency": self.provider_concurrency,
                "databaseConcurrency": self.database_concurrency,
                "queue": [{
                    "taskId": waiter.task_id,
                    "userId": waiter.user_id,
                    "executionId": waiter.execution_id,
                    "queuedAt": waiter.queued_at,
                } for waiter in self._queue],
            }

    def _admit_locked(self) -> list[_Waiter]:
        capacity = self.max_active - len(self._active)
        admitted: list[_Waiter] = []
        for waiter in list(self._queue):
            if len(admitted) >= capacity:
                break
            if self._active_users[waiter.user_id] >= self.max_active_per_user:
                continue
            self._queue.remove(waiter)
            self._active.add(waiter.execution_id)
            if waiter.user_id:
                self._active_users[waiter.user_id] += 1
            waiter.admitted = True
            waiter.wakeup.set()
            admitted.append(waiter)
        return admitted


def _env_int(name: str, default: int) -> int:
    raw = __import__("os").environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc


def build_scheduler() -> TaskScheduler:
    """Build the process-wide scheduler from environment configuration."""
    return TaskScheduler()
