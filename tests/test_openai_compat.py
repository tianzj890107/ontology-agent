import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

from open_claude.openai_compat import (
    clear_tool_results,
    sanitize_messages,
    seed_tool_results_from_messages,
    to_openai_messages,
)
from open_claude import compact


def _tool_chain(messages):
    """Extract (assistant tool_use ids, tool_result ids) from internal format."""
    calls, results = [], []
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if message.get("role") == "assistant" and isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") in ("tool_use", "tool_call"):
                    calls.append(str(block.get("id") or ""))
        elif message.get("role") == "user" and isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    results.append(str(block.get("tool_use_id") or block.get("tool_call_id") or ""))
        elif message.get("role") == "tool":
            results.append(str(message.get("tool_call_id") or message.get("tool_use_id") or ""))
    return calls, results


def _assert_paired(testcase, messages):
    """Every assistant tool_use id must have exactly one matching result."""
    calls, results = _tool_chain(messages)
    testcase.assertEqual(sorted(calls), sorted(results),
                         "every assistant tool_use must be paired with one result")
    testcase.assertEqual(len(calls), len(set(calls)), "no duplicate tool_use id")
    testcase.assertEqual(len(results), len(set(results)), "no duplicate tool result id")


class OpenAIMessageContractTests(unittest.TestCase):
    def test_strip_reasoning_removes_thinking_but_keeps_tools_and_text(self):
        messages = to_openai_messages("", [
            {"role": "user", "content": "继续"},
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "内部推理"},
                {"type": "text", "text": "已分析"},
                {"type": "tool_use", "id": "call-1", "name": "Read", "input": {}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "content": "结果"},
            ]},
        ], strip_reasoning=True)

        assistant = messages[1]
        self.assertEqual(assistant["role"], "assistant")
        self.assertEqual(assistant["content"], "已分析")
        self.assertNotIn("reasoning_content", assistant)
        self.assertEqual(assistant["tool_calls"][0]["id"], "call-1")
        self.assertEqual(messages[2]["role"], "tool")

    def test_strip_reasoning_drops_reasoning_only_assistant_message(self):
        messages = to_openai_messages("", [
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "只有推理"},
            ]},
            {"role": "user", "content": "继续"},
        ], strip_reasoning=True)

        self.assertEqual([m["role"] for m in messages], ["user"])

    def test_recoverable_reasoning_error_retries_with_stripped_reasoning(self):
        from open_claude import openai_compat

        error_text = (
            "litellm.BadRequestError: DeepseekException - "
            '{"error":{"message":"The `reasoning_content` in the thinking mode '
            'must be passed back to the API.","type":"invalid_request_error",'
            '"param":null,"code":"invalid_request_error"}} '
            "Received Model Group=direct-deepseek-v4-flash"
        )
        calls = []

        class _FakeDelta:
            content = "重试成功"
            reasoning_content = None
            tool_calls = None

        class _FakeChoice:
            delta = _FakeDelta()
            finish_reason = "stop"

        class _FakeChunk:
            choices = [_FakeChoice()]
            usage = None

        def create(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise RuntimeError(error_text)
            if len(calls) == 2:
                raise RuntimeError(error_text)
            return [_FakeChunk()]

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        messages = [
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "推理"},
                {"type": "tool_use", "id": "call-1", "name": "Read", "input": {}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "content": "结果"},
            ]},
        ]

        with patch.object(openai_compat, "_client", return_value=fake_client):
            events = list(openai_compat.stream(
                "deepseek", "deepseek-v4-flash", messages, "", None, None, None,
                api_key="k"))

        self.assertFalse([e for e in events if e.get("type") == "error"])
        self.assertTrue(any(e.get("type") == "provider_retry" for e in events))
        retry = next(e for e in events if e.get("type") == "provider_retry")
        self.assertEqual(retry["attempt"], 2)
        self.assertTrue(any(e.get("type") == "text_delta" for e in events))
        self.assertTrue(any(e.get("type") == "message_end" for e in events))
        # The successful retry request must not carry any reasoning back.
        self.assertEqual(len(calls), 3)
        for message in calls[-1]["messages"]:
            self.assertNotIn("reasoning_content", message)

    def test_tool_result_follows_matching_assistant_tool_call(self):
        messages = to_openai_messages("system", [
            {"role": "user", "content": "读取文件"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "call-1", "name": "Read", "input": {"file_path": "a.txt"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "content": "内容"},
            ]},
        ])

        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[3]["role"], "tool")
        self.assertEqual(messages[3]["tool_call_id"], "call-1")
        self.assertEqual(messages[2]["tool_calls"][0]["id"], "call-1")

    def test_reasoning_content_is_preserved_for_tool_turns(self):
        messages = to_openai_messages("", [
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "先判断文件范围"},
                {"type": "tool_use", "id": "call-1", "name": "Read", "input": {}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "content": "结果"},
            ]},
        ])

        self.assertEqual(messages[0]["reasoning_content"], "先判断文件范围")
        self.assertEqual(messages[1]["role"], "tool")

    def test_orphan_tool_result_is_not_sent_as_tool_message(self):
        messages = to_openai_messages("", [
            {"role": "user", "content": "继续"},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "stale", "content": "旧结果"},
            ]},
        ])

        self.assertFalse(any(message.get("role") == "tool" for message in messages))
        self.assertIn("旧结果", messages[-1]["content"])

    def test_missing_legacy_tool_ids_are_repaired_when_unambiguous(self):
        messages = to_openai_messages("", [
            {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Read", "input": {}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "content": "结果"},
            ]},
        ])

        self.assertEqual(messages[1]["role"], "tool")
        self.assertEqual(messages[1]["tool_call_id"], messages[0]["tool_calls"][0]["id"])

    def test_compaction_keeps_tool_call_and_result_together(self):
        messages = [
            {"role": "user", "content": "u0"},
            {"role": "assistant", "content": "a0"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "call-2", "name": "Read", "input": {}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call-2", "content": "r2"},
            ]},
            {"role": "assistant", "content": "a3"},
            {"role": "user", "content": "u3"},
            {"role": "assistant", "content": "a4"},
            {"role": "user", "content": "u4"},
            {"role": "assistant", "content": "a5"},
        ]
        with patch.object(compact, "_generate_summary", return_value="summary"):
            compacted = compact.compact_conversation(None, messages, "test-model")

        # The recent portion must start with the tool call, not its orphaned
        # result.  The summary occupies the first two synthetic messages.
        self.assertEqual(compacted[2]["role"], "assistant")
        self.assertEqual(compacted[2]["content"][0]["type"], "tool_use")
        self.assertEqual(compacted[3]["content"][0]["type"], "tool_result")


