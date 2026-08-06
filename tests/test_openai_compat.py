import pathlib
import sys
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

from open_claude.openai_compat import to_openai_messages
from open_claude import compact


class OpenAIMessageContractTests(unittest.TestCase):
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
