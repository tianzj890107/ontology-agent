"""Durable, expiring execution leases with fencing for 47313/47314.

A lease is a token-gated claim:

- the ownership token is an unguessable opaque string stored on the main
  key (string type with TTL);
- execution metadata lives in a companion hash (Redis) or a sidecar file
  (file backend);
- ``renew``/``release`` are token-checked atomically (Lua under Redis,
  ``flock`` under the file backend) so a stale worker can never renew or
  release a newer owner's lease;
- a per-task monotonic fence counter is persisted so an old execution can
  never write final state for a newer execution.

The module is server-agnostic: it never touches task stores, repositories or
workspaces.  47313/47314 use it through ``execution_coordinator``.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]

DEFAULT_LEASE_SECONDS = 120.0
DEFAULT_HEARTBEAT_SECONDS = 5.0

TOKEN_SUFFIX = ":token"
META_SUFFIX = ":meta"
FENCE_SUFFIX = ":fence"

# Claim: atomically take the lease when the token key is absent.
# KEYS[1]=token key, KEYS[2]=meta hash key
# ARGV[1]=ownership token, ARGV[2]=ttl ms, ARGV[3]=execution_id,
# ARGV[4]=owner_instance_id, ARGV[5]=fence_token, ARGV[6]=attempt,
# ARGV[7]=acquired_at, ARGV[8]=lease_expires_at, ARGV[9]=heartbeat_at,
# ARGV[10]=status, ARGV[11]=user_id
CLAIM_SCRIPT = """
if redis.call("exists", KEYS[1]) == 1 then
  return 0
end
redis.call("set", KEYS[1], ARGV[1], "PX", ARGV[2])
redis.call("hset", KEYS[2],
  "execution_id", ARGV[3],
  "owner_instance_id", ARGV[4],
  "fence_token", ARGV[5],
  "attempt", ARGV[6],
  "acquired_at", ARGV[7],
  "lease_expires_at", ARGV[8],
  "heartbeat_at", ARGV[9],
  "status", ARGV[10],
  "user_id", ARGV[11])
redis.call("pexpire", KEYS[2], ARGV[2])
return 1
"""

# Renew: extend TTL only when the token still matches.
# KEYS[1]=token key, KEYS[2]=meta hash key
# ARGV[1]=ownership token, ARGV[2]=ttl ms, ARGV[3]=heartbeat_at,
# ARGV[4]=lease_expires_at
RENEW_SCRIPT = """
if redis.call("get", KEYS[1]) ~= ARGV[1] then
  return 0
end
redis.call("pexpire", KEYS[1], ARGV[2])
redis.call("hset", KEYS[2], "heartbeat_at", ARGV[3], "lease_expires_at", ARGV[4])
redis.call("pexpire", KEYS[2], ARGV[2])
return 1
"""

# Release: delete the lease only when the token still matches.
# KEYS[1]=token key, KEYS[2]=meta hash key; ARGV[1]=ownership token
RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) ~= ARGV[1] then
  return 0
end
redis.call("del", KEYS[1])
redis.call("del", KEYS[2])
return 1
"""

_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]")


def _safe_task_id(task_id: str) -> str:
    return _SAFE_ID.sub("_", str(task_id or "task"))[:80] or "task"


