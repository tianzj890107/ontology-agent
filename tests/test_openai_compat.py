import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

from open_claude.openai_compat import to_openai_messages
from open_claude import compact


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


if __name__ == "__main__":
    unittest.main()
