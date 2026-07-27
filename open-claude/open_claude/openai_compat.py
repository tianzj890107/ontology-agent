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
from typing import Any, Generator, Optional

from .config import PROVIDERS, get_api_key_for, get_provider_base_url


def _client(provider: str):
    """Build an OpenAI SDK client pointed at the provider's endpoint."""
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError(
            "The 'openai' package is required for non-Anthropic models. "
            "Install it with:  pip install openai"
        ) from e

    key = get_api_key_for(provider)
    if not key:
        envs = ", ".join(PROVIDERS.get(provider, {}).get("env", [])) or "the provider API key"
        raise RuntimeError(f"No API key for provider '{provider}'. Set {envs}.")

    return OpenAI(api_key=key, base_url=get_provider_base_url(provider))


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


# ---------------------------------------------------------------------------
# Format conversion: Anthropic blocks <-> OpenAI messages
# ---------------------------------------------------------------------------

def to_openai_messages(system_prompt: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if system_prompt:
        out.append({"role": "system", "content": system_prompt})

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            continue

        if role == "assistant":
            text_parts = []
            tool_calls = []
            for blk in content:
                if not isinstance(blk, dict):
                    continue
                if blk.get("type") == "text":
                    text_parts.append(blk.get("text", ""))
                elif blk.get("type") == "tool_use":
                    tool_calls.append({
                        "id": blk.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": blk.get("name", ""),
                            "arguments": json.dumps(blk.get("input", {}), ensure_ascii=False),
                        },
                    })
            m: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts) or None}
            if tool_calls:
                m["tool_calls"] = tool_calls
            out.append(m)
        else:
            # user message: either tool_result blocks or text blocks
            tool_results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
            if tool_results:
                for blk in tool_results:
                    c = blk.get("content", "")
                    if isinstance(c, list):
                        c = "\n".join(
                            x.get("text") if isinstance(x, dict) else str(x) for x in c
                        )
                    out.append({
                        "role": "tool",
                        "tool_call_id": blk.get("tool_use_id", ""),
                        "content": str(c),
                    })
            else:
                # Preserve Anthropic-style base64 images for Qwen-VL and other
                # OpenAI-compatible multimodal endpoints.
                parts = []
                for blk in content:
                    if not isinstance(blk, dict):
                        continue
                    if blk.get("type") == "text":
                        parts.append({"type": "text", "text": blk.get("text", "")})
                    elif blk.get("type") == "image":
                        source = blk.get("source") or {}
                        if source.get("type") == "base64" and source.get("data"):
                            media = source.get("media_type", "image/png")
                            parts.append({"type": "image_url", "image_url": {
                                "url": f"data:{media};base64,{source['data']}"
                            }})
                        elif blk.get("image_url"):
                            parts.append({"type": "image_url", "image_url": blk["image_url"]})
                out.append({"role": "user", "content": parts or ""})

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
           temperature: Optional[float], _allow_fallback: bool = True) -> Generator[dict[str, Any], None, None]:
    """Yield the same normalized events as api.stream_message, for OpenAI-style APIs."""
    try:
        client = _client(provider)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": to_openai_messages(system_prompt, messages),
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
        # Qwen 配额/限流错误时，在同一能力类别中自动换模型。
        # fallback 调用只收集单次结果用于判断失败，成功后再按统一事件格式输出。
        if _allow_fallback and provider == "qwen" and _is_quota_error(e):
            for fallback in _qwen_fallback_models(model):
                events = list(stream(provider, fallback, messages, system_prompt, tools,
                                     max_tokens, temperature, _allow_fallback=False))
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
         temperature: Optional[float]) -> dict[str, Any]:
    """Return {"content": [normalized blocks], "stop_reason", "usage"}."""
    client = _client(provider)
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

    resp = client.chat.completions.create(**kwargs)
    msg = resp.choices[0].message

    content: list[dict[str, Any]] = []
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
