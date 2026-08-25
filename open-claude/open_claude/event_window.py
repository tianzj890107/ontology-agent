"""Shared event-window computation for the 47313 workbench and 47314
standalone modeling service.

The two services expose the same absolute-position cursor protocol for their
append-only event journals:

- windows are half-open intervals ``[start, end)`` over absolute event
  positions (0-based, equal to the persisted ``seq`` in both services);
- ``since=N`` starts at the first unread position N;
- ``before=N`` returns the window strictly before position N;
- ``tail=true`` returns the newest ``limit`` events;
- ``nextCursor`` is always ``eventEnd``, so incremental readers never rely on
  ``cursor + delta.length`` alone;
- ``limit`` is clamped to ``[1, MAX_EVENT_PAGE_LIMIT]``.

This module is deliberately free of any import from ``oc_codex_server`` or
``standalone_modeling_server`` so both services can share one boundary
definition without a circular import.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional, Sequence, Tuple

DEFAULT_EVENT_PAGE_LIMIT = 80
MAX_EVENT_PAGE_LIMIT = 200

_INT_RE = re.compile(r"^[+-]?\d+$")


def _as_int(value: Any, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and _INT_RE.match(value.strip()):
        return int(value.strip())
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_window(
    query: Mapping[str, Any],
    total: int,
    default_limit: int = DEFAULT_EVENT_PAGE_LIMIT,
    max_limit: int = MAX_EVENT_PAGE_LIMIT,
) -> Tuple[int, int]:
    """Compute the half-open window ``[start, end)`` for one events request.

    ``query`` is the parsed query-string mapping (``parse_qs`` output or a
    plain dict of lists).  ``total`` is the number of events in the journal.

    Cursor contract:
    - ``tail`` / ``before``: ``end`` is ``before`` (or ``total`` when tailing),
      ``start`` is ``max(0, end - limit)``;
    - otherwise ``since=N``: ``start`` is N clamped to ``[0, total]`` and
      ``end`` is ``total``.
    """
    try:
        total = max(0, int(total))
    except (TypeError, ValueError):
        total = 0
    if not isinstance(query, Mapping):
        query = {}
    try:
        limit = _as_int((query.get("limit") or [default_limit])[0], default_limit)
    except (TypeError, IndexError, ValueError):
        limit = default_limit
    limit = max(1, min(max(1, int(max_limit)), int(limit)))

    if "tail" in query or "before" in query:
        end = _as_int((query.get("before") or [total])[0], total)
        end = max(0, min(total, end))
        start = max(0, end - limit)
    else:
        start = _as_int((query.get("since") or [0])[0], 0)
        start = max(0, min(total, start))
        end = total
    return start, end


def window_response(
    events: Sequence[Any],
    start: int,
    end: int,
    total: int,
    *,
    scope_id: Optional[str] = None,
    scope_key: str = "runId",
) -> dict[str, Any]:
    """Build the unified pagination payload shared by both services.

    ``scope_id`` is the run/task id exposed in the response (for example
    ``taskId`` on 47313 or ``runId`` on 47314); when omitted the response does
    not carry a scope key.
    """
    try:
        total = max(0, int(total))
        start = max(0, min(total, int(start)))
        end = max(start, min(total, int(end)))
    except (TypeError, ValueError):
        total = 0
        start = 0
        end = 0
    events = list(events) if events is not None else []
    payload: dict[str, Any] = {
        "events": events,
        "eventStart": start,
        "eventEnd": end,
        "eventTotal": total,
        "eventHasMore": start > 0,
        "nextCursor": end,
    }
    if scope_id is not None:
        payload[scope_key] = scope_id
    return payload
