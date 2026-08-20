"""
OpenAI-compatible provider adapter.

Qwen (DashScope), Zhipu GLM, Moonshot (Kimi), DeepSeek, and OpenAI all speak the
OpenAI Chat Completions protocol, so they share this single adapter. It:

  - converts open-claude's Anthropic-style message/tool format to OpenAI's,
  - streams responses while emitting the SAME normalized event dicts that
    api.stream_message yields for Anthropic, and
  - offers a non-streaming `send` returning normalized content blocks.

The `openai` package is an optional dependency, imported lazily so that users who
only use Anthropic models never need it.
"""

import json
import os
import threading
from typing import Any, Callable, Generator, Iterable, Mapping, Optional

from .config import PROVIDERS, get_api_key_for, get_provider_base_url


_TIMEOUT_ENV_DEFAULTS = {
    "ONTOLOGY_LLM_CONNECT_TIMEOUT": 5.0,
    "ONTOLOGY_LLM_READ_TIMEOUT": 600.0,
    "ONTOLOGY_LLM_WRITE_TIMEOUT": 600.0,
    "ONTOLOGY_LLM_POOL_TIMEOUT": 600.0,
}


def provider_timeout_config() -> dict[str, float]:
    """Resolve explicit provider transport timeouts from the environment."""
    resolved: dict[str, float] = {}
    for name, default in _TIMEOUT_ENV_DEFAULTS.items():
        raw = os.environ.get(name, "").strip()
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = default
        resolved[name] = value if value > 0 else default
    return resolved


def provider_timeout_summary() -> str:
    """Non-sensitive one-line timeout summary for startup logs."""
    config = provider_timeout_config()
    return ("provider transport timeouts: "
            f"connect={config['ONTOLOGY_LLM_CONNECT_TIMEOUT']:g}s "
            f"read={config['ONTOLOGY_LLM_READ_TIMEOUT']:g}s "
            f"write={config['ONTOLOGY_LLM_WRITE_TIMEOUT']:g}s "
            f"pool={config['ONTOLOGY_LLM_POOL_TIMEOUT']:g}s")


def _provider_timeout():
    """Build the SDK timeout object, falling back to httpx when available."""
    try:
        from openai import Timeout as OpenAITimeout
    except ImportError:
        OpenAITimeout = None
    config = provider_timeout_config()
    kwargs = {
        "connect": config["ONTOLOGY_LLM_CONNECT_TIMEOUT"],
        "read": config["ONTOLOGY_LLM_READ_TIMEOUT"],
        "write": config["ONTOLOGY_LLM_WRITE_TIMEOUT"],
        "pool": config["ONTOLOGY_LLM_POOL_TIMEOUT"],
    }
    if OpenAITimeout is not None:
        return OpenAITimeout(**kwargs)
    try:
        import httpx
        return httpx.Timeout(**kwargs)
    except ImportError:
        return None


def _client(provider: str, api_key: str | None = None):
    """Build an OpenAI SDK client pointed at the provider's endpoint."""
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError(
            "The 'openai' package is required for non-Anthropic models. "
            "Install it with:  pip install openai"
        ) from e

    key = api_key or get_api_key_for(provider)
    if not key:
        envs = ", ".join(PROVIDERS.get(provider, {}).get("env", [])) or "the provider API key"
        raise RuntimeError(f"No API key for provider '{provider}'. Set {envs}.")

    return OpenAI(api_key=key, base_url=get_provider_base_url(provider),
                  timeout=_provider_timeout())


def _qwen_fallback_models(model: str) -> list[str]:
    """Return same-capability Qwen models, preserving the configured .env order."""
    vision = [x.strip() for x in os.environ.get("QWEN_VISION_MODELS", "").split(",") if x.strip()]
    text = [x.strip() for x in os.environ.get("QWEN_TEXT_MODELS", "").split(",") if x.strip()]
    category = vision if model in vision or model.startswith("qwen3-vl") or model.startswith("qwen-vl") else text
    if not category:
        category = ["qwen3.6-flash", "qwen-plus", "qwen-turbo"] if not vision else vision
    return [m for m in category if m and m != model][:8]


