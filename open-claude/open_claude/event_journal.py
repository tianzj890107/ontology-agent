"""Append-only JSONL event journal helpers shared by 47313 and 47314.

Both services persist one JSON event per line.  The journal is the crash-safe
fact source: a partial (truncated) final line is ignored on recovery, earlier
valid events are never lost, and the next ``seq`` resumes from the last valid
line.

Persistence contract
---------------------
- ``append_line`` serializes appends under a caller-provided lock and calls
  ``flush()`` after every event.  ``fsync`` is deliberately skipped on the hot
  path; the bounded task-state snapshot (47313 ``.web_tasks.json``) and run
  index (47314) are fsync'd via atomic replace and provide the crash-safe
  fallback.  Tests document and verify this split.
- Offset index: each journal may carry a sidecar ``<path>.idx`` JSONL with one
  ``[seq, byte_offset]`` entry per ``INDEX_STRIDE`` events.  The index is
  append-only on the hot path and rebuilt (idempotently) when missing or stale,
  so tail/range reads never parse the whole journal.

This module must not import either HTTP server; callers pass their own locks
and paths.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Callable, Iterable, Optional, Sequence

INDEX_STRIDE = 128
_READ_CHUNK = 64 * 1024
_parse_line: Callable[[str], Any] = json.loads


# -- low-level helpers -------------------------------------------------------


def _open_text(path: str, mode: str = "r", encoding: str = "utf-8"):
    return open(path, mode, encoding=encoding)


def _index_path(path: str) -> str:
    return str(path) + ".idx"


def _valid_events(events: Iterable[Any]) -> list[dict[str, Any]]:
    return [event for event in events if isinstance(event, dict)]


def append_line(path: str, event: dict[str, Any], *, lock: Optional[Any] = None) -> None:
    """Append one JSON event line and flush.

    ``lock`` serializes concurrent writers; when omitted the caller must
    already serialize appends for this path.
    """
    if not isinstance(event, dict):
        return
    data = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
    if lock is not None:
        with lock:
            _append_raw(path, data, event)
    else:
        _append_raw(path, data, event)


def _append_raw(path: str, data: str, event: dict[str, Any]) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    seq = event.get("seq")
    offset = 0
    try:
        with _open_text(path, "a") as fh:
            offset = fh.tell()
            fh.write(data)
            fh.flush()
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError:
        return
    if isinstance(seq, int) and seq % INDEX_STRIDE == 0:
        _append_index(path, offset, seq)


def _append_index(path: str, offset: int, seq: int) -> None:
    index = _index_path(path)
    try:
        with _open_text(index, "a") as fh:
            fh.write(json.dumps([seq, offset], separators=(",", ":")))
            fh.write("\n")
            fh.flush()
    except OSError:
        pass


def seed(path: str, events: Sequence[dict[str, Any]], *, lock: Optional[Any] = None) -> bool:
    """Atomically create a journal from legacy events, never overwriting one.

    Returns True when the journal was seeded.  Idempotent: a second call with
    an existing journal is a no-op and returns False.
    """
    if not isinstance(events, list) or not events:
        return False
    if os.path.exists(path):
        return False
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    try:
        if lock is not None:
            with lock:
                if os.path.exists(path):
                    return False
                _write_seed(path, events)
        else:
            if os.path.exists(path):
                return False
            _write_seed(path, events)
    except OSError:
        return False
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return True


def _write_seed(path: str, events: Sequence[dict[str, Any]]) -> None:
    with _open_text(path, "x") as fh:
        offset = 0
        for event in events:
            if not isinstance(event, dict):
                continue
            seq = event.get("seq")
            if isinstance(seq, int) and seq % INDEX_STRIDE == 0:
                _append_index(path, offset, seq)
            fh.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")
            offset = fh.tell()
        fh.flush()


# -- reads -------------------------------------------------------------------


def read_all_valid(path: str, *, lock: Optional[Any] = None) -> list[dict[str, Any]]:
    """Read every valid event.  Corrupt lines are skipped, never fatal."""
    events: list[dict[str, Any]] = []
    try:
        if lock is not None:
            with lock:
                _read_all_into(path, events)
        else:
            _read_all_into(path, events)
    except OSError:
        return []
    return events


def _read_all_into(path: str, events: list[dict[str, Any]]) -> None:
    with _open_text(path) as fh:
        for line in fh:
            try:
                event = _parse_line(line)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(event, dict):
                events.append(event)


def last_valid_seq(path: str, *, lock: Optional[Any] = None) -> Optional[int]:
    """Return the logical position of the last valid event.

    Journals written before persistent event identities were introduced do
    not contain ``seq``.  Their line position is nevertheless the original
    absolute event position, so recovery must use it instead of treating a
    non-empty legacy journal as empty.  Taking the maximum also handles a
    journal containing legacy lines followed by newly sequenced events.
    """
    seq: Optional[int] = None
    try:
        if lock is not None:
            with lock:
                seq = _last_valid_seq_unlocked(path)
        else:
            seq = _last_valid_seq_unlocked(path)
    except OSError:
        return None
    return seq


def _last_valid_seq_unlocked(path: str) -> Optional[int]:
    seq: Optional[int] = None
    valid_position = -1
    with _open_text(path) as fh:
        for line in fh:
            try:
                event = _parse_line(line)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(event, dict):
                continue
            valid_position += 1
            if isinstance(event.get("seq"), int):
                explicit_seq = int(event["seq"])
                seq = explicit_seq if seq is None else max(seq, explicit_seq)
    if valid_position < 0:
        return None
    return max(valid_position, seq if seq is not None else valid_position)


def tail_events(path: str, limit: int, *, lock: Optional[Any] = None) -> list[dict[str, Any]]:
    """Return the last ``limit`` valid events without parsing the full journal.

    Reads backwards from EOF in bounded chunks, so a 430k-line journal costs
    O(limit) parse work and a few hundred KB of I/O.
    """
    try:
        limit = max(1, int(limit))
    except (TypeError, ValueError):
        limit = 1
    if not os.path.exists(path):
        return []
    raw_lines = _tail_raw_lines(path, limit, lock=lock)
    events: list[dict[str, Any]] = []
    for raw in raw_lines:
        try:
            event = _parse_line(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _tail_raw_lines(path: str, limit: int, *, lock: Optional[Any] = None) -> list[str]:
    """Return up to ``limit`` final complete lines (oldest to newest)."""
    if lock is not None:
        with lock:
            return _tail_raw_lines_unlocked(path, limit)
    return _tail_raw_lines_unlocked(path, limit)


def _tail_raw_lines_unlocked(path: str, limit: int) -> list[str]:
    try:
        fh = open(path, "rb")
    except OSError:
        return []
    try:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        if size <= 0:
            return []
        pos = size
        data = b""
        while pos > 0:
            chunk_size = min(_READ_CHUNK, pos)
            pos -= chunk_size
            fh.seek(pos)
            data = fh.read(chunk_size) + data
            # Every event line ends with '\n'; count complete lines so far.
            if data.count(b"\n") >= limit + 1:
                break
        lines = data.split(b"\n")
        # Drop a truncated final line (file does not end with '\n').
        if lines and lines[-1] != b"":
            lines.pop()
        else:
            lines.pop() if lines and lines[-1] == b"" else None
        if lines and lines[-1] == b"":
            lines.pop()
        # When we stopped before the file start, the first element may start
        # mid-line; we read at least limit+1 complete lines, so dropping it is
        # safe.
        if pos > 0 and lines:
            lines = lines[1:]
        return [line.decode("utf-8", errors="replace") for line in lines[-limit:]]
    finally:
        fh.close()


def read_range(
    path: str,
    start: int,
    end: int,
    *,
    lock: Optional[Any] = None,
    parse_hook: Optional[Callable[[str], Any]] = None,
) -> list[dict[str, Any]]:
    """Return valid events at absolute positions ``[start, end)``.

    Uses the sidecar offset index so ``start`` is located in O(log n) index
    entries plus at most ``INDEX_STRIDE`` parsed lines.  The index is rebuilt
    idempotently when missing or stale (journal truncated or grown past it).
    """
    try:
        start = max(0, int(start))
        end = max(0, int(end))
    except (TypeError, ValueError):
        return []
    if start >= end or not os.path.exists(path):
        return []
    loader = parse_hook or _parse_line
    for attempt in range(2):
        events: list[dict[str, Any]] = []
        try:
            if lock is not None:
                with lock:
                    completed = _read_range_unlocked(path, start, end, events, loader)
            else:
                completed = _read_range_unlocked(path, start, end, events, loader)
        except OSError:
            return []
        if completed or attempt == 1:
            return events
        # The index was stale (journal truncated or missing entries).  Rebuild
        # once and retry so the second pass reads the fresh index.
        rebuild_index(path, lock=lock)
    return []


def _read_range_unlocked(
    path: str,
    start: int,
    end: int,
    events: list[dict[str, Any]],
    loader: Callable[[str], Any],
) -> bool:
    offset, position = _seek_offset(path, start)
    if offset is None:
        return False
    with _open_text(path) as fh:
        fh.seek(offset)
        for line in fh:
            if position >= end:
                return True
            try:
                event = loader(line)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(event, dict):
                continue
            if position >= start:
                events.append(event)
            position += 1
    # Reaching EOF exactly at ``end`` is a completed window (the normal tail /
    # since case where ``end == total``).  Only a position short of ``end``
    # means the index is stale (journal truncated or missing entries).
    return position >= end


def _seek_offset(path: str, start: int) -> tuple[Optional[int], int]:
    """Return ``(byte_offset, position_at_offset)`` for absolute position start."""
    entries = _index_entries(path)
    if not entries:
        return None, start
    best_seq = -1
    best_offset = 0
    lo, hi = 0, len(entries) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if entries[mid][0] <= start:
            best_seq, best_offset = entries[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    if best_seq < 0:
        return 0, 0
    return best_offset, best_seq


def rebuild_index(path: str, *, lock: Optional[Any] = None) -> None:
    """Idempotently rebuild the offset index from the current journal."""
    if not os.path.exists(path):
        return
    entries: list[list[int]] = []
    try:
        if lock is not None:
            with lock:
                _scan_offsets(path, entries)
        else:
            _scan_offsets(path, entries)
    except OSError:
        return
    index = _index_path(path)
    try:
        with _open_text(index, "w") as fh:
            for seq, offset in entries:
                fh.write(json.dumps([seq, offset], separators=(",", ":")))
                fh.write("\n")
            fh.flush()
        try:
            os.chmod(index, 0o600)
        except OSError:
            pass
    except OSError:
        pass


def _scan_offsets(path: str, entries: list[list[int]]) -> None:
    with _open_text(path) as fh:
        offset = 0
        seq = 0
        line = fh.readline()
        while line:
            try:
                event = _parse_line(line)
            except (TypeError, ValueError, json.JSONDecodeError):
                line = fh.readline()
                continue
            if not isinstance(event, dict):
                line = fh.readline()
                continue
            if seq % INDEX_STRIDE == 0:
                entries.append([seq, offset])
            seq += 1
            offset = fh.tell()
            line = fh.readline()


def _index_entries(path: str) -> list[list[int]]:
    """Load index entries, rebuilding the index when missing or stale."""
    index = _index_path(path)
    entries: list[list[int]] = []
    try:
        with _open_text(index) as fh:
            for line in fh:
                try:
                    pair = _parse_line(line)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if isinstance(pair, list) and len(pair) == 2:
                    try:
                        entries.append([int(pair[0]), int(pair[1])])
                    except (TypeError, ValueError):
                        continue
    except OSError:
        entries = []
    if entries:
        return entries
    rebuild_index(path)
    entries = []
    try:
        with _open_text(index) as fh:
            for line in fh:
                try:
                    pair = _parse_line(line)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if isinstance(pair, list) and len(pair) == 2:
                    try:
                        entries.append([int(pair[0]), int(pair[1])])
                    except (TypeError, ValueError):
                        continue
    except OSError:
        return []
    return entries


def count_valid_lines(path: str, *, lock: Optional[Any] = None) -> int:
    """Return the number of valid events in the journal (used by tests)."""
    return len(read_all_valid(path, lock=lock))
