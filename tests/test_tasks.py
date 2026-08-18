import sys
import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

from open_claude.tasks import TaskStore, get_task_store  # noqa: E402
import oc_codex_server  # noqa: E402


class _FakeConversation:
    def __init__(self):
        self.profile = type("Profile", (), {"max_iterations": 1})()
        self.messages = []
        self.system_prompt = ""
        self.model = "test-model"
        self.cost_tracker = type("Cost", (), {"total_cost_usd": 0.0})()

    def add_user_message(self, text):
        self.messages.append({"role": "user", "content": text})

    def _maybe_compact(self):
        return None


class TaskStateMachineTests(unittest.TestCase):
    def test_modeling_guard_default_token_budget_is_one_hundred_million(self):
        with patch.dict(os.environ, {
            "ONTOLOGY_MODELING_MAX_TOKENS": "",
        }, clear=False):
            os.environ.pop("ONTOLOGY_MODELING_MAX_TOKENS", None)
            guard = oc_codex_server.ModelingExecutionGuard()
        self.assertEqual(guard.max_tokens, 100_000_000)

    @staticmethod
    def _modeling_task(directory, project, expected_files=None):
        task = oc_codex_server.Task(
            project=project,
            cwd=directory,
            task_type="modeling",
            mission_context={
                "taskType": "modeling",
                "expectedFiles": expected_files or [],
            },
            user_id="test",
            defer_runtime=True,
        )
        task.conv = _FakeConversation()
        return task

    def test_modeling_guard_limits_and_counts(self):
        with patch.dict(os.environ, {
            "ONTOLOGY_MODELING_MAX_SECONDS": "1",
            "ONTOLOGY_MODELING_MAX_TOOL_CALLS": "2",
            "ONTOLOGY_MODELING_MAX_TOKENS": "10",
            "ONTOLOGY_MODELING_MAX_GATE_RETRIES": "3",
        }, clear=False):
            guard = oc_codex_server.ModelingExecutionGuard()
            self.assertEqual(guard.record_tool_call(), "")
            self.assertEqual(guard.record_tool_call(), "MODEL_TOOL_CALL_LIMIT")
            self.assertEqual(guard.record_usage({"input_tokens": 10}),
                             "MODEL_TOOL_CALL_LIMIT")

    def test_same_gate_without_new_evidence_blocks_and_preserves_result(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "mission-work").mkdir()
            (Path(directory) / "mission-work" / "existing.csv").write_text(
                "preserve", encoding="utf-8")
            task = self._modeling_task(directory, "gate-repeat-test",
                                       ["business_objects.csv"])
            task.conv.profile.max_iterations = 1
            checkpoint = {
                "status": "FAILED",
                "issues": [type("Issue", (), {
                    "code": "MISSING_EVIDENCE",
                    "severity": "ERROR",
                    "message": "需要独立证据",
                })()],
            }
            with patch.object(task, "_stream_once", return_value="end_turn") as stream, \
                    patch.object(oc_codex_server, "finalize_modeling_task",
                                 return_value=checkpoint), \
                    patch.object(oc_codex_server, "persist_tasks"), \
                    patch.object(oc_codex_server, "_append_task_history"):
                task.stream_turn("开始建模", lambda _event: None, conversational=False)

            self.assertEqual(task.status, "blocked")
            self.assertEqual(task.run_result.get("status"), "BLOCKED")
            self.assertEqual(task.modeling_block_reason,
                             "MODEL_GATE_REPEATED_WITHOUT_NEW_EVIDENCE")
            self.assertEqual(stream.call_count, 1)
            self.assertTrue((Path(directory) / "mission-work").exists())

    def test_new_evidence_allows_one_gate_repair_window(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._modeling_task(directory, "gate-evidence-test")
            task.conv.profile.max_iterations = 1
            failed = {"status": "FAILED", "issues": []}
            checkpoints = [failed, {"status": "PASSED", "issues": []},
                           {"status": "PASSED", "issues": []}]
            evidence = iter(["before", "after"])

            with patch.object(task, "_stream_once", return_value="end_turn") as stream, \
                    patch.object(oc_codex_server, "finalize_modeling_task",
                                 side_effect=lambda _task: checkpoints.pop(0)), \
                    patch.object(oc_codex_server, "_modeling_evidence_signature",
                                 side_effect=lambda _cwd: next(evidence)), \
                    patch.object(oc_codex_server, "persist_tasks"), \
                    patch.object(oc_codex_server, "_append_task_history"):
                task.stream_turn("开始建模", lambda _event: None, conversational=False)

            self.assertEqual(task.status, "idle")
            self.assertEqual(stream.call_count, 1)

    def test_user_daily_quota_is_not_an_agent_execution_block(self):
        with patch.dict(os.environ, {
            "ONTOLOGY_USER_DAILY_CALL_LIMIT": "0",
            "ONTOLOGY_USER_DAILY_TOKEN_LIMIT": "0",
            "ONTOLOGY_USER_DAILY_COST_USD": "0",
        }, clear=False):
            allowed, error = oc_codex_server.check_user_budget("quota-test")
        self.assertTrue(allowed)
        self.assertEqual(error, "")

    def test_modeling_gate_opens_next_window_until_passed(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._modeling_task(directory, "gate-test",
                                       ["business_objects.csv"])
            task.conv.profile.max_iterations = 1
            checkpoints = []

            def checkpoint(_task):
                checkpoints.append(True)
                if len(checkpoints) == 1:
                    return {"status": "FAILED", "issues": []}
                return {"status": "PASSED", "issues": []}

            with patch.object(task, "_stream_once", return_value="end_turn"), \
                    patch.object(oc_codex_server, "finalize_modeling_task",
                                 side_effect=checkpoint), \
                    patch.object(oc_codex_server, "persist_tasks"), \
                    patch.object(oc_codex_server, "_append_task_history"):
                task.stream_turn("开始建模", lambda _event: None, conversational=False)

            self.assertEqual(task.status, "idle")
            # First call blocks the end_turn; second call is the new window;
            # the finalizer runs once more in stream_turn's final cleanup.
            self.assertGreaterEqual(len(checkpoints), 3)
            self.assertTrue(any(
                "当前建模回合不能结束" in str(message.get("content", ""))
                for message in task.conv.messages
                if message.get("role") == "user"
            ))

    def test_unknown_task_is_explicit_error_and_does_not_create_task(self):
        with tempfile.TemporaryDirectory() as directory:
            store = get_task_store(directory)
            result = store.update_checked(3, status="completed")
            self.assertFalse(result.ok)
            self.assertEqual(result.code, "TASK_NOT_FOUND")
            self.assertEqual(store.list_all(), [])

    def test_illegal_transition_is_rejected_and_valid_completion_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            store = get_task_store(directory)
            task = store.create("Produce artifact")
            illegal = store.update_checked(task.id, status="completed")
            self.assertFalse(illegal.ok)
            self.assertEqual(task.status, "pending")
            self.assertTrue(store.update_checked(task.id, status="in_progress").ok)
            self.assertTrue(store.update_checked(task.id, status="completed").ok)
            repeat = store.update_checked(task.id, status="completed")
            self.assertTrue(repeat.ok)
            self.assertEqual(task.status, "completed")

    def test_retry_with_same_idempotency_key_does_not_duplicate_active_task(self):
        with tempfile.TemporaryDirectory() as directory:
            store = get_task_store(directory)
            first = store.create("Same step", metadata={"idempotencyKey": "run-1"})
            second = store.create("Same step", metadata={"idempotencyKey": "run-1"})
            self.assertIs(first, second)
            self.assertEqual(len(store.list_all()), 1)

    def test_task_ids_are_scoped_and_not_task_list_positions(self):
        with tempfile.TemporaryDirectory() as root:
            first_dir = str(Path(root) / "one")
            second_dir = str(Path(root) / "two")
            first = get_task_store(first_dir).create("First")
            second = get_task_store(second_dir).create("Second")
            self.assertEqual(first.id, 1)
            self.assertEqual(second.id, 1)
            self.assertEqual(get_task_store(first_dir).list_all()[0].subject, "First")
            self.assertEqual(get_task_store(second_dir).list_all()[0].subject, "Second")

    def test_task_state_survives_store_reconstruction(self):
        with tempfile.TemporaryDirectory() as directory:
            first = TaskStore(directory)
            task = first.create("Persisted step")
            second = TaskStore(directory)
            self.assertEqual(second.get(task.id).subject, "Persisted step")


if __name__ == "__main__":
    unittest.main()
