"""Standalone, task-independent modeling-run API.

This service is deliberately a sidecar to ``oc_codex_server.py``.  It reuses
the existing modeling engine, decision/audit writer and sandbox boundary, but
has its own run store and workspace root.  The existing 47313 workbench is not
imported by this process until after the standalone root is selected and does
not share its task registry or HTTP routes.

Public workspace names are generic and canonical::

    <run>/input, <run>/work, <run>/output

New runs only create the canonical directories.  Historical runs created
before the rename may still contain ``mission-*`` symlink aliases; those are
resolved read-only through ``LEGACY_ALIASES`` (the centralized compatibility
mapping) and never appear in user-facing API responses or Agent prompts.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hmac
import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import time
import uuid
import weakref
from collections import Counter
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from open_claude.event_journal import append_line as _journal_append_line
from open_claude.event_journal import read_all_valid as _journal_read_all_valid
from open_claude.event_window import parse_window as _parse_event_window
from open_claude.event_window import window_response as _event_window_response
from open_claude.execution_coordinator import (
    CoordinatorConfig as _CoordinatorConfig,
    ExecutionCoordinator as _ExecutionCoordinator,
)
from open_claude.execution_lease import (
    FileExecutionLeaseStore as _FileExecutionLeaseStore,
    RedisExecutionLeaseStore as _RedisExecutionLeaseStore,
)
from open_claude.lifecycle import LazyService, LifecycleTracker
from open_claude.run_repository import SQLiteRunRepository


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ROOT = SCRIPT_DIR / "sandbox" / "standalone-modeling-runs"
FRONTEND_DIST = SCRIPT_DIR.parent / "frontend" / "dist"
DATABASE_SOURCES_FILE = Path(os.environ.get(
    "MODELING_DATABASE_SOURCES_FILE",
    str(SCRIPT_DIR.parent / ".standalone-modeling-data-sources.json"),
)).resolve()
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")
MAX_BODY_BYTES = 64 * 1024 * 1024
EVENT_CHECKPOINT_COUNT = 64
EVENT_CHECKPOINT_SECONDS = 0.5
DEFAULT_MAX_ACTIVE_RUNS = 10
DEFAULT_MAX_ACTIVE_PER_USER = 3
DEFAULT_MAX_QUEUED_PER_USER = 3
DEFAULT_MAX_QUEUED_RUNS = 50
DEFAULT_MAX_ONLINE_USERS = 100
MAX_ACTIVE_RUNS_LIMIT = 32
MAX_QUEUED_RUNS_LIMIT = 1000
DEFAULT_LEASE_SECONDS = 120.0
DEFAULT_HEARTBEAT_SECONDS = 5.0
_BROWSER_SESSION_TTL = 30 * 60
_BROWSER_SESSION_LOCK = threading.RLock()
_BROWSER_SESSIONS: dict[str, float] = {}
_BROWSER_SESSION_USERS: dict[str, str] = {}
PUBLIC_DIRS = ("input", "work", "output")

# Default checkpoint-resume instruction used when the user does not provide
# their own continuation text.  When the user does provide text it is kept
# verbatim and only this short constraint is appended.
RESUME_CHECKPOINT_PROMPT = (
    "继续执行上一次未完成的任务，从中断位置继续。不要重复已经完成的步骤。\n"
    "继续当前建模运行，不要从头执行。请读取 work/modeling_state.json、"
    "work/validation_report.json（如存在）以及现有 work/output 文件；"
    "保留已经 PASS 且产物未变化的阶段，只处理第一个未完成或失败的阶段。"
    "不要重复输入盘点、数据库连接验证或 schema 提取；如果当前阶段需要"
    "修复，完成修复后继续后续阶段。"
)
RESUME_CHECKPOINT_SUFFIX = (
    "\n\n继续当前建模运行，不要从头执行；保留已经 PASS 且产物未变化的阶段，"
    "只处理第一个未完成或失败的阶段；不要重复输入盘点、数据库连接验证或 "
    "schema 提取。"
)
_FILE_TREE_SKIP_DIRS = {".git", ".open-claude", "node_modules", "__pycache__", ".venv", "venv", "pylibs", ".py_deps"}
_WEB_HIDDEN_FILES = {".db_connection.json", ".env", ".env.local", "credentials.json",
                    "db_connection.py", "verify_database.py"}
_DECISION_AUDIT_FILENAMES = {
    "business_object_decisions.csv", "relation_decisions.csv", "rule_decisions.csv",
    "indicator_decisions.csv", "logical_entity_decisions.csv", "all_attributes.csv",
}
LEGACY_ALIASES = {
    "mission-input": "input",
    "mission-work": "work",
    "mission-output": "output",
}
INTERNAL_FILENAMES = {
    "modeling_state.json", "validation_report.json", "business_object_decisions.csv",
    "relation_decisions.csv", "rule_decisions.csv", "indicator_decisions.csv",
    "logical_entity_decisions.csv", "all_attributes.csv",
}
DEFAULT_ARTIFACTS = (
    "business_objects.csv",
    "logical_entities.csv",
    "business_attributes.csv",
    "entity_relations.csv",
    "business_rules.csv",
    "terms.csv",
    "indicators.csv",
)
DEFAULT_MODELING_PROMPT = (
    "请直接读取当前任务 input/ 中自动提供的四份 v0.0.1 规范/模板文件，"
    "结合已选择的数据表或上传文件完成本体建模，并生成所选正式输出和审计文件；"
    "无需等待用户补充建模要求。"
)
_MISSING = object()
BOOT = LifecycleTracker("standalone-modeling")


def _load_model_catalog() -> dict[str, Any]:
    """Expose the same safe model choices used by the 47313 workbench."""
    try:
        from open_claude.config import configured_models, get_model, get_model_provider
        current = get_model()
        models = [{
            "id": str(item.get("id")),
            "label": str(item.get("label") or item.get("id")),
            "provider": str(item.get("provider") or get_model_provider(item.get("id"))),
        } for item in configured_models() if item.get("id")]
        return {"model": current, "provider": get_model_provider(current), "models": models}
    except (ImportError, OSError, RuntimeError, ValueError, TypeError):
        # The API-only test/runtime path can run without the LLM configuration
        # stack. Keep the endpoint stable and let the UI show its fallback.
        return {"model": "", "provider": "", "models": []}


MODEL_CATALOG = LazyService("model_catalog", _load_model_catalog)


def _model_catalog() -> dict[str, Any]:
    return MODEL_CATALOG.get()


def _is_web_visible_file(rel: str) -> bool:
    parts = str(rel or "").replace("\\", "/").split("/")
    return not any(part in _WEB_HIDDEN_FILES or part.startswith(".") for part in parts)


def _file_tree_display_path(rel: str) -> str:
    """Use 47313's root/input/work/output presentation for standalone runs."""
    normalized = str(rel or "").replace("\\", "/").lstrip("./")
    parts = normalized.split("/")
    if len(parts) >= 2 and parts[0] == "work":
        if parts[1] in _DECISION_AUDIT_FILENAMES:
            return "work/" + "/".join(parts[1:])
        return "root/work/" + "/".join(parts[1:])
    if len(parts) >= 2 and parts[0] == "input":
        if len(parts) == 2 and "v0.0.1" in parts[1].lower():
            return "root/input/" + parts[1]
        if parts[1].lower().endswith("-sheets"):
            return "root/work/" + "/".join(parts[1:])
        return "input/" + "/".join(parts[1:])
    if len(parts) >= 2 and parts[0] == "output":
        return "output/" + "/".join(parts[1:])
    return normalized


def _load_database_sources() -> list[dict[str, Any]]:
    """Load server-side data sources without exposing credentials to clients."""
    if not DATABASE_SOURCES_FILE.exists():
        return []
    try:
        raw = json.loads(DATABASE_SOURCES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("database source registry is invalid") from exc
    items = raw.get("sources") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise RuntimeError("database source registry must contain an array")
    sources = []
    for item in items:
        if not isinstance(item, dict):
            raise RuntimeError("database source entry must be an object")
        source_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        if not source_id or not name:
            raise RuntimeError("database source entry requires id and name")
        config = dict(item.get("config") or item)
        config.pop("id", None)
        config.pop("name", None)
        config.pop("label", None)
        normalized = _normalize_database_config(config)
        if normalized is None:
            raise RuntimeError(f"database source {source_id} has no connection config")
        sources.append({"id": source_id, "name": name, "config": normalized})
    return sources


def _database_source_options() -> list[dict[str, Any]]:
    """Return safe metadata for the standalone database selector."""
    options = []
    for item in _load_database_sources():
        config = item["config"]
        options.append({
            "id": item["id"],
            "name": item["name"],
            "dbType": config.get("dbType", ""),
            "database": config.get("database", ""),
            "sourceSchema": config.get("sourceSchema", ""),
        })
    return options


def _database_source_config(source_id: Any) -> tuple[str, dict[str, Any]]:
    requested = str(source_id or "").strip()
    for item in _load_database_sources():
        if item["id"] == requested:
            return requested, dict(item["config"])
    raise ClientInputError(
        "Unknown database source",
        details={"invalidDatabaseSourceId": requested}, status=422)


def _database_source_engine(config: dict[str, Any]):
    """Create a SQLAlchemy engine for a registered source."""
    from sqlalchemy import URL, create_engine
    from open_claude.credential_crypto import decrypt_connection_credential

    db_type = str(config.get("dbType") or "POSTGRESQL").upper().replace("-", "_")
    dialects = {
        "POSTGRESQL": "postgresql+psycopg2",
        "GAUSSDB": "postgresql+psycopg2",
        "MYSQL": "mysql+pymysql",
        "ORACLE": "oracle+oracledb",
    }
    dialect = dialects.get(db_type)
    if not dialect:
        raise RuntimeError(f"暂不支持的数据库类型: {db_type}")
    password = decrypt_connection_credential(config.get("password"),
                                              config.get("passwordEncrypted"))
    return create_engine(URL.create(
        dialect,
        username=config["username"], password=password,
        host=config["host"], port=int(config.get("port", 5432)),
        database=config["database"],
    ))


def _list_database_source_schemas(source_id: Any) -> dict[str, Any]:
    """List selectable schemas without exposing connection credentials."""
    _, config = _database_source_config(source_id)
    from sqlalchemy import text

    engine = _database_source_engine(config)
    try:
        with engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT schema_name FROM information_schema.schemata "
                "ORDER BY schema_name"
            )).mappings().all()
    finally:
        engine.dispose()
    excluded = {"information_schema", "pg_catalog"}
    schemas = [str(row["schema_name"]) for row in rows
               if str(row["schema_name"]) not in excluded
               and not str(row["schema_name"]).lower().startswith("pg_")]
    default_schema = str(config.get("sourceSchema") or "").strip()
    return {"schemas": schemas, "defaultSchema": default_schema}


def _list_database_source_tables(source_id: Any, schemas: list[str] | None = None) -> dict[str, Any]:
    """Read table names through the same SQLAlchemy credential path as 47313."""
    _, config = _database_source_config(source_id)
    from sqlalchemy import text

    selected = schemas if schemas is not None else config.get("selectedSchemas")
    if not isinstance(selected, list) or not selected:
        selected = [str(config.get("sourceSchema") or "public")]
    selected = list(dict.fromkeys(str(schema).strip() for schema in selected if str(schema).strip()))
    if not selected:
        raise ClientInputError("至少选择一个 Schema", status=422)
    engine = _database_source_engine(config)
    try:
        with engine.connect() as connection:
            placeholders = ", ".join(f":schema_{index}" for index in range(len(selected)))
            params = {f"schema_{index}": schema for index, schema in enumerate(selected)}
            rows = connection.execute(text(
                "SELECT table_schema, table_name, table_type "
                "FROM information_schema.tables "
                f"WHERE table_schema IN ({placeholders}) "
                "AND table_type IN ('BASE TABLE', 'VIEW') "
                "ORDER BY table_schema, table_name"
            ), params).mappings().all()
    finally:
        engine.dispose()
    return {
        "schemas": selected,
        "schema": selected[0] if len(selected) == 1 else "",
        "tables": [{"schema": row["table_schema"], "name": row["table_name"],
                    "type": row["table_type"]}
                   for row in rows],
    }


