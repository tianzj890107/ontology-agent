"""
In-memory task management system for Open Claude.

Provides TaskCreate, TaskUpdate, TaskList, TaskGet tools for tracking
multi-step work within a conversation session.
"""

import threading
import logging
import os
import hashlib
import json
import tempfile
from dataclasses import dataclass
from typing import Any, Optional


logger = logging.getLogger(__name__)

TASK_STATES = frozenset({"pending", "in_progress", "completed", "failed", "cancelled"})
TASK_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
TASK_ALLOWED_TRANSITIONS = {
    "pending": frozenset({"pending", "in_progress", "cancelled"}),
    "in_progress": frozenset({"in_progress", "completed", "failed", "cancelled"}),
    "completed": frozenset({"completed"}),
    "failed": frozenset({"failed", "in_progress", "cancelled"}),
    "cancelled": frozenset({"cancelled"}),
}


@dataclass(frozen=True)
class TaskMutationResult:
    ok: bool
    code: str
    message: str
    task: "Task | None" = None


class Task:
    """A single task."""
    __slots__ = ("id", "subject", "description", "status", "active_form", "owner", "metadata")

    def __init__(self, task_id: int, subject: str, description: str = "",
                 active_form: str = "", owner: str = ""):
        self.id = task_id
        self.subject = subject
        self.description = description
        self.status = "pending"  # pending | in_progress | completed
        self.active_form = active_form
        self.owner = owner
        self.metadata: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "subject": self.subject,
            "status": self.status,
        }
        if self.description:
            d["description"] = self.description
        if self.active_form:
            d["activeForm"] = self.active_form
        if self.owner:
            d["owner"] = self.owner
        if self.metadata:
            d["metadata"] = self.metadata
        return d

    def summary(self) -> str:
        status_icon = {"pending": "o", "in_progress": "*", "completed": "+"}.get(self.status, "?")
        return f"#{self.id} [{status_icon} {self.status}] {self.subject}"


