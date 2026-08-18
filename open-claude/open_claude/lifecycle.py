"""Small lifecycle primitives shared by the web and standalone services.

The loader is intentionally dependency-free.  It records readiness without
making optional services part of process startup, and its single-flight
implementation makes concurrent first use initialize a service only once.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class StageRecord:
    name: str
    status: str
    elapsed_ms: float
    detail: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "elapsedMs": round(self.elapsed_ms, 2),
            "detail": self.detail,
        }


class LifecycleTracker:
    """Thread-safe stage timing and readiness snapshot."""

    def __init__(self, service: str):
        self.service = service
        self.started_at = time.perf_counter()
        self._lock = threading.RLock()
        self._records: dict[str, StageRecord] = {}
        self.mark("process_start")

    def mark(self, name: str, status: str = "ready", detail: str = "") -> StageRecord:
        record = StageRecord(
            name=str(name), status=str(status),
            elapsed_ms=(time.perf_counter() - self.started_at) * 1000,
            detail=str(detail or ""),
        )
        with self._lock:
            self._records[record.name] = record
        return record

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            records = {key: value.as_dict() for key, value in self._records.items()}
            core = self._records.get("core_ready")
            full = self._records.get("full_ready")
            return {
                "service": self.service,
                "core": "ready" if core and core.status == "ready" else "loading",
                "full": "ready" if full and full.status == "ready" else "on_demand",
                "stages": records,
            }


class LazyService(Generic[T]):
    """Initialize a service once, with concurrent callers sharing the result."""

    def __init__(self, name: str, factory: Callable[[], T]):
        self.name = name
        self.factory = factory
        self._condition = threading.Condition(threading.RLock())
        self._status = "NOT_LOADED"
        self._value: T | None = None
        self._error: BaseException | None = None

    @property
    def status(self) -> str:
        with self._condition:
            return self._status

    def get(self) -> T:
        with self._condition:
            if self._status == "READY":
                return self._value  # type: ignore[return-value]
            if self._status == "FAILED":
                raise RuntimeError(f"lazy service {self.name} failed") from self._error
            if self._status == "LOADING":
                while self._status == "LOADING":
                    self._condition.wait()
                if self._status == "READY":
                    return self._value  # type: ignore[return-value]
                raise RuntimeError(f"lazy service {self.name} failed") from self._error
            self._status = "LOADING"
        try:
            value = self.factory()
        except BaseException as exc:
            with self._condition:
                self._error = exc
                self._status = "FAILED"
                self._condition.notify_all()
            raise
        with self._condition:
            self._value = value
            self._error = None
            self._status = "READY"
            self._condition.notify_all()
            return value

    def retry(self) -> T:
        with self._condition:
            if self._status == "LOADING":
                raise RuntimeError(f"lazy service {self.name} is loading")
            self._status = "NOT_LOADED"
            self._value = None
            self._error = None
        return self.get()
