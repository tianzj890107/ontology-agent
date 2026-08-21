"""Shared persistent repository boundary for standalone modeling runs.

The service can later point this small interface at PostgreSQL without making
the HTTP/worker layer know about storage details.  SQLite is the current
stdlib-backed deployment fallback: it gives separate API/worker processes a
shared durable state source and uses transactional upserts, while the legacy
JSON snapshot remains only as a migration/inspection compatibility artifact.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol


class RunRepository(Protocol):
    def upsert(self, snapshot: dict[str, Any]) -> None: ...
    def load_all(self) -> list[dict[str, Any]]: ...
    def get(self, run_id: str) -> dict[str, Any] | None: ...
    def delete(self, run_id: str) -> None: ...
    def compare_and_swap(self, snapshot: dict[str, Any], *,
                         expected_status: str, expected_updated_at: float) -> bool: ...


class SQLiteRunRepository:
    """Durable run metadata store with process-safe transactional updates."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._init_lock, self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=30000")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS modeling_runs ("
                "run_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, status TEXT NOT NULL, "
                "updated_at REAL NOT NULL, payload TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_modeling_runs_user_status "
                "ON modeling_runs(user_id, status)"
            )

    def _with_schema_recovery(self, operation):
        """Run one store operation, recreating the schema if the table is gone.

        An externally deleted/corrupted database file must not leave every
        modeling API request failing with ``no such table`` until a restart:
        ``CREATE TABLE IF NOT EXISTS`` is idempotent, so re-initializing once
        and retrying the operation self-heals the store in place.
        """
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            self._initialize()
            return operation()

    def upsert(self, snapshot: dict[str, Any]) -> None:
        self._with_schema_recovery(lambda: self._upsert(snapshot))

    def _upsert(self, snapshot: dict[str, Any]) -> None:
        run_id = str(snapshot["runId"])
        payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO modeling_runs(run_id,user_id,status,updated_at,payload) "
                "VALUES(?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET "
                "user_id=excluded.user_id,status=excluded.status,"
                "updated_at=excluded.updated_at,payload=excluded.payload",
                (run_id, str(snapshot.get("userId") or "anonymous"),
                 str(snapshot.get("status") or "CREATED"),
                 float(snapshot.get("updatedAt") or 0), payload),
            )
            connection.commit()

    def load_all(self) -> list[dict[str, Any]]:
        return self._with_schema_recovery(self._load_all)

    def _load_all(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM modeling_runs ORDER BY updated_at, run_id").fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                value = json.loads(row["payload"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                result.append(value)
        return result

    def get(self, run_id: str) -> dict[str, Any] | None:
        return self._with_schema_recovery(lambda: self._get(run_id))

    def _get(self, run_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM modeling_runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            return None
        try:
            value = json.loads(row["payload"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def delete(self, run_id: str) -> None:
        self._with_schema_recovery(lambda: self._delete(run_id))

    def _delete(self, run_id: str) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM modeling_runs WHERE run_id=?", (run_id,))

    def compare_and_swap(self, snapshot: dict[str, Any], *,
                         expected_status: str, expected_updated_at: float) -> bool:
        return self._with_schema_recovery(
            lambda: self._compare_and_swap(snapshot, expected_status=expected_status,
                                           expected_updated_at=expected_updated_at))

    def _compare_and_swap(self, snapshot: dict[str, Any], *,
                          expected_status: str, expected_updated_at: float) -> bool:
        """Commit a state mutation only if no other process changed the run."""
        run_id = str(snapshot["runId"])
        payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, updated_at FROM modeling_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if not row:
                connection.rollback()
                return False
            if (str(row["status"]) != str(expected_status)
                    or float(row["updated_at"]) != float(expected_updated_at)):
                connection.rollback()
                return False
            connection.execute(
                "UPDATE modeling_runs SET user_id=?,status=?,updated_at=?,payload=? "
                "WHERE run_id=? AND status=? AND updated_at=?",
                (str(snapshot.get("userId") or "anonymous"),
                 str(snapshot.get("status") or "CREATED"),
                 float(snapshot.get("updatedAt") or 0), payload, run_id,
                 str(expected_status), float(expected_updated_at)),
            )
            connection.commit()
            return True