def _is_quota_error(error: Exception) -> bool:
    msg = str(error).lower()
    markers = ("quota", "rate limit", "ratelimit", "too many requests", "insufficient_quota",
               "billing", "余额", "限额", "配额", "429")
    return any(x in msg for x in markers)


def _is_provider_timeout(error: Exception) -> bool:
    """Whether a provider failure is a transport/read timeout, not a 400/429.

    The SDK raises ``APITimeoutError`` when a streaming read stays silent
    beyond the configured read timeout.  These failures must never be treated
    as the same error class as modeling total-time budget pauses: the run is
    paused at the current checkpoint with the partial turn discarded, and the
    user can continue from there.
    """
    if type(error).__name__ in ("APITimeoutError", "APIConnectionError", "ReadTimeout", "ConnectTimeout"):
        return True
    text = str(error or "").lower()
    return any(marker in text for marker in (
        "timed out", "read timeout", "connect timeout", "write timeout",
        "apiconnectionerror", "apitimeouterror",
    ))


def _is_recoverable_provider_error(error: Exception) -> bool:
    """Whether a provider 400 is recoverable by resending the same turn.

    DeepSeek thinking-mode gateways require ``reasoning_content`` to be passed
    back verbatim for every reasoning turn; when a tool turn is retried without
    it they answer with a 400 that only means the conversation history is not
    self-consistent.  The request itself is safe to resend, optionally with
    reasoning stripped, so the task can continue instead of failing.

    A reasoning-only assistant (a stream interrupted right after the thinking
    phase) also produces a 400 ("content or tool_calls must be set").  The
    outgoing history is sanitized before the retry drops that invalid turn, so
    the same request is safe to resend once.
    """
    text = str(error or "").lower()
    markers = (
        "insufficient tool messages following tool_calls message",
        "insufficient tool messages",
        "tool_call_id",
        "tool messages",
        "role tool",
        "must be passed back",
        "content or tool_calls must be set",
        "invalid assistant message",
    )
    return any(marker in text for marker in markers)


# ---------------------------------------------------------------------------
# Tool-call chain sanitization
#
# Every outgoing request must satisfy the OpenAI protocol invariant: each
# assistant ``tool_calls`` id is followed by exactly one ``role=tool`` result,
# with no orphan results and no duplicate ids.  Broken chains arise when a run
# crashes between the assistant turn and its tool results, when compaction or
# session restore trims a pair, or when a provider rejects the previous turn.
# ``sanitize_messages`` repairs the chain before conversion; missing results
# are recovered from the persisted tool-result store and, when no real result
# exists, the conversation is truncated to the last consistent checkpoint so
# the current LLM step is re-issued instead of failing the whole run.
# ---------------------------------------------------------------------------

_tool_result_store: dict[str, dict[str, Any]] = {}
_tool_result_store_lock = threading.Lock()
_TOOL_RESULT_STORE_CAP = 2000


def remember_tool_result(tool_call_id: str, content: Any, *,
                         is_error: bool = False) -> None:
    """Register one real tool execution result for later recovery."""
    tid = str(tool_call_id or "")
    if not tid:
        return
    with _tool_result_store_lock:
        _tool_result_store[tid] = {"content": content, "is_error": bool(is_error)}
        if len(_tool_result_store) > _TOOL_RESULT_STORE_CAP:
            # Bound process memory; tool ids are unique per turn so evicting
            # the oldest completed turns is safe.
            for stale in list(_tool_result_store)[:len(_tool_result_store) - _TOOL_RESULT_STORE_CAP]:
                _tool_result_store.pop(stale, None)


def clear_tool_results() -> None:
    """Drop every remembered tool result (test isolation / run teardown)."""
    with _tool_result_store_lock:
        _tool_result_store.clear()


def seed_tool_results(records: Iterable[Mapping[str, Any]]) -> None:
    """Register persisted ``tool_result`` events (event journal / task log)."""
    for record in records or ():
        if not isinstance(record, Mapping):
            continue
        tid = str(record.get("tool_use_id") or record.get("tool_call_id") or "")
        if tid:
            remember_tool_result(tid, record.get("content", ""),
                                 is_error=bool(record.get("is_error")))