def _is_table_count_request(prompt: Any) -> bool:
    """Recognize a read-only table-count question before the model starts."""
    text = str(prompt or "").strip().lower()
    asks_count = any(token in text for token in ("多少表", "几张表", "表数量", "表的数量", "how many tables"))
    defer_modeling = any(token in text for token in ("先别建模", "暂不建模", "不要建模", "不建模", "don't model", "do not model"))
    return asks_count and defer_modeling


def _table_count_answer(run: "ModelingRun") -> str:
    if run.database_source_id:
        selected_schemas = (run.database or {}).get("selectedSchemas") if isinstance(run.database, dict) else None
        result = _list_database_source_tables(run.database_source_id, selected_schemas)
    else:
        raise ClientInputError("当前运行没有可查询的数据源", status=422)
    counts = Counter(str(item.get("type") or "").upper() for item in result.get("tables", []))
    total = len(result.get("tables", []))
    base_tables = counts.get("BASE TABLE", 0)
    views = counts.get("VIEW", 0)
    schema = result.get("schema") or "当前 Schema"
    return (f"已连接数据库 {run.database_source_id}，Schema `{schema}` 共发现 {total} 个对象："
            f"{base_tables} 张物理表、{views} 个视图。按表清单口径，当前共有 {total} 个对象；"
            "本轮按你的要求只回答数量，不启动建模。")
RUN_STATES = {
    "CREATED", "INPUT_READY", "QUEUED", "CLAIMED", "ANALYZING", "VALIDATING",
    "SUCCEEDED", "CANCELLING", "CANCELLED", "FAILED", "BLOCKED",
}
RUN_TRANSITIONS = {
    "CREATED": {"INPUT_READY", "QUEUED", "ANALYZING", "VALIDATING", "FAILED", "BLOCKED"},
    "INPUT_READY": {"INPUT_READY", "QUEUED", "ANALYZING", "VALIDATING", "FAILED", "BLOCKED"},
    "QUEUED": {"CLAIMED", "CANCELLED", "FAILED"},
    "CLAIMED": {"ANALYZING", "CANCELLING", "FAILED"},
    # VALIDATING is an internal completion step; the public validate endpoint
    # still rejects ANALYZING through ModelingRunManager.validate().
    "ANALYZING": {"VALIDATING", "SUCCEEDED", "CANCELLING", "FAILED", "BLOCKED"},
    "VALIDATING": {"SUCCEEDED", "CANCELLING", "FAILED", "BLOCKED"},
    "SUCCEEDED": set(),
    "CANCELLING": {"CANCELLED", "FAILED"},
    "CANCELLED": {"QUEUED", "FAILED"},
    "FAILED": {"INPUT_READY", "QUEUED", "ANALYZING", "VALIDATING"},
    "BLOCKED": {"INPUT_READY", "QUEUED", "ANALYZING", "VALIDATING"},
}
ARTIFACT_PARSE_ELEMENTS = {
    "business_objects.csv": "BUSINESS_OBJECT",
    "logical_entities.csv": "LOGICAL_ENTITY",
    "business_attributes.csv": "BUSINESS_ATTRIBUTE",
    "entity_relations.csv": "ENTITY_RELATION",
    "business_rules.csv": "BUSINESS_RULE",
    "terms.csv": "TERM",
    "indicators.csv": "METRIC",
}


class ClientInputError(ValueError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None, status: int = 422):
        super().__init__(message)
        self.details = details or {}
        self.status = status


class ActiveRunError(RuntimeError):
    """Compatibility error for callers that still expect an active-run conflict."""

    def __init__(self, run_id: str):
        super().__init__(f"another modeling run is already active: {run_id}")
        self.run_id = run_id


class StateTransitionError(RuntimeError):
    def __init__(self, run_id: str, previous: str, requested: str):
        super().__init__(f"invalid run state transition: {previous} -> {requested}")
        self.run_id = run_id
        self.previous = previous
        self.requested = requested


class QueueLimitError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class _RunHandle:
    """Small compatibility handle with a Thread-like join API.

    The actual work is owned by the shared ExecutionCoordinator worker pool;
    the adapter marks the handle finished when the worker exits so existing
    callers can keep using a Thread-like join without owning the future.
    """
    def __init__(self):
        self._done = threading.Event()

    def finish(self) -> None:
        self._done.set()

    def join(self, timeout: float | None = None) -> None:
        self._done.wait(timeout)

    def is_alive(self) -> bool:
        return not self._done.is_set()


def _build_standalone_lease_store(lease_dir: str,
                                  lease_seconds: float) -> Any:
    """Build the 47314 durable lease store from ``MODELING_SERVER_*`` env."""
    kind = str(os.environ.get("MODELING_SERVER_LEASE_STORE", "file")).strip().lower()
    if kind in {"", "none", "off", "disabled"}:
        return None
    if kind == "redis":
        url = (str(os.environ.get("MODELING_REDIS_URL", "") or "").strip()
               or str(os.environ.get("REDIS_URL", "") or "").strip())
        if not url:
            raise ValueError("MODELING_SERVER_LEASE_STORE=redis 需要 "
                             "MODELING_REDIS_URL 或 REDIS_URL")
        try:
            import redis  # noqa: PLC0415 - lazy optional dependency
        except ImportError as exc:
            raise RuntimeError("MODELING_SERVER_LEASE_STORE=redis 需要安装 "
                               "redis 包") from exc
        return _RedisExecutionLeaseStore(
            redis.Redis.from_url(url, decode_responses=True),
            prefix="ontology:47314:", lease_seconds=lease_seconds)
    if kind != "file":
        raise ValueError(f"未知的 MODELING_SERVER_LEASE_STORE: {kind}")
    directory = str(os.environ.get("MODELING_SERVER_LEASE_DIR", "") or "").strip()
    if not directory:
        directory = lease_dir
    if not directory:
        raise ValueError("file lease store 需要 MODELING_SERVER_LEASE_DIR")
    return _FileExecutionLeaseStore(directory, lease_seconds=lease_seconds)


class _StandaloneExecutionAdapter:
    """Bridge 47314 runs into the shared ExecutionCoordinator.

    Run state stays in RunStore; this adapter only connects coordinator
    callbacks (queue admission, worker start, heartbeat-loss events, worker
    completion) back to the manager's store transitions and worker body.
    """

    scope = "ontology:47314"

    def __init__(self, manager: "ModelingRunManager"):
        self.manager = manager
        self.instance_id = manager.worker_id

    def _run(self, execution_id: str) -> Any:
        store = self.manager.store
        with store.lock:
            run = store.runs.get(execution_id)
        return run

    def record_event(self, execution_id: str, event: dict[str, Any]) -> None:
        run = self._run(execution_id)
        if run is None:
            return
        try:
            self.manager.store.append_event(
                run, event.get("type", "agent_event"), **event)
        except Exception:
            pass
        if event.get("code") == "LEASE_LOST":
            # A lost lease must stop the run and never leave a permanent
            # working state.  The store transition CAS prevents a stale
            # worker from overwriting this terminal state afterwards.
            try:
                self.manager.store.transition(
                    run, "FAILED", error="WORKER_LEASE_EXPIRED",
                    allowed_from={"CLAIMED", "ANALYZING", "VALIDATING"})
            except StateTransitionError:
                pass

    def on_queued(self, execution_id: str, position: int,
                  queue_length: int) -> None:
        # execute() records run_queued with the exact claim position; the
        # coordinator callback is only used for bookkeeping parity.
        return None

    def on_started(self, execution_id: str) -> None:
        run = self._run(execution_id)
        if run is None or run.status != "QUEUED":
            return
        now = time.time()
        attempt = int(getattr(run, "attempt_number", 0) or 0) + 1
        try:
            self.manager.store.transition_and_update(
                run, "CLAIMED", allowed_from={"QUEUED"},
                changes={
                    "attempt_number": attempt,
                    "attempt_id": f"{run.run_id}-attempt-{attempt}-"
                                  f"{uuid.uuid4().hex[:8]}",
                    "worker_id": self.manager.worker_id,
                    "claimed_at": now,
                    "heartbeat_at": now,
                    "lease_expires_at": now + self.manager.lease_seconds,
                    "cancel_requested": False,
                })
        except StateTransitionError:
            return

    def run_worker(self, execution_id: str, token: Any) -> None:
        run = self._run(execution_id)
        if run is None or token.cancelled:
            return
        execution_guard = None
        coordinator = getattr(self.manager, "coordinator", None)
        if coordinator is not None:
            execution_guard = coordinator.execution_context(execution_id)
        self.manager._run_worker(run, token=token,
                                 execution_guard=execution_guard)

    def on_finished(self, execution_id: str, ok: bool, token: Any) -> None:
        del ok, token
        handle = self.manager.threads.get(execution_id)
        if handle is not None:
            handle.finish()
        self.manager.execution_modes.pop(execution_id, None)
        self.manager.execution_prompts.pop(execution_id, None)


def _normalize_requested_artifacts(value: Any) -> list[str]:
    """Validate the explicit API contract; never silently widen the scope."""
    if value is None:
        return list(DEFAULT_ARTIFACTS)
    if not isinstance(value, list) or not value:
        raise ClientInputError(
            "requestedArtifacts must be a non-empty array when provided",
            details={"requestedArtifacts": value}, status=422)
    values = [str(item).strip() for item in value]
    invalid = sorted({item for item in values if item not in DEFAULT_ARTIFACTS})
    if invalid:
        raise ClientInputError(
            "Unknown requested artifact",
            details={"invalidArtifacts": invalid}, status=422)
    duplicates = sorted({item for item in values if values.count(item) > 1})
    if duplicates:
        raise ClientInputError(
            "requestedArtifacts contains duplicates",
            details={"duplicateArtifacts": duplicates}, status=422)
    return values