@dataclass
class LeaseRecord:
    """One durable execution claim with fencing metadata."""

    task_id: str
    execution_id: str
    owner_id: str
    fence_token: int
    attempt: int
    acquired_at: float
    lease_expires_at: float
    heartbeat_at: float = 0.0
    status: str = "CLAIMED"
    user_id: str = ""
    queued_at: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0

    def expired(self, now: float) -> bool:
        return now >= self.lease_expires_at

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Any) -> Optional["LeaseRecord"]:
        if not isinstance(value, dict):
            return None
        try:
            return cls(
                task_id=str(value.get("task_id") or value.get("taskId") or ""),
                execution_id=str(value.get("execution_id") or value.get("executionId") or ""),
                owner_id=str(value.get("owner_id") or value.get("ownerId") or ""),
                fence_token=int(value.get("fence_token")
                                if value.get("fence_token") is not None
                                else value.get("fenceToken") or 0),
                attempt=int(value.get("attempt") or 0),
                acquired_at=float(value.get("acquired_at") or value.get("acquiredAt") or 0),
                lease_expires_at=float(value.get("lease_expires_at")
                                       or value.get("leaseExpiresAt") or 0),
                heartbeat_at=float(value.get("heartbeat_at") or value.get("heartbeatAt") or 0),
                status=str(value.get("status") or "CLAIMED"),
                user_id=str(value.get("user_id") or value.get("userId") or ""),
                queued_at=float(value.get("queued_at") or value.get("queuedAt") or 0),
                started_at=float(value.get("started_at") or value.get("startedAt") or 0),
                finished_at=float(value.get("finished_at") or value.get("finishedAt") or 0),
            )
        except (TypeError, ValueError):
            return None

    @classmethod
    def from_redis_meta(cls, task_id: str, meta: dict[str, Any]) -> Optional["LeaseRecord"]:
        if not isinstance(meta, dict) or not meta:
            return None
        return cls(
            task_id=task_id,
            execution_id=str(meta.get("execution_id") or ""),
            owner_id=str(meta.get("owner_instance_id") or meta.get("owner_id") or ""),
            fence_token=int(meta.get("fence_token") or 0),
            attempt=int(meta.get("attempt") or 0),
            acquired_at=float(meta.get("acquired_at") or 0),
            lease_expires_at=float(meta.get("lease_expires_at") or 0),
            heartbeat_at=float(meta.get("heartbeat_at") or 0),
            status=str(meta.get("status") or "CLAIMED"),
            user_id=str(meta.get("user_id") or ""),
            queued_at=float(meta.get("queued_at") or 0),
            started_at=float(meta.get("started_at") or 0),
            finished_at=float(meta.get("finished_at") or 0),
        )


class FileExecutionLeaseStore:
    """Per-task lease file guarded by ``flock`` (cross-process on one host).

    The lease record and the monotonic fence counter are both persisted under
    the same per-task lock; fence values never decrease even across restarts.
    """

    def __init__(self, lease_dir: str | os.PathLike,
                 lease_seconds: float = DEFAULT_LEASE_SECONDS,
                 clock: Callable[[], float] = time.time):
        self.lease_dir = Path(lease_dir)
        self.lease_seconds = float(lease_seconds)
        self._clock = clock
        self._local_locks: dict[str, threading.Lock] = {}
        self._multi_host_safe = False

    def _paths(self, task_id: str) -> tuple[Path, Path]:
        safe = _safe_task_id(task_id)
        return (self.lease_dir / f"{safe}.lease.json",
                self.lease_dir / f"{safe}.lease.lock")

    def _fence_path(self, task_id: str) -> Path:
        return self.lease_dir / f"{_safe_task_id(task_id)}.fence"

    def _local_lock(self, task_id: str) -> threading.Lock:
        return self._local_locks.setdefault(task_id, threading.Lock())

    def try_claim(self, task_id: str, owner_id: str, execution_id: str,
                  lease_seconds: Optional[float] = None,
                  fence_token: Optional[int] = None,
                  attempt: int = 1,
                  status: str = "CLAIMED",
                  user_id: str = "",
                  now: Optional[float] = None) -> tuple[bool, Optional[LeaseRecord]]:
        """Atomically claim a lease if free or expired, bumping the fence."""
        path, lock_path = self._paths(task_id)
        duration = float(lease_seconds if lease_seconds is not None else self.lease_seconds)
        timestamp = float(now if now is not None else self._clock())
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock(task_id, lock_path):
            current = self._read(path)
            if current is not None and not current.expired(timestamp):
                return False, current
            fence = (int(fence_token) if fence_token is not None
                     else self._next_fence_locked(task_id))
            record = LeaseRecord(
                task_id=str(task_id), execution_id=execution_id,
                owner_id=owner_id, fence_token=fence, attempt=int(attempt),
                acquired_at=timestamp, lease_expires_at=timestamp + duration,
                heartbeat_at=timestamp, status=str(status), user_id=str(user_id),
                queued_at=timestamp if status == "QUEUED" else 0.0,
            )
            self._write(path, record)
            return True, record

    def renew(self, task_id: str, execution_id: str,
              lease_seconds: Optional[float] = None) -> bool:
        """Extend the lease only if it still belongs to ``execution_id``."""
        path, lock_path = self._paths(task_id)
        duration = float(lease_seconds if lease_seconds is not None else self.lease_seconds)
        with self._lock(task_id, lock_path):
            current = self._read(path)
            if current is None or current.execution_id != execution_id:
                return False
            current.lease_expires_at = self._clock() + duration
            current.heartbeat_at = self._clock()
            self._write(path, current)
            return True

    def release(self, task_id: str, execution_id: str) -> bool:
        """Clear the lease only if it still belongs to ``execution_id``."""
        path, lock_path = self._paths(task_id)
        with self._lock(task_id, lock_path):
            current = self._read(path)
            if current is None or current.execution_id != execution_id:
                return False
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return True

    def read(self, task_id: str) -> Optional[LeaseRecord]:
        return self._read(self._paths(task_id)[0])

    def next_fence(self, task_id: str) -> int:
        _, lock_path = self._paths(task_id)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock(task_id, lock_path):
            return self._next_fence_locked(task_id)

    def _next_fence_locked(self, task_id: str) -> int:
        path = self._fence_path(task_id)
        current = 0
        try:
            current = int(path.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            current = 0
        current += 1
        tmp = path.with_suffix(".fence.tmp")
        tmp.write_text(str(current), encoding="utf-8")
        os.replace(tmp, path)
        return current

    def _lock(self, task_id: str, lock_path: Path):
        if fcntl is not None:
            lock_fh = open(lock_path, "a+b")
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            return _FileLockContext(lock_fh)
        return _ThreadLockContext(self._local_lock(task_id))

    @staticmethod
    def _read(path: Path) -> Optional[LeaseRecord]:
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        try:
            return LeaseRecord.from_dict(json.loads(raw))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _write(path: Path, record: LeaseRecord) -> None:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record.to_dict(), ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, path)