def seed_tool_results_from_messages(messages: Iterable[Mapping[str, Any]]) -> None:
    """Scan a restored transcript and register every real tool result.

    This is the session-restore counterpart of ``_execute_pending_tools``:
    after a process restart the in-memory store is empty, so the sanitizer
    must be able to recover tool results from the persisted transcript itself.
    """
    for message in messages or ():
        if not isinstance(message, Mapping):
            continue
        if message.get("role") == "tool":
            tid = str(message.get("tool_call_id") or message.get("tool_use_id") or "")
            if tid:
                remember_tool_result(tid, message.get("content", ""),
                                     is_error=bool(message.get("is_error")))
            continue
        content = message.get("content")
        if message.get("role") == "user" and isinstance(content, list):
            for block in content:
                if (isinstance(block, Mapping)
                        and block.get("type") == "tool_result"
                        and (block.get("tool_use_id") or block.get("tool_call_id"))):
                    remember_tool_result(
                        str(block.get("tool_use_id") or block.get("tool_call_id")),
                        block.get("content", ""),
                        is_error=bool(block.get("is_error")))


def _lookup_persisted_tool_result(tool_call_id: str) -> dict[str, Any] | None:
    with _tool_result_store_lock:
        return _tool_result_store.get(str(tool_call_id or ""))


def _is_tool_use_block(block: Any) -> bool:
    return (isinstance(block, dict)
            and block.get("type") in ("tool_use", "tool_call"))


def _is_tool_result_block(block: Any) -> bool:
    return isinstance(block, dict) and block.get("type") == "tool_result"


def _assistant_has_sendable_payload(message: Mapping[str, Any]) -> bool:
    """Whether an assistant message can be sent to an OpenAI-compatible API.

    Assistant messages must carry non-empty text or tool_calls.  A turn that
    only contains thinking/reasoning (for example a stream interrupted right
    after the reasoning phase) cannot be represented in the protocol and must
    be dropped from the outgoing history; the persisted thinking stays as a
    UI audit event only.
    """
    content = message.get("content")
    if isinstance(content, str):
        return bool(str(content).strip())
    if not isinstance(content, list):
        return False
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") in ("tool_use", "tool_call"):
            return True
        if block.get("type") == "text" and str(block.get("text") or "").strip():
            return True
    return False


def _orphan_tool_result_text(tool_id: str, content: Any) -> str:
    """Keep malformed historical tool output without sending it as ``role=tool``.

    OpenAI-compatible APIs reject a tool message unless it immediately follows
    an assistant message containing the matching ``tool_calls`` entry.  Older
    sessions can contain a result whose assistant call was compacted away or
    whose call id was not persisted.  Representing that output as a normal user
    message preserves the context while keeping the request valid.
    """
    suffix = f"，{tool_id}" if tool_id else ""
    label = f"工具结果（历史记录{suffix}）"
    return f"{label}：\n{_tool_result_text(content)}"


def _tool_result_text(content: Any) -> str:
    """Convert an Anthropic tool result to the string OpenAI expects."""
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or json.dumps(item, ensure_ascii=False)))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content or "")


