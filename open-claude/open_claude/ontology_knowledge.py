"""Static ontology Agent knowledge loader.

The build step lives in ``scripts/build_agent_knowledge.py``.  This module is
intentionally dependency-free and only selects/reads already generated
Markdown files; it never parses product DOCX/XLSX sources at runtime.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping, Optional


SOURCE_GROUPS = {
    "source_codev0.0.1.md": ("source", "code", "源码", "source_code"),
    "system_pagev0.0.1.md": ("system", "page", "ui", "页面"),
    "business_documentv0.0.1.md": ("document", "doc", "文档", "business_document"),
    "multi_source_datav0.0.1.md": ("data", "database", "table", "数据", "source_model"),
    "natural_languagev0.0.1.md": ("natural", "language", "nl", "自然语言"),
}

# 专项数据治理技能仅在任务明确要求相应解析要素或输出文件时注入。这样既能让
# TERM/RULE/METRIC 使用各自的证据与质量规则，又不会让普通实体建模任务产生
# 不在 execution-context.expectedFiles 中的额外文件。
MODELING_SKILL_MODULES = (
    ("TERM", "业务术语v0.0.1.md",
     ("TERM", "TERMS", "BUSINESS_TERM", "BUSINESS_TERMS", "术语", "业务术语"),
     ("terms.csv", "business_terms.csv")),
    ("RULE", "业务规则v0.0.1.md",
     ("RULE", "RULES", "BUSINESS_RULE", "BUSINESS_RULES", "业务规则"),
     ("business_rules.csv", "rules.csv")),
    ("METRIC", "指标v0.0.1.md",
     ("METRIC", "METRICS", "INDICATOR", "INDICATORS", "ATOMIC_INDICATOR",
      "COMPOSITE_INDICATOR", "指标"),
     ("metrics.csv", "indicator.csv", "atomic_indicators.csv",
      "composite_indicators.csv", "indicator_lineage.csv")),
    ("ACTION", "动作v0.0.1.md",
     ("ACTION", "ACTIONS", "动作"),
     ("actions.csv",)),
)


def normalize_task_type(task_type: str) -> str:
    """Map Ontology execution-context task types to Agent modes.

    The gateway uses values such as ``DOCUMENT_MODELING`` and
    ``DATA_SOURCE_MODELING``; these must still receive the modeling knowledge
    and instructions rather than being treated as an unknown mode.
    """
    raw = str(task_type or "").strip().lower()
    if raw == "integration" or "integration" in raw or "disambigu" in raw:
        return "integration"
    if raw == "modeling" or "modeling" in raw or raw in {"model", "ontology"}:
        return "modeling"
    return raw


def knowledge_filename(task_type: str, context: Optional[Mapping[str, object]] = None) -> str:
    """Return a safe relative Markdown path for a task mode."""
    kind = normalize_task_type(task_type)
    if kind == "integration":
        return "integration/all_sourcesv0.0.1.md"
    if kind != "modeling":
        return ""
    mode = str((context or {}).get("sourceMode") or "").lower()
    selected = next((name for name, tokens in SOURCE_GROUPS.items()
                     if any(token in mode for token in tokens)), "all_sourcesv0.0.1.md")
    return f"modeling/{selected}"


def modeling_skill_modules(context: Optional[Mapping[str, object]] = None) -> tuple[tuple[str, str], ...]:
    """Return requested TERM/RULE/METRIC static skill modules in stable order.

    ``parseElements`` is the only source of the requested modeling scope.  The
    output filenames are an allow-list for writing/uploading, not a signal for
    selecting which modeling assets to identify.
    """
    context = context or {}
    requested: set[str] = set()
    raw_elements = context.get("parseElements")
    values = raw_elements if isinstance(raw_elements, list) else [raw_elements]
    for value in values:
        if isinstance(value, Mapping):
            value = (value.get("code") or value.get("value") or value.get("name")
                     or value.get("label") or "")
        requested.add(str(value or "").upper().replace("-", "_"))

    joined = " ".join(requested)
    selected = []
    for code, filename, aliases, output_files in MODELING_SKILL_MODULES:
        alias_match = any(alias.upper().replace("-", "_") in joined for alias in aliases)
        if alias_match:
            selected.append((code, filename))
    return tuple(selected)


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

    if normalize_task_type(task_type) != "modeling":
        return read(path)

    if path.name == "all_sourcesv0.0.1.md":
        parts = [read(path)]
    else:
        parts = [read(root / "modeling" / "basev0.0.1.md"), read(path)]
    for _, filename in modeling_skill_modules(context):
        content = read(root / filename)
        if content:
            parts.append(f"# 建模专项技能：{filename}\n\n{content}")
    return "\n\n---\n\n".join(part for part in parts if part)