class _FileLockContext:
    def __init__(self, lock_fh):
        self._fh = lock_fh

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        try:
            if fcntl is not None:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
        return False


class _ThreadLockContext:
    def __init__(self, lock):
        self._lock = lock

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, *exc):
        self._lock.release()
        return False


class RedisExecutionLeaseStore:
    """Lease store backed by Redis (token key + meta hash + fence counter).

    The ownership token is stored on the token key (string, ``SET NX PX`` via
    the claim script); ``renew``/``release`` compare the token inside Lua so
    an old execution can never release a newer owner's lease.  Fences come
    from a per-task ``INCR`` key.
    """

    def __init__(self, client: Any, prefix: str = "ontology:",
                 lease_seconds: float = DEFAULT_LEASE_SECONDS,
                 clock: Callable[[], float] = time.time):
        self._client = client
        self._prefix = str(prefix)
        self.lease_seconds = float(lease_seconds)
        self._clock = clock

    def _keys(self, task_id: str) -> tuple[str, str, str]:
        safe = _safe_task_id(task_id)
        return (f"{self._prefix}{safe}{TOKEN_SUFFIX}",
                f"{self._prefix}{safe}{META_SUFFIX}",
                f"{self._prefix}{safe}{FENCE_SUFFIX}")

    def try_claim(self, task_id: str, owner_id: str, execution_id: str,
                  lease_seconds: Optional[float] = None,
                  fence_token: Optional[int] = None,
                  attempt: int = 1,
                  status: str = "CLAIMED",
                  user_id: str = "",
                  now: Optional[float] = None) -> tuple[bool, Optional[LeaseRecord]]:
        token_key, meta_key, fence_key = self._keys(task_id)
        duration = float(lease_seconds if lease_seconds is not None else self.lease_seconds)
        timestamp = float(now if now is not None else self._clock())
        fence = (int(fence_token) if fence_token is not None
                 else int(self._client.incr(fence_key) or 1))
        created = self._client.eval(
            CLAIM_SCRIPT, 2, token_key, meta_key,
            # ARGV layout matches the script header: 1=ownership token,
            # 2=ttl ms, 3=execution_id, 4=owner_instance_id, 5=fence_token,
            # 6=attempt, 7=acquired_at, 8=lease_expires_at, 9=heartbeat_at,
            # 10=status, 11=user_id
            execution_id, int(duration * 1000), execution_id, owner_id,
            str(fence), str(int(attempt)), str(timestamp),
            str(timestamp + duration), str(timestamp),
            status, str(user_id))
        if not created:
            return False, self.read(task_id)
        return True, LeaseRecord(
            task_id=str(task_id), execution_id=execution_id,
            owner_id=owner_id, fence_token=fence, attempt=int(attempt),
            acquired_at=timestamp, lease_expires_at=timestamp + duration,
            heartbeat_at=timestamp, status=status, user_id=str(user_id),
            queued_at=timestamp if status == "QUEUED" else 0.0,
        )

    def renew(self, task_id: str, execution_id: str,
              lease_seconds: Optional[float] = None) -> bool:
        token_key, meta_key, _ = self._keys(task_id)
        duration = float(lease_seconds if lease_seconds is not None else self.lease_seconds)
        now = self._clock()
        result = self._client.eval(RENEW_SCRIPT, 2, token_key, meta_key,
                                   execution_id, int(duration * 1000),
                                   str(now), str(now + duration))
        return bool(result)

    def release(self, task_id: str, execution_id: str) -> bool:
        token_key, meta_key, _ = self._keys(task_id)
        result = self._client.eval(RELEASE_SCRIPT, 2, token_key, meta_key,
                                   execution_id)
        return bool(result)

    def read(self, task_id: str) -> Optional[LeaseRecord]:
        token_key, meta_key, _ = self._keys(task_id)
        token = self._client.get(token_key)
        if not token:
            return None
        meta = self._client.hgetall(meta_key)
        if not meta:
            return None
        return LeaseRecord.from_redis_meta(str(task_id), meta)

    def next_fence(self, task_id: str) -> int:
        _, _, fence_key = self._keys(task_id)
        return int(self._client.incr(fence_key) or 1)