def sanitize_messages(messages: list[dict[str, Any]], *,
                      restore: Callable[[str], dict[str, Any] | None] | None = None,
                      truncate: bool = True) -> list[dict[str, Any]]:
    """Repair an internal (Anthropic-style) message chain in place.

    Guaranteed invariant on the returned list: every assistant ``tool_use`` id
    has exactly one matching ``tool_result`` in the following user message; no
    orphan tool result survives; no duplicate result survives.  When a tool
    result is missing it is first recovered from ``restore`` (defaults to the
    persisted tool-result store, which producers populate from real executions
    and servers seed from event journals).  A missing result with no real
    source is never fabricated: the assistant message that requested it and
    everything after it is truncated, so the current LLM step re-issues from
    the last consistent checkpoint instead of failing the run.
    """
    if not isinstance(messages, list):
        return messages
    resolver = restore if callable(restore) else _lookup_persisted_tool_result

    result: list[dict[str, Any]] = []
    # (index in result, original tool ids, remaining tool ids) for every
    # assistant tool_use turn.
    pending_turns: list[tuple[int, list[str], list[str]]] = []
    active_window: dict[str, bool] = {}

    def consume(tool_id: str) -> None:
        for _, _, remaining in reversed(pending_turns):
            if tool_id in remaining:
                remaining.remove(tool_id)
                return

    for message in messages:
        if not isinstance(message, dict):
            result.append(message)
            continue
        role = message.get("role")
        content = message.get("content")

        if role == "assistant" and isinstance(content, list):
            rebuilt: list[Any] = []
            tool_ids: list[str] = []
            for block in content:
                if _is_tool_use_block(block):
                    raw_id = str(block.get("id") or "")
                    if not raw_id:
                        raw_id = f"call_{len(tool_ids)}"
                    normalized = dict(block)
                    normalized["id"] = raw_id
                    rebuilt.append(normalized)
                    tool_ids.append(raw_id)
                else:
                    rebuilt.append(block)
            if tool_ids:
                pending_turns.append((len(result), list(tool_ids), list(tool_ids)))
                active_window = {tid: True for tid in tool_ids}
                result.append({**message, "content": rebuilt})
                continue
            active_window = {}
            if not _assistant_has_sendable_payload({"role": role, "content": rebuilt}):
                # Reasoning-only / empty assistant turns cannot be represented
                # in the OpenAI protocol.  Drop them so the next user message
                # remains sendable; the persisted thinking is kept only as an
                # audit event, never as provider history.
                continue
            result.append(message)
            continue

        if role == "user" and isinstance(content, list):
            results = [block for block in content if _is_tool_result_block(block)]
            if results:
                seen: set[str] = set()
                kept: list[dict[str, Any]] = []
                orphan_blocks: list[dict[str, Any]] = []
                other = [block for block in content if not _is_tool_result_block(block)]
                for block in results:
                    tid = str(block.get("tool_use_id") or block.get("tool_call_id") or "")
                    if not tid and len(active_window) == 1:
                        tid = next(iter(active_window))
                    if tid in active_window and tid not in seen:
                        seen.add(tid)
                        normalized = dict(block)
                        normalized["tool_use_id"] = tid
                        kept.append(normalized)
                        consume(tid)
                        active_window.pop(tid, None)
                    elif tid in seen:
                        # duplicate result for an already-consumed call: the
                        # duplicate is dropped entirely, only one result stays.
                        continue
                    else:
                        # orphan (no pending assistant call): preserved so the
                        # converter can keep the content as plain user text;
                        # it will never be emitted as a role=tool message.
                        orphan_blocks.append(block)
                if kept or other or orphan_blocks:
                    result.append({**message, "content": other + kept + orphan_blocks})
                if other:
                    # Plain user content closes the pending tool window.
                    active_window = {}
                continue
            active_window = {}
            result.append(message)
            continue

        active_window = {}
        if role == "assistant" and not _assistant_has_sendable_payload(message):
            continue
        result.append(message)

    if truncate:
        # Process newest unpaired turn first so inserts for later turns never
        # shift the assistant indices of earlier turns.  Inserting a repair
        # after the turn's existing result messages keeps the original order.
        for index, original_ids, remaining in reversed(pending_turns):
            if not remaining:
                continue
            resolved = {tid: resolver(tid) for tid in remaining}
            resolved = {tid: value for tid, value in resolved.items()
                        if isinstance(value, Mapping)}
            if len(resolved) == len(remaining):
                pos = index + 1
                while pos < len(result):
                    msg = result[pos]
                    content = msg.get("content")
                    if (msg.get("role") == "user" and isinstance(content, list)
                            and any(
                                _is_tool_result_block(block)
                                and str(block.get("tool_use_id") or block.get("tool_call_id") or "")
                                in original_ids
                                for block in content)):
                        pos += 1
                    else:
                        break
                repair = [{"type": "tool_result", "tool_use_id": tid,
                           "content": resolved[tid].get("content", ""),
                           "is_error": bool(resolved[tid].get("is_error"))}
                          for tid in remaining]
                result.insert(pos, {"role": "user", "content": repair})
                continue
            # No real result exists for at least one id: never fabricate a
            # success.  Truncate to the last consistent checkpoint so the
            # current step re-issues without the unpaired tool call.
            del result[index:]
            break

    messages[:] = result
    return result


