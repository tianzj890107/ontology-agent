"""Unified task filesystem boundary and process isolation helpers.

The web server gives each Conversation a task directory as ``cwd``.  This
module is the single boundary implementation used by file tools and by every
child process that an Agent can cause to run.  Path checks alone are not a
safe boundary for arbitrary shell syntax, so Linux shell processes are run in
a bubblewrap mount namespace where only the current task directory is
writable and task-unrelated data directories are absent.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
from pathlib import Path
from typing import Iterable, Sequence


logger = logging.getLogger(__name__)


class SandboxViolation(ValueError):
    """Raised when a requested path resolves outside the current task root."""


class SandboxRuntimeUnavailable(RuntimeError):
    """Raised when a shell cannot be safely isolated on this host."""


PUBLIC_VIOLATION = (
    "Sandbox violation: attempted filesystem access outside the current task workspace."
)


def _real(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(os.fspath(path))))


def _is_within(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:
        return False


def is_within_root(path: str | os.PathLike[str], root: str | os.PathLike[str]) -> bool:
    """Return whether the resolved path is the root or a real child of it."""
    return _is_within(_real(path), _real(root))


def _log_violation(task_root: str, operation: str, requested: object,
                   resolved: str = "", reason: str = "outside task root") -> None:
    logger.warning(
        "SANDBOX_VIOLATION %s",
        json.dumps({
            "event_type": "SANDBOX_VIOLATION",
            "operation": operation,
            "requested_path": str(requested)[:2000],
            "resolved_path": resolved[:2000],
            "sandbox_root": task_root,
            "reason": reason,
        }, ensure_ascii=False, separators=(",", ":")),
    )


class TaskSandboxBoundary:
    """Resolve and validate every path against one concrete task directory."""

    def __init__(self, task_root: str | os.PathLike[str],
                 allowed_root: str | os.PathLike[str] | None = None):
        root = _real(task_root)
        if not os.path.isdir(root) or root == os.path.dirname(root):
            raise SandboxViolation(PUBLIC_VIOLATION)
        if allowed_root is not None and not _is_within(root, _real(allowed_root)):
            _log_violation(root, "bind-task-root", task_root, root,
                           "task root is outside the process sandbox")
            raise SandboxViolation(PUBLIC_VIOLATION)
        self.root = root

    def _candidate(self, raw: object) -> str:
        if not isinstance(raw, (str, os.PathLike)):
            raise SandboxViolation(PUBLIC_VIOLATION)
        value = os.fspath(raw)
        if not value:
            raise SandboxViolation(PUBLIC_VIOLATION)
        return value if os.path.isabs(value) else os.path.join(self.root, value)

    def resolve(self, raw: object, *, operation: str = "access") -> str:
        """Return a concrete real path, rejecting traversal and symlink escape."""
        candidate = self._candidate(raw)
        resolved = _real(candidate)
        if not _is_within(resolved, self.root):
            _log_violation(self.root, operation, raw, resolved)
            raise SandboxViolation(PUBLIC_VIOLATION)
        return resolved

    def resolve_parent(self, raw: object, *, operation: str = "write") -> str:
        """Resolve a possibly-new file and independently validate its parent."""
        candidate = self._candidate(raw)
        lexical = os.path.abspath(candidate)
        parent = _real(os.path.dirname(lexical))
        if not _is_within(parent, self.root):
            _log_violation(self.root, operation, raw, parent,
                           "parent directory is outside task root")
            raise SandboxViolation(PUBLIC_VIOLATION)
        resolved = _real(lexical)
        if not _is_within(resolved, self.root):
            _log_violation(self.root, operation, raw, resolved,
                           "target resolves outside task root")
            raise SandboxViolation(PUBLIC_VIOLATION)
        return resolved

    def validate_pattern_scope(self, raw: object, *, operation: str = "glob") -> None:
        """Validate the non-wildcard prefix of a glob before traversal."""
        if not isinstance(raw, (str, os.PathLike)):
            raise SandboxViolation(PUBLIC_VIOLATION)
        value = os.fspath(raw)
        wildcard_positions = [value.find(char) for char in "*?["]
        positions = [pos for pos in wildcard_positions if pos >= 0]
        prefix = value[:min(positions)] if positions else value
        if positions:
            prefix = os.path.dirname(prefix) or "."
        self.resolve(prefix, operation=operation)

    def filter_existing(self, paths: Iterable[str], *, operation: str) -> list[str]:
        safe: list[str] = []
        for path in paths:
            try:
                safe.append(self.resolve(path, operation=operation))
            except SandboxViolation:
                continue
        return safe

    def _components(self, resolved: str) -> list[str]:
        relative = os.path.relpath(resolved, self.root)
        if relative == os.curdir:
            return []
        components = [part for part in relative.split(os.sep) if part not in ("", ".")]
        if any(part == os.pardir for part in components):
            raise SandboxViolation(PUBLIC_VIOLATION)
        return components

    def _open_directory(self, resolved: str, *, create: bool = False) -> int:
        """Open a directory chain without following symlinks during traversal."""
        components = self._components(resolved)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        current = os.open(self.root, flags | nofollow)
        try:
            for component in components:
                try:
                    child = os.open(component, flags | nofollow, dir_fd=current)
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(component, dir_fd=current)
                    child = os.open(component, flags | nofollow, dir_fd=current)
                os.close(current)
                current = child
            return current
        except Exception:
            os.close(current)
            raise

    def open_text(self, raw: object, mode: str, *, operation: str = "read"):
        """Open a text file through validated directory descriptors.

        The caller receives a normal text file object, but the final open is
        relative to a no-symlink directory fd.  This closes the check/use gap
        that a second process could otherwise exploit by swapping a symlink
        after ``realpath`` validation.
        """
        creating = any(flag in mode for flag in ("w", "a", "x", "+"))
        resolved = (self.resolve_parent(raw, operation=operation)
                    if creating else self.resolve(raw, operation=operation))
        parent = os.path.dirname(resolved)
        name = os.path.basename(resolved)
        parent_fd = self._open_directory(parent, create=creating)
        try:
            flags = (os.O_RDONLY if not creating else os.O_WRONLY | os.O_CREAT)
            if "w" in mode:
                flags |= os.O_TRUNC
            elif "a" in mode:
                flags |= os.O_APPEND
            if "+" in mode:
                flags = (flags & ~os.O_RDONLY) | os.O_RDWR
            flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(name, flags, 0o666, dir_fd=parent_fd)
        finally:
            os.close(parent_fd)
        return os.fdopen(fd, mode, encoding="utf-8", errors="replace", newline="\n")


def boundary_for(cwd: str) -> TaskSandboxBoundary | None:
    """Build the task boundary when the web server enabled confinement."""
    process_root = os.environ.get("OC_SANDBOX_ROOT")
    if not process_root:
        return None
    try:
        return TaskSandboxBoundary(cwd, allowed_root=process_root)
    except SandboxViolation:
        _log_violation(_real(process_root), "task-cwd", cwd,
                       _real(cwd), "invalid task cwd")
        raise


def _add_parent_dirs(args: list[str], path: str) -> None:
    """Create the task path's parent mount points in bwrap's empty root."""
    current = os.path.dirname(path)
    prefixes: list[str] = []
    while current and current != os.path.dirname(current) and current != "/":
        prefixes.append(current)
        current = os.path.dirname(current)
    for prefix in reversed(prefixes):
        args.extend(("--dir", prefix))


def _ro_bind_if_present(args: list[str], source: str, target: str | None = None) -> None:
    if os.path.exists(source):
        args.extend(("--ro-bind", source, target or source))


def _shared_agent_venv() -> str:
    """Return the process-wide venv that sandboxed commands may reuse."""
    configured = os.environ.get("ONTOLOGY_AGENT_SHARED_VENV", "").strip()
    candidate = configured or str(Path(__file__).resolve().parents[2] / ".venv")
    resolved = os.path.realpath(candidate)
    if os.path.isfile(os.path.join(resolved, "bin", "python")):
        return resolved
    return ""


def isolated_argv(argv: Sequence[str], cwd: str) -> tuple[list[str], dict[str, str]]:
    """Return an argv/env pair that runs inside the current task filesystem."""
    boundary = boundary_for(cwd)
    if boundary is None:
        return list(argv), os.environ.copy()

    bwrap = shutil.which("bwrap")
    if platform.system() != "Linux" or not bwrap:
        raise SandboxRuntimeUnavailable(
            "secure task command isolation is unavailable; shell execution was refused"
        )

    root = boundary.root
    args = [
        bwrap,
        "--die-with-parent",
        "--new-session",
        "--unshare-pid",
        "--ro-bind", "/usr", "/usr",
    ]
    for system_dir in ("/bin", "/sbin", "/lib", "/lib64", "/usr/local"):
        _ro_bind_if_present(args, system_dir)
    args.extend(("--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--tmpfs", "/etc"))
    # Keep runtime support files available without exposing /etc/passwd or the
    # host's arbitrary configuration.  The task bind is added after these
    # mounts and is the only writable host filesystem subtree.
    for source in ("/etc/ssl", "/etc/ca-certificates", "/etc/hosts",
                   "/etc/resolv.conf", "/etc/nsswitch.conf", "/etc/ld.so.cache",
                   "/etc/localtime", "/etc/timezone"):
        target = source
        if os.path.isdir(source):
            args.extend(("--dir", target))
        _ro_bind_if_present(args, source, target)
    shared_venv = _shared_agent_venv()
    if shared_venv and not _is_within(shared_venv, root):
        _add_parent_dirs(args, shared_venv)
        args.extend(("--ro-bind", shared_venv, shared_venv))
    _add_parent_dirs(args, root)
    args.extend(("--bind", root, root, "--dir", "/tmp/agent-home",
                 "--chdir", root, "--"))
    args.extend(argv)

    env = os.environ.copy()
    env.update({
        "HOME": "/tmp/agent-home",
        "TMPDIR": "/tmp",
        "PWD": root,
        "OLDPWD": root,
        "OC_SANDBOX_ROOT": root,
    })
    if shared_venv:
        env.update({
            "ONTOLOGY_AGENT_SHARED_VENV": shared_venv,
            "VIRTUAL_ENV": shared_venv,
            "PATH": shared_venv + "/bin:" + env.get("PATH", ""),
            "PYTHONNOUSERSITE": "1",
        })
    return args, env


def run_isolated(argv: Sequence[str], cwd: str, *, timeout: int = 120,
                 input_text: str | None = None):
    """Run a child process with the task filesystem boundary enforced."""
    isolated, env = isolated_argv(argv, cwd)
    import subprocess
    return subprocess.run(
        isolated,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=cwd,
        env=env,
        input=input_text,
    )
