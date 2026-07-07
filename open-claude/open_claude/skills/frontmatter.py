"""YAML frontmatter parser for skill files."""

import re
from typing import Any, Optional


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """
    Parse YAML frontmatter from a markdown string.
    Returns (metadata_dict, body_text).
    """
    content = content.strip()
    if not content.startswith("---"):
        return {}, content

    # Find closing ---
    end_match = re.search(r"\n---\s*\n", content[3:])
    if not end_match:
        # Try end of string
        end_match = re.search(r"\n---\s*$", content[3:])
        if not end_match:
            return {}, content

    yaml_block = content[3 : 3 + end_match.start()]
    body = content[3 + end_match.end() :]

    # Simple YAML parser (no dependency needed for flat key-value)
    metadata: dict[str, Any] = {}
    for line in yaml_block.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        # Strip quotes
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]

        # Type coercion
        if value.lower() in ("true", "yes"):
            metadata[key] = True
        elif value.lower() in ("false", "no"):
            metadata[key] = False
        else:
            metadata[key] = value

    return metadata, body.strip()


# Frontmatter field name mapping to internal names
FIELD_MAP = {
    "description": "description",
    "when_to_use": "when_to_use",
    "user-invocable": "user_invocable",
    "argument-hint": "argument_hint",
    "allowed-tools": "allowed_tools",
    "model": "model",
    "context": "context",
    "agent": "agent",
    "paths": "paths",
    "name": "name",
    "version": "version",
}


def normalize_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize frontmatter keys to internal names."""
    result: dict[str, Any] = {}
    for raw_key, value in raw.items():
        internal_key = FIELD_MAP.get(raw_key, raw_key.replace("-", "_"))
        result[internal_key] = value
    return result