# ---------------------------------------------------------------------------
# Format conversion: Anthropic blocks <-> OpenAI messages
# ---------------------------------------------------------------------------


def to_openai_messages(system_prompt: str, messages: list[dict[str, Any]],
                       strip_reasoning: bool = False) -> list[dict[str, Any]]:
    """Convert internal Anthropic-style history to a valid OpenAI message list.

    In particular, never emit an orphan ``role=tool`` message.  A compacted or
    partially persisted session may contain a tool result without its preceding
    assistant tool call; forwarding that record makes DeepSeek/LiteLLM return a
    400 before it can answer the next user message.

    The history is sanitized first: every assistant ``tool_use`` id is paired
    with exactly one ``tool_result`` (recovered from the persisted result store
    or truncated to the last consistent checkpoint), orphans and duplicates are
    removed, and missing tool ids are filled deterministically.  This keeps the
    converted OpenAI message list valid for every provider.

    ``strip_reasoning`` drops every assistant reasoning block (and the
    provider-native ``reasoning_content`` field) from the outgoing history.
    DeepSeek thinking-mode gateways return a recoverable 400 when a reasoning
    turn is not passed back verbatim; resending the same conversation without
    reasoning keeps the request self-consistent so execution can continue.
    """
    sanitize_messages(messages)
    out: list[dict[str, Any]] = []
    if system_prompt:
        out.append({"role": "system", "content": system_prompt})

    # Only tool results belonging to the immediately preceding assistant tool
    # call may be emitted with role=tool.  This also handles duplicate or stale
    # ids in old transcripts without weakening the provider contract.
    pending_tool_ids: set[str] = set()

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        top_level_reasoning = "" if strip_reasoning else str(
            msg.get("reasoning_content") or msg.get("reasoning") or "")

        if isinstance(content, str):
            if role == "tool":
                tool_id = str(msg.get("tool_call_id") or msg.get("tool_use_id") or "")
                if not tool_id and len(pending_tool_ids) == 1:
                    tool_id = next(iter(pending_tool_ids))
                if tool_id and tool_id in pending_tool_ids:
                    out.append({"role": "tool", "tool_call_id": tool_id,
                                "content": content})
                    pending_tool_ids.discard(tool_id)
                else:
                    out.append({"role": "user", "content":
                                _orphan_tool_result_text(tool_id, content)})
                continue
            if role == "assistant" and not content.strip():
                # Empty assistant text is rejected by OpenAI-compatible APIs
                # when no tool_calls accompany it; drop the turn instead.
                pending_tool_ids.clear()
                continue
            converted: dict[str, Any] = {
                "role": role if role in ("user", "assistant", "system") else "user",
                "content": content,
            }
            if role == "assistant" and top_level_reasoning:
                converted["reasoning_content"] = top_level_reasoning
            out.append(converted)
            pending_tool_ids.clear()
            continue
        if not isinstance(content, list):
            continue

        if role == "assistant":
            text_parts = []
            block_reasoning_parts = []
            tool_calls = []
            for blk in content:
                if not isinstance(blk, dict):
                    continue
                if blk.get("type") == "text":
                    text_parts.append(str(blk.get("text") or ""))
                elif blk.get("type") in ("thinking", "reasoning"):
                    if not strip_reasoning:
                        block_reasoning_parts.append(str(
                            blk.get("thinking") or blk.get("reasoning_content") or blk.get("text") or ""
                        ))
                elif blk.get("type") in ("tool_use", "tool_call"):
                    tool_id = str(blk.get("id") or "")
                    # A stable id is required by the OpenAI protocol.  The
                    # streaming adapter normally supplies this fallback, but
                    # it also protects sessions written by older versions.
                    if not tool_id:
                        tool_id = f"call_{len(tool_calls)}"
                    tool_calls.append({
                        "id": tool_id,
                        "type": "function",
                        "function": {
                            "name": str(blk.get("name") or ""),
                            "arguments": json.dumps(blk.get("input") or blk.get("arguments") or {},
                                                      ensure_ascii=False),
                        },
                    })
            # A restored session may contain both the normalized top-level
            # field and the original thinking block.  Prefer the block in
            # that case so reasoning is not sent twice to the provider.
            reasoning_parts = block_reasoning_parts or ([top_level_reasoning] if top_level_reasoning else [])
            if tool_calls:
                assistant_message: dict[str, Any] = {
                    "role": "assistant", "content": "".join(text_parts) or None,
                    "tool_calls": tool_calls,
                }
                if reasoning_parts:
                    assistant_message["reasoning_content"] = "".join(reasoning_parts)
                out.append(assistant_message)
                pending_tool_ids = {str(call["id"]) for call in tool_calls}
            elif text_parts:
                assistant_message = {"role": "assistant", "content": "".join(text_parts)}
                if reasoning_parts:
                    assistant_message["reasoning_content"] = "".join(reasoning_parts)
                out.append(assistant_message)
                pending_tool_ids.clear()
            elif reasoning_parts:
                # Reasoning-only assistant: the OpenAI protocol requires
                # content or tool_calls, so this turn cannot be forwarded.
                # Drop it; the next user message remains sendable, and any
                # follow-up "reasoning_content must be passed back" 400 is
                # handled by the strip-reasoning retry.
                pending_tool_ids.clear()
            else:
                pending_tool_ids.clear()
            continue

        # User messages can contain text, images, and/or Anthropic tool
        # results.  Keep valid results first, then preserve any text/image
        # content as a normal user message.
        tool_results = [
            b for b in content
            if isinstance(b, dict) and b.get("type") == "tool_result"
        ]
        text_or_image_blocks = [
            b for b in content
            if isinstance(b, dict) and b.get("type") != "tool_result"
        ]
        orphan_results: list[str] = []
        for blk in tool_results:
            tool_id = str(blk.get("tool_use_id") or blk.get("tool_call_id") or "")
            if not tool_id and len(pending_tool_ids) == 1:
                tool_id = next(iter(pending_tool_ids))
            result = _tool_result_text(blk.get("content", ""))
            if tool_id and tool_id in pending_tool_ids:
                out.append({"role": "tool", "tool_call_id": tool_id,
                            "content": result})
                pending_tool_ids.discard(tool_id)
            else:
                orphan_results.append(_orphan_tool_result_text(tool_id, result))

        if orphan_results:
            out.append({"role": "user", "content": "\n\n".join(orphan_results)})

        if text_or_image_blocks:
            # Preserve Anthropic-style base64 images for Qwen-VL and other
            # OpenAI-compatible multimodal endpoints.
            parts = []
            for blk in text_or_image_blocks:
                if not isinstance(blk, dict):
                    continue
                if blk.get("type") == "text":
                    parts.append({"type": "text", "text": str(blk.get("text") or "")})
                elif blk.get("type") == "image":
                    source = blk.get("source") or {}
                    if source.get("type") == "base64" and source.get("data"):
                        media = source.get("media_type", "image/png")
                        parts.append({"type": "image_url", "image_url": {
                            "url": f"data:{media};base64,{source['data']}"
                        }})
                    elif blk.get("image_url"):
                        parts.append({"type": "image_url", "image_url": blk["image_url"]})
            if parts:
                out.append({"role": "user", "content": parts})

        # A plain user message after a tool call invalidates that pending call
        # sequence; any stale result later in the transcript is orphaned.
        if text_or_image_blocks or orphan_results:
            pending_tool_ids.clear()

    return out


