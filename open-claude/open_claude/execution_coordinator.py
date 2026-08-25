"""Shared execution coordination for 47313 (workbench) and 47314 (standalone).

This module is the single scheduling core used by both services:

- bounded global/per-user active and queued quotas;
- fair FIFO admission that skips users already at their active cap;
- an explicit waiter lifecycle (WAITING -> ADMITTED | CANCELLED | RELEASED)
  so cancelling a queued execution never leaves a thread waiting forever;
- a strictly bounded worker pool: the HTTP handler never waits on a queue;
  ``POST /send`` claims, records the user event and returns ``202``;
- provider/database ``BoundedSemaphore`` pairs that callers hold only around
  the actual LLM/database operation;
- durable execution leases + per-task monotonic fences via
  ``execution_lease`` (file/flock or Redis token+hash), owned exclusively by
  the coordinator (no second per-task lease claim on the service side);
- heartbeat renewal with lease-loss detection (a lost lease cancels the
  worker and forbids formal side effects);
- a unified metrics structure for ``/health``.

Backends:

- local/file: in-process queue + counters; the lease is durable (flock files
  shared by every process on the same host) so a second process cannot claim
  the same task; quota counters are per-process and reported accordingly;
- redis: queue, counters, lease, fences and fairness all live in Redis behind
  atomic Lua scripts, so multiple instances share one quota budget.

Identity model
--------------

- ``resource_id`` is the mutex key (47313 ``task.id`` / 47314 ``run.run_id``):
  only one execution per resource may be active or queued at any time;
- ``execution_id`` is a fresh per-attempt UUID held by exactly one claim;
- ``owner_instance_id`` identifies the process that created the claim; a
  Redis dispatcher may only admit its own queued executions (owner-affinity),
  because the executable payload lives in the owner's memory;
- ``fence_token`` is a monotonic per-resource counter; every formal side
  effect is guarded by ``ExecutionContext.assert_current()`` which checks the
  token, the fence and the owner before writing state.

Queued leases use a longer TTL (``queued_lease_seconds``) than admitted
executions and are renewed by the owner's dispatcher, so a long queue wait can
never turn into a ghost queue item.  Expired admitted/queued leases are
recovered through a bounded ``SCAN`` (never ``KEYS``) plus an atomic Lua
cleanup; only one instance can win the recovery.

The module never imports ``oc_codex_server`` or ``standalone_modeling_server``;
services connect through an :class:`ExecutionAdapter`.
"""
from __future__ import annotations

import os
import socket
import threading
import time
import uuid
from collections import Counter, deque
import queue
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol

from open_claude.execution_lease import (
    DEFAULT_LEASE_SECONDS,
    FileExecutionLeaseStore,
    LeaseRecord,
    RENEW_SCRIPT,
    RedisExecutionLeaseStore,
    _safe_task_id,
)

DEFAULT_MAX_ACTIVE = 10
DEFAULT_MAX_ACTIVE_PER_USER = 3
DEFAULT_MAX_QUEUED_PER_USER = 3
DEFAULT_MAX_QUEUED = 50
MAX_ACTIVE_LIMIT = 32
MAX_QUEUED_LIMIT = 1000
DEFAULT_PROVIDER_CONCURRENCY = 10
DEFAULT_DATABASE_CONCURRENCY = 10
DEFAULT_HEARTBEAT_SECONDS = 5.0
DEFAULT_MAX_HEARTBEAT_FAILURES = 3
# Queued executions are expected to wait longer than one execution lease;
# the owner's dispatcher also renews its own queued items so a long wait can
# never expire the token while the owner is alive.
DEFAULT_QUEUED_LEASE_SECONDS = 600.0
# Metadata lives on past the ownership token so an expired execution can be
# recovered atomically instead of disappearing together with the token.
DEFAULT_RECOVERY_SECONDS = 3600.0


