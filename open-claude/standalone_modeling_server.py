"""Standalone, task-independent modeling-run API.

This service is deliberately a sidecar to ``oc_codex_server.py``.  It reuses
the existing modeling engine, decision/audit writer and sandbox boundary, but
has its own run store and workspace root.  The existing 47313 workbench is not
imported by this process until after the standalone root is selected and does
not share its task registry or HTTP routes.

Public workspace names are generic::

    <run>/input, <run>/work, <run>/output

The legacy modeling engine sees safe aliases named ``mission-input``,
``mission-work`` and ``mission-output``.  All aliases resolve inside the same
run root, so runtime, validator and file APIs operate on one workspace.
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
from collections import Counter
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


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
DEFAULT_MAX_ACTIVE_RUNS = 2
MAX_ACTIVE_RUNS_LIMIT = 32
_BROWSER_SESSION_TTL = 30 * 60
_BROWSER_SESSION_LOCK = threading.RLock()
_BROWSER_SESSIONS: dict[str, float] = {}
PUBLIC_DIRS = ("input", "work", "output")
_FILE_TREE_SKIP_DIRS = {".git", ".open-claude", "node_modules", "__pycache__", ".venv", "venv", "pylibs", ".py_deps"}
_WEB_HIDDEN_FILES = {".db_connection.json", ".env", ".env.local", "credentials.json",
                    "db_connection.py", "verify_database.py"}
_DECISION_AUDIT_FILENAMES = {
    "business_object_decisions.csv", "relation_decisions.csv", "rule_decisions.csv",
    "indicator_decisions.csv", "logical_entity_decisions.csv",
}
LEGACY_ALIASES = {
    "mission-input": "input",
    "mission-work": "work",
    "mission-output": "output",
}
INTERNAL_FILENAMES = {
    "modeling_state.json", "validation_report.json", "business_object_decisions.csv",
    "relation_decisions.csv", "rule_decisions.csv", "indicator_decisions.csv",
    "logical_entity_decisions.csv",
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
    "请直接读取当前任务 mission-input 中自动提供的四份 v0.0.1 规范/模板文件，"
    "结合已选择的数据表或上传文件完成本体建模，并生成所选正式输出和审计文件；"
    "无需等待用户补充建模要求。"
)
_MISSING = object()


def _model_catalog() -> dict[str, Any]:
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


def _list_database_source_tables(source_id: Any) -> dict[str, Any]:
    """Read table names through the same SQLAlchemy credential path as 47313."""
    _, config = _database_source_config(source_id)
    from sqlalchemy import URL, create_engine, text
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
    engine = create_engine(URL.create(
        dialect,
        username=config["username"], password=password,
        host=config["host"], port=int(config.get("port", 5432)),
        database=config["database"],
    ))
    schema = str(config.get("sourceSchema") or "public")
    try:
        with engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT table_schema, table_name, table_type "
                "FROM information_schema.tables "
                "WHERE table_schema = :schema "
                "AND table_type IN ('BASE TABLE', 'VIEW') "
                "ORDER BY table_name"
            ), {"schema": schema}).mappings().all()
    finally:
        engine.dispose()
    return {
        "schema": schema,
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
        result = _list_database_source_tables(run.database_source_id)
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
    "CREATED", "INPUT_READY", "QUEUED", "ANALYZING", "VALIDATING", "READY_FOR_EXPORT", "FAILED",
}
RUN_TRANSITIONS = {
    "CREATED": {"INPUT_READY", "QUEUED", "ANALYZING", "VALIDATING", "FAILED"},
    "INPUT_READY": {"INPUT_READY", "QUEUED", "ANALYZING", "VALIDATING", "FAILED"},
    "QUEUED": {"ANALYZING", "FAILED"},
    # VALIDATING is an internal completion step; the public validate endpoint
    # still rejects ANALYZING through ModelingRunManager.validate().
    "ANALYZING": {"VALIDATING", "READY_FOR_EXPORT", "FAILED"},
    "VALIDATING": {"READY_FOR_EXPORT", "FAILED"},
    "READY_FOR_EXPORT": set(),
    "FAILED": {"INPUT_READY", "QUEUED", "ANALYZING", "VALIDATING"},
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
    required = ("host", "username", "password", "database")
    missing = [name for name in required if not isinstance(config.get(name), str)
               or not config[name].strip()]
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
    status: str = "CREATED"
    source_mode: str = "NATURAL_LANGUAGE"
    prompt: str = ""
    requested_artifacts: list[str] = field(default_factory=lambda: list(DEFAULT_ARTIFACTS))
    database_source_id: str = ""
    database: dict[str, Any] | None = None
    model: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    error: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    state_lock: threading.RLock = field(default_factory=threading.RLock,
                                         repr=False, compare=False)

    def as_dict(self, *, include_database: bool = False,
                include_events: bool = True) -> dict[str, Any]:
        result = {
            "runId": self.run_id,
            "workspaceId": self.run_id,
            "root": self.root,
            "status": self.status,
            "sourceMode": self.source_mode,
            "prompt": self.prompt,
            "requestedArtifacts": self.requested_artifacts,
            "databaseSourceId": self.database_source_id or None,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "error": self.error,
            "eventsCount": len(self.events),
            "databaseConfigured": bool(self.database),
            "model": self.model,
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
        self.lock = threading.RLock()
        # Event journals are per-run files.  Keep checkpoint bookkeeping out
        # of the store lock so concurrent runs do not serialize every streamed
        # thinking event behind the global run index lock.
        self._checkpoint_lock = threading.RLock()
        self.runs: dict[str, ModelingRun] = {}
        self._events_since_checkpoint: dict[str, int] = {}
        self._last_event_checkpoint: dict[str, float] = {}
        self._load()

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
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        event = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(event, dict):
                        journal.append(event)
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
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False,
                                    separators=(",", ":")))
            handle.write("\n")
            handle.flush()

    def _load(self) -> None:
        if not self.index_path.exists():
            return
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
            for item in raw if isinstance(raw, list) else []:
                run = ModelingRun(
                    run_id=str(item["runId"]), root=str(item["root"]),
                    status=str(item.get("status", "CREATED")),
                    source_mode=str(item.get("sourceMode", "NATURAL_LANGUAGE")),
                    prompt=str(item.get("prompt", "")),
                    requested_artifacts=list(item.get("requestedArtifacts") or DEFAULT_ARTIFACTS),
                    database_source_id=str(item.get("databaseSourceId") or ""),
                    database=(dict(item["database"]) if isinstance(item.get("database"), dict)
                              else None),
                    model=str(item.get("model") or ""),
                    created_at=float(item.get("createdAt", time.time())),
                    updated_at=float(item.get("updatedAt", time.time())),
                    error=str(item.get("error", "")),
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
        self._recover_interrupted_runs()

    def _recover_interrupted_runs(self) -> None:
        changed = False
        for run in self.runs.values():
            if run.status not in {"QUEUED", "ANALYZING", "VALIDATING"}:
                continue
            previous = run.status
            reason = {
                "QUEUED": "SERVER_RESTARTED_WHILE_QUEUED",
                "ANALYZING": "SERVER_RESTARTED_DURING_ANALYSIS",
                "VALIDATING": "SERVER_RESTARTED_DURING_VALIDATION",
            }[previous]
            run.status = "FAILED"
            run.error = reason
            run.updated_at = time.time()
            event = {"seq": len(run.events), "type": "run_interrupted",
                     "timestamp": run.updated_at,
                     "previousStatus": previous, "reason": reason}
            run.events.append(event)
            self._append_event_journal(run, event)
            changed = True
        if changed:
            self._save()

    def _save(self) -> None:
        with self.lock:
            snapshots = []
            for run in self.runs.values():
                with run.state_lock:
                    snapshots.append(run.as_dict(include_database=True, include_events=False))
            _atomic_write(self.index_path, _json_dump(snapshots))

    def _run_root(self, run_id: str) -> Path:
        path = (self.root / run_id).resolve()
        if path.parent != self.root:
            raise ValueError("invalid run id")
        return path

    @staticmethod
    def _ensure_alias(root: Path, alias: str, target: str) -> None:
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
               database: Any = None, database_source_id: Any = None,
               selected_tables: Any = None) -> ModelingRun:
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
        with self.lock:
            run_id = f"run_{uuid.uuid4().hex}"
            root = self._run_root(run_id)
            root.mkdir(parents=True, exist_ok=False)
            for name in PUBLIC_DIRS:
                (root / name).mkdir()
            for alias, target in LEGACY_ALIASES.items():
                self._ensure_alias(root, alias, target)
            normalized_prompt = str(prompt or "").strip() or DEFAULT_MODELING_PROMPT
            run = ModelingRun(run_id=run_id, root=str(root),
                              source_mode=str(source_mode or "NATURAL_LANGUAGE"),
                              prompt=normalized_prompt, requested_artifacts=requested,
                              database_source_id=source_id,
                              database=normalized_database)
            self.runs[run_id] = run
            self._save()
            return run

    def get(self, run_id: str) -> ModelingRun:
        with self.lock:
            if run_id not in self.runs:
                raise KeyError(run_id)
            return self.runs[run_id]

    def remove(self, run: ModelingRun) -> None:
        """Rollback a run that failed during initial persistence."""
        with self.lock, run.state_lock:
            self.runs.pop(run.run_id, None)
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
            self._transition_locked(run, target, allowed_from=allowed_from)
            if error is not None:
                run.error = str(error)
            run.updated_at = time.time()
            self._save()

    def restore_after_question(self, run: ModelingRun, target: str) -> None:
        """Return a question-only turn to its pre-question stable state.

        This is deliberately not part of the public transition graph: input
        upload and external APIs must never be able to use ANALYZING as a
        general-purpose way back to INPUT_READY.
        """
        target = str(target or "INPUT_READY").upper()
        if target not in {"INPUT_READY", "FAILED"}:
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
            event = {"seq": len(run.events), "type": event_type, "timestamp": time.time(), **payload}
            run.events.append(event)
            run.updated_at = event["timestamp"]
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
            self._save()
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
    def __init__(self, store: RunStore, max_active_runs: int | None = None):
        self.store = store
        self.threads: dict[str, threading.Thread] = {}
        self.execution_modes: dict[str, tuple[bool, str]] = {}
        configured_limit = max_active_runs
        if configured_limit is None:
            configured_limit = os.environ.get("MODELING_SERVER_MAX_ACTIVE_RUNS", str(DEFAULT_MAX_ACTIVE_RUNS))
        try:
            configured_limit = int(configured_limit)
        except (TypeError, ValueError) as exc:
            raise ValueError("MODELING_SERVER_MAX_ACTIVE_RUNS must be an integer") from exc
        if not 1 <= configured_limit <= MAX_ACTIVE_RUNS_LIMIT:
            raise ValueError(
                f"MODELING_SERVER_MAX_ACTIVE_RUNS must be between 1 and {MAX_ACTIVE_RUNS_LIMIT}")
        self.max_active_runs = configured_limit
        self.active_slots = threading.BoundedSemaphore(configured_limit)
        # Disable the legacy web-task persistence at the adapter boundary, not
        # only immediately before one worker starts.  This protects every
        # standalone code path, including future helpers added to the reused
        # Task implementation.
        try:
            from oc_codex_server import configure_task_persistence
            configure_task_persistence(False)
        except ImportError:
            # API-only tests can use RunStore without the LLM execution stack.
            pass

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
        if self.threads.get(run.run_id) and self.threads[run.run_id].is_alive():
            raise RuntimeError("modeling run is already executing")
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
                    run, "INPUT_READY", allowed_from={"CREATED", "INPUT_READY", "FAILED"})
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
        with self.store.lock, run.state_lock:
            return_status = "FAILED" if run.status == "FAILED" else "INPUT_READY"
            self.store._transition_locked(
                run, "QUEUED", allowed_from={"CREATED", "INPUT_READY", "FAILED"})
            if prompt is not None:
                run.prompt = str(prompt)
            if model is not None:
                run.model = requested_model
            run.error = ""
            run.updated_at = time.time()
            self.store._save()
            self.execution_modes[run.run_id] = (conversational, return_status)
        self.store.append_event(run, "run_queued", maxActiveRuns=self.max_active_runs)
        thread = threading.Thread(target=self._run_worker, args=(run,),
                                  name=f"modeling-{run.run_id}", daemon=True)
        self.threads[run.run_id] = thread
        thread.start()

    def _run_worker(self, run: ModelingRun) -> None:
        acquired = self.active_slots.acquire()
        if not acquired:
            self.store.transition(run, "FAILED", error="unable to acquire modeling worker slot",
                                  allowed_from={"QUEUED"})
            self.store.append_event(run, "run_failed", error=run.error)
            return
        try:
            self.store.transition(run, "ANALYZING", allowed_from={"QUEUED"})
            self.store.append_event(run, "run_started", maxActiveRuns=self.max_active_runs)
            self._execute(run)
        except Exception as exc:  # noqa: BLE001 - queued worker failures are persisted.
            if run.status in {"ANALYZING", "VALIDATING"}:
                self.store.transition(run, "FAILED", error=f"{type(exc).__name__}: {exc}")
            else:
                self.store.update(run, error=f"{type(exc).__name__}: {exc}")
            self.store.append_event(run, "run_failed", error=run.error)
        finally:
            self.active_slots.release()

    def _execute(self, run: ModelingRun) -> None:
        conversational, return_status = self.execution_modes.get(
            run.run_id, (False, "INPUT_READY"))
        try:
            # The import is intentionally inside the worker: API-only tests do
            # not need model/provider dependencies, and 47313 has no shared
            # process state with this service.
            from oc_codex_server import Task
            task = Task(project=run.run_id, cwd=run.root, repository_id="",
                        task_code="", task_type="modeling", mission_context=self._context(run),
                        task_id=run.run_id, user_id="standalone-modeling")
            if run.model:
                task.conv.model = run.model
            # There is no browser approval channel on this API.  Commands are
            # still confined by TaskSandboxBoundary; this only permits the
            # sandboxed run to progress without an interactive workbench.
            task.conv.permissions.mode = "always_allow"
            task.conv.system_prompt += (
                "\n\n[独立通用建模运行]\n"
                "本次运行没有平台 taskCode、回调或业务任务绑定。只处理当前 ModelingRun。"
                "对外工作区使用 input/、work/、output/；内部 mission-* 目录只是安全别名。"
                "所有审计和中间态写入 work/，正式交付文件写入 output/。"
                "数据库连接必须执行 input/verify_database.py 或导入 input/db_connection.py 的 create_db_engine；"
                "禁止直接读取 input/.db_connection.json 的加密 password，也禁止手工拼接连接 URL；"
                "数据库查询必须使用连接 helper 配置的 sourceSchema/search_path，不得默认查询 public。"
            )

            def emit(event: dict[str, Any]) -> None:
                self.store.append_event(run, event.get("type", "agent_event"), **event)

            task.stream_turn(run.prompt, emit, conversational=conversational)
            if task.status == "error":
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
                self.store.append_event(run, "run_ready" if run.status == "READY_FOR_EXPORT"
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
                        else {"CREATED", "INPUT_READY", "FAILED"})
        self.store.transition(run, "VALIDATING", error="", allowed_from=allowed_from)
        try:
            result = finalize_semantic_model(Path(run.root) / "work",
                                             output_dir=Path(run.root) / "output",
                                             required_outputs=run.requested_artifacts,
                                             validate_artifact_schema=True)
            report = load_validation_report(Path(run.root) / "work") or {}
            status = str(report.get("semantic_validation_status") or report.get("status") or "")
            if result.get("status") == "FAILED" or status == "FAILED":
                self.store.transition(run, "FAILED", error="semantic validation failed")
            else:
                self.store.transition(run, "READY_FOR_EXPORT", error="")
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
        return bool(browser_token and _BROWSER_SESSIONS.get(browser_token, 0) > now)


def _issue_browser_session() -> str:
    token = secrets.token_urlsafe(32)
    with _BROWSER_SESSION_LOCK:
        _BROWSER_SESSIONS[token] = time.time() + _BROWSER_SESSION_TTL
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

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send(200, {"status": "ok", "service": "standalone-modeling", "port": self.server.server_port})
            return
        if not parsed.path.startswith("/api/") and self._serve_frontend(parsed.path):
            return
        if not _authorized(self):
            self._send(401, {"error": "unauthorized"})
            return
        if parsed.path == "/api/modeling-runs":
            with self.manager.store.lock:
                runs = sorted(self.manager.store.runs.values(),
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
        tables_match = re.fullmatch(r"/api/modeling-data-sources/([^/]+)/tables", parsed.path)
        if tables_match:
            try:
                result = _list_database_source_tables(unquote(tables_match.group(1)))
                self._send(200, {"sourceId": unquote(tables_match.group(1)), **result})
            except ClientInputError as exc:
                self._send(exc.status, {"error": str(exc), **exc.details})
            except (OSError, RuntimeError, ValueError, ImportError) as exc:
                self._send(502, {"error": f"无法读取数据库表清单: {exc}"})
            return
        content_match = re.fullmatch(r"/api/modeling-runs/([^/]+)/files/content", parsed.path)
        if content_match:
            try:
                run = self._run(unquote(content_match.group(1)))
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
            run = self._run(unquote(match.group(1)))
            suffix = match.group(2)
            if suffix == "files":
                self._send(200, {"runId": run.run_id, "files": self.manager.store.list_files(run)})
            elif suffix == "events":
                query = parse_qs(parsed.query)
                since = int((query.get("since") or ["0"])[0])
                with run.state_lock:
                    events = list(run.events[since:])
                self._send(200, {"runId": run.run_id, "events": events})
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
                                                 database=database,
                                                 database_source_id=database_source_id,
                                                 selected_tables=payload.get("selectedTables"))
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
            match = re.fullmatch(r"/api/modeling-runs/([^/]+)/(inputs|execute|validate)", parsed.path)
            if not match:
                self._send(404, {"error": "not found"})
                return
            run = self._run(unquote(match.group(1)))
            action = match.group(2)
            if action == "inputs":
                files = payload.get("files", _MISSING)
                if files is _MISSING:
                    raise ClientInputError("files is required", status=422)
                self._send(200, {"runId": run.run_id, "written": self.manager.store.put_files(run, files)})
            elif action == "execute":
                intent = str(payload.get("intent") or "auto").strip().lower()
                self.manager.execute(run, payload.get("prompt"), payload.get("model"), intent)
                self._send(202, run.as_dict())
            else:
                report = self.manager.validate(run)
                self._send(200, {"runId": run.run_id, "status": run.status, "report": report})
        except ClientInputError as exc:
            self._send(exc.status, {"error": str(exc), **exc.details})
        except ActiveRunError as exc:
            self._send(409, {"error": str(exc), "code": "ACTIVE_RUN_EXISTS",
                             "activeRunId": exc.run_id})
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
    args = parser.parse_args(argv)
    root = str(Path(args.root).resolve())
    # The reused execution engine reads this boundary from process env.  This
    # process owns its own root and never changes the existing 47313 process.
    os.environ["OC_SANDBOX_ROOT"] = root
    # Make sibling imports work when started from any cwd.
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    store = RunStore(root)
    manager = ModelingRunManager(store, max_active_runs=args.max_active_runs)
    ModelingHandler.manager = manager
    server = ThreadingHTTPServer((args.host, args.port), ModelingHandler)
    print(
        f"standalone modeling server listening on {args.host}:{args.port} "
        f"root={root} max_active_runs={manager.max_active_runs}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