def to_openai_tools(tools: Optional[list[dict[str, Any]]]) -> Optional[list[dict[str, Any]]]:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
            },
        }
        for t in tools
    ]


def _usage_dict(u) -> dict[str, int]:
    return {
        "input_tokens": getattr(u, "prompt_tokens", 0) or 0,
        "output_tokens": getattr(u, "completion_tokens", 0) or 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------

def stream(provider: str, model: str, messages: list[dict[str, Any]], system_prompt: str,
           tools: Optional[list[dict[str, Any]]], max_tokens: Optional[int],
           temperature: Optional[float], _allow_fallback: bool = True,
           api_key: str | None = None,
           strip_reasoning: bool = False) -> Generator[dict[str, Any], None, None]:
    """Yield the same normalized events as api.stream_message, for OpenAI-style APIs."""
    try:
        client = _client(provider, api_key)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": to_openai_messages(system_prompt, messages,
                                           strip_reasoning=strip_reasoning),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        oai_tools = to_openai_tools(tools)
        if oai_tools:
            kwargs["tools"] = oai_tools
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            kwargs["temperature"] = temperature
        if provider == "qwen":
            # DashScope's OpenAI-compatible API accepts this provider-specific
            # switch through extra_body.  False is explicit so a thinking model
            # does not unexpectedly consume the user's quota.
            thinking = os.environ.get("QWEN_ENABLE_THINKING", "").strip().lower()
            if thinking:
                kwargs["extra_body"] = {"enable_thinking": thinking in ("1", "true", "yes", "on")}

        tool_acc: dict[int, dict[str, str]] = {}
        order: list[int] = []
        started: set[int] = set()
        usage = {"input_tokens": 0, "output_tokens": 0,
                 "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        finish = None

        for chunk in client.chat.completions.create(**kwargs):
            if getattr(chunk, "usage", None):
                usage.update(_usage_dict(chunk.usage))
            if not getattr(chunk, "choices", None):
                continue
            choice = chunk.choices[0]
            delta = choice.delta

            if getattr(delta, "content", None):
                yield {"type": "text_delta", "text": delta.content}

            # DeepSeek-compatible gateways require the model's reasoning
            # content to be passed back verbatim when the response also
            # contains tool calls.  Normalize both common SDK field names so
            # the web/REPL history can persist it for the next turn.
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning is None:
                reasoning = getattr(delta, "reasoning", None)
            if reasoning:
                yield {"type": "thinking_delta", "text": reasoning}

            for tc in (getattr(delta, "tool_calls", None) or []):
                idx = tc.index if tc.index is not None else 0
                if idx not in tool_acc:
                    tool_acc[idx] = {"id": tc.id or f"call_{idx}", "name": "", "args": ""}
                    order.append(idx)
                if tc.id:
                    tool_acc[idx]["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn:
                    if getattr(fn, "name", None):
                        tool_acc[idx]["name"] = fn.name
                        if idx not in started:
                            started.add(idx)
                            yield {"type": "tool_use_start",
                                   "id": tool_acc[idx]["id"], "name": fn.name}
                    if getattr(fn, "arguments", None):
                        tool_acc[idx]["args"] += fn.arguments

            if getattr(choice, "finish_reason", None):
                finish = choice.finish_reason

        for idx in order:
            t = tool_acc[idx]
            try:
                inp = json.loads(t["args"]) if t["args"] else {}
            except json.JSONDecodeError:
                inp = {}
            yield {"type": "tool_use_end", "id": t["id"], "name": t["name"], "input": inp}

        stop_reason = "tool_use" if (finish == "tool_calls" or order) else "end_turn"
        yield {"type": "message_end", "stop_reason": stop_reason, "usage": usage}

    except Exception as e:
        # A provider transport/read timeout pauses the turn at the current
        # checkpoint instead of retrying the same request blindly.  The
        # partial turn is never persisted as provider history (the caller
        # drops reasoning-only assistants), so the user can continue from
        # the last durable state.
        if _is_provider_timeout(e):
            yield {
                "type": "error",
                "error": "模型流式响应长时间无数据，本轮已暂停，可继续执行",
                "code": "LLM_STREAM_TIMEOUT",
                "recoverable": True,
                "detail": str(e)[:400],
            }
            return
        # Tool-chain / thinking-mode 400s are recoverable.  Sanitize the
        # history again (a missing tool result may now be restorable from the
        # persisted store, or the chain is truncated to the last consistent
        # checkpoint), then retry the same request once as-is, and once with
        # reasoning stripped from the outgoing history.  Only the current LLM
        # step is retried: checkpoints, stages and the run state are untouched,
        # so a successful retry continues instead of restarting the run.
        if _allow_fallback and _is_recoverable_provider_error(e):
            sanitize_messages(messages)
            for attempt, retry_strip in ((1, False), (2, True)):
                retry_events = list(stream(provider, model, messages, system_prompt,
                                           tools, max_tokens, temperature,
                                           _allow_fallback=False, api_key=api_key,
                                           strip_reasoning=retry_strip))
                failed = next((x for x in retry_events if x.get("type") == "error"), None)
                if failed and not any(x.get("type") == "message_end" for x in retry_events):
                    continue
                yield {
                    "type": "provider_retry",
                    "attempt": attempt,
                    "text": ("模型网关返回可恢复错误，已自动重试并继续执行"
                             if not retry_strip else
                             "模型网关消息链/思考模式校验失败，已修复消息链并清理 reasoning 后自动重试并继续执行"),
                }
                yield from retry_events
                return
        # Qwen 配额/限流错误时，在同一能力类别中自动换模型。
        # fallback 调用只收集单次结果用于判断失败，成功后再按统一事件格式输出。
        if _allow_fallback and provider == "qwen" and _is_quota_error(e):
            for fallback in _qwen_fallback_models(model):
                events = list(stream(provider, fallback, messages, system_prompt, tools,
                                     max_tokens, temperature, _allow_fallback=False,
                                     api_key=api_key, strip_reasoning=strip_reasoning))
                failed = next((x for x in events if x.get("type") == "error"), None)
                if failed and not any(x.get("type") == "message_end" for x in events):
                    continue
                yield {"type": "model_switch", "from": model, "to": fallback,
                       "reason": "当前模型额度不足,已自动切换同类模型"}
                yield from events
                return
        yield {"type": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Non-streaming (used for compaction summaries and sub-agents)
# ---------------------------------------------------------------------------

def send(provider: str, model: str, messages: list[dict[str, Any]], system_prompt: str,
         tools: Optional[list[dict[str, Any]]], max_tokens: Optional[int],
         temperature: Optional[float], api_key: str | None = None) -> dict[str, Any]:
    """Return {"content": [normalized blocks], "stop_reason", "usage"}."""
    try:
        resp = _send_once(provider, model, messages, system_prompt, tools,
                          max_tokens, temperature, api_key)
    except Exception as e:
        if _is_provider_timeout(e):
            raise RuntimeError(
                "LLM_STREAM_TIMEOUT: 模型响应超时，本轮已暂停，可继续执行"
            ) from e
        if not _is_recoverable_provider_error(e):
            raise
        # Sanitize (recover/truncate the tool chain) and retry only this call.
        sanitize_messages(messages)
        resp = _send_once(provider, model, messages, system_prompt, tools,
                          max_tokens, temperature, api_key)
    msg = resp.choices[0].message

    content: list[dict[str, Any]] = []
    reasoning = getattr(msg, "reasoning_content", None)
    if reasoning is None:
        reasoning = getattr(msg, "reasoning", None)
    if reasoning:
        content.append({"type": "thinking", "thinking": reasoning})
    if getattr(msg, "content", None):
        content.append({"type": "text", "text": msg.content})
    for tc in (getattr(msg, "tool_calls", None) or []):
        try:
            inp = json.loads(tc.function.arguments) if tc.function.arguments else {}
        except json.JSONDecodeError:
            inp = {}
        content.append({"type": "tool_use", "id": tc.id,
                        "name": tc.function.name, "input": inp})

    stop_reason = "tool_use" if getattr(msg, "tool_calls", None) else "end_turn"
    return {
        "content": content,
        "stop_reason": stop_reason,
        "usage": _usage_dict(resp.usage) if getattr(resp, "usage", None) else
                 {"input_tokens": 0, "output_tokens": 0,
                  "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
    }


def _send_once(provider: str, model: str, messages: list[dict[str, Any]],
               system_prompt: str, tools: Optional[list[dict[str, Any]]],
               max_tokens: Optional[int], temperature: Optional[float],
               api_key: str | None = None) -> Any:
    """Perform one non-streaming OpenAI-compatible completion request."""
    client = _client(provider, api_key)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": to_openai_messages(system_prompt, messages),
    }
    oai_tools = to_openai_tools(tools)
    if oai_tools:
        kwargs["tools"] = oai_tools
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if temperature is not None:
        kwargs["temperature"] = temperature
    if provider == "qwen":
        thinking = os.environ.get("QWEN_ENABLE_THINKING", "").strip().lower()
        if thinking:
            kwargs["extra_body"] = {"enable_thinking": thinking in ("1", "true", "yes", "on")}
    return client.chat.completions.create(**kwargs)