class SchedulerLimitError(RuntimeError):
    """Raised when a new execution cannot even enter the bounded queue."""

    def __init__(self, code: str, message: str, *, details: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


class CancellationToken:
    """Cooperative cancellation shared by a worker and its heartbeat."""

    def __init__(self):
        self._event = threading.Event()
        self._reason = ""

    def cancel(self, reason: str) -> None:
        if not self._event.is_set():
            self._reason = str(reason)
        self._event.set()

    @property
    def reason(self) -> str:
        return self._reason or ""

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def throw_if_cancelled(self) -> None:
        if self._event.is_set():
            raise ExecutionCancelled(self._reason or "cancelled")

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Wait until cancelled; returns True when cancelled before timeout."""
        return self._event.wait(timeout)


class ExecutionCancelled(Exception):
    """Raised inside a worker when its execution was cancelled or lost."""


@dataclass(frozen=True)
class CoordinatorConfig:
    """Bounded scheduling configuration.

    Environment variable parsing happens at the service entry point; the
    shared module only receives this object.
    """

    service_namespace: str = "ontology"
    max_active: int = DEFAULT_MAX_ACTIVE
    max_active_per_user: int = DEFAULT_MAX_ACTIVE_PER_USER
    max_queued_per_user: int = DEFAULT_MAX_QUEUED_PER_USER
    max_queued: int = DEFAULT_MAX_QUEUED
    max_active_limit: int = MAX_ACTIVE_LIMIT
    max_queued_limit: int = MAX_QUEUED_LIMIT
    provider_concurrency: int = DEFAULT_PROVIDER_CONCURRENCY
    database_concurrency: int = DEFAULT_DATABASE_CONCURRENCY
    lease_seconds: float = DEFAULT_LEASE_SECONDS
    queued_lease_seconds: float = DEFAULT_QUEUED_LEASE_SECONDS
    recovery_seconds: float = DEFAULT_RECOVERY_SECONDS
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS
    max_heartbeat_failures: int = DEFAULT_MAX_HEARTBEAT_FAILURES
    backend: str = "file"          # none | file | redis
    lease_dir: Optional[str] = None
    redis_url: Optional[str] = None
    redis_prefix: str = "ontology:"
    worker_pool_size: Optional[int] = None

    def validate(self) -> "CoordinatorConfig":
        if not 1 <= self.max_active <= self.max_active_limit:
            raise ValueError(f"max_active must be between 1 and {self.max_active_limit}")
        if not 1 <= self.max_queued <= self.max_queued_limit:
            raise ValueError(f"max_queued must be between 1 and {self.max_queued_limit}")
        if not 1 <= self.max_active_per_user <= self.max_active:
            raise ValueError("max_active_per_user must be between 1 and max_active")
        if not 1 <= self.max_queued_per_user:
            raise ValueError("max_queued_per_user must be positive")
        if self.provider_concurrency < 1 or self.database_concurrency < 1:
            raise ValueError("provider/database concurrency must be positive")
        if self.lease_seconds <= 0 or self.heartbeat_seconds <= 0:
            raise ValueError("lease/heartbeat intervals must be positive")
        if self.queued_lease_seconds < self.lease_seconds:
            raise ValueError("queued_lease_seconds must be >= lease_seconds")
        if self.recovery_seconds < self.queued_lease_seconds:
            raise ValueError("recovery_seconds must be >= queued_lease_seconds")
        if self.max_heartbeat_failures < 1:
            raise ValueError("max_heartbeat_failures must be positive")
        return self


@dataclass
class ClaimResult:
    """Outcome of one execution claim."""

    decision: str        # admitted | queued | active_exists | user_queue_limit | global_queue_full
    resource_id: str
    execution_id: str
    fence_token: int = 0
    queue_position: int = 0
    queue_length: int = 0
    error_code: str = ""
    error: str = ""


class Waiter:
    """One queued execution with an explicit lifecycle.

    States: WAITING -> ADMITTED | CANCELLED | RELEASED.  A queued execution is
    admitted exactly once; ``cancel``/``release`` are idempotent and always
    wake the waiter so no thread waits forever.
    """

    __slots__ = ("resource_id", "execution_id", "user_id", "queued_at", "state", "wakeup",
                 "fence_token", "attempt", "token")

    WAITING = "WAITING"
    ADMITTED = "ADMITTED"
    CANCELLED = "CANCELLED"
    RELEASED = "RELEASED"

    def __init__(self, resource_id: str, execution_id: str, user_id: str,
                 fence_token: int,
                 attempt: int, token: CancellationToken, now: float):
        self.resource_id = resource_id
        self.execution_id = execution_id
        self.user_id = user_id
        self.queued_at = now
        self.state = self.WAITING
        self.fence_token = fence_token
        self.attempt = attempt
        self.token = token
        self.wakeup = threading.Event()

    def wait_for_slot(self, timeout: Optional[float] = None) -> bool:
        """Block until admitted (True) or cancelled/released (False)."""
        while self.state == self.WAITING:
            if not self.wakeup.wait(timeout):
                return False
        return self.state == self.ADMITTED


class _TaskHandle:
    """Minimal future-like handle with a timeout-aware wait.

    Used instead of ``concurrent.futures.Future`` so shutdown can bound the
    wait for running workers without depending on ThreadPoolExecutor internals.
    """

    __slots__ = ("_done", "_exc")

    def __init__(self) -> None:
        self._done = threading.Event()
        self._exc: Optional[BaseException] = None

    def set_result(self) -> None:
        self._done.set()

    def set_exception(self, exc: BaseException) -> None:
        self._exc = exc
        self._done.set()

    def done(self) -> bool:
        return self._done.is_set()

    def result(self, timeout: Optional[float] = None) -> None:
        if not self._done.wait(timeout):
            raise TimeoutError("task still running")
        if self._exc is not None:
            raise self._exc


class _BoundedWorkerPool:
    """Bounded daemon-thread pool with an explicit, bounded lifecycle.

    ``ThreadPoolExecutor`` threads are non-daemon and ``shutdown(wait=True)``
    blocks until every running worker returns, so one hung worker would hang
    process exit forever.  This pool uses daemon threads (they never block
    interpreter shutdown) and a bounded pending queue; ``shutdown`` only
    stops accepting work and wakes idle workers - stragglers are abandoned to
    lease expiry + recovery instead of being waited on.
    """

    def __init__(self, max_workers: int, name_prefix: str = "exec-worker"):
        self._max_workers = max(1, int(max_workers))
        self._pending: queue.Queue[Optional[Callable[[], None]]] = queue.Queue(
            maxsize=self._max_workers)
        self._lock = threading.Lock()
        self._stopped = False
        self._threads: list[threading.Thread] = []
        for index in range(self._max_workers):
            thread = threading.Thread(target=self._worker_loop,
                                      name=f"{name_prefix}-{index}",
                                      daemon=True)
            thread.start()
            self._threads.append(thread)

    def _worker_loop(self) -> None:
        while True:
            task = self._pending.get()
            if task is None:
                return
            try:
                task()
            except Exception:
                pass

    def submit(self, task: Callable[[], None]) -> bool:
        with self._lock:
            if self._stopped:
                return False
            try:
                self._pending.put_nowait(task)
            except queue.Full:
                return False
        return True

    def shutdown(self) -> None:
        """Stop accepting work and wake idle workers; never blocks."""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
        for _ in self._threads:
            try:
                self._pending.put_nowait(None)
            except queue.Full:
                pass


class ExecutionAdapter(Protocol):
    """Bridge implemented by 47313 and 47314.

    The coordinator owns quotas, the queue, the worker pool, leases, fences
    and heartbeats; the adapter owns service state and the actual work.
    """

    scope: str
    instance_id: str

    def record_event(self, execution_id: str, event: dict) -> None: ...
    def on_queued(self, execution_id: str, position: int, queue_length: int) -> None: ...
    def on_started(self, execution_id: str) -> None: ...
    def run_worker(self, execution_id: str, token: CancellationToken) -> None: ...
    def on_finished(self, execution_id: str, ok: bool, token: CancellationToken) -> None: ...


class _Execution:
    __slots__ = ("resource_id", "execution_id", "user_id", "token", "fence_token", "attempt",
                 "queued", "waiter", "future", "heartbeat_stop", "heartbeat_thread",
                 "abandoned")

    def __init__(self, resource_id: str, execution_id: str, user_id: str,
                 token: CancellationToken,
                 fence_token: int, attempt: int, queued: bool, waiter: Optional[Waiter]):
        self.resource_id = resource_id
        self.execution_id = execution_id
        self.user_id = user_id
        self.token = token
        self.fence_token = fence_token
        self.attempt = attempt
        self.queued = queued
        self.waiter = waiter
        self.future: Optional["_TaskHandle"] = None
        self.heartbeat_stop: Optional[threading.Event] = None
        self.heartbeat_thread: Optional[threading.Thread] = None
        self.abandoned = False


class _LocalBackend:
    """In-process queue + counters; durable lease via ``lease_store``.

    ``lease_store`` may be a FileExecutionLeaseStore (flock, same-host
    multi-process safe) or None (memory-only, processLocal).  The backend is
    keyed by ``resource_id`` (the mutex); the durable lease and the in-memory
    maps store the unique ``execution_id`` of the current claim.
    """

    def __init__(self, config: CoordinatorConfig, lease_store: Optional[Any],
                 instance_id: str, clock: Callable[[], float] = time.time):
        self.config = config
        self.lease_store = lease_store
        self.instance_id = instance_id
        self._clock = clock
        self._lock = threading.RLock()
        self._queue: deque[Waiter] = deque()
        self._active: set[str] = set()
        self._active_fences: dict[str, int] = {}
        self._active_users: Counter[str] = Counter()
        self._execution_users: dict[str, str] = {}
        self._memory_leases: dict[str, LeaseRecord] = {}
        self._memory_fence: dict[str, int] = {}
        self._leases_created = 0
        self._expired_recovered = 0

    # -- claim ---------------------------------------------------------------

    def claim(self, resource_id: str, execution_id: str, user_id: str,
              attempt: int, now: Optional[float] = None,
              lease_pre_claimed: bool = False) -> tuple[ClaimResult, Optional[Waiter]]:
        del lease_pre_claimed  # no service double-claim; coordinator owns the lease
        timestamp = float(now if now is not None else self._clock())
        if self.lease_store is not None:
            ok, active = self._lease_claim(resource_id, execution_id, user_id,
                                           attempt, timestamp)
            if not ok:
                return (ClaimResult(
                    "active_exists", resource_id, execution_id,
                    error_code="ACTIVE_RUN_EXISTS",
                    error="该任务已有执行正在进行",
                    fence_token=active.fence_token if active else 0), None)
            fence = active.fence_token if active else 0
        else:
            with self._lock:
                if resource_id in self._memory_leases:
                    active = self._memory_leases[resource_id]
                    return (ClaimResult(
                        "active_exists", resource_id, execution_id,
                        error_code="ACTIVE_RUN_EXISTS",
                        error="该任务已有执行正在进行",
                        fence_token=active.fence_token), None)
                fence = self._memory_fence.get(resource_id, 0) + 1
                self._memory_fence[resource_id] = fence
                self._memory_leases[resource_id] = LeaseRecord(
                    task_id=resource_id, execution_id=execution_id,
                    owner_id=self.instance_id, fence_token=fence,
                    attempt=attempt, acquired_at=timestamp,
                    lease_expires_at=timestamp + self.config.queued_lease_seconds,
                    heartbeat_at=timestamp, status="CLAIMED", user_id=user_id,
                    queued_at=timestamp)
        with self._lock:
            if len(self._active) < self.config.max_active \
                    and self._active_users[user_id] < self.config.max_active_per_user:
                self._active.add(resource_id)
                self._active_fences[resource_id] = fence
                self._execution_users[resource_id] = user_id
                if user_id:
                    self._active_users[user_id] += 1
                return (ClaimResult("admitted", resource_id, execution_id,
                                    fence_token=fence), None)
            queued_user = sum(1 for waiter in self._queue if waiter.user_id == user_id)
            if queued_user >= self.config.max_queued_per_user:
                return (ClaimResult(
                    "user_queue_limit", resource_id, execution_id,
                    error_code="USER_QUEUE_LIMIT_REACHED",
                    error="该用户排队任务已达到上限"), None)
            if len(self._queue) >= self.config.max_queued:
                return (ClaimResult(
                    "global_queue_full", resource_id, execution_id,
                    error_code="GLOBAL_QUEUE_FULL",
                    error="全局排队任务已达到上限"), None)
            token = CancellationToken()
            waiter = Waiter(resource_id, execution_id, user_id, fence,
                            attempt, token, timestamp)
            self._queue.append(waiter)
            return (ClaimResult(
                "queued", resource_id, execution_id, fence_token=fence,
                queue_position=self._queue.index(waiter) + 1,
                queue_length=len(self._queue)), waiter)

    def _lease_claim(self, resource_id: str, execution_id: str, user_id: str,
                     attempt: int, timestamp: float,
                     status: str = "CLAIMED") -> tuple[bool, Optional[LeaseRecord]]:
        try:
            previous = self.lease_store.read(resource_id)
            ok, record = self.lease_store.try_claim(
                resource_id, self.instance_id, execution_id,
                lease_seconds=self.config.queued_lease_seconds,
                attempt=attempt, status=status, user_id=user_id,
                now=timestamp)
        except Exception:
            # A lease-store failure must not block the degraded single-process
            # case: fall back to the in-memory lease.
            with self._lock:
                if resource_id in self._memory_leases:
                    return False, self._memory_leases[resource_id]
                fence = self._memory_fence.get(resource_id, 0) + 1
                self._memory_fence[resource_id] = fence
                record = LeaseRecord(
                    task_id=resource_id, execution_id=execution_id,
                    owner_id=self.instance_id, fence_token=fence,
                    attempt=attempt, acquired_at=timestamp,
                    lease_expires_at=timestamp + self.config.queued_lease_seconds,
                    heartbeat_at=timestamp, status="CLAIMED", user_id=user_id)
                self._memory_leases[resource_id] = record
                return True, record
        if ok:
            if previous is not None and previous.expired(timestamp) \
                    and previous.owner_id != self.instance_id:
                self._expired_recovered += 1
            self._leases_created += 1
        return ok, record

    # -- admission / cancellation / release -----------------------------------

    def admit_next(self) -> Optional[str]:
        with self._lock:
            capacity = self.config.max_active - len(self._active)
            if capacity <= 0:
                return None
            for waiter in list(self._queue):
                if waiter.user_id and self._active_users[waiter.user_id] >= self.config.max_active_per_user:
                    continue
                self._queue.remove(waiter)
                waiter.state = Waiter.ADMITTED
                waiter.wakeup.set()
                self._active.add(waiter.resource_id)
                self._active_fences[waiter.resource_id] = waiter.fence_token
                self._execution_users[waiter.resource_id] = waiter.user_id
                if waiter.user_id:
                    self._active_users[waiter.user_id] += 1
                return waiter.resource_id
            return None

    def cancel(self, resource_id: str, execution_id: str,
              fence_token: int) -> bool:
        del execution_id  # local queue is keyed by resource_id
        with self._lock:
            for waiter in self._queue:
                if waiter.resource_id == resource_id:
                    self._queue.remove(waiter)
                    waiter.state = Waiter.CANCELLED
                    waiter.wakeup.set()
                    self._release_lease(resource_id, fence_token)
                    return True
            return False

    def release(self, resource_id: str, execution_id: str,
                fence_token: int, was_queued: bool) -> None:
        del execution_id  # local release is fence-guarded, not token-guarded
        with self._lock:
            # A queued waiter may be released without ever running; wake it so
            # ``wait_for_slot`` returns False instead of blocking forever.
            for waiter in list(self._queue):
                if waiter.resource_id == resource_id:
                    self._queue.remove(waiter)
                    waiter.state = Waiter.RELEASED
                    waiter.wakeup.set()
                    break
            # A stale fence must never release the newer execution's active
            # slot; only the fence that admitted this resource may free it.
            if self._active_fences.get(resource_id) == fence_token:
                self._active.discard(resource_id)
                self._active_fences.pop(resource_id, None)
                user_id = self._execution_users.pop(resource_id, "")
                if user_id:
                    remaining = self._active_users[user_id] - 1
                    if remaining <= 0:
                        self._active_users.pop(user_id, None)
                    else:
                        self._active_users[user_id] = remaining
            self._release_lease(resource_id, fence_token)

    def heartbeat(self, resource_id: str, execution_id: str) -> bool:
        if self.lease_store is None:
            return True
        try:
            return bool(self.lease_store.renew(
                resource_id, execution_id,
                lease_seconds=self.config.lease_seconds))
        except Exception:
            return False

    def verify_fence(self, resource_id: str, execution_id: str,
                     fence_token: int) -> bool:
        record = self.read(resource_id)
        if record is None:
            return False
        return (str(record.execution_id) == str(execution_id)
                and int(record.fence_token) == int(fence_token)
                and str(record.owner_id) == str(self.instance_id))

    def read(self, resource_id: str) -> Optional[LeaseRecord]:
        if self.lease_store is not None:
            try:
                return self.lease_store.read(resource_id)
            except Exception:
                return None
        with self._lock:
            return self._memory_leases.get(resource_id)

    def _release_lease(self, resource_id: str, fence_token: int) -> None:
        if self.lease_store is not None:
            try:
                current = self.lease_store.read(resource_id)
                if current is not None \
                        and int(current.fence_token) == int(fence_token):
                    self.lease_store.release(resource_id, current.execution_id)
            except Exception:
                pass
            return
        with self._lock:
            current = self._memory_leases.get(resource_id)
            if current is not None \
                    and int(current.fence_token) == int(fence_token):
                self._memory_leases.pop(resource_id, None)

    def recover_expired(self) -> int:
        """Reclaim expired in-memory leases (memory-only backend)."""
        if self.lease_store is not None:
            # File leases are reclaimed lazily at claim time.
            return 0
        now = self._clock()
        recovered = 0
        with self._lock:
            for resource_id, record in list(self._memory_leases.items()):
                if record.expired(now):
                    self._memory_leases.pop(resource_id, None)
                    if self._active_fences.get(resource_id) == record.fence_token:
                        self._active.discard(resource_id)
                        self._active_fences.pop(resource_id, None)
                        user_id = self._execution_users.pop(resource_id, "")
                        if user_id:
                            remaining = self._active_users[user_id] - 1
                            if remaining <= 0:
                                self._active_users.pop(user_id, None)
                            else:
                                self._active_users[user_id] = remaining
                    recovered += 1
        if recovered:
            self._expired_recovered += recovered
        return recovered

    def metrics(self) -> dict[str, Any]:
        with self._lock:
            queued_times = [waiter.queued_at for waiter in self._queue]
            return {
                "activeRuns": len(self._active),
                "queuedRuns": len(self._queue),
                "oldestQueuedSeconds": (
                    max(0.0, self._clock() - min(queued_times)) if queued_times else 0.0),
                "activeLeases": self._leases_created,
                "expiredLeasesRecovered": self._expired_recovered,
            }


REDIS_CLAIM_SCRIPT = """
-- KEYS: 1=token key, 2=meta key, 3=fence key, 4=global queue,
--       5=counters:active, 6=counters:queued
-- ARGV: 1=token(execution_id), 2=user_id, 3=owner_instance_id, 4=now,
--       5=lease_ms, 6=max_active, 7=max_active_per_user, 8=max_queued,
--       9=max_queued_per_user, 10=attempt, 11=prefix, 12=counter ttl ms,
--       13=queued_ttl_ms, 14=recovery_ttl_ms, 15=resource_id
if redis.call("exists", KEYS[1]) == 1 then
  return {-1, redis.call("hget", KEYS[2], "execution_id")}
end
local fence = tonumber(redis.call("incr", KEYS[3]))
local user_active_key = ARGV[11] .. "counters:active:" .. ARGV[2]
local user_queued_key = ARGV[11] .. "counters:queued:" .. ARGV[2]
local user_queue_key = ARGV[11] .. "queue:" .. ARGV[2]
local active = tonumber(redis.call("get", KEYS[5]) or "0")
local user_active = tonumber(redis.call("get", user_active_key) or "0")
if active < tonumber(ARGV[6]) and user_active < tonumber(ARGV[7]) then
  redis.call("set", KEYS[1], ARGV[1], "PX", ARGV[5])
  redis.call("hset", KEYS[2],
    "resource_id", ARGV[15],
    "execution_id", ARGV[1],
    "user_id", ARGV[2],
    "owner_instance_id", ARGV[3],
    "fence_token", tostring(fence),
    "attempt", ARGV[10],
    "acquired_at", ARGV[4],
    "lease_expires_at", ARGV[4] + ARGV[5] / 1000,
    "heartbeat_at", ARGV[4],
    "status", "ADMITTED")
  redis.call("pexpire", KEYS[2], ARGV[14])
  redis.call("incr", KEYS[5])
  redis.call("incr", user_active_key)
  redis.call("pexpire", KEYS[5], ARGV[12])
  redis.call("pexpire", user_active_key, ARGV[12])
  return {1, fence, 0, 0}
end
local queued = tonumber(redis.call("get", KEYS[6]) or "0")
local user_queued = tonumber(redis.call("get", user_queued_key) or "0")
if queued >= tonumber(ARGV[8]) then
  return {-2, 0}
end
if user_queued >= tonumber(ARGV[9]) then
  return {-3, 0}
end
-- A queued execution owns the lease for the (longer) queued TTL; the meta
-- survives on the recovery TTL so a dead owner can be recovered atomically.
redis.call("set", KEYS[1], ARGV[1], "PX", ARGV[13])
redis.call("hset", KEYS[2],
  "resource_id", ARGV[15],
  "execution_id", ARGV[1],
  "user_id", ARGV[2],
  "owner_instance_id", ARGV[3],
  "fence_token", tostring(fence),
  "attempt", ARGV[10],
  "acquired_at", ARGV[4],
  "lease_expires_at", ARGV[4] + ARGV[13] / 1000,
  "heartbeat_at", ARGV[4],
  "status", "QUEUED",
  "queued_at", ARGV[4])
redis.call("pexpire", KEYS[2], ARGV[14])
redis.call("rpush", KEYS[4], ARGV[15])
redis.call("rpush", user_queue_key, ARGV[15])
redis.call("incr", KEYS[6])
redis.call("incr", user_queued_key)
redis.call("pexpire", KEYS[6], ARGV[12])
redis.call("pexpire", user_queued_key, ARGV[12])
return {0, fence, tonumber(redis.call("llen", KEYS[4])), tonumber(redis.call("llen", user_queue_key))}
"""

REDIS_ADMIT_SCRIPT = """
-- KEYS: 1=global queue, 2=counters:active, 3=counters:queued
-- ARGV: 1=max_active, 2=max_active_per_user, 3=now, 4=lease_ms,
--       5=prefix, 6=counter ttl ms, 7=instance_id, 8=recovery_ttl_ms
-- Owner-affinity admission: a dispatcher may only admit executions it owns
-- (the executable payload lives in the owner's memory); other instances'
-- items are rotated without being admitted or deleted.
local total = tonumber(redis.call("llen", KEYS[1]))
if total == 0 then return {0} end
local scanned = 0
while scanned < total do
  local id = redis.call("lindex", KEYS[1], 0)
  if not id then break end
  local meta_key = ARGV[5] .. "execution:" .. id .. ":meta"
  local owner = redis.call("hget", meta_key, "owner_instance_id") or ""
  local user = redis.call("hget", meta_key, "user_id") or ""
  local active = tonumber(redis.call("get", KEYS[2]) or "0")
  local user_active = tonumber(redis.call("get", ARGV[5] .. "counters:active:" .. user) or "0")
  if owner == ARGV[7] and active < tonumber(ARGV[1]) and user_active < tonumber(ARGV[2]) then
    redis.call("lpop", KEYS[1])
    redis.call("lrem", ARGV[5] .. "queue:" .. user, 1, id)
    redis.call("incr", KEYS[2])
    redis.call("incr", ARGV[5] .. "counters:active:" .. user)
    local q = tonumber(redis.call("get", KEYS[3]) or "0")
    if q > 0 then redis.call("set", KEYS[3], q - 1) end
    local uq = tonumber(redis.call("get", ARGV[5] .. "counters:queued:" .. user) or "0")
    if uq > 0 then redis.call("set", ARGV[5] .. "counters:queued:" .. user, uq - 1) end
    redis.call("hset", meta_key,
      "status", "ADMITTED", "started_at", ARGV[3],
      "lease_expires_at", ARGV[3] + ARGV[4] / 1000)
    -- Admitted executions switch to the execution lease TTL + heartbeat.
    redis.call("pexpire", ARGV[5] .. "execution:" .. id .. ":token", ARGV[4])
    redis.call("pexpire", meta_key, ARGV[8])
    redis.call("pexpire", KEYS[2], ARGV[6])
    redis.call("pexpire", ARGV[5] .. "counters:active:" .. user, ARGV[6])
    redis.call("pexpire", ARGV[5] .. "counters:queued:" .. user, ARGV[6])
    return {1, id}
  end
  redis.call("lpop", KEYS[1])
  redis.call("rpush", KEYS[1], id)
  scanned = scanned + 1
end
return {0}
"""

REDIS_RENEW_QUEUED_SCRIPT = """
-- KEYS: 1=global queue
-- ARGV: 1=prefix, 2=instance_id, 3=queued_ttl_ms, 4=recovery_ttl_ms
-- The owner dispatcher renews its own queued items so a long queue wait
-- cannot expire the token while the owner is still alive.
local total = tonumber(redis.call("llen", KEYS[1]))
if total == 0 then return 0 end
local renewed = 0
local i = 0
while i < total do
  local id = redis.call("lindex", KEYS[1], i)
  if not id then break end
  local meta_key = ARGV[1] .. "execution:" .. id .. ":meta"
  if (redis.call("hget", meta_key, "owner_instance_id") or "") == ARGV[2]
     and (redis.call("hget", meta_key, "status") or "") == "QUEUED" then
    redis.call("pexpire", ARGV[1] .. "execution:" .. id .. ":token", ARGV[3])
    redis.call("pexpire", meta_key, ARGV[4])
    renewed = renewed + 1
  end
  i = i + 1
end
return renewed
"""

REDIS_RELEASE_SCRIPT = """
-- KEYS: 1=token key, 2=meta key
-- ARGV: 1=token(execution_id), 2=fence_token, 3=prefix,
--       4=counter ttl ms, 5=resource_id
if redis.call("get", KEYS[1]) ~= ARGV[1] then
  return 0
end
if redis.call("hget", KEYS[2], "fence_token") ~= tostring(ARGV[2]) then
  return 0
end
local user = redis.call("hget", KEYS[2], "user_id") or ""
local was_queued = redis.call("hget", KEYS[2], "status") == "QUEUED"
redis.call("del", KEYS[1])
redis.call("del", KEYS[2])
local active_key = ARGV[3] .. "counters:active"
local user_active_key = ARGV[3] .. "counters:active:" .. user
local queued_key = ARGV[3] .. "counters:queued"
local user_queued_key = ARGV[3] .. "counters:queued:" .. user
if was_queued then
  -- Queue items are resource ids (claim pushes ARGV[resource_id]); the
  -- ownership token is the execution id and must not be used for lrem.
  redis.call("lrem", ARGV[3] .. "queue", 1, ARGV[5])
  redis.call("lrem", ARGV[3] .. "queue:" .. user, 1, ARGV[5])
  local q = tonumber(redis.call("get", queued_key) or "0")
  if q > 0 then redis.call("set", queued_key, q - 1) end
  local uq = tonumber(redis.call("get", user_queued_key) or "0")
  if uq > 0 then redis.call("set", user_queued_key, uq - 1) end
else
  local a = tonumber(redis.call("get", active_key) or "0")
  if a > 0 then redis.call("set", active_key, a - 1) end
  local ua = tonumber(redis.call("get", user_active_key) or "0")
  if ua > 0 then redis.call("set", user_active_key, ua - 1) end
end
redis.call("pexpire", active_key, ARGV[4])
redis.call("pexpire", user_active_key, ARGV[4])
redis.call("pexpire", queued_key, ARGV[4])
redis.call("pexpire", user_queued_key, ARGV[4])
return 1
"""

REDIS_CANCEL_SCRIPT = """
-- KEYS: 1=token key, 2=meta key
-- ARGV: 1=token(execution_id), 2=fence_token, 3=prefix, 4=resource_id
if redis.call("get", KEYS[1]) ~= ARGV[1] then
  return 0
end
if redis.call("hget", KEYS[2], "fence_token") ~= tostring(ARGV[2]) then
  return 0
end
local status = redis.call("hget", KEYS[2], "status")
if status ~= "QUEUED" then
  redis.call("hset", KEYS[2], "cancel_requested", "1")
  return 0
end
local user = redis.call("hget", KEYS[2], "user_id") or ""
redis.call("del", KEYS[1])
redis.call("del", KEYS[2])
redis.call("lrem", ARGV[3] .. "queue", 1, ARGV[4])
redis.call("lrem", ARGV[3] .. "queue:" .. user, 1, ARGV[4])
local q = tonumber(redis.call("get", ARGV[3] .. "counters:queued") or "0")
if q > 0 then redis.call("set", ARGV[3] .. "counters:queued", q - 1) end
local uq = tonumber(redis.call("get", ARGV[3] .. "counters:queued:" .. user) or "0")
if uq > 0 then redis.call("set", ARGV[3] .. "counters:queued:" .. user, uq - 1) end
return 1
"""

REDIS_RECOVER_SCRIPT = """
-- KEYS: 1=token key, 2=meta key
-- ARGV: 1=token(execution_id), 2=prefix, 3=counter ttl ms
-- Recover an execution whose token expired (crashed worker / dead owner) but
-- whose metadata still exists inside the recovery window.  Only one instance
-- can win: the meta key is deleted atomically here, and a re-claimed token
-- makes this a no-op so a new execution is never touched.
if redis.call("exists", KEYS[1]) == 1 then
  return 0
end
local status = redis.call("hget", KEYS[2], "status")
if not status then
  return 0
end
if status ~= "ADMITTED" and status ~= "QUEUED" then
  return 0
end
local user = redis.call("hget", KEYS[2], "user_id") or ""
local was_queued = status == "QUEUED"
redis.call("del", KEYS[2])
local active_key = ARGV[2] .. "counters:active"
local user_active_key = ARGV[2] .. "counters:active:" .. user
local queued_key = ARGV[2] .. "counters:queued"
local user_queued_key = ARGV[2] .. "counters:queued:" .. user
if was_queued then
  redis.call("lrem", ARGV[2] .. "queue", 1, ARGV[1])
  redis.call("lrem", ARGV[2] .. "queue:" .. user, 1, ARGV[1])
  local q = tonumber(redis.call("get", queued_key) or "0")
  if q > 0 then redis.call("set", queued_key, q - 1) end
  local uq = tonumber(redis.call("get", user_queued_key) or "0")
  if uq > 0 then redis.call("set", user_queued_key, uq - 1) end
else
  local a = tonumber(redis.call("get", active_key) or "0")
  if a > 0 then redis.call("set", active_key, a - 1) end
  local ua = tonumber(redis.call("get", user_active_key) or "0")
  if ua > 0 then redis.call("set", user_active_key, ua - 1) end
end
redis.call("pexpire", active_key, ARGV[3])
redis.call("pexpire", user_active_key, ARGV[3])
redis.call("pexpire", queued_key, ARGV[3])
redis.call("pexpire", user_queued_key, ARGV[3])
return 1
"""

class _RedisBackend:
    """Everything (lease, fence, quotas, queue) lives in Redis via Lua.

    Multiple instances share one quota budget and one fair queue; the claim
    script atomically checks the per-task lease and both quota caps.  Only
    the owning instance's dispatcher may admit a queued execution (owner
    affinity), because the executable payload lives in the owner's memory.
    """

    def __init__(self, config: CoordinatorConfig, client: Any,
                 instance_id: str, clock: Callable[[], float] = time.time):
        self.config = config
        self._client = client
        self.instance_id = instance_id
        self._clock = clock
        self._prefix = str(config.redis_prefix or "ontology:")
        if not self._prefix.endswith(":"):
            self._prefix += ":"
        self._leases_created = 0
        self._expired_recovered = 0
        self._counter_ttl_ms = int(max(60.0, config.lease_seconds * 10) * 1000)
        self._queued_ttl_ms = int(config.queued_lease_seconds * 1000)
        self._recovery_ttl_ms = int(config.recovery_seconds * 1000)

    def _keys(self, resource_id: str) -> tuple[str, str, str]:
        return (f"{self._prefix}execution:{resource_id}:token",
                f"{self._prefix}execution:{resource_id}:meta",
                f"{self._prefix}execution:{resource_id}:fence")

    def claim(self, resource_id: str, execution_id: str, user_id: str,
              attempt: int, now: Optional[float] = None,
              lease_pre_claimed: bool = False) -> tuple[ClaimResult, Optional[Waiter]]:
        del lease_pre_claimed  # coordinator owns the lease; no service double-claim
        timestamp = float(now if now is not None else self._clock())
        token_key, meta_key, fence_key = self._keys(resource_id)
        result = self._client.eval(
            REDIS_CLAIM_SCRIPT, 6, token_key, meta_key, fence_key,
            f"{self._prefix}queue", f"{self._prefix}counters:active",
            f"{self._prefix}counters:queued",
            execution_id, user_id, self.instance_id, str(timestamp),
            int(self.config.lease_seconds * 1000), self.config.max_active,
            self.config.max_active_per_user, self.config.max_queued,
            self.config.max_queued_per_user, int(attempt), self._prefix,
            self._counter_ttl_ms, self._queued_ttl_ms, self._recovery_ttl_ms,
            resource_id)
        code = int(result[0])
        if code == -1:
            active_id = result[1] if len(result) > 1 else ""
            return (ClaimResult(
                "active_exists", resource_id, execution_id,
                error_code="ACTIVE_RUN_EXISTS",
                error="该任务已有执行正在进行",
                fence_token=0), None)
        fence = int(result[1])
        if code == 1:
            self._leases_created += 1
            return (ClaimResult("admitted", resource_id, execution_id,
                                fence_token=fence), None)
        if code == -2:
            return (ClaimResult(
                "global_queue_full", resource_id, execution_id,
                error_code="GLOBAL_QUEUE_FULL",
                error="全局排队任务已达到上限"), None)
        if code == -3:
            return (ClaimResult(
                "user_queue_limit", resource_id, execution_id,
                error_code="USER_QUEUE_LIMIT_REACHED",
                error="该用户排队任务已达到上限"), None)
        position = int(result[2]) if len(result) > 2 else 0
        length = int(result[3]) if len(result) > 3 else position
        return (ClaimResult(
            "queued", resource_id, execution_id, fence_token=fence,
            queue_position=position, queue_length=length), None)

    def admit_next(self) -> Optional[str]:
        result = self._client.eval(
            REDIS_ADMIT_SCRIPT, 3, f"{self._prefix}queue",
            f"{self._prefix}counters:active", f"{self._prefix}counters:queued",
            self.config.max_active, self.config.max_active_per_user,
            str(self._clock()), int(self.config.lease_seconds * 1000),
            self._prefix, self._counter_ttl_ms, self.instance_id,
            self._recovery_ttl_ms)
        if result and int(result[0]) == 1:
            return str(result[1])
        return None

    def renew_queued(self) -> int:
        """Renew TTLs of queued executions owned by this instance."""
        try:
            result = self._client.eval(
                REDIS_RENEW_QUEUED_SCRIPT, 1, f"{self._prefix}queue",
                self._prefix, self.instance_id, self._queued_ttl_ms,
                self._recovery_ttl_ms)
            return int(result or 0)
        except Exception:
            return 0

    def cancel(self, resource_id: str, execution_id: str,
              fence_token: int) -> bool:
        token_key, meta_key, _ = self._keys(resource_id)
        result = self._client.eval(REDIS_CANCEL_SCRIPT, 2, token_key, meta_key,
                                   execution_id, fence_token, self._prefix,
                                   resource_id)
        return bool(result)

    def release(self, resource_id: str, execution_id: str,
                fence_token: int, was_queued: bool) -> None:
        del was_queued  # Lua derives queued-ness from the meta status itself
        token_key, meta_key, _ = self._keys(resource_id)
        try:
            self._client.eval(REDIS_RELEASE_SCRIPT, 2, token_key, meta_key,
                              execution_id, fence_token, self._prefix,
                              self._counter_ttl_ms, resource_id)
        except Exception:
            pass

    def heartbeat(self, resource_id: str, execution_id: str) -> bool:
        token_key, meta_key, _ = self._keys(resource_id)
        try:
            now = self._clock()
            result = self._client.eval(
                RENEW_SCRIPT, 2, token_key, meta_key,
                execution_id, int(self.config.lease_seconds * 1000),
                str(now), str(now + self.config.lease_seconds))
            return bool(result)
        except Exception:
            return False

    def verify_fence(self, resource_id: str, execution_id: str,
                     fence_token: int) -> bool:
        _, meta_key, _ = self._keys(resource_id)
        try:
            meta = self._client.hgetall(meta_key)
        except Exception:
            return False
        if not meta:
            return False
        return (str(meta.get("execution_id") or "") == str(execution_id)
                and int(meta.get("fence_token") or 0) == int(fence_token)
                and str(meta.get("owner_instance_id") or "") == str(self.instance_id))

    def read(self, resource_id: str) -> Optional[LeaseRecord]:
        _, meta_key, _ = self._keys(resource_id)
        try:
            token = self._client.get(
                f"{self._prefix}execution:{resource_id}:token")
            meta = self._client.hgetall(meta_key)
        except Exception:
            return None
        if not token or not meta:
            return None
        return LeaseRecord.from_redis_meta(str(resource_id), meta)

    def _iter_meta_keys(self):
        # SCAN-based iteration: ``KEYS`` blocks a production Redis.  The
        # scan is bounded by the recovery window because every meta key gets
        # a TTL, so stale keys disappear on their own.  A production backend
        # must provide ``scan_iter`` (checked at construction); there is no
        # ``keys()`` fallback so fake clients cannot diverge from production.
        yield from self._client.scan_iter(
            match=f"{self._prefix}execution:*:meta", count=200)

    def _expired_for_recovery(self, meta: dict[str, Any], now: float) -> bool:
        status = meta.get("status")
        if status == "ADMITTED":
            return float(meta.get("lease_expires_at") or 0) <= now
        if status == "QUEUED":
            queued_at = float(meta.get("queued_at") or 0)
            return queued_at + self.config.queued_lease_seconds <= now
        return False

    def recover_expired(self) -> int:
        """Recover crashed/dead-owner executions without blocking Redis.

        Scans meta keys inside the recovery window; an execution is recovered
        only when its ownership token is gone and its lease/queue TTL has
        passed.  The atomic Lua cleanup makes a multi-instance recovery race
        safe: only one instance can delete the meta key.
        """
        recovered = 0
        now = self._clock()
        try:
            for meta_key in self._iter_meta_keys():
                meta = self._client.hgetall(meta_key)
                if not meta or meta.get("status") not in {"ADMITTED", "QUEUED"}:
                    continue
                resource_id = str(meta.get("resource_id") or meta.get("execution_id") or "")
                if not resource_id:
                    continue
                token_key, current_meta, _ = self._keys(resource_id)
                if self._client.get(
                        f"{self._prefix}execution:{resource_id}:token"):
                    continue
                if not self._expired_for_recovery(meta, now):
                    continue
                result = self._client.eval(
                    REDIS_RECOVER_SCRIPT, 2, token_key, current_meta,
                    resource_id, self._prefix, self._counter_ttl_ms)
                if result:
                    recovered += 1
        except Exception:
            return recovered
        if recovered:
            self._expired_recovered += recovered
        return recovered

    def metrics(self) -> dict[str, Any]:
        try:
            active = int(self._client.get(f"{self._prefix}counters:active") or 0)
            queued = int(self._client.get(f"{self._prefix}counters:queued") or 0)
            oldest = 0.0
            head = self._client.lindex(f"{self._prefix}queue", 0)
            if head:
                meta = self._client.hgetall(
                    f"{self._prefix}execution:{head}:meta")
                queued_at = float((meta or {}).get("queued_at") or 0)
                if queued_at:
                    oldest = max(0.0, self._clock() - queued_at)
        except Exception:
            active = queued = 0
            oldest = 0.0
        return {
            "activeRuns": active,
            "queuedRuns": queued,
            "oldestQueuedSeconds": oldest,
            "activeLeases": self._leases_created,
            "expiredLeasesRecovered": self._expired_recovered,
        }


class ExecutionCoordinator:
    """Bounded, fair execution coordinator with worker pool + leases/fences.

    ``claim`` never blocks: an execution is either admitted immediately
    (submitted to the bounded worker pool), enqueued (the dispatcher admits
    it later), or rejected with an explicit error.  HTTP handlers therefore
    never occupy a thread for the queue wait.  The coordinator is the single
    owner of the durable lease, the queue and the fence; services only call
    ``claim``/``cancel``/``release`` and never claim a second lease.
    """

    def __init__(self, config: CoordinatorConfig, adapter: ExecutionAdapter,
                 lease_store: Optional[Any] = None,
                 instance_id: Optional[str] = None,
                 redis_client: Optional[Any] = None):
        self.config = config.validate()
        self.adapter = adapter
        self.instance_id = instance_id or _new_instance_id()
        self.lease_store = lease_store
        if self.config.backend == "redis":
            if not self.config.redis_url and redis_client is None:
                raise ValueError("backend=redis 需要 redis_url")
            if redis_client is None:
                try:
                    import redis  # noqa: PLC0415 - lazy optional dependency
                except ImportError as exc:
                    raise RuntimeError("backend=redis 需要安装 redis 包") from exc
                redis_client = redis.Redis.from_url(self.config.redis_url,
                                                    decode_responses=True)
                try:
                    redis_client.ping()
                except Exception as exc:
                    raise RuntimeError("无法连接 Redis，启动失败") from exc
                # Startup capability probe: the multi-instance protocol relies
                # on atomic Lua/EVAL scripts, so a Redis that cannot EVAL must
                # fail startup instead of silently degrading to local mode.
                try:
                    redis_client.eval("return 1", 0)
                except Exception as exc:
                    raise RuntimeError(
                        "Redis Lua/EVAL 能力检查失败，启动中止") from exc
            self.backend = _RedisBackend(self.config, redis_client, self.instance_id)
        else:
            if lease_store is None and self.config.lease_dir:
                lease_store = FileExecutionLeaseStore(
                    self.config.lease_dir, lease_seconds=self.config.lease_seconds)
            # Publish the store we actually use so health/metrics report the
            # real backend instead of a memory-only local view.
            self.lease_store = lease_store
            self.backend = _LocalBackend(self.config, lease_store, self.instance_id)
        if self.config.backend == "redis" and not callable(
                getattr(self.backend._client, "scan_iter", None)):
            raise RuntimeError(
                "Redis 客户端必须支持 scan_iter（真实 redis-py 与 FakeRedis 均支持）; "
                "生产路径禁止回退到 KEYS")
        self.provider_slots = threading.BoundedSemaphore(self.config.provider_concurrency)
        self.database_slots = threading.BoundedSemaphore(self.config.database_concurrency)
        pool_size = self.config.worker_pool_size or self.config.max_active
        self._pool = _BoundedWorkerPool(pool_size, name_prefix="exec-worker")
        # Keyed by resource_id (the mutex): at most one execution per resource.
        self._executions: dict[str, _Execution] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._stopping = False
        self._dispatcher = threading.Thread(target=self._dispatch_loop,
                                            name="exec-dispatcher", daemon=True)
        self._dispatcher.start()

    # -- public API ---------------------------------------------------------

    def claim(self, resource_id: str, execution_id: str, user_id: str,
              attempt: int = 1, lease_pre_claimed: bool = False) -> ClaimResult:
        if self._stopping:
            return ClaimResult(
                "stopping", resource_id, execution_id,
                error_code="COORDINATOR_STOPPING",
                error="服务正在停止，无法接受新的执行")
        result, waiter = self.backend.claim(resource_id, execution_id, user_id,
                                            attempt,
                                            lease_pre_claimed=lease_pre_claimed)
        if result.decision in {"admitted", "queued"}:
            token = waiter.token if waiter is not None else CancellationToken()
            entry = _Execution(resource_id, execution_id, user_id, token,
                               result.fence_token, attempt,
                               queued=(result.decision == "queued"),
                               waiter=waiter)
            with self._lock:
                self._executions[resource_id] = entry
            if result.decision == "admitted":
                self._submit(resource_id)
            else:
                self.adapter.on_queued(resource_id, result.queue_position,
                                       result.queue_length)
        return result

    def cancel(self, resource_id: str) -> bool:
        with self._lock:
            entry = self._executions.get(resource_id)
        if entry is None:
            return False
        removed = self.backend.cancel(
            resource_id, entry.execution_id, entry.fence_token)
        entry.token.cancel("CANCELLED")
        if removed:
            with self._lock:
                self._executions.pop(resource_id, None)
        return True

    def release(self, resource_id: str, execution_id: str,
                fence_token: int) -> None:
        with self._lock:
            entry = self._executions.get(resource_id)
            was_queued = bool(entry and entry.waiter
                              and entry.waiter.state == Waiter.WAITING)
        self.backend.release(resource_id, execution_id, fence_token, was_queued)
        with self._lock:
            self._executions.pop(resource_id, None)

    def verify_fence(self, resource_id: str, execution_id: str,
                     fence_token: int) -> bool:
        return self.backend.verify_fence(resource_id, execution_id, fence_token)

    def read_lease(self, resource_id: str) -> Optional[LeaseRecord]:
        return self.backend.read(resource_id)

    def execution_context(self, resource_id: str) -> Optional["ExecutionContext"]:
        """Guard object for the current execution of ``resource_id``."""
        with self._lock:
            entry = self._executions.get(resource_id)
        if entry is None:
            return None
        return ExecutionContext(self, resource_id, entry.execution_id,
                                entry.fence_token, entry.token)

    def metrics(self) -> dict[str, Any]:
        backend_metrics = self.backend.metrics()
        if isinstance(self.lease_store, FileExecutionLeaseStore):
            backend_kind = "file"
            multi_process_safe = True
            multi_host_safe = False
            quota_scope = "process"
            queue_scope = "process"
            lease_multi_process = True
        elif isinstance(self.lease_store, RedisExecutionLeaseStore):
            backend_kind = "redis"
            multi_process_safe = True
            multi_host_safe = True
            quota_scope = "cluster"
            queue_scope = "cluster"
            lease_multi_process = True
        elif self.config.backend == "redis":
            backend_kind = "redis"
            multi_process_safe = True
            multi_host_safe = True
            quota_scope = "cluster"
            queue_scope = "cluster"
            lease_multi_process = True
        else:
            backend_kind = "local"
            multi_process_safe = False
            multi_host_safe = False
            quota_scope = "process"
            queue_scope = "process"
            lease_multi_process = False
        return {
            "concurrency": {
                "activeRuns": backend_metrics.get("activeRuns", 0),
                "queuedRuns": backend_metrics.get("queuedRuns", 0),
                "maxActiveRuns": self.config.max_active,
                "maxActivePerUser": self.config.max_active_per_user,
                "maxQueuedPerUser": self.config.max_queued_per_user,
                "maxQueuedRuns": self.config.max_queued,
                "oldestQueuedSeconds": backend_metrics.get("oldestQueuedSeconds", 0.0),
                "providerConcurrency": self.config.provider_concurrency,
                "providerInUse": max(0, self.config.provider_concurrency
                                     - self.provider_slots._value),  # noqa: SLF001
                "databaseConcurrency": self.config.database_concurrency,
                "databaseInUse": max(0, self.config.database_concurrency
                                     - self.database_slots._value),  # noqa: SLF001
            },
            "coordination": {
                "backend": backend_kind,
                "instanceId": self.instance_id,
                "multiProcessSafe": multi_process_safe,
                "multiHostSafe": multi_host_safe,
                "leaseMultiProcessSafe": lease_multi_process,
                "quotaScope": quota_scope,
                "queueScope": queue_scope,
                "leaseSeconds": self.config.lease_seconds,
                "queuedLeaseSeconds": self.config.queued_lease_seconds,
                "heartbeatSeconds": self.config.heartbeat_seconds,
                "activeLeases": backend_metrics.get("activeLeases", 0),
                "expiredLeasesRecovered": backend_metrics.get("expiredLeasesRecovered", 0),
            },
        }

    def shutdown(self, timeout: float = 10.0) -> None:
        """Bounded graceful shutdown that never blocks past ``timeout``.

        1. reject new claims (``COORDINATOR_STOPPING``);
        2. stop the dispatcher;
        3. cancel queued executions and return their queue/counter slots;
        4. cancel active executions with a SHUTDOWN token;
        5. wait at most ``timeout`` for active workers to finish;
        6. after the deadline, stop renewing abandoned leases and let them
           expire so another instance can recover the resources; the daemon
           workers never block interpreter exit.
        """
        self._stop.set()
        with self._lock:
            self._stopping = True
        self._dispatcher.join(timeout=min(2.0, float(timeout)))
        entries = list(self._executions.values())
        for entry in entries:
            entry.token.cancel("SHUTDOWN")
            if entry.queued and entry.waiter is not None \
                    and entry.waiter.state == Waiter.WAITING:
                try:
                    self.backend.cancel(
                        entry.resource_id, entry.execution_id,
                        entry.fence_token)
                except Exception:
                    pass
                entry.waiter.state = Waiter.CANCELLED
                entry.waiter.wakeup.set()
                with self._lock:
                    if self._executions.get(entry.resource_id) is entry:
                        self._executions.pop(entry.resource_id, None)
        deadline = time.monotonic() + max(0.0, float(timeout))
        handles = [e.future for e in entries
                   if e.future is not None and not e.future.done()]
        for handle in handles:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                handle.result(timeout=remaining)
            except TimeoutError:
                break
            except Exception:
                continue
        # Abandoned workers: stop renewing their leases (expiry lets another
        # instance recover) and mark the entry so a late-returning worker can
        # never write formal status or call on_finished.
        with self._lock:
            remaining_entries = list(self._executions.values())
        for entry in remaining_entries:
            self._stop_heartbeat(entry)
            entry.abandoned = True
        self._pool.shutdown()

    # -- internals ----------------------------------------------------------

    def _submit(self, resource_id: str) -> None:
        with self._lock:
            entry = self._executions.get(resource_id)
            if entry is None or entry.future is not None:
                return
            if entry.waiter is not None and entry.waiter.state != Waiter.ADMITTED:
                return
            handle = _TaskHandle()
            entry.future = handle
        if self._pool.submit(lambda: self._run_task(resource_id, handle)):
            return
        # Shutdown won the race between admission and submission: cancel the
        # claim and return its resources instead of leaving a ghost entry.
        try:
            self.backend.cancel(resource_id, entry.execution_id,
                                entry.fence_token)
        except Exception:
            pass
        entry.token.cancel("SHUTDOWN")
        with self._lock:
            if self._executions.get(resource_id) is entry:
                self._executions.pop(resource_id, None)

    def _run_task(self, resource_id: str, handle: _TaskHandle) -> None:
        try:
            self._run(resource_id)
        except BaseException as exc:  # noqa: BLE001 - report via the handle
            handle.set_exception(exc)
        else:
            handle.set_result()

    def _dispatch_loop(self) -> None:
        recover_counter = 0
        while not self._stop.is_set():
            try:
                execution_id = self.backend.admit_next()
                if execution_id:
                    with self._lock:
                        entry = self._executions.get(execution_id)
                    if entry is not None and not entry.token.cancelled:
                        self._submit(execution_id)
            except Exception:
                pass
            # The owner dispatcher keeps its own queued items alive so a long
            # queue wait can never expire the token while the owner runs.
            if recover_counter % 5 == 0 and hasattr(self.backend, "renew_queued"):
                try:
                    self.backend.renew_queued()
                except Exception:
                    pass
            recover_counter += 1
            if recover_counter % 25 == 0:
                try:
                    recovered = self.backend.recover_expired()
                    # Freed capacity is admitted immediately after recovery.
                    if recovered:
                        execution_id = self.backend.admit_next()
                        if execution_id:
                            with self._lock:
                                entry = self._executions.get(execution_id)
                            if entry is not None and not entry.token.cancelled:
                                self._submit(execution_id)
                except Exception:
                    pass
            self._stop.wait(0.1)

    def _run(self, resource_id: str) -> None:
        with self._lock:
            entry = self._executions.get(resource_id)
        if entry is None:
            return
        token = entry.token
        ok = False
        try:
            if token.cancelled:
                # A stale worker (superseded by a newer claim) must not run
                # adapter completion bookkeeping for the newer execution.
                with self._lock:
                    current = self._executions.get(resource_id)
                if current is entry and not entry.abandoned:
                    try:
                        self.adapter.on_finished(resource_id, False, token)
                    except Exception:
                        pass
                return
            # Heartbeat must run before any potentially blocking startup side
            # effect (e.g. a platform RUNNING network callback inside
            # ``on_started``): the lease keeps renewing while ``on_started``
            # blocks, so another instance cannot claim the resource.
            self._start_heartbeat(entry)
            try:
                # Fence is verified before on_started: a lease-lost or
                # superseded execution must not even send RUNNING.
                context = ExecutionContext(self, resource_id,
                                           entry.execution_id,
                                           entry.fence_token, token)
                context.assert_current()
                try:
                    self.adapter.on_started(resource_id)
                except Exception:
                    ok = False
                    try:
                        self.adapter.record_event(resource_id, {
                            "type": "error",
                            "error": "on_started 执行异常，已按可恢复中断处理",
                            "recoverable": True,
                        })
                    except Exception:
                        pass
                else:
                    # on_started may have blocked long enough for the
                    # heartbeat to fail; a cancelled token must not run the
                    # worker.
                    if not token.cancelled:
                        try:
                            self.adapter.run_worker(resource_id, token)
                            ok = not token.cancelled
                        except ExecutionCancelled:
                            ok = False
                        except Exception:
                            ok = False
                            try:
                                self.adapter.record_event(resource_id, {
                                    "type": "error",
                                    "error": "worker 执行异常，已按可恢复中断处理",
                                    "recoverable": True,
                                })
                            except Exception:
                                pass
            except ExecutionCancelled:
                ok = False
            finally:
                self._stop_heartbeat(entry)
            # A lost/stale lease must never report success.
            if ok and not self.backend.verify_fence(
                    resource_id, entry.execution_id, entry.fence_token):
                ok = False
            with self._lock:
                current = self._executions.get(resource_id)
            if current is entry and not entry.abandoned:
                try:
                    # Exactly one on_finished per execution: the exception
                    # paths above never call it, so no double notification,
                    # a superseded execution never cleans up the newer
                    # entry's bookkeeping, and an abandoned (shutdown
                    # timeout) worker never writes formal status.
                    self.adapter.on_finished(resource_id, ok, token)
                except Exception:
                    pass
        finally:
            was_queued = bool(entry.waiter and entry.waiter.state == Waiter.WAITING)
            self.backend.release(resource_id, entry.execution_id,
                                 entry.fence_token, was_queued)
            with self._lock:
                # A newer execution may have replaced this entry (recovered
                # lease); a stale worker must never pop the new entry.
                if self._executions.get(resource_id) is entry:
                    self._executions.pop(resource_id, None)

    def _start_heartbeat(self, entry: _Execution) -> None:
        if self.lease_store is None and not isinstance(self.backend, _RedisBackend):
            return
        stop = threading.Event()
        entry.heartbeat_stop = stop
        failures = 0

        def loop():
            nonlocal failures
            while not stop.wait(self.config.heartbeat_seconds):
                renewed = self.backend.heartbeat(
                    entry.resource_id, entry.execution_id)
                if renewed:
                    failures = 0
                    continue
                failures += 1
                if failures >= self.config.max_heartbeat_failures:
                    entry.token.cancel("LEASE_LOST")
                    try:
                        self.adapter.record_event(entry.resource_id, {
                            "type": "error",
                            "code": "LEASE_LOST",
                            "error": "执行租约丢失，已停止本轮执行",
                            "recoverable": True,
                        })
                    except Exception:
                        pass
                    stop.set()

        thread = threading.Thread(target=loop, name=f"lease-hb-{entry.resource_id}",
                                  daemon=True)
        entry.heartbeat_thread = thread
        thread.start()

    def _stop_heartbeat(self, entry: _Execution) -> None:
        stop = entry.heartbeat_stop
        if stop is not None:
            stop.set()
        entry.heartbeat_stop = None
        entry.heartbeat_thread = None


class ExecutionContext:
    """Fencing + cancellation guard for one execution's formal side effects.

    Every side effect that can overwrite state (uploads, platform callbacks,
    checkpoint updates, final run status) must call ``assert_current()``
    first: it raises :class:`ExecutionCancelled` when the cancellation token
    fired (e.g. ``LEASE_LOST``) and :class:`StaleExecution` when the fence no
    longer matches (a newer execution owns the resource).
    """

    __slots__ = ("coordinator", "resource_id", "execution_id",
                 "fence_token", "token")

    def __init__(self, coordinator: ExecutionCoordinator, resource_id: str,
                 execution_id: str, fence_token: int,
                 token: CancellationToken):
        self.coordinator = coordinator
        self.resource_id = resource_id
        self.execution_id = execution_id
        self.fence_token = fence_token
        self.token = token

    def assert_current(self) -> None:
        if self.token.cancelled:
            raise ExecutionCancelled(self.token.reason or "cancelled")
        if not self.coordinator.verify_fence(
                self.resource_id, self.execution_id, self.fence_token):
            raise StaleExecution(
                self.resource_id, self.execution_id, self.fence_token)

    def cancelled(self) -> bool:
        return self.token.cancelled


class StaleExecution(ExecutionCancelled):
    """Raised when a side effect belongs to an execution that lost the fence."""

    def __init__(self, resource_id: str, execution_id: str, fence_token: int):
        super().__init__(f"STALE_EXECUTION {resource_id} {execution_id} "
                         f"fence={fence_token}")
        self.resource_id = resource_id
        self.execution_id = execution_id
        self.fence_token = fence_token


def acquire_cancelable(semaphore: Any, token: Optional[CancellationToken] = None,
                       timeout: float = 0.2,
                       reason: str = "资源等待被取消") -> bool:
    """Acquire ``semaphore`` without blocking past ``timeout`` on cancellation.

    Returns True once acquired; raises :class:`ExecutionCancelled` when the
    token fires while waiting.  ``semaphore`` may be None (no limit).
    """
    if semaphore is None:
        return True
    while token is None or not token.cancelled:
        if semaphore.acquire(timeout=timeout):
            return True
    raise ExecutionCancelled(reason)


def _new_instance_id() -> str:
    host = socket.gethostname()
    return f"{host}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