def build_lease_store(lease_dir: Optional[str | os.PathLike] = None,
                      prefix: str = "ontology:") -> Optional[Any]:
    """Build the configured lease store.

    ``TASKS_LEASE_STORE`` selects the backend: ``file`` (default, flock-based
    per-task files under ``TASKS_LEASE_DIR`` or ``lease_dir``) or ``redis``
    (requires ``REDIS_URL`` and the ``redis`` package).  ``none`` disables
    durable leases entirely.  ``TASKS_LEASE_SECONDS`` sets the default lease
    length.
    """
    kind = str(os.environ.get("TASKS_LEASE_STORE", "file")).strip().lower()
    try:
        lease_seconds = float(os.environ.get("TASKS_LEASE_SECONDS",
                                             str(DEFAULT_LEASE_SECONDS)))
    except (TypeError, ValueError) as exc:
        raise ValueError("TASKS_LEASE_SECONDS must be a number") from exc
    if lease_seconds <= 0:
        raise ValueError("TASKS_LEASE_SECONDS must be positive")
    if kind in {"", "none", "off", "disabled"}:
        return None
    if kind == "redis":
        url = str(os.environ.get("REDIS_URL", "") or "").strip()
        if not url:
            raise ValueError("TASKS_LEASE_STORE=redis requires REDIS_URL")
        try:
            import redis  # noqa: PLC0415 - lazy optional dependency
        except ImportError as exc:
            raise RuntimeError("TASKS_LEASE_STORE=redis 需要安装 redis 包") from exc
        redis_prefix = str(os.environ.get("TASKS_REDIS_LEASE_PREFIX", prefix) or "")
        client = redis.Redis.from_url(url, decode_responses=True)
        return RedisExecutionLeaseStore(client, prefix=redis_prefix,
                                        lease_seconds=lease_seconds)
    if kind != "file":
        raise ValueError(f"未知的 TASKS_LEASE_STORE: {kind}")
    directory = str(os.environ.get("TASKS_LEASE_DIR", "") or "").strip() or lease_dir
    if not directory:
        raise ValueError("file lease store 需要 TASKS_LEASE_DIR 或 lease_dir")
    return FileExecutionLeaseStore(directory, lease_seconds=lease_seconds)
