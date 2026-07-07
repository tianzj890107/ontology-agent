"""
In-memory task management system for Open Claude.

Provides TaskCreate, TaskUpdate, TaskList, TaskGet tools for tracking
multi-step work within a conversation session.
"""

import threading
from typing import Any, Optional


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

    def __init__(self):
        self._tasks: dict[int, Task] = {}
        self._next_id = 1
        self._lock = threading.Lock()

    def create(self, subject: str, description: str = "",
               active_form: str = "", owner: str = "") -> Task:
        with self._lock:
            task = Task(self._next_id, subject, description, active_form, owner)
            self._tasks[self._next_id] = task
            self._next_id += 1
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

    def update(self, task_id: int, **kwargs) -> Optional[Task]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            if "status" in kwargs:
                val = kwargs["status"]
                if val == "deleted":
                    del self._tasks[task_id]
                    return task
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
            return task


# Global singleton
_store: Optional[TaskStore] = None


def get_task_store() -> TaskStore:
    global _store
    if _store is None:
        _store = TaskStore()
    return _store


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

TASK_CREATE_SCHEMA = {
    "name": "TaskCreate",
    "description": (
        "Create a new task to track work. Use for breaking complex work into steps."
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
        },
        "required": ["subject"],
    },
}

TASK_UPDATE_SCHEMA = {
    "name": "TaskUpdate",
    "description": (
        "Update a task's status or details. Use status 'in_progress' when starting, "
        "'completed' when done, 'deleted' to remove."
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
                "description": "New status: pending, in_progress, completed, or deleted.",
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
    store = get_task_store()
    subject = params["subject"]
    description = params.get("description", "")
    active_form = params.get("activeForm", "")
    task = store.create(subject, description, active_form)
    return f"Task #{task.id} created: {task.subject}"


def execute_task_update(params: dict[str, Any], cwd: str) -> str:
    store = get_task_store()
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

    task = store.update(task_id, **kwargs)
    if not task:
        return f"Error: Task #{task_id} not found"

    if kwargs.get("status") == "deleted":
        return f"Task #{task_id} deleted"
    return f"Task #{task_id} updated: {task.summary()}"


def execute_task_list(params: dict[str, Any], cwd: str) -> str:
    store = get_task_store()
    status = params.get("status")
    tasks = store.list_all(status)
    if not tasks:
        return "No tasks found." + (f" (filter: status={status})" if status else "")
    lines = [t.summary() for t in tasks]
    return "\n".join(lines)


def execute_task_get(params: dict[str, Any], cwd: str) -> str:
    store = get_task_store()
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
