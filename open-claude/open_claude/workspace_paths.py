"""Centralized task/run workspace path mapping.

Canonical per-task/run workspace layout is ``input/``, ``work/``, ``output/``::

    input/   current task/run raw inputs, reference templates and safe
             connection helpers
    work/    intermediate state, candidates, decision audits, validation
             reports and checkpoint/resume data
    output/  final formal deliverables

Historical tasks created before the rename may still store files under
``mission-input/``, ``mission-work/`` and ``mission-output/``.  All new writes
use the canonical names; legacy directories are only resolved through this
module (reads, and continued writes for historical tasks that have no
canonical directory yet), so the compatibility layer lives in one place and
never appears in user-facing UI, API paths or Agent prompts.
"""

from __future__ import annotations

import os
from typing import Iterable


CANONICAL_DIRS = ("input", "work", "output")
LEGACY_DIRS = ("mission-input", "mission-work", "mission-output")
LEGACY_TO_CANONICAL = dict(zip(LEGACY_DIRS, CANONICAL_DIRS))
CANONICAL_TO_LEGACY = dict(zip(CANONICAL_DIRS, LEGACY_DIRS))
#: Top-level directories that belong to a task/run workspace.
WORKSPACE_TOP_DIRS = frozenset(CANONICAL_DIRS + LEGACY_DIRS)


class WorkspacePathError(ValueError):
    """Raised when a workspace path cannot be safely resolved."""


def _real(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(os.fspath(path))))


def _is_within(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:
        return False


def _first_existing(cwd: str, names: Iterable[str]) -> str:
    """Return the first existing child directory, else the canonical candidate."""
    names = list(names)
    for name in names:
        candidate = os.path.join(cwd, name)
        if os.path.isdir(candidate):
            return candidate
    return os.path.join(cwd, names[0])


def input_dir(cwd: str | os.PathLike[str]) -> str:
    """Physical input directory: canonical ``input`` wins, legacy fallback."""
    return _first_existing(os.fspath(cwd), ("input", "mission-input"))


def work_dir(cwd: str | os.PathLike[str]) -> str:
    """Physical work directory: canonical ``work`` wins, legacy fallback."""
    return _first_existing(os.fspath(cwd), ("work", "mission-work"))


def output_dir(cwd: str | os.PathLike[str]) -> str:
    """Physical output directory: canonical ``output`` wins, legacy fallback."""
    return _first_existing(os.fspath(cwd), ("output", "mission-output"))


def workspace_dir(cwd: str | os.PathLike[str], name: str) -> str:
    """Resolve a workspace-relative directory name (canonical or legacy)."""
    name = str(name or "").strip().strip("/")
    if not name or name in {".", ".."} or "/" in name:
        raise WorkspacePathError(f"invalid workspace directory name: {name!r}")
    canonical = LEGACY_TO_CANONICAL.get(name, name)
    legacy = CANONICAL_TO_LEGACY.get(canonical, name)
    return _first_existing(os.fspath(cwd), (canonical, legacy))


def ensure_workspace_dirs(cwd: str | os.PathLike[str]) -> list[str]:
    """Create the canonical ``input``/``work``/``output`` dirs (new tasks/runs).

    Never creates legacy ``mission-*`` names.  Returns the created paths.
    """
    root = os.fspath(cwd)
    created = []
    for name in CANONICAL_DIRS:
        path = os.path.join(root, name)
        os.makedirs(path, exist_ok=True)
        created.append(path)
    return created


def normalize_relpath(rel: str) -> str:
    """Map a legacy ``mission-*`` relative path to its canonical logical path.

    The returned path is the unified logical form used by the file API,
    download/upload contracts and the frontend.
    """
    parts = str(rel or "").replace("\\", "/").strip("/").split("/")
    if parts and parts[0] in LEGACY_TO_CANONICAL:
        parts[0] = LEGACY_TO_CANONICAL[parts[0]]
    return "/".join(parts)


def resolve_workspace_path(cwd: str | os.PathLike[str], rel: str,
                           *, must_exist: bool = True) -> str | None:
    """Resolve a logical workspace-relative path to a real physical path.

    ``rel`` may use canonical (``output/x.csv``) or legacy (``mission-output/...``)
    prefixes.  Canonical layout wins when both exist; for writes
    (``must_exist=False``) the canonical path is always returned so new data
    never lands in a legacy directory.  ``None`` is returned when the file
    does not exist under either layout.
    """
    root = _real(os.fspath(cwd))
    rel = str(rel or "").replace("\\", "/").strip("/")
    if not rel or not _is_within(os.path.join(root, rel), root):
        return None
    parts = rel.split("/")
    head = parts[0]
    canonical_head = LEGACY_TO_CANONICAL.get(head, head)
    legacy_head = CANONICAL_TO_LEGACY.get(canonical_head, canonical_head)
    tail = "/".join(parts[1:])
    candidates = [os.path.join(root, canonical_head, tail) if tail else os.path.join(root, canonical_head)]
    if legacy_head != canonical_head:
        candidates.append(os.path.join(root, legacy_head, tail) if tail else os.path.join(root, legacy_head))
    if not must_exist:
        return candidates[0]
    for candidate in candidates:
        resolved = _real(candidate)
        if os.path.isfile(resolved) and _is_within(resolved, root):
            return resolved
    return None


def validate_task_workspace(cwd: str | os.PathLike[str] | None,
                            *, allowed_root: str | os.PathLike[str] | None = None,
                            repo_root: str | os.PathLike[str] | None = None,
                            source_root: str | os.PathLike[str] | None = None,
                            home_dir: str | os.PathLike[str] | None = None) -> str:
    """Validate a task/run workspace before creating or using it.

    Rejects empty paths, the repository root, the server source directory,
    the HOME directory, sandbox data roots themselves, relative-path escapes
    and symlink escapes.  Returns the canonical realpath on success.
    """
    if not cwd or not str(cwd).strip():
        raise WorkspacePathError("empty workspace path is not allowed")
    resolved = _real(os.fspath(cwd))
    if not resolved or resolved == os.path.dirname(resolved):
        raise WorkspacePathError(f"invalid workspace path: {cwd!r}")
    banned = []
    for label, candidate in (("repo-root", repo_root), ("source-root", source_root),
                             ("home", home_dir), ("allowed-root", allowed_root)):
        if not candidate:
            continue
        banned.append((label, _real(os.fspath(candidate))))
    for label, root in banned:
        if resolved == root:
            raise WorkspacePathError(
                f"workspace must not be the {label}: {cwd!r}")
        if label == "allowed-root" and not _is_within(resolved, root):
            raise WorkspacePathError(
                f"workspace is outside the allowed data root: {cwd!r}")
    return resolved