def _normalize_database_config(value: Any) -> dict[str, Any] | None:
    """Validate the same database context shape consumed by the 47313 Task.

    The password is deliberately preserved as supplied (plaintext legacy or
    ConnectionConfigCrypto ciphertext) so the existing 47313 materialization
    and fail-closed crypto service remain the only credential implementation.
    It is never included in the public run response.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ClientInputError("database must be an object", status=422)
    config = dict(value)
    allow_empty_password = config.get("allowEmptyPassword", False)
    if not isinstance(allow_empty_password, bool):
        raise ClientInputError("database.allowEmptyPassword must be a boolean", status=422)
    required = ("host", "username", "database")
    missing = [name for name in required if not isinstance(config.get(name), str)
               or not config[name].strip()]
    if not allow_empty_password and (not isinstance(config.get("password"), str)
                                     or not config["password"].strip()):
        missing.append("password")
    if missing:
        raise ClientInputError(
            "database is missing required connection fields",
            details={"missingFields": sorted(set(missing))}, status=422)
    if "port" in config:
        try:
            port = int(config["port"])
        except (TypeError, ValueError) as exc:
            raise ClientInputError("database.port must be an integer", status=422) from exc
        if not 1 <= port <= 65535:
            raise ClientInputError("database.port is outside the valid range", status=422)
        config["port"] = port
    for name in ("dbType", "sourceSchema"):
        if name in config and config[name] is not None and not isinstance(config[name], str):
            raise ClientInputError(f"database.{name} must be a string", status=422)
    if "selectedSchemas" in config:
        if not isinstance(config["selectedSchemas"], list) or not all(
                isinstance(item, str) and item.strip() for item in config["selectedSchemas"]):
            raise ClientInputError("database.selectedSchemas must be an array of strings", status=422)
    if "selectedTables" in config:
        if not isinstance(config["selectedTables"], list) or not all(
                isinstance(item, str) and item.strip() for item in config["selectedTables"]):
            raise ClientInputError("database.selectedTables must be an array of strings", status=422)
    return config


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


def _safe_relpath(value: str) -> str:
    value = str(value or "").replace("\\", "/").strip()
    if not value or value.startswith("/") or "\x00" in value:
        raise ValueError("path must be a non-empty relative path")
    parts = [part for part in value.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ValueError("path traversal is not allowed")
    if parts[0] in LEGACY_ALIASES:
        parts[0] = LEGACY_ALIASES[parts[0]]
    if parts[0] not in PUBLIC_DIRS:
        raise ValueError("path must start with input, work or output")
    return "/".join(parts)


@dataclass
class ModelingRun:
    run_id: str
    root: str
    user_id: str = "anonymous"
    idempotency_key: str = ""
    status: str = "CREATED"
    source_mode: str = "NATURAL_LANGUAGE"
    title: str = ""
    prompt: str = ""
    requested_artifacts: list[str] = field(default_factory=lambda: list(DEFAULT_ARTIFACTS))
    database_source_id: str = ""
    database: dict[str, Any] | None = None
    model: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    error: str = ""
    attempt_id: str = ""
    attempt_number: int = 0
    worker_id: str = ""
    claimed_at: float = 0.0
    heartbeat_at: float = 0.0
    lease_expires_at: float = 0.0
    cancel_requested: bool = False
    result_attempt_id: str = ""
    resume_session_id: str = ""
    checkpoint_stage: str = ""
    checkpoint_signature: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    state_lock: threading.RLock = field(default_factory=threading.RLock,
                                         repr=False, compare=False)

    def as_dict(self, *, include_database: bool = False,
                include_events: bool = True) -> dict[str, Any]:
        result = {
            "runId": self.run_id,
            "workspaceId": self.run_id,
            "root": self.root,
            "userId": self.user_id,
            "idempotencyKey": self.idempotency_key or None,
            "status": self.status,
            "sourceMode": self.source_mode,
            "title": self.title,
            "prompt": self.prompt,
            "requestedArtifacts": self.requested_artifacts,
            "databaseSourceId": self.database_source_id or None,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "error": self.error,
            "eventsCount": len(self.events),
            "databaseConfigured": bool(self.database),
            "model": self.model,
            "attemptId": self.attempt_id or None,
            "attemptNumber": self.attempt_number,
            "workerId": self.worker_id or None,
            "claimedAt": self.claimed_at or None,
            "heartbeatAt": self.heartbeat_at or None,
            "leaseExpiresAt": self.lease_expires_at or None,
            "cancelRequested": self.cancel_requested,
            "resultAttemptId": self.result_attempt_id or None,
            "resumeSessionId": self.resume_session_id or None,
            "checkpointStage": self.checkpoint_stage or None,
            "checkpointSignature": self.checkpoint_signature or None,
        }
        if include_events:
            result["events"] = self.events
        if include_database and self.database is not None:
            result["database"] = self.database
        return result


class RunStore:
    """Persistent run metadata plus one workspace per run."""

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / ".runs.json"
        self.repository = SQLiteRunRepository(self.root / ".runs.sqlite3")
        self.lock = threading.RLock()
        # Event journals are per-run files.  Keep checkpoint bookkeeping out
        # of the store lock so concurrent runs do not serialize every streamed
        # thinking event behind the global run index lock.
        self._checkpoint_lock = threading.RLock()
        self.runs: dict[str, ModelingRun] = {}
        self._managers: weakref.WeakSet[Any] = weakref.WeakSet()
        self._events_since_checkpoint: dict[str, int] = {}
        self._last_event_checkpoint: dict[str, float] = {}
        self._load()

    def register_manager(self, manager: Any) -> None:
        self._managers.add(manager)

    def close_managers(self) -> None:
        for manager in list(self._managers):
            try:
                manager.close()
            except Exception:
                continue

    @staticmethod
    def _events_path(run: ModelingRun) -> Path:
        return Path(run.root) / ".events.jsonl"

    def _read_event_journal(self, run: ModelingRun,
                            legacy_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Load append-only events while preserving pre-journal indexes."""
        path = self._events_path(run)
        if not path.is_file():
            return legacy_events
        journal: list[dict[str, Any]] = []
        try:
            journal = _journal_read_all_valid(str(path))
        except OSError:
            return legacy_events
        if not legacy_events:
            return journal
        # Older indexes stored events inline.  A journal created after such
        # an index starts at the next sequence number; avoid dropping either
        # history when the service upgrades in place.
        merged = {int(event.get("seq", index)): event
                  for index, event in enumerate(legacy_events)
                  if isinstance(event, dict)}
        merged.update({int(event.get("seq", len(merged))): event
                       for event in journal})
        return [merged[key] for key in sorted(merged)]

    def _hydrate_repository_item(self, item: dict[str, Any]) -> ModelingRun:
        run = ModelingRun(
            run_id=str(item["runId"]), root=str(item["root"]),
            user_id=str(item.get("userId") or "anonymous"),
            idempotency_key=str(item.get("idempotencyKey") or ""),
            status=str(item.get("status", "CREATED")),
            source_mode=str(item.get("sourceMode", "NATURAL_LANGUAGE")),
            title=str(item.get("title") or ""),
            prompt=str(item.get("prompt", "")),
            requested_artifacts=list(item.get("requestedArtifacts") or DEFAULT_ARTIFACTS),
            database_source_id=str(item.get("databaseSourceId") or ""),
            database=(dict(item["database"]) if isinstance(item.get("database"), dict) else None),
            model=str(item.get("model") or ""),
            created_at=float(item.get("createdAt", time.time())),
            updated_at=float(item.get("updatedAt", time.time())),
            error=str(item.get("error", "")),
            attempt_id=str(item.get("attemptId") or ""),
            attempt_number=int(item.get("attemptNumber") or 0),
            worker_id=str(item.get("workerId") or ""),
            claimed_at=float(item.get("claimedAt") or 0),
            heartbeat_at=float(item.get("heartbeatAt") or 0),
            lease_expires_at=float(item.get("leaseExpiresAt") or 0),
            cancel_requested=bool(item.get("cancelRequested", False)),
            result_attempt_id=str(item.get("resultAttemptId") or ""),
            resume_session_id=str(item.get("resumeSessionId") or ""),
            checkpoint_stage=str(item.get("checkpointStage") or ""),
            checkpoint_signature=str(item.get("checkpointSignature") or ""),
            events=[],
        )
        run.events = self._read_event_journal(run, [])
        return run

    def refresh_from_repository(self) -> None:
        """Refresh run metadata so separate API/worker processes converge."""
        with self.lock:
            for item in self.repository.load_all():
                run_id = str(item.get("runId") or "")
                if not run_id:
                    continue
                existing = self.runs.get(run_id)
                if existing is None:
                    self.runs[run_id] = self._hydrate_repository_item(item)
                    continue
                if float(item.get("updatedAt") or 0) <= existing.updated_at:
                    continue
                with existing.state_lock:
                    existing.status = str(item.get("status") or existing.status)
                    existing.error = str(item.get("error") or "")
                    existing.user_id = str(item.get("userId") or existing.user_id)
                    existing.title = str(item.get("title") or existing.title)
                    existing.prompt = str(item.get("prompt") or existing.prompt)
                    existing.model = str(item.get("model") or existing.model)
                    existing.attempt_id = str(item.get("attemptId") or "")
                    existing.attempt_number = int(item.get("attemptNumber") or 0)
                    existing.worker_id = str(item.get("workerId") or "")
                    existing.claimed_at = float(item.get("claimedAt") or 0)
                    existing.heartbeat_at = float(item.get("heartbeatAt") or 0)
                    existing.lease_expires_at = float(item.get("leaseExpiresAt") or 0)
                    existing.cancel_requested = bool(item.get("cancelRequested", False))
                    existing.result_attempt_id = str(item.get("resultAttemptId") or "")
                    existing.resume_session_id = str(item.get("resumeSessionId") or existing.resume_session_id)
                    existing.checkpoint_stage = str(item.get("checkpointStage") or existing.checkpoint_stage)
                    existing.checkpoint_signature = str(item.get("checkpointSignature") or existing.checkpoint_signature)
                    existing.updated_at = float(item.get("updatedAt") or existing.updated_at)

    def _append_event_journal(self, run: ModelingRun, event: dict[str, Any]) -> None:
        path = self._events_path(run)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Migrate an old inline-event run once, before appending new events.
        if not path.exists() and len(run.events) > 1:
            with path.open("w", encoding="utf-8") as handle:
                for previous in run.events[:-1]:
                    handle.write(json.dumps(previous, ensure_ascii=False,
                                             separators=(",", ":")))
                    handle.write("\n")
        _journal_append_line(str(path), event)

    def _load(self) -> None:
        repository_items = self.repository.load_all()
        if repository_items:
            raw_items = repository_items
        elif self.index_path.exists():
            try:
                raw_items = json.loads(self.index_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                raw_items = []
        else:
            return
        try:
            for item in raw_items if isinstance(raw_items, list) else []:
                run = ModelingRun(
                    run_id=str(item["runId"]), root=str(item["root"]),
                    user_id=str(item.get("userId") or "anonymous"),
                    idempotency_key=str(item.get("idempotencyKey") or ""),
                    status=str(item.get("status", "CREATED")),
                    source_mode=str(item.get("sourceMode", "NATURAL_LANGUAGE")),
                    title=str(item.get("title") or ""),
                    prompt=str(item.get("prompt", "")),
                    requested_artifacts=list(item.get("requestedArtifacts") or DEFAULT_ARTIFACTS),
                    database_source_id=str(item.get("databaseSourceId") or ""),
                    database=(dict(item["database"]) if isinstance(item.get("database"), dict)
                              else None),
                    model=str(item.get("model") or ""),
                    created_at=float(item.get("createdAt", time.time())),
                    updated_at=float(item.get("updatedAt", time.time())),
                    error=str(item.get("error", "")),
                    attempt_id=str(item.get("attemptId") or ""),
                    attempt_number=int(item.get("attemptNumber") or 0),
                    worker_id=str(item.get("workerId") or ""),
                    claimed_at=float(item.get("claimedAt") or 0),
                    heartbeat_at=float(item.get("heartbeatAt") or 0),
                    lease_expires_at=float(item.get("leaseExpiresAt") or 0),
                    cancel_requested=bool(item.get("cancelRequested", False)),
                    result_attempt_id=str(item.get("resultAttemptId") or ""),
                    resume_session_id=str(item.get("resumeSessionId") or ""),
                    checkpoint_stage=str(item.get("checkpointStage") or ""),
                    checkpoint_signature=str(item.get("checkpointSignature") or ""),
                    events=[],
                )
                legacy_events = [event for event in (item.get("events") or [])
                                 if isinstance(event, dict)]
                run.events = self._read_event_journal(run, legacy_events)
                self.runs[run.run_id] = run
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            # A corrupt index must not make existing run directories unsafe or
            # inaccessible.  New runs can still be created and the index will
            # be repaired on the next save.
            self.runs = {}
        if not repository_items and self.runs:
            # Migrate the legacy JSON index once; subsequent state changes use
            # the shared repository as the conditional-write source.
            self._save()
        self._recover_interrupted_runs()

    def _recover_interrupted_runs(self) -> None:
        changed = False
        for run in self.runs.values():
            if run.status not in {"CLAIMED", "ANALYZING", "VALIDATING"}:
                continue
            previous = run.status
            reason = {
                "CLAIMED": "SERVER_RESTARTED_AFTER_WORKER_CLAIM",
                "ANALYZING": "SERVER_RESTARTED_DURING_ANALYSIS",
                "VALIDATING": "SERVER_RESTARTED_DURING_VALIDATION",
            }[previous]
            run.status = "FAILED"
            run.error = reason
            run.worker_id = ""
            run.lease_expires_at = 0.0
            run.updated_at = time.time()
            event = {"seq": len(run.events), "type": "run_interrupted",
                     "timestamp": run.updated_at,
                     "previousStatus": previous, "reason": reason}
            run.events.append(event)
            self._append_event_journal(run, event)
            changed = True
        if changed:
            self._save()

    def _save(self, *, persist_repository: bool = True) -> None:
        with self.lock:
            snapshots = []
            for run in self.runs.values():
                with run.state_lock:
                    snapshots.append(run.as_dict(include_database=True, include_events=False))
            if persist_repository:
                for snapshot in snapshots:
                    self.repository.upsert(snapshot)
            _atomic_write(self.index_path, _json_dump(snapshots))

    def _run_root(self, run_id: str) -> Path:
        path = (self.root / run_id).resolve()
        if path.parent != self.root:
            raise ValueError("invalid run id")
        return path

    @staticmethod
    def _ensure_alias(root: Path, alias: str, target: str) -> None:
        """Deprecated: only used to repair/read historical run aliases.

        New runs never create ``mission-*`` aliases.
        """
        link = root / alias
        if link.is_symlink():
            if link.resolve() == (root / target).resolve():
                return
            link.unlink()
        elif link.exists():
            if link.is_dir() and not any(link.iterdir()):
                link.rmdir()
            else:
                raise RuntimeError(f"workspace alias already contains data: {alias}")
        link.symlink_to(target, target_is_directory=True)

    def create(self, source_mode: str, prompt: str, artifacts: Any = None,
               title: str = "",
               database: Any = None, database_source_id: Any = None,
               selected_tables: Any = None, selected_schemas: Any = None,
               user_id: str = "anonymous",
               idempotency_key: str | None = None) -> ModelingRun:
        # Validate all client-controlled options before creating the run root.
        # In particular, an invalid requestedArtifacts value must not leave an
        # unregistered directory behind.
        requested = _normalize_requested_artifacts(artifacts)
        source_id = str(database_source_id or "").strip()
        if source_id and database is not None:
            raise ClientInputError(
                "provide only one of databaseSourceId or database", status=422)
        normalized_database = (_database_source_config(source_id)[1]
                               if source_id else _normalize_database_config(database))
        if normalized_database is not None and selected_tables is not None:
            normalized_database["selectedTables"] = selected_tables
            normalized_database = _normalize_database_config(normalized_database)
        if normalized_database is not None and selected_schemas is not None:
            normalized_database["selectedSchemas"] = selected_schemas
            normalized_database = _normalize_database_config(normalized_database)
        normalized_user = str(user_id or "anonymous").strip() or "anonymous"
        normalized_key = str(idempotency_key or "").strip()
        with self.lock:
            if normalized_key:
                for existing in self.runs.values():
                    if (existing.user_id == normalized_user
                            and existing.idempotency_key == normalized_key):
                        return existing
            run_id = f"run_{uuid.uuid4().hex}"
            root = self._run_root(run_id)
            root.mkdir(parents=True, exist_ok=False)
            for name in PUBLIC_DIRS:
                (root / name).mkdir()
            normalized_prompt = str(prompt or "").strip() or DEFAULT_MODELING_PROMPT
            normalized_title = str(title or "").strip()
            run = ModelingRun(run_id=run_id, root=str(root),
                              user_id=normalized_user, idempotency_key=normalized_key,
                              source_mode=str(source_mode or "NATURAL_LANGUAGE"),
                              title=normalized_title,
                              prompt=normalized_prompt, requested_artifacts=requested,
                              database_source_id=source_id,
                              database=normalized_database)
            self.runs[run_id] = run
            self._save()
            return run

    def counts(self, *, user_id: str | None = None) -> dict[str, int]:
        with self.lock:
            runs = [run for run in self.runs.values()
                    if user_id is None or run.user_id == user_id]
            return {
                "active": sum(run.status in {"CLAIMED", "ANALYZING", "VALIDATING", "CANCELLING"}
                               for run in runs),
                "queued": sum(run.status == "QUEUED" for run in runs),
            }

    def list_for_user(self, user_id: str) -> list[ModelingRun]:
        with self.lock:
            return [run for run in self.runs.values() if run.user_id == user_id]

    def request_cancel(self, run: ModelingRun) -> None:
        if run.status == "QUEUED":
            self.transition_and_update(run, "CANCELLED", allowed_from={"QUEUED"},
                                       changes={"cancel_requested": True})
        elif run.status in {"CLAIMED", "ANALYZING", "VALIDATING"}:
            self.transition_and_update(
                run, "CANCELLING",
                allowed_from={"CLAIMED", "ANALYZING", "VALIDATING"},
                changes={"cancel_requested": True})
        else:
            raise StateTransitionError(run.run_id, run.status, "CANCELLING")
        self.append_event(run, "run_cancellation_requested")

    def heartbeat(self, run: ModelingRun, *, worker_id: str,
                  lease_seconds: float) -> None:
        with self.lock, run.state_lock:
            if run.worker_id != worker_id or run.status not in {
                    "CLAIMED", "ANALYZING", "VALIDATING", "CANCELLING"}:
                return
            now = time.time()
        try:
            self.transition_and_update(
                run, run.status, allowed_from={run.status},
                changes={"heartbeat_at": now, "lease_expires_at": now + lease_seconds})
        except StateTransitionError:
            # A cancellation, failure or another worker's terminal update won
            # the CAS; the heartbeat must not resurrect it.
            return

    def get(self, run_id: str) -> ModelingRun:
        with self.lock:
            if run_id not in self.runs:
                snapshot = self.repository.get(run_id)
                if snapshot:
                    self.runs[run_id] = self._hydrate_repository_item(snapshot)
                else:
                    raise KeyError(run_id)
            run = self.runs[run_id]
            snapshot = self.repository.get(run_id)
            if snapshot and float(snapshot.get("updatedAt") or 0) > run.updated_at:
                with run.state_lock:
                    run.status = str(snapshot.get("status") or run.status)
                    run.error = str(snapshot.get("error") or "")
                    run.title = str(snapshot.get("title") or run.title)
                    run.prompt = str(snapshot.get("prompt") or run.prompt)
                    run.model = str(snapshot.get("model") or run.model)
                    run.attempt_id = str(snapshot.get("attemptId") or "")
                    run.attempt_number = int(snapshot.get("attemptNumber") or 0)
                    run.worker_id = str(snapshot.get("workerId") or "")
                    run.claimed_at = float(snapshot.get("claimedAt") or 0)
                    run.heartbeat_at = float(snapshot.get("heartbeatAt") or 0)
                    run.lease_expires_at = float(snapshot.get("leaseExpiresAt") or 0)
                    run.cancel_requested = bool(snapshot.get("cancelRequested", False))
                    run.result_attempt_id = str(snapshot.get("resultAttemptId") or "")
                    run.resume_session_id = str(snapshot.get("resumeSessionId") or run.resume_session_id)
                    run.checkpoint_stage = str(snapshot.get("checkpointStage") or run.checkpoint_stage)
                    run.checkpoint_signature = str(snapshot.get("checkpointSignature") or run.checkpoint_signature)
                    run.updated_at = float(snapshot.get("updatedAt") or run.updated_at)
            return run

    def remove(self, run: ModelingRun) -> None:
        """Rollback a run that failed during initial persistence."""
        with self.lock, run.state_lock:
            self.runs.pop(run.run_id, None)
            self.repository.delete(run.run_id)
            root = Path(run.root)
            if root.exists():
                import shutil
                shutil.rmtree(root)
            self._save()

    def update(self, run: ModelingRun, **changes: Any) -> None:
        with self.lock:
            with run.state_lock:
                if "status" in changes:
                    status = changes.pop("status")
                    self._transition_locked(run, status)
                for key, value in changes.items():
                    setattr(run, key, value)
                run.updated_at = time.time()
                self._save()

    def transition_and_update(self, run: ModelingRun, target: str, *,
                              allowed_from: set[str] | None = None,
                              changes: dict[str, Any] | None = None) -> None:
        """Atomically validate, transition and update run metadata.

        This is the write path used by queue admission and worker claim so a
        second API/worker process cannot win the same source-state transition
        after the first process has read it.
        """
        changes = dict(changes or {})
        with self.lock, run.state_lock:
            previous = run.status
            previous_updated_at = run.updated_at
            previous_values = {key: getattr(run, key) for key in changes if hasattr(run, key)}
            self._transition_locked(run, target, allowed_from=allowed_from)
            for key, value in changes.items():
                setattr(run, key, value)
            run.updated_at = time.time()
            snapshot = run.as_dict(include_database=True, include_events=False)
            if not self.repository.compare_and_swap(
                    snapshot, expected_status=previous,
                    expected_updated_at=previous_updated_at):
                run.status = previous
                run.updated_at = previous_updated_at
                for key, value in previous_values.items():
                    setattr(run, key, value)
                raise StateTransitionError(run.run_id, previous, str(target))
            self._save()

    def _transition_locked(self, run: ModelingRun, target: str,
                           *, allowed_from: set[str] | None = None) -> None:
        target = str(target or "").upper()
        previous = str(run.status or "CREATED").upper()
        if target not in RUN_STATES:
            raise StateTransitionError(run.run_id, previous, target)
        if allowed_from is not None and previous not in {str(item).upper() for item in allowed_from}:
            raise StateTransitionError(run.run_id, previous, target)
        if target == previous:
            return
        if target not in RUN_TRANSITIONS.get(previous, set()):
            raise StateTransitionError(run.run_id, previous, target)
        run.status = target

    def transition(self, run: ModelingRun, target: str, *, error: str | None = None,
                   allowed_from: set[str] | None = None) -> None:
        with self.lock, run.state_lock:
            # The source-state check and mutation intentionally share this
            # critical section.  Callers must not check run.status first and
            # then call transition after releasing the lock.
            previous = run.status
            previous_updated_at = run.updated_at
            previous_error = run.error
            self._transition_locked(run, target, allowed_from=allowed_from)
            if error is not None:
                run.error = str(error)
            run.updated_at = time.time()
            snapshot = run.as_dict(include_database=True, include_events=False)
            if not self.repository.compare_and_swap(
                    snapshot, expected_status=previous,
                    expected_updated_at=previous_updated_at):
                run.status = previous
                run.error = previous_error
                run.updated_at = previous_updated_at
                raise StateTransitionError(run.run_id, previous, str(target))
            self._save()

    def restore_after_question(self, run: ModelingRun, target: str) -> None:
        """Return a question-only turn to its pre-question stable state.

        This is deliberately not part of the public transition graph: input
        upload and external APIs must never be able to use ANALYZING as a
        general-purpose way back to INPUT_READY.
        """
        target = str(target or "INPUT_READY").upper()
        if target not in {"INPUT_READY", "FAILED", "BLOCKED"}:
            target = "INPUT_READY"
        with self.lock, run.state_lock:
            if run.status != "ANALYZING":
                raise StateTransitionError(run.run_id, run.status, target)
            run.status = target
            if target == "INPUT_READY":
                run.error = ""
            run.updated_at = time.time()
            self._save()

    def append_event(self, run: ModelingRun, event_type: str, **payload: Any) -> dict[str, Any]:
        with run.state_lock:
            event = {"seq": len(run.events), "type": event_type, "timestamp": time.time(),
                     "userId": run.user_id, "runId": run.run_id,
                     "attemptId": run.attempt_id or None, **payload}
            run.events.append(event)
            self._append_event_journal(run, event)
            now = event["timestamp"]
        # Journal append is already serialized per run.  Only the occasional
        # metadata checkpoint needs the global store lock.
        with self._checkpoint_lock:
            count = self._events_since_checkpoint.get(run.run_id, 0) + 1
            last = self._last_event_checkpoint.get(run.run_id, 0.0)
            checkpoint = count >= EVENT_CHECKPOINT_COUNT or now - last >= EVENT_CHECKPOINT_SECONDS
            if checkpoint:
                self._events_since_checkpoint[run.run_id] = count
            else:
                self._events_since_checkpoint[run.run_id] = count
        if checkpoint:
            # Event journals are append-only and intentionally do not write a
            # stale in-memory run snapshot over a newer state committed by a
            # different API/worker process.  State mutations call _save with
            # repository persistence enabled.
            self._save(persist_repository=False)
            with self._checkpoint_lock:
                current = self._events_since_checkpoint.get(run.run_id, 0)
                self._events_since_checkpoint[run.run_id] = max(0, current - count)
                self._last_event_checkpoint[run.run_id] = now
        return event

    def _boundary(self, run: ModelingRun):
        # Import lazily so unit tests for path and persistence do not require
        # the complete LLM runtime.  Production execution uses the same guard.
        from open_claude.sandbox import TaskSandboxBoundary
        return TaskSandboxBoundary(run.root)

    @classmethod
    def _normalize_input_files(cls, files: Any) -> list[tuple[str, bytes]]:
        if not isinstance(files, list):
            raise ClientInputError("files must be an array", status=422)
        normalized: list[tuple[str, bytes]] = []
        for index, item in enumerate(files):
            if not isinstance(item, dict):
                raise ClientInputError(
                    "each files item must be an object",
                    details={"index": index}, status=422)
            name = item.get("name") or item.get("path")
            if not isinstance(name, str) or not name.strip():
                raise ClientInputError(
                    "each files item requires a non-empty string name",
                    details={"index": index}, status=422)
            rel = cls._input_relpath(name)
            raw_base64 = item.get("contentBase64")
            if raw_base64 is not None:
                if not isinstance(raw_base64, str):
                    raise ClientInputError(
                        "contentBase64 must be a string",
                        details={"index": index}, status=422)
                try:
                    data = base64.b64decode(raw_base64, validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise ClientInputError(
                        "contentBase64 is not valid base64",
                        details={"index": index}, status=422) from exc
            else:
                content = item.get("content", "")
                if not isinstance(content, str):
                    raise ClientInputError(
                        "content must be a string when contentBase64 is absent",
                        details={"index": index}, status=422)
                data = content.encode("utf-8")
            normalized.append((rel, data))
        return normalized

    @classmethod
    def validate_input_files(cls, files: Any) -> None:
        """Validate a complete files payload without filesystem side effects."""
        cls._normalize_input_files(files)

    def put_files(self, run: ModelingRun, files: list[dict[str, Any]]) -> list[str]:
        # Validate and decode every item before changing run state or writing
        # the first file.  A malformed later item therefore cannot create a
        # partially processed input request.
        normalized = self._normalize_input_files(files)
        written: list[str] = []
        boundary = self._boundary(run)
        with self.lock, run.state_lock:
            self._transition_locked(run, "INPUT_READY")
            for rel, data in normalized:
                parent = boundary.resolve_parent(str(Path(run.root) / rel))
                # resolve_parent returns the validated target path and checks
                # the nearest existing parent, including symlink targets.
                target = Path(parent)
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
                tmp.write_bytes(data)
                os.replace(tmp, target)
                written.append(rel)
            run.updated_at = time.time()
            self._save()
        return written

    @staticmethod
    def _input_relpath(value: Any) -> str:
        raw = str(value or "").replace("\\", "/").strip()
        if raw.startswith("/") or raw.startswith("../") or "/../" in raw or raw == "..":
            raise ClientInputError("input path traversal is not allowed", status=422)
        parts = [part for part in raw.split("/") if part not in ("", ".")]
        if not parts or any(part == ".." for part in parts):
            raise ClientInputError("input path traversal is not allowed", status=422)
        if parts[0] == "mission-input":
            parts[0] = "input"
        elif parts[0] != "input":
            # A bare filename is convenient, but it is always placed under
            # input; work/output aliases are never accepted here.
            if len(parts) == 1:
                parts.insert(0, "input")
            else:
                raise ClientInputError("inputs may only write the input namespace", status=422)
        if parts[0] != "input":
            raise ClientInputError("inputs may only write the input namespace", status=422)
        if parts[-1] in INTERNAL_FILENAMES:
            raise ClientInputError("internal modeling state cannot be uploaded as input",
                                   status=422)
        return "/".join(parts)

    def _public_path(self, run: ModelingRun, value: str) -> Path:
        rel = _safe_relpath(value)
        boundary = self._boundary(run)
        resolved = Path(boundary.resolve(str(Path(run.root) / rel)))
        run_root = Path(run.root).resolve()
        if run_root not in resolved.parents and resolved != run_root:
            raise ValueError("path outside current modeling run")
        if resolved.parts[len(run_root.parts)] not in PUBLIC_DIRS:
            raise ValueError("path must be inside input, work or output")
        return resolved

    def list_files(self, run: ModelingRun) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        root = Path(run.root).resolve()
        for directory in PUBLIC_DIRS:
            base = root / directory
            if not base.is_dir():
                continue
            for current, dirs, files in os.walk(base):
                dirs[:] = sorted(directory for directory in dirs
                                  if directory not in _FILE_TREE_SKIP_DIRS
                                  and not directory.startswith("."))
                for filename in sorted(files):
                    path = Path(current) / filename
                    rel = path.relative_to(root).as_posix()
                    if not _is_web_visible_file(rel) or not path.is_file():
                        continue
                    stat = path.stat()
                    rows.append({"path": rel,
                                 "displayPath": _file_tree_display_path(rel),
                                 "size": stat.st_size,
                                 "modifiedAt": stat.st_mtime,
                                 "mtime": stat.st_mtime})
        return rows

    def read_file(self, run: ModelingRun, value: str) -> bytes:
        return self._public_path(run, value).read_bytes()


class ModelingRunManager:
    """Fair, bounded scheduler for standalone modeling runs.

    Run state remains in RunStore; this manager owns only transient executor
    futures and scheduling metadata.  A queued run never gets a worker
    thread, and a claimed run is protected by the store's atomic transition.
    """
    def __init__(self, store: RunStore, max_active_runs: int | None = None,
                 max_active_per_user: int | None = None,
                 max_queued_per_user: int | None = None,
                 max_queued_runs: int | None = None,
                 lease_seconds: float | None = None,
                 heartbeat_seconds: float | None = None):
        self.store = store
        self.store.register_manager(self)
        self.threads: dict[str, _RunHandle] = {}
        self.execution_modes: dict[str, tuple[bool, str]] = {}
        # The user-provided continuation text ("" when not provided) for the
        # next attempt.  Kept separate from run.prompt so a resume never
        # overwrites the user's own words with the fixed checkpoint prompt.
        self.execution_prompts: dict[str, str] = {}
        # Reused Task/Conversation per run inside this process so a continue
        # keeps the in-memory session instead of rebuilding the runtime and
        # reloading the whole journal.
        self.tasks: dict[str, Any] = {}
        self.scheduler_lock = threading.RLock()
        self.scheduler_wakeup = threading.Condition(self.scheduler_lock)
        self.stop_event = threading.Event()
        self.worker_id = f"standalone-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.max_online_users = int(os.environ.get("MODELING_SERVER_MAX_ONLINE_USERS",
                                                   str(DEFAULT_MAX_ONLINE_USERS)))
        if self.max_online_users < 1:
            raise ValueError("MODELING_SERVER_MAX_ONLINE_USERS must be positive")
        self.online_users: dict[str, float] = {}

        def configured(value: int | None, env_name: str, default: int, limit: int) -> int:
            raw = value if value is not None else os.environ.get(env_name, str(default))
            try:
                result = int(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{env_name} must be an integer") from exc
            if not 1 <= result <= limit:
                raise ValueError(f"{env_name} must be between 1 and {limit}")
            return result

        self.max_active_runs = configured(max_active_runs, "MODELING_SERVER_MAX_ACTIVE_RUNS",
                                          DEFAULT_MAX_ACTIVE_RUNS, MAX_ACTIVE_RUNS_LIMIT)
        self.max_active_per_user = configured(max_active_per_user,
                                              "MODELING_SERVER_MAX_ACTIVE_PER_USER",
                                              DEFAULT_MAX_ACTIVE_PER_USER, MAX_ACTIVE_RUNS_LIMIT)
        self.max_active_per_user = min(self.max_active_per_user, self.max_active_runs)
        self.max_queued_per_user = configured(max_queued_per_user,
                                              "MODELING_SERVER_MAX_QUEUED_PER_USER",
                                              DEFAULT_MAX_QUEUED_PER_USER, MAX_QUEUED_RUNS_LIMIT)
        self.max_queued_runs = configured(max_queued_runs, "MODELING_SERVER_MAX_QUEUED",
                                          DEFAULT_MAX_QUEUED_RUNS, MAX_QUEUED_RUNS_LIMIT)
        self.lease_seconds = float(lease_seconds if lease_seconds is not None else
                                   os.environ.get("MODELING_SERVER_LEASE_SECONDS", DEFAULT_LEASE_SECONDS))
        self.heartbeat_seconds = float(heartbeat_seconds if heartbeat_seconds is not None else
                                       os.environ.get("MODELING_SERVER_HEARTBEAT_SECONDS",
                                                      DEFAULT_HEARTBEAT_SECONDS))
        if self.lease_seconds <= 0 or self.heartbeat_seconds <= 0:
            raise ValueError("lease and heartbeat intervals must be positive")
        provider_limit = int(os.environ.get("MODELING_PROVIDER_CONCURRENCY", str(self.max_active_runs)))
        database_limit = int(os.environ.get("MODELING_DATABASE_CONCURRENCY", str(self.max_active_runs)))
        if provider_limit < 1 or database_limit < 1:
            raise ValueError("provider/database concurrency must be positive")
        self.provider_concurrency = provider_limit
        self.database_concurrency = database_limit
        # P1/P2: the shared ExecutionCoordinator owns the fair queue, global
        # and per-user quotas, provider/database semaphores, durable leases,
        # fencing and heartbeat.  Env parsing stays in the service entry
        # point; the coordinator only receives a config object.  The old
        # per-service scheduler loop is replaced by the coordinator dispatcher.
        backend = str(os.environ.get("MODELING_SERVER_COORDINATOR_BACKEND",
                                     "file")).strip().lower()
        lease_dir = str(os.environ.get(
            "MODELING_SERVER_LEASE_DIR",
            str(Path(store.root) / ".modeling_leases"))).strip()
        if backend in {"", "none", "off", "disabled"}:
            self.coordinator: _ExecutionCoordinator | None = None
            self.provider_slots: Any = threading.BoundedSemaphore(provider_limit)
            self.database_slots: Any = threading.BoundedSemaphore(database_limit)
        else:
            lease_store = None
            redis_url = ""
            if backend == "redis":
                redis_url = (str(os.environ.get("MODELING_REDIS_URL", "") or "").strip()
                             or str(os.environ.get("REDIS_URL", "") or "").strip())
                if not redis_url:
                    raise ValueError("MODELING_SERVER_COORDINATOR_BACKEND=redis "
                                     "需要 MODELING_REDIS_URL 或 REDIS_URL")
            elif backend != "file":
                raise ValueError(f"未知的 MODELING_SERVER_COORDINATOR_BACKEND: {backend}")
            else:
                lease_store = _build_standalone_lease_store(
                    lease_dir, self.lease_seconds)
            config = _CoordinatorConfig(
                service_namespace="ontology:47314",
                max_active=self.max_active_runs,
                max_active_per_user=self.max_active_per_user,
                max_queued_per_user=self.max_queued_per_user,
                max_queued=self.max_queued_runs,
                provider_concurrency=provider_limit,
                database_concurrency=database_limit,
                lease_seconds=self.lease_seconds,
                heartbeat_seconds=self.heartbeat_seconds,
                backend=backend,
                lease_dir=lease_dir,
                redis_url=redis_url or None,
                redis_prefix="ontology:47314:",
            )
            self.coordinator = _ExecutionCoordinator(
                config, _StandaloneExecutionAdapter(self),
                lease_store=lease_store)
            self.provider_slots = self.coordinator.provider_slots
            self.database_slots = self.coordinator.database_slots
        # Compatibility scheduler thread: admission, heartbeat and expiry
        # recovery are owned by the coordinator dispatcher.  This thread only
        # watches shutdown/workspace removal so legacy ``stop_event`` /
        # ``scheduler_thread`` callers keep working.
        self.scheduler_thread = threading.Thread(target=self._scheduler_compat_loop,
                                                 name="modeling-scheduler", daemon=True)
        self.scheduler_thread.start()
        # Disable legacy web-task persistence at the adapter boundary.  The
        # standalone manager has no authority to write 47313's task index.
        try:
            import oc_codex_server as web
            web.configure_task_persistence(False)
        except ImportError:
            pass

    def close(self) -> None:
        self.stop_event.set()
        with self.scheduler_wakeup:
            self.scheduler_wakeup.notify_all()
        if self.coordinator is not None:
            self.coordinator.shutdown(timeout=2.0)
        if self.scheduler_thread is not threading.current_thread():
            self.scheduler_thread.join(timeout=2)

    def metrics(self) -> dict[str, Any]:
        counts = self.store.counts()
        user_counts = {}
        with self.store.lock:
            for run in self.store.runs.values():
                user_counts.setdefault(run.user_id, {"active": 0, "queued": 0})
                if run.status in {"CLAIMED", "ANALYZING", "VALIDATING", "CANCELLING"}:
                    user_counts[run.user_id]["active"] += 1
                elif run.status == "QUEUED":
                    user_counts[run.user_id]["queued"] += 1
            queued = [run.created_at for run in self.store.runs.values()
                      if run.status == "QUEUED"]
        coordinator_metrics = {}
        if self.coordinator is not None:
            coordinator_metrics = self.coordinator.metrics()
        return {
            "onlineUsers": len(self.online_users),
            "maxOnlineUsers": self.max_online_users,
            "users": user_counts,
            "concurrency": {
                "activeRuns": counts["active"],
                "queuedRuns": counts["queued"],
                "maxActiveRuns": self.max_active_runs,
                "maxActivePerUser": self.max_active_per_user,
                "maxQueuedPerUser": self.max_queued_per_user,
                "maxQueuedRuns": self.max_queued_runs,
                "oldestQueuedSeconds": (
                    max(0.0, time.time() - min(queued)) if queued else 0.0),
                "providerConcurrency": self.provider_concurrency,
                "providerInUse": coordinator_metrics.get("concurrency", {})
                                  .get("providerInUse", 0),
                "databaseConcurrency": self.database_concurrency,
                "databaseInUse": coordinator_metrics.get("concurrency", {})
                                 .get("databaseInUse", 0),
            },
            "coordination": coordinator_metrics.get("coordination", {}),
        }

    def touch_user(self, user_id: str) -> None:
        now = time.time()
        with self.scheduler_lock:
            self.online_users = {
                key: seen for key, seen in self.online_users.items()
                if now - seen < 30 * 60
            }
            if user_id not in self.online_users and len(self.online_users) >= self.max_online_users:
                raise QueueLimitError(
                    "ONLINE_USER_LIMIT_REACHED", "在线用户数已达到上限",
                    details={"maxOnlineUsers": self.max_online_users})
            self.online_users[user_id] = now

    def _context(self, run: ModelingRun) -> dict[str, Any]:
        context = {
            "taskType": "modeling",
            "sourceMode": run.source_mode,
            "prompt": run.prompt,
            "expectedFiles": run.requested_artifacts,
            "parseElements": [ARTIFACT_PARSE_ELEMENTS[name] for name in run.requested_artifacts],
            "standaloneModelingRun": True,
        }
        if run.database is not None:
            # The reused 47313 Task locates this exact context shape, writes
            # the encrypted .db_connection.json into the run input namespace,
            # and creates the shared db_connection.py/verify_database.py
            # helpers.  It also performs the fail-closed decryption check.
            context["database"] = json.loads(json.dumps(run.database, ensure_ascii=False))
        return context

    @staticmethod
    def _resolve_conversational_intent(prompt: Any, intent: Any = "auto") -> bool:
        requested = str(intent or "auto").strip().lower()
        if requested not in {"auto", "chat", "execute"}:
            raise ClientInputError(
                "intent 仅支持 auto、chat 或 execute",
                details={"intent": requested}, status=422)
        if requested == "execute":
            return False
        if requested == "chat":
            return True
        from oc_codex_server import is_conversational_turn
        return is_conversational_turn(prompt)

    def execute(self, run: ModelingRun, prompt: str | None = None,
                model: str | None = None, intent: str = "auto") -> None:
        requested_model = str(model or "").strip() if model is not None else None
        if requested_model:
            allowed_models = {item["id"] for item in _model_catalog()["models"]}
            if requested_model not in allowed_models:
                raise ClientInputError("未知模型", details={"model": requested_model}, status=422)
        requested_prompt = str(prompt) if prompt is not None else run.prompt
        conversational = self._resolve_conversational_intent(requested_prompt, intent)
        if str(intent or "auto").strip().lower() != "execute" and _is_table_count_request(requested_prompt):
            with self.store.lock, run.state_lock:
                self.store._transition_locked(
                    run, "INPUT_READY",
                    allowed_from={"CREATED", "INPUT_READY", "FAILED", "BLOCKED", "CANCELLED"})
                if prompt is not None:
                    run.prompt = requested_prompt
                if model is not None:
                    run.model = requested_model
                run.error = ""
                run.updated_at = time.time()
                self.store._save()
            self.store.append_event(run, "assistant", text=_table_count_answer(run))
            self.store.append_event(run, "done", status="INPUT_READY")
            return
        with self.scheduler_wakeup, self.store.lock, run.state_lock:
            self.store.refresh_from_repository()
            if run.status in {"QUEUED", "CLAIMED", "ANALYZING", "VALIDATING", "CANCELLING"}:
                raise StateTransitionError(run.run_id, run.status, "QUEUED")
            return_status = run.status if run.status in {"FAILED", "BLOCKED"} else "INPUT_READY"
            # A conversational question on a FAILED/BLOCKED run keeps its
            # failure/block reason so the restored state still explains why
            # the modeling stopped; only a real continuation clears it.
            # A question asked from CANCELLED restores to INPUT_READY, so the
            # stale "cancelled by user" error must not leak into the new turn.
            changes = ({} if (conversational and return_status in {"FAILED", "BLOCKED"})
                       else {"error": ""})
            if model is not None:
                changes["model"] = requested_model
            # P1/P2: the shared coordinator owns queue limits and admission.
            # ``claim`` never blocks the HTTP thread: it either admits
            # immediately, enqueues, or returns an explicit limit error.
            claim = None
            run_queued = False
            queue_position = 0
            queue_length = 0
            if self.coordinator is not None and not self.stop_event.is_set():
                attempt = int(getattr(run, "attempt_number", 0) or 0) + 1
                claim = self.coordinator.claim(
                    run.run_id, uuid.uuid4().hex, run.user_id, attempt=attempt)
                if claim.decision == "active_exists":
                    raise StateTransitionError(run.run_id, run.status, "QUEUED")
                if claim.decision == "user_queue_limit":
                    raise QueueLimitError(
                        "USER_QUEUE_LIMIT_REACHED", "该用户排队任务已达到上限",
                        details={"maxQueuedPerUser": self.max_queued_per_user})
                if claim.decision == "global_queue_full":
                    raise QueueLimitError(
                        "GLOBAL_QUEUE_FULL", "全局排队任务已达到上限",
                        details={"maxQueuedRuns": self.max_queued_runs})
                run_queued = claim.decision == "queued"
                queue_position = int(getattr(claim, "queue_position", 0) or 0)
                queue_length = int(getattr(claim, "queue_length", 0) or 0)
            else:
                # Legacy/stopped fallback: enforce limits from the store and
                # queue without coordinator admission (tests stop the
                # scheduler to freeze runs in QUEUED).
                queued_global = self.store.counts()["queued"]
                queued_user = self.store.counts(user_id=run.user_id)["queued"]
                if queued_user >= self.max_queued_per_user:
                    raise QueueLimitError(
                        "USER_QUEUE_LIMIT_REACHED",
                        "该用户排队任务已达到上限",
                        details={"maxQueuedPerUser": self.max_queued_per_user})
                if queued_global >= self.max_queued_runs:
                    raise QueueLimitError(
                        "GLOBAL_QUEUE_FULL", "全局排队任务已达到上限",
                        details={"maxQueuedRuns": self.max_queued_runs})
                run_queued = True
            self.store.transition_and_update(
                run, "QUEUED",
                allowed_from={"CREATED", "INPUT_READY", "FAILED", "BLOCKED", "CANCELLED"},
                changes=changes)
            self.execution_modes[run.run_id] = (conversational, return_status)
            self.execution_prompts[run.run_id] = str(prompt or "").strip()
            self.threads[run.run_id] = _RunHandle()
        if prompt is not None and str(prompt).strip():
            self.store.append_event(run, "user", text=str(prompt).strip())
        if run_queued:
            queued_payload: dict[str, Any] = {
                "maxActiveRuns": self.max_active_runs,
            }
            if queue_position:
                queued_payload["position"] = queue_position
                queued_payload["queueLength"] = queue_length
            self.store.append_event(run, "run_queued", **queued_payload)
        with self.scheduler_wakeup:
            self.scheduler_wakeup.notify_all()

    def _scheduler_compat_loop(self) -> None:
        # The shared coordinator owns queue admission, heartbeat and lease
        # expiry recovery.  This compatibility loop only watches for shutdown
        # and workspace removal so legacy stop_event/scheduler_thread callers
        # keep working.
        while not self.stop_event.is_set():
            if not self.store.root.exists():
                self.stop_event.set()
                return
            self.stop_event.wait(0.25)

    def _recover_expired_leases(self) -> None:
        """Fail runs whose durable coordinator lease is gone or expired.

        The coordinator's backend reclaims expired leases atomically; this
        store-side pass turns a lost lease into a retryable FAILED state so a
        run never stays permanently ``working``.
        """
        coordinator = getattr(self, "coordinator", None)
        now = time.time()
        with self.store.lock:
            candidates: list[tuple[ModelingRun, str]] = []
            for run in self.store.runs.values():
                if run.status not in {"CLAIMED", "ANALYZING", "VALIDATING"}:
                    continue
                if run.lease_expires_at and run.lease_expires_at < now:
                    # Legacy store-level lease (e.g. a run marked CLAIMED by
                    # an older worker or a direct transition).
                    candidates.append((run, "WORKER_LEASE_EXPIRED"))
                    continue
                if coordinator is not None:
                    record = coordinator.read_lease(run.run_id)
                    if record is None or record.expired(now):
                        candidates.append((run, "WORKER_LEASE_EXPIRED"))
        for run, reason in candidates:
            try:
                self.store.transition(run, "FAILED", error=reason,
                                      allowed_from={"CLAIMED", "ANALYZING", "VALIDATING"})
                self.store.append_event(run, "worker_lost", reason=reason,
                                        attemptId=run.attempt_id)
            except StateTransitionError:
                continue

    def cancel(self, run: ModelingRun) -> None:
        """Cancel a queued or running run and drop its coordinator waiter."""
        self.store.request_cancel(run)
        if self.coordinator is not None:
            self.coordinator.cancel(run.run_id)

    def _run_worker(self, run: ModelingRun, token: Any = None,
                    execution_guard: Any = None) -> None:
        try:
            if token is not None:
                token.throw_if_cancelled()
            if run.status == "CANCELLING":
                self.store.transition(run, "CANCELLED", error="cancelled by user",
                                      allowed_from={"CANCELLING"})
                return
            if run.status != "CLAIMED":
                # The run was cancelled/removed while queued; the coordinator
                # already released its admission slot in on_finished.
                return
            self.store.transition(run, "ANALYZING", allowed_from={"CLAIMED"})
            self.store.append_event(run, "run_started", maxActiveRuns=self.max_active_runs,
                                    workerId=self.worker_id, attemptId=run.attempt_id)
            if self.coordinator is None:
                # Degraded mode: no shared coordinator, so keep a coarse slot
                # window so local concurrency limits still apply.
                with self.provider_slots:
                    if run.database is not None or run.database_source_id:
                        with self.database_slots:
                            self._execute(run)
                    else:
                        self._execute(run)
            else:
                # The coordinator's provider/database slots are acquired inside
                # Task.stream_turn only around the real model request and tool
                # execution window; never hold them across the whole turn.
                self._execute(run, token=token, execution_guard=execution_guard)
            if run.status == "CANCELLING":
                self.store.transition(run, "CANCELLED", error="cancelled by user",
                                      allowed_from={"CANCELLING"})
        except Exception as exc:  # noqa: BLE001 - queued worker failures are persisted.
            if run.status in {"CLAIMED", "ANALYZING", "VALIDATING", "CANCELLING"}:
                self.store.transition(run, "FAILED", error=f"{type(exc).__name__}: {exc}")
            else:
                self.store.update(run, error=f"{type(exc).__name__}: {exc}")
            self.store.append_event(run, "run_failed", error=run.error)
        finally:
            with self.scheduler_wakeup:
                self.scheduler_wakeup.notify_all()

    @staticmethod
    def _checkpoint_for_run(run: ModelingRun) -> tuple[str, str]:
        """Return the latest durable validation stage without re-running it."""
        path = Path(run.root) / "work" / "modeling_state.json"
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return run.checkpoint_stage, run.checkpoint_signature
        stages = state.get("validationStages") if isinstance(state, dict) else None
        if not isinstance(stages, dict):
            return run.checkpoint_stage, run.checkpoint_signature
        ordered = [str(key) for key in stages]
        passed = [(key, stages[key]) for key in ordered
                  if isinstance(stages[key], dict) and stages[key].get("status") == "PASSED"]
        if not passed:
            return run.checkpoint_stage, run.checkpoint_signature
        key, row = passed[-1]
        return key, str(row.get("signature") or "")

    def _persist_task_checkpoint(self, run: ModelingRun, task: Any) -> None:
        """Persist provider session and stage checkpoint after every attempt."""
        stage, signature = self._checkpoint_for_run(run)
        session_id = str(getattr(task, "session_id", lambda: "")() or "")
        changes = {"checkpoint_stage": stage, "checkpoint_signature": signature}
        if session_id:
            changes["resume_session_id"] = session_id
        self.store.update(run, **changes)

    def _execute(self, run: ModelingRun, token: Any = None,
                execution_guard: Any = None) -> None:
        conversational, return_status = self.execution_modes.get(
            run.run_id, (False, "INPUT_READY"))
        try:
            if token is not None:
                token.throw_if_cancelled()
            if run.cancel_requested:
                return
            # The import is intentionally inside the worker: API-only tests do
            # not need model/provider dependencies, and 47313 has no shared
            # process state with this service.
            from oc_codex_server import Task
            task = self.tasks.get(run.run_id)
            if task is None:
                task = Task(project=run.run_id, cwd=run.root, repository_id="",
                            task_code="", task_type="modeling", mission_context=self._context(run),
                            resume_session_id=run.resume_session_id or None,
                            task_id=run.run_id, user_id="standalone-modeling")
                self.tasks[run.run_id] = task
            if run.model:
                task.conv.model = run.model
            # There is no browser approval channel on this API.  Commands are
            # still confined by TaskSandboxBoundary; this only permits the
            # sandboxed run to progress without an interactive workbench.
            task.conv.permissions.mode = "always_allow"
            if "[独立通用建模运行]" not in task.conv.system_prompt:
                task.conv.system_prompt += (
                    "\n\n[独立通用建模运行]\n"
                    "本次运行没有平台 taskCode、回调或业务任务绑定。只处理当前 ModelingRun。"
                    "对外工作区使用 input/、work/、output/；所有审计和中间态写入 work/，"
                    "正式交付文件写入 output/。"
                    "含样例数据模板（含样例数据-sheets/*.csv）仅用于理解字段、编码和页面显示等填写示例，"
                    "不是当前任务真实输入，不得把样例行复制到结果或据此新增建模对象;"
                    "数据库连接必须执行 input/verify_database.py 或导入 input/db_connection.py 的 create_db_engine；"
                    "禁止直接读取 input/.db_connection.json 的加密 password，也禁止手工拼接连接 URL；"
                    "数据库查询必须使用连接 helper 配置的 sourceSchema/search_path，不得默认查询 public；"
                    "数据库模式必须先执行 input/extract_schema.py 提取表结构到 work/schema_extract.json，"
                    "并基于该文件建模;缺少表结构证据时禁止导出正式 CSV;"
                    "schema_extract.json 的 tableNames 位于文件首部，先读取它获取全部表名清单，"
                    "再按需用 grep 按表名或列名定向查询单表定义，禁止反复整文件读取;"
                    "模板与规范 CSV 只需读取一次理解结构，不得重复读取同一文件。"
                )

            def emit(event: dict[str, Any]) -> None:
                self.store.append_event(run, event.get("type", "agent_event"), **event)

            self._persist_task_checkpoint(run, task)
            resuming = bool(run.resume_session_id or run.attempt_number > 1)
            requested_prompt = (self.execution_prompts.pop(run.run_id, "") or "").strip()
            if conversational:
                # A normal question/cancellation turn is sent verbatim; the
                # checkpoint constraint only applies to modeling continuations.
                resume_prompt = requested_prompt or run.prompt
            elif requested_prompt:
                # The user's own continuation text is preserved verbatim;
                # only a short checkpoint constraint is appended so the model
                # does not restart the whole run.
                resume_prompt = requested_prompt if not resuming \
                    else requested_prompt + RESUME_CHECKPOINT_SUFFIX
            elif resuming:
                resume_prompt = RESUME_CHECKPOINT_PROMPT
            else:
                resume_prompt = run.prompt
            task.stream_turn(
                resume_prompt, emit, conversational=conversational,
                cancellation_token=token, execution_guard=execution_guard,
                provider_slots=self.provider_slots,
                database_slots=self.database_slots)
            if token is not None:
                token.throw_if_cancelled()
            self._persist_task_checkpoint(run, task)
            if run.status in {"SUCCEEDED", "CANCELLED"}:
                self.tasks.pop(run.run_id, None)
            if run.cancel_requested:
                if run.status in {"ANALYZING", "VALIDATING"}:
                    self.store.transition(run, "CANCELLING",
                                          allowed_from={"ANALYZING", "VALIDATING"})
                return
            if task.status == "blocked":
                self.store.transition(
                    run, "BLOCKED", error=task.modeling_block_reason or "modeling execution blocked",
                    allowed_from={"ANALYZING", "VALIDATING"})
                self.store.append_event(run, "run_blocked", error=run.error)
            elif task.status == "error":
                self.store.transition(run, "FAILED", error="modeling execution failed")
                self.store.append_event(run, "run_failed", error=run.error)
            elif conversational:
                # A question is a completed conversation turn, not a modeling
                # run.  Return to the stable pre-question state and do not run
                # the formal artifact/semantic finalize gate.
                self.store.restore_after_question(run, return_status)
                self.store.append_event(run, "query_finished", status=run.status)
            else:
                report = self.validate(run, internal=True)
                self.store.append_event(run, "run_ready" if run.status == "SUCCEEDED"
                                        else "run_failed",
                                        semanticValidationStatus=report.get("semantic_validation_status", ""),
                                        error=run.error)
        except Exception as exc:  # noqa: BLE001 - API must persist the run failure.
            if run.status in {"ANALYZING", "VALIDATING"}:
                self.store.transition(run, "FAILED", error=f"{type(exc).__name__}: {exc}")
            else:
                self.store.update(run, error=f"{type(exc).__name__}: {exc}")
            self.store.append_event(run, "run_failed", error=run.error)
        finally:
            self.execution_modes.pop(run.run_id, None)

    def validate(self, run: ModelingRun, *, internal: bool = False) -> dict[str, Any]:
        from open_claude.modeling_reliability import finalize_semantic_model, load_validation_report
        # Internal execution validation is allowed only after its own
        # analysis reaches ANALYZING completion.  The public endpoint has a
        # separate allow-list and can never use ANALYZING -> VALIDATING.
        allowed_from = ({"ANALYZING"} if internal
                        else {"CREATED", "INPUT_READY", "FAILED", "BLOCKED"})
        self.store.transition(run, "VALIDATING", error="", allowed_from=allowed_from)
        try:
            result = finalize_semantic_model(Path(run.root) / "work",
                                             output_dir=Path(run.root) / "output",
                                             required_outputs=run.requested_artifacts,
                                             validate_artifact_schema=True,
                                             context={"expectedFiles": run.requested_artifacts,
                                                      "taskType": "modeling"})
            report = load_validation_report(Path(run.root) / "work") or {}
            status = str(report.get("semantic_validation_status") or report.get("status") or "")
            if result.get("status") == "FAILED" or status == "FAILED":
                self.store.transition(run, "FAILED", error="semantic validation failed")
            else:
                self.store.transition(run, "SUCCEEDED", error="")
            self.store.append_event(run, "validation_finished", report=report)
            return report
        except Exception as exc:  # noqa: BLE001 - preserve structured failure state.
            if run.status == "VALIDATING":
                self.store.transition(run, "FAILED", error=f"{type(exc).__name__}: {exc}")
            else:
                self.store.update(run, error=f"{type(exc).__name__}: {exc}")
            self.store.append_event(run, "validation_failed", error=run.error)
            raise


def _authorized(handler: BaseHTTPRequestHandler) -> bool:
    configured = os.environ.get("ONTOLOGY_STANDALONE_API_KEY", "").strip()
    if not configured:
        # Development fallback is local-only.  Production deployment sets a
        # generated key and therefore never exposes an unauthenticated API.
        host = str(handler.client_address[0] if handler.client_address else "")
        return host in {"127.0.0.1", "::1", "localhost"}
    supplied = handler.headers.get("X-Modeling-API-Key", "")
    if configured and hmac.compare_digest(supplied, configured):
        return True
    cookie_header = handler.headers.get("Cookie", "")
    browser_token = next((part.strip().split("=", 1)[1]
                          for part in cookie_header.split(";")
                          if part.strip().startswith("standalone_session=") and "=" in part), "")
    now = time.time()
    with _BROWSER_SESSION_LOCK:
        expired = [token for token, expires_at in _BROWSER_SESSIONS.items()
                   if expires_at <= now]
        for token in expired:
            _BROWSER_SESSIONS.pop(token, None)
            _BROWSER_SESSION_USERS.pop(token, None)
        return bool(browser_token and _BROWSER_SESSIONS.get(browser_token, 0) > now)


def _issue_browser_session(user_id: str = "browser") -> str:
    token = secrets.token_urlsafe(32)
    with _BROWSER_SESSION_LOCK:
        _BROWSER_SESSIONS[token] = time.time() + _BROWSER_SESSION_TTL
        _BROWSER_SESSION_USERS[token] = user_id
    return token


class ModelingHandler(BaseHTTPRequestHandler):
    server_version = "StandaloneModeling/1.0"
    manager: ModelingRunManager

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[standalone-modeling] " + (fmt % args) + "\n")

    def _send(self, status: int, body: Any) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_frontend(self, request_path: str) -> bool:
        """Serve the shared React build in standalone mode.

        The build is the same React/Ant Design workbench used by 47313, but
        the injected flag selects its standalone run UI. API routes remain
        authenticated and are never handled by this static fallback.
        """
        dist = FRONTEND_DIST.resolve()
        if not dist.is_dir():
            return False
        relative = unquote(request_path or "/").lstrip("/")
        candidate = (dist / relative).resolve() if relative else dist / "index.html"
        if dist not in candidate.parents and candidate != dist:
            self._send(400, {"error": "invalid static path"})
            return True
        if candidate.is_dir() or not candidate.is_file():
            candidate = dist / "index.html"
        if not candidate.is_file():
            return False
        try:
            data = candidate.read_bytes()
        except OSError as exc:
            self._send(500, {"error": str(exc)})
            return True
        if candidate.name == "index.html":
            marker = b"<script>window.__STANDALONE_MODELING__=true;</script>"
            data = data.replace(b"</head>", marker + b"</head>", 1)
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8"
                         if content_type.startswith("text/") or content_type == "application/javascript"
                         else content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store" if candidate.name == "index.html" else "public, max-age=31536000, immutable")
        if candidate.name == "index.html":
            self.send_header("Set-Cookie", f"standalone_session={_issue_browser_session()}; Path=/; Max-Age={_BROWSER_SESSION_TTL}; HttpOnly; SameSite=Lax")
        self.end_headers()
        self.wfile.write(data)
        return True

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_BODY_BYTES:
            raise ValueError("request body too large")
        raw = self.rfile.read(length) if length else b"{}"
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON object required")
        return value

    def _run(self, run_id: str) -> ModelingRun:
        if not RUN_ID_RE.fullmatch(run_id):
            raise KeyError(run_id)
        return self.manager.store.get(run_id)

    def _user_id(self) -> str:
        supplied = (self.headers.get("X-Modeling-User") or
                    self.headers.get("X-User-ID") or "").strip()
        if supplied:
            if len(supplied) > 128 or any(ch in supplied for ch in "\r\n"):
                raise ClientInputError("invalid user identity", status=422)
            self.manager.touch_user(supplied)
            return supplied
        cookie_header = self.headers.get("Cookie", "")
        browser_token = next((part.strip().split("=", 1)[1]
                              for part in cookie_header.split(";")
                              if part.strip().startswith("standalone_session=") and "=" in part), "")
        with _BROWSER_SESSION_LOCK:
            user_id = _BROWSER_SESSION_USERS.get(browser_token, "anonymous")
        self.manager.touch_user(user_id)
        return user_id

    def _owned_run(self, run: ModelingRun) -> ModelingRun:
        if run.user_id != self._user_id():
            raise KeyError(run.run_id)
        return run

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            metrics = self.manager.metrics() if getattr(self, "manager", None) else {}
            self._send(200, {
                "status": "ok", "service": "standalone-modeling",
                "port": self.server.server_port,
                "readiness": BOOT.snapshot(),
                "capabilities": {
                    "model_catalog": MODEL_CATALOG.status,
                    "database_metadata": "on_demand",
                    "agent_runtime": "on_demand",
                },
                "concurrency": metrics.get("concurrency", {}),
                "coordination": metrics.get("coordination", {}),
                "onlineUsers": metrics.get("onlineUsers", 0),
                "maxOnlineUsers": metrics.get("maxOnlineUsers", 0),
            })
            return
        if not parsed.path.startswith("/api/") and self._serve_frontend(parsed.path):
            return
        if not _authorized(self):
            self._send(401, {"error": "unauthorized"})
            return
        if parsed.path == "/api/modeling-runs":
            user_id = self._user_id()
            self.manager.store.refresh_from_repository()
            with self.manager.store.lock:
                runs = sorted((item for item in self.manager.store.runs.values()
                               if item.user_id == user_id),
                              key=lambda item: item.updated_at, reverse=True)
                self._send(200, {"runs": [run.as_dict(include_events=False) for run in runs]})
            return
        if parsed.path == "/api/modeling-models":
            self._send(200, _model_catalog())
            return
        if parsed.path == "/api/modeling-data-sources":
            try:
                self._send(200, {"sources": _database_source_options()})
            except (ClientInputError, OSError, RuntimeError, ValueError) as exc:
                self._send(500, {"error": str(exc)})
            return
        schemas_match = re.fullmatch(r"/api/modeling-data-sources/([^/]+)/schemas", parsed.path)
        if schemas_match:
            source_id = unquote(schemas_match.group(1))
            try:
                self._send(200, {"sourceId": source_id,
                                 **_list_database_source_schemas(source_id)})
            except ClientInputError as exc:
                self._send(exc.status, {"error": str(exc), **exc.details})
            except (OSError, RuntimeError, ValueError, ImportError) as exc:
                self._send(502, {"error": f"无法读取数据库 Schema: {exc}"})
            return
        tables_match = re.fullmatch(r"/api/modeling-data-sources/([^/]+)/tables", parsed.path)
        if tables_match:
            source_id = unquote(tables_match.group(1))
            try:
                requested_schemas = []
                query = parse_qs(parsed.query)
                for value in query.get("schema", []) + query.get("schemas", []):
                    requested_schemas.extend(item.strip() for item in value.split(",") if item.strip())
                result = _list_database_source_tables(source_id, requested_schemas or None)
                self._send(200, {"sourceId": source_id, **result})
            except ClientInputError as exc:
                self._send(exc.status, {"error": str(exc), **exc.details})
            except (OSError, RuntimeError, ValueError, ImportError) as exc:
                self._send(502, {"error": f"无法读取数据库表清单: {exc}"})
            return
        content_match = re.fullmatch(r"/api/modeling-runs/([^/]+)/files/content", parsed.path)
        if content_match:
            try:
                run = self._owned_run(self._run(unquote(content_match.group(1))))
                rel = (parse_qs(parsed.query).get("path") or [""])[0]
                data = self.manager.store.read_file(run, rel)
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except KeyError:
                self._send(404, {"error": "modeling run not found"})
            except (ValueError, OSError) as exc:
                self._send(400, {"error": str(exc)})
            return
        match = re.fullmatch(r"/api/modeling-runs/([^/]+)(?:/(files|events))?", parsed.path)
        if not match:
            self._send(404, {"error": "not found"})
            return
        try:
            run = self._owned_run(self._run(unquote(match.group(1))))
            suffix = match.group(2)
            if suffix == "files":
                self._send(200, {"runId": run.run_id, "files": self.manager.store.list_files(run)})
            elif suffix == "events":
                query = parse_qs(parsed.query)
                with run.state_lock:
                    total = len(run.events)
                    start, end = _parse_event_window(query, total)
                    events = list(run.events[start:end])
                # Cursor contract: `since` and `before` are absolute positions
                # into the append-only journal. `nextCursor`/`eventEnd` is the
                # next unread seq, so the client never relies on
                # `cursor + delta.length` alone.  The window computation is
                # shared with 47313 via open_claude.event_window.
                self._send(200, _event_window_response(
                    events, start, end, total, scope_id=run.run_id,
                    scope_key="runId"))
            else:
                query = parse_qs(parsed.query)
                include_events = (query.get("includeEvents", ["true"])[0].lower()
                                  not in {"0", "false", "no"})
                with run.state_lock:
                    payload = run.as_dict(include_events=include_events)
                    payload["files"] = self.manager.store.list_files(run)
                self._send(200, payload)
        except KeyError:
            self._send(404, {"error": "modeling run not found"})
        except (ValueError, OSError) as exc:
            self._send(400, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        if not _authorized(self):
            self._send(401, {"error": "unauthorized"})
            return
        parsed = urlparse(self.path)
        try:
            payload = self._body()
            if parsed.path == "/api/modeling-runs":
                files = payload.get("files", _MISSING)
                # Validate the complete client request before RunStore.create
                # can create a directory or write the run index.
                if files is not _MISSING:
                    self.manager.store.validate_input_files(files)
                if "database" in payload and "dataSource" in payload:
                    raise ClientInputError(
                        "provide only one of database or dataSource", status=422)
                database_source_id = payload.get("databaseSourceId")
                database = payload.get("database", payload.get("dataSource"))
                if database_source_id is not None and database is not None:
                    raise ClientInputError(
                        "provide only one of databaseSourceId or database", status=422)
                run = self.manager.store.create(payload.get("sourceMode", "NATURAL_LANGUAGE"),
                                                 payload.get("prompt", ""),
                                                 payload.get("requestedArtifacts"),
                                                 title=payload.get("title", ""),
                                                 database=database,
                                                 database_source_id=database_source_id,
                                                 selected_tables=payload.get("selectedTables"),
                                                 selected_schemas=payload.get("selectedSchemas"),
                                                 user_id=self._user_id(),
                                                 idempotency_key=self.headers.get("Idempotency-Key"))
                if files is not _MISSING and files:
                    try:
                        self.manager.store.put_files(run, files)
                    except Exception:
                        # At this point the request was valid, so this is an
                        # initialization I/O failure.  Avoid leaving an
                        # unreturned, half-initialized run behind.
                        self.manager.store.remove(run)
                        raise
                self._send(201, run.as_dict())
                return
            match = re.fullmatch(r"/api/modeling-runs/([^/]+)/(inputs|execute|validate|cancel)", parsed.path)
            if not match:
                self._send(404, {"error": "not found"})
                return
            run = self._owned_run(self._run(unquote(match.group(1))))
            action = match.group(2)
            if action == "inputs":
                files = payload.get("files", _MISSING)
                if files is _MISSING:
                    raise ClientInputError("files is required", status=422)
                self._send(200, {"runId": run.run_id, "written": self.manager.store.put_files(run, files)})
            elif action == "execute":
                intent = str(payload.get("intent") or "auto").strip().lower()
                self.manager.execute(run, payload.get("prompt"), payload.get("model"), intent)
                # 202 responses are status summaries only. The full event
                # journal is read exclusively through /events?since= so the
                # client cannot double-apply the same snapshot as a delta.
                self._send(202, run.as_dict(include_events=False))
            elif action == "cancel":
                self.manager.cancel(run)
                self._send(202, run.as_dict(include_events=False))
            else:
                report = self.manager.validate(run)
                self._send(200, {"runId": run.run_id, "status": run.status, "report": report})
        except ClientInputError as exc:
            self._send(exc.status, {"error": str(exc), **exc.details})
        except ActiveRunError as exc:
            self._send(409, {"error": str(exc), "code": "ACTIVE_RUN_EXISTS",
                             "activeRunId": exc.run_id})
        except QueueLimitError as exc:
            self._send(429, {"error": str(exc), "code": exc.code, **exc.details})
        except StateTransitionError as exc:
            self._send(409, {"error": str(exc), "code": "INVALID_STATE_TRANSITION",
                             "runId": exc.run_id, "previousStatus": exc.previous,
                             "requestedStatus": exc.requested})
        except KeyError:
            self._send(404, {"error": "modeling run not found"})
        except (ValueError, OSError, RuntimeError, binascii.Error) as exc:
            self._send(400, {"error": str(exc)})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Standalone task-independent ontology modeling API")
    parser.add_argument("--host", default=os.environ.get("MODELING_SERVER_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MODELING_SERVER_PORT", "47314")))
    parser.add_argument("--root", default=os.environ.get("MODELING_SERVER_ROOT", str(DEFAULT_ROOT)))
    parser.add_argument(
        "--max-active-runs", type=int,
        default=int(os.environ.get("MODELING_SERVER_MAX_ACTIVE_RUNS", str(DEFAULT_MAX_ACTIVE_RUNS))),
        help=f"maximum number of simultaneous modeling workers (1-{MAX_ACTIVE_RUNS_LIMIT})",
    )
    parser.add_argument("--max-active-per-user", type=int,
                        default=int(os.environ.get("MODELING_SERVER_MAX_ACTIVE_PER_USER",
                                                   str(DEFAULT_MAX_ACTIVE_PER_USER))))
    parser.add_argument("--max-queued-per-user", type=int,
                        default=int(os.environ.get("MODELING_SERVER_MAX_QUEUED_PER_USER",
                                                   str(DEFAULT_MAX_QUEUED_PER_USER))))
    parser.add_argument("--max-queued-runs", type=int,
                        default=int(os.environ.get("MODELING_SERVER_MAX_QUEUED",
                                                   str(DEFAULT_MAX_QUEUED_RUNS))))
    args = parser.parse_args(argv)
    BOOT.mark("process_bootstrap")
    root = str(Path(args.root).resolve())
    # The reused execution engine reads this boundary from process env.  This
    # process owns its own root and never changes the existing 47313 process.
    os.environ["OC_SANDBOX_ROOT"] = root
    # Make sibling imports work when started from any cwd.
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    store = RunStore(root)
    manager = ModelingRunManager(store, max_active_runs=args.max_active_runs,
                                 max_active_per_user=args.max_active_per_user,
                                 max_queued_per_user=args.max_queued_per_user,
                                 max_queued_runs=args.max_queued_runs)
    BOOT.mark("common_ready", detail="run store restored")
    ModelingHandler.manager = manager
    server = ThreadingHTTPServer((args.host, args.port), ModelingHandler)
    BOOT.mark("core_ready")
    BOOT.mark("routes_ready")
    print(
        f"standalone modeling server listening on {args.host}:{args.port} "
        f"root={root} max_active_runs={manager.max_active_runs} "
        f"max_active_per_user={manager.max_active_per_user} "
        f"max_queued_per_user={manager.max_queued_per_user} "
        f"max_queued_runs={manager.max_queued_runs}",
        flush=True,
    )
    try:
        from open_claude.openai_compat import provider_timeout_summary
        print(f"[standalone-modeling] {provider_timeout_summary()}", flush=True)
    except Exception:
        # The timeout summary is informational; a missing optional import
        # must not prevent startup.
        pass
    print(f"[BOOT] core ready: {BOOT.snapshot()['stages']['core_ready']['elapsedMs']:.2f}ms", flush=True)
    print("[BOOT] database metadata, Agent runtime and document parsing: on-demand", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        manager.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