class TaskStore:
    """Thread-safe in-memory task store."""

    def __init__(self, scope: str = ""):
        self._tasks: dict[int, Task] = {}
        self._next_id = 1
        self._lock = threading.Lock()
        self._scope = os.path.realpath(scope) if scope else "default"
        digest = hashlib.sha256(self._scope.encode("utf-8")).hexdigest()[:24]
        self._state_path = os.path.join(tempfile.gettempdir(), "open-claude-task-state",
                                        digest + ".json")
        self._load()

    def _load(self) -> None:
        try:
            with open(self._state_path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, TypeError, ValueError):
            return
        if not isinstance(payload, dict) or payload.get("scope") != self._scope:
            return
        tasks = payload.get("tasks")
        if not isinstance(tasks, list):
            return
        for item in tasks:
            if not isinstance(item, dict):
                continue
            try:
                task_id = int(item["id"])
            except (KeyError, TypeError, ValueError):
                continue
            task = Task(task_id, str(item.get("subject") or ""),
                        str(item.get("description") or ""),
                        str(item.get("activeForm") or ""),
                        str(item.get("owner") or ""))
            status = str(item.get("status") or "pending")
            task.status = status if status in TASK_STATES else "pending"
            task.metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            self._tasks[task_id] = task
        self._next_id = max(self._tasks, default=0) + 1

    def _persist(self) -> None:
        payload = {"scope": self._scope, "tasks": [task.to_dict() for task in self._tasks.values()]}
        directory = os.path.dirname(self._state_path)
        try:
            os.makedirs(directory, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".task-state.", suffix=".tmp", dir=directory)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._state_path)
            try:
                os.chmod(self._state_path, 0o600)
            except OSError:
                pass
        except OSError:
            try:
                os.unlink(temporary)
            except (UnboundLocalError, OSError):
                pass

    def create(self, subject: str, description: str = "",
               active_form: str = "", owner: str = "", metadata: dict[str, Any] | None = None) -> Task:
        with self._lock:
            metadata = metadata if isinstance(metadata, dict) else {}
            idempotency_key = str(metadata.get("idempotencyKey") or "").strip()
            if idempotency_key:
                for existing in self._tasks.values():
                    if existing.metadata.get("idempotencyKey") == idempotency_key \
                            and existing.status not in TASK_TERMINAL_STATES:
                        return existing
            task = Task(self._next_id, subject, description, active_form, owner)
            task.metadata.update(metadata)
            self._tasks[self._next_id] = task
            self._next_id += 1
            self._persist()
            return task

    def get(self, task_id: int) -> Optional[Task]:
        with self._lock:
            return self._tasks.get(task_id)

    def list_all(self, status: Optional[str] = None) -> list[Task]:
        with self._lock:
            tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return tasks

    def update_checked(self, task_id: int, **kwargs) -> TaskMutationResult:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                logger.warning("TASK_NOT_FOUND task_id=%s scope=%s", task_id, self.scope)
                return TaskMutationResult(False, "TASK_NOT_FOUND", f"Error: TASK_NOT_FOUND task_id={task_id}")
            if "status" in kwargs:
                val = str(kwargs["status"] or "").strip().lower()
                if val == "deleted":
                    logger.warning("TASK_DELETE_NOT_ALLOWED task_id=%s scope=%s", task_id, self.scope)
                    return TaskMutationResult(False, "TASK_DELETE_NOT_ALLOWED",
                                              f"Error: TASK_DELETE_NOT_ALLOWED task_id={task_id}")
                if val not in TASK_STATES:
                    return TaskMutationResult(False, "INVALID_TASK_STATE",
                                              f"Error: INVALID_TASK_STATE status={val}")
                if val not in TASK_ALLOWED_TRANSITIONS.get(task.status, frozenset()):
                    logger.warning("INVALID_TASK_STATE_TRANSITION task_id=%s previous=%s requested=%s",
                                   task_id, task.status, val)
                    return TaskMutationResult(
                        False, "INVALID_TASK_STATE_TRANSITION",
                        f"Error: INVALID_TASK_STATE_TRANSITION {task.status}->{val}", task)
                task.status = val
            if "subject" in kwargs:
                task.subject = kwargs["subject"]
            if "description" in kwargs:
                task.description = kwargs["description"]
            if "active_form" in kwargs:
                task.active_form = kwargs["active_form"]
            if "owner" in kwargs:
                task.owner = kwargs["owner"]
            if "metadata" in kwargs and isinstance(kwargs["metadata"], dict):
                for k, v in kwargs["metadata"].items():
                    if v is None:
                        task.metadata.pop(k, None)
                    else:
                        task.metadata[k] = v
            self._persist()
            return TaskMutationResult(True, "OK", f"Task #{task_id} updated: {task.summary()}", task)

    def update(self, task_id: int, **kwargs) -> Optional[Task]:
        """Compatibility wrapper; callers needing the error code use update_checked."""
        result = self.update_checked(task_id, **kwargs)
        return result.task if result.ok else None

    @property
    def scope(self) -> str:
        return getattr(self, "_scope", "")


# One authoritative in-process store per workspace.  Task IDs are local to
# that store; a mission ID, step number, or TaskList position is never an ID.
_stores: dict[str, TaskStore] = {}
_stores_lock = threading.Lock()


def get_task_store(scope: str = "") -> TaskStore:
    key = os.path.realpath(scope) if scope else "default"
    with _stores_lock:
        store = _stores.get(key)
        if store is None:
            store = TaskStore(key)
            _stores[key] = store
        return store


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

TASK_CREATE_SCHEMA = {
    "name": "TaskCreate",
    "description": (
        "Create a new local planning task. The returned task id is authoritative for later updates; "
        "do not guess an id or use a mission id as a task id."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "Short task title in imperative form (e.g. 'Run tests').",
            },
            "description": {
                "type": "string",
                "description": "Detailed description of what needs to be done.",
            },
            "activeForm": {
                "type": "string",
                "description": "Present continuous form for spinner display (e.g. 'Running tests').",
            },
            "metadata": {
                "type": "object",
                "description": "Optional structured metadata, including an idempotencyKey for retries.",
            },
        },
        "required": ["subject"],
    },
}