class ToolChainSanitizerTests(unittest.TestCase):
    """Regression coverage for LLM tool-call message chain 400 repair."""

    def setUp(self):
        clear_tool_results()

    def test_single_tool_normal(self):
        messages = [
            {"role": "user", "content": "读取文件"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "call-1", "name": "Read", "input": {}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "content": "内容"}]},
            {"role": "user", "content": "继续"},
        ]
        sanitize_messages(messages)
        _assert_paired(self, messages)
        converted = to_openai_messages("", list(messages))
        tool_messages = [m for m in converted if m["role"] == "tool"]
        self.assertEqual([m["tool_call_id"] for m in tool_messages], ["call-1"])

    def test_multiple_tool_calls_normal(self):
        messages = [
            {"role": "user", "content": "开始"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "call-1", "name": "Read", "input": {}},
                {"type": "tool_use", "id": "call-2", "name": "Bash", "input": {}},
                {"type": "tool_use", "id": "call-3", "name": "Glob", "input": {}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "content": "r1"},
                {"type": "tool_result", "tool_use_id": "call-2", "content": "r2"},
                {"type": "tool_result", "tool_use_id": "call-3", "content": "r3"},
            ]},
        ]
        sanitize_messages(messages)
        _assert_paired(self, messages)
        converted = to_openai_messages("", list(messages))
        tool_messages = [m for m in converted if m["role"] == "tool"]
        self.assertEqual([m["tool_call_id"] for m in tool_messages],
                         ["call-1", "call-2", "call-3"])

    def test_missing_one_tool_result_recovered_from_persisted_store(self):
        messages = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "call-1", "name": "Read", "input": {}},
                {"type": "tool_use", "id": "call-2", "name": "Bash", "input": {}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "content": "r1"},
            ]},
        ]
        sanitize_messages(messages, restore=lambda tid: (
            {"content": "saved-r2"} if tid == "call-2" else None))
        _assert_paired(self, messages)
        results = [b.get("tool_use_id") for m in messages if m.get("role") == "user"
                   for b in m.get("content", []) if b.get("type") == "tool_result"]
        self.assertEqual(results, ["call-1", "call-2"])
        contents = [b.get("content") for m in messages if m.get("role") == "user"
                    for b in m.get("content", []) if b.get("type") == "tool_result"]
        self.assertIn("saved-r2", contents)

    def test_seed_tool_results_from_restored_transcript_then_recover(self):
        restored = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "call-1", "name": "Read", "input": {}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "content": "真实结果"}]},
        ]
        seed_tool_results_from_messages(restored)
        broken = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "call-1", "name": "Read", "input": {}}]},
        ]
        sanitize_messages(broken)
        _assert_paired(self, broken)
        self.assertIn("真实结果", str(broken[-1]["content"]))

    def test_missing_tool_result_without_source_truncates_to_checkpoint(self):
        messages = [
            {"role": "user", "content": "u0"},
            {"role": "assistant", "content": "a0"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "call-9", "name": "Read", "input": {}}]},
            {"role": "user", "content": "后续问题"},
        ]
        sanitize_messages(messages)  # no restore source, no persisted entry
        self.assertEqual(messages, [
            {"role": "user", "content": "u0"},
            {"role": "assistant", "content": "a0"},
        ])
        converted = to_openai_messages("", list(messages))
        self.assertTrue(all(m["role"] != "tool" for m in converted))

    def test_orphan_tool_result_is_never_sent_as_tool_message(self):
        messages = [
            {"role": "user", "content": "继续"},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "stale", "content": "旧结果"}]},
        ]
        sanitize_messages(messages)
        calls, results = _tool_chain(messages)
        self.assertEqual(calls, [])
        self.assertEqual(results, ["stale"])
        converted = to_openai_messages("", list(messages))
        self.assertFalse(any(m.get("role") == "tool" for m in converted))
        self.assertIn("旧结果", converted[-1]["content"])

    def test_duplicate_tool_result_kept_once(self):
        messages = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "call-1", "name": "Read", "input": {}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "content": "第一个"},
                {"type": "tool_result", "tool_use_id": "call-1", "content": "重复"}]},
        ]
        sanitize_messages(messages)
        _assert_paired(self, messages)
        results = [b for m in messages if m.get("role") == "user"
                   for b in m.get("content", []) if b.get("type") == "tool_result"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["content"], "第一个")

    def test_tool_call_id_mismatch_recovered_from_store(self):
        # A wrong id is dropped from the tool chain, the real result is
        # recovered from the persisted store, and the stale output is kept
        # as plain user text.
        messages = [
            {"role": "user", "content": "u0"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "call-1", "name": "Read", "input": {}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "wrong-id", "content": "错配结果"}]},
        ]
        sanitize_messages(messages, restore=lambda tid: (
            {"content": "真实结果"} if tid == "call-1" else None))
        calls, results = _tool_chain(messages)
        self.assertEqual(calls, ["call-1"])
        self.assertEqual(results, ["call-1", "wrong-id"])
        converted = to_openai_messages("", list(messages))
        tool_messages = [m for m in converted if m.get("role") == "tool"]
        # The recovered real result is now properly paired and may be sent as
        # role=tool; the wrong-id stale output is only user text.
        self.assertEqual([m["tool_call_id"] for m in tool_messages], ["call-1"])
        self.assertTrue(any("错配结果" in m["content"] for m in converted
                            if m.get("role") == "user"))
        self.assertTrue(any("真实结果" in m["content"] for m in converted
                            if m.get("role") == "tool"))

    def test_tool_call_id_mismatch_without_source_truncates(self):
        # Wrong id with no recoverable source: the unpaired assistant call
        # and everything after it is dropped at the last consistent
        # checkpoint; no fabricated success is ever sent.
        messages = [
            {"role": "user", "content": "u0"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "call-1", "name": "Read", "input": {}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "wrong-id", "content": "错配结果"}]},
        ]
        sanitize_messages(messages)
        calls, results = _tool_chain(messages)
        self.assertEqual(calls, [])
        self.assertEqual(results, [])
        self.assertEqual([m.get("content") for m in messages], ["u0"])
        converted = to_openai_messages("", list(messages))
        self.assertFalse(any(m.get("role") == "tool" for m in converted))

    def test_deepseek_reasoning_content_kept_with_tool_calls(self):
        messages = [
            {"role": "user", "content": "继续"},
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "内部推理"},
                {"type": "tool_use", "id": "call-1", "name": "Read", "input": {}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "content": "结果"}]},
        ]
        sanitize_messages(messages)
        _assert_paired(self, messages)
        converted = to_openai_messages("", list(messages))
        assistant = converted[1]
        self.assertEqual(assistant["role"], "assistant")
        self.assertEqual(assistant["reasoning_content"], "内部推理")
        self.assertEqual(assistant["tool_calls"][0]["id"], "call-1")
        self.assertEqual(converted[2]["role"], "tool")

    def test_recoverable_tool_chain_400_retries_only_current_step(self):
        from open_claude import openai_compat

        error_text = (
            "litellm.BadRequestError: DeepseekException - "
            '{"error":{"message":"Insufficient tool messages following '
            'tool_calls message for every tool call id.","code":400}}'
        )
        calls = []

        class _FakeDelta:
            content = "重试成功"
            reasoning_content = None
            tool_calls = None

        class _FakeChoice:
            delta = _FakeDelta()
            finish_reason = "stop"

        class _FakeChunk:
            choices = [_FakeChoice()]
            usage = None

        def create(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise RuntimeError(error_text)
            if len(calls) == 2:
                raise RuntimeError(error_text)
            return [_FakeChunk()]

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        messages = [
            {"role": "user", "content": "继续"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "call-1", "name": "Read", "input": {}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "content": "结果"}]},
        ]
        original_object = messages

        with patch.object(openai_compat, "_client", return_value=fake_client):
            events = list(openai_compat.stream(
                "deepseek", "deepseek-v4-flash", messages, "", None, None, None,
                api_key="k"))

        self.assertFalse([e for e in events if e.get("type") == "error"])
        self.assertTrue(any(e.get("type") == "provider_retry" for e in events))
        self.assertTrue(any(e.get("type") == "text_delta" for e in events))
        # Only the current LLM step is retried (2 retries after the original
        # 400), never a fresh run: the same conversation list is reused and
        # no completed stage/tool execution is re-issued.
        self.assertEqual(len(calls), 3)
        self.assertIs(messages, original_object)

    def test_send_retries_same_call_after_tool_chain_400(self):
        from open_claude import openai_compat

        error_text = (
            "litellm.BadRequestError - {'error': {'message': "
            "'The `reasoning_content` in the thinking mode must be passed back "
            "to the API.', 'code': 'invalid_request_error'}}"
        )
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise RuntimeError(error_text)
            message = SimpleNamespace(
                content="正常回答",
                reasoning_content=None,
                tool_calls=None,
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=message)],
                usage=None,
            )

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        messages = [
            {"role": "user", "content": "继续"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "call-1", "name": "Read", "input": {}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "content": "结果"}]},
        ]
        original_object = messages

        with patch.object(openai_compat, "_client", return_value=fake_client):
            result = openai_compat.send(
                "deepseek", "deepseek-v4-flash", messages, "", None, None, None,
                api_key="k")

        self.assertEqual(len(calls), 2)  # original + one retry, same step
        self.assertIs(messages, original_object)
        self.assertEqual(result["stop_reason"], "end_turn")
        self.assertEqual(result["content"][0]["text"], "正常回答")


if __name__ == "__main__":
    unittest.main()
