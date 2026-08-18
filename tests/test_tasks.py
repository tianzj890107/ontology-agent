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


class TaskStateMachineTests(unittest.TestCase):
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
            task = oc_codex_server.Task(
                project="gate-test",
                cwd=directory,
                task_type="modeling",
                mission_context={
                    "taskType": "modeling",
                    "expectedFiles": ["business_objects.csv"],
                },
                user_id="test",
            )
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