TASK_UPDATE_SCHEMA = {
    "name": "TaskUpdate",
    "description": (
        "Update an existing local task. Use only the id returned by TaskCreate; "
        "invalid ids and illegal state transitions are explicit errors."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "taskId": {
                "type": "string",
                "description": "The task ID to update.",
            },
            "status": {
                "type": "string",
                "description": "New status: pending, in_progress, completed, failed, or cancelled.",
            },
            "subject": {
                "type": "string",
                "description": "New task title.",
            },
            "description": {
                "type": "string",
                "description": "New description.",
            },
            "activeForm": {
                "type": "string",
                "description": "New spinner text.",
            },
        },
        "required": ["taskId"],
    },
}

TASK_LIST_SCHEMA = {
    "name": "TaskList",
    "description": "List all tasks, optionally filtered by status.",
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "Filter by status: pending, in_progress, or completed.",
            },
        },
        "required": [],
    },
}

TASK_GET_SCHEMA = {
    "name": "TaskGet",
    "description": "Get details of a specific task by ID.",
    "input_schema": {
        "type": "object",
        "properties": {
            "taskId": {
                "type": "string",
                "description": "The task ID to retrieve.",
            },
        },
        "required": ["taskId"],
    },
}


# ---------------------------------------------------------------------------
# Tool executors
# ---------------------------------------------------------------------------

def execute_task_create(params: dict[str, Any], cwd: str) -> str:
    store = get_task_store(cwd)
    subject = params["subject"]
    description = params.get("description", "")
    active_form = params.get("activeForm", "")
    metadata = params.get("metadata") if isinstance(params.get("metadata"), dict) else {}
    task = store.create(subject, description, active_form, metadata=metadata)
    return f"Task #{task.id} created: {task.subject}"


def execute_task_update(params: dict[str, Any], cwd: str) -> str:
    store = get_task_store(cwd)
    try:
        task_id = int(params["taskId"])
    except (ValueError, TypeError):
        return f"Error: Invalid task ID: {params.get('taskId')}"

    kwargs: dict[str, Any] = {}
    if "status" in params:
        kwargs["status"] = params["status"]
    if "subject" in params:
        kwargs["subject"] = params["subject"]
    if "description" in params:
        kwargs["description"] = params["description"]
    if "activeForm" in params:
        kwargs["active_form"] = params["activeForm"]
    if "metadata" in params:
        kwargs["metadata"] = params["metadata"]

    result = store.update_checked(task_id, **kwargs)
    return result.message


def execute_task_list(params: dict[str, Any], cwd: str) -> str:
    store = get_task_store(cwd)
    status = params.get("status")
    tasks = store.list_all(status)
    if not tasks:
        return "No tasks found." + (f" (filter: status={status})" if status else "")
    lines = [t.summary() for t in tasks]
    return "\n".join(lines)


def execute_task_get(params: dict[str, Any], cwd: str) -> str:
    store = get_task_store(cwd)
    try:
        task_id = int(params["taskId"])
    except (ValueError, TypeError):
        return f"Error: Invalid task ID: {params.get('taskId')}"

    task = store.get(task_id)
    if not task:
        return f"Error: Task #{task_id} not found"

    lines = [
        f"Task #{task.id}",
        f"  Subject: {task.subject}",
        f"  Status:  {task.status}",
    ]
    if task.description:
        lines.append(f"  Description: {task.description}")
    if task.active_form:
        lines.append(f"  Active form: {task.active_form}")
    if task.owner:
        lines.append(f"  Owner: {task.owner}")
    if task.metadata:
        lines.append(f"  Metadata: {task.metadata}")
    return "\n".join(lines)


# All task tool schemas and executors
TASK_TOOL_SCHEMAS = [
    TASK_CREATE_SCHEMA,
    TASK_UPDATE_SCHEMA,
    TASK_LIST_SCHEMA,
    TASK_GET_SCHEMA,
]

TASK_TOOL_EXECUTORS = {
    "TaskCreate": execute_task_create,
    "TaskUpdate": execute_task_update,
    "TaskList": execute_task_list,
    "TaskGet": execute_task_get,
}
