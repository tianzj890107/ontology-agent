"""Static ontology Agent knowledge loader.

The build step lives in ``scripts/build_agent_knowledge.py``.  This module is
intentionally dependency-free and only selects/reads already generated
Markdown files; it never parses product DOCX/XLSX sources at runtime.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Optional


SOURCE_GROUPS = {
    "source_code.md": ("source", "code", "源码", "source_code"),
    "system_page.md": ("system", "page", "ui", "页面"),
    "business_document.md": ("document", "doc", "文档", "business_document"),
    "multi_source_data.md": ("data", "database", "table", "数据", "source_model"),
    "natural_language.md": ("natural", "language", "nl", "自然语言"),
}


def knowledge_filename(task_type: str, context: Optional[Mapping[str, object]] = None) -> str:
    """Return a safe relative Markdown path for a task mode."""
    kind = str(task_type or "").strip().lower()
    if kind == "integration":
        return "integration/all_sources.md"
    if kind != "modeling":
        return ""
    mode = str((context or {}).get("sourceMode") or "").lower()
    selected = next((name for name, tokens in SOURCE_GROUPS.items()
                     if any(token in mode for token in tokens)), "all_sources.md")
    return f"modeling/{selected}"


def load_static_knowledge(directory: str | Path, task_type: str,
                          context: Optional[Mapping[str, object]] = None) -> str:
    """Read prebuilt Markdown knowledge, composing common + source rules.

    Source-specific files intentionally contain only their own rules so the
    repository remains auditable and avoids copying the same large modeling
    specification into every file.  The Agent still receives the common
    modeling rules followed by the selected source-specific rules.
    """
    relative = knowledge_filename(task_type, context)
    if not relative:
        return ""
    root = Path(directory).resolve()
    path = (root / relative).resolve()
    if root not in path.parents:
        return ""

    def read(path_to_read: Path) -> str:
        if root not in path_to_read.parents:
            return ""
        try:
            return path_to_read.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return ""

    if str(task_type or "").strip().lower() == "modeling" and path.name != "all_sources.md":
        common = read(root / "modeling" / "base.md")
        specific = read(path)
        return "\n\n---\n\n".join(part for part in (common, specific) if part)
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""
