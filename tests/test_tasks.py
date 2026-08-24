import json
import sys
import tempfile
import unittest
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

from open_claude.tasks import TaskStore, get_task_store  # noqa: E402
from open_claude.repl import Conversation  # noqa: E402
from open_claude.openai_compat import (  # noqa: E402
    clear_tool_results,
    remember_tool_result,
)
import oc_codex_server  # noqa: E402


class _FakeConversation:
    def __init__(self):
        self.client = None
        self.profile = type("Profile", (), {
            "max_iterations": 1,
            "max_tokens": 4096,
            "temperature": 0.3,
            "thinking": False,
            "thinking_budget": 0,
        })()
        self.messages = []
        self.session = type("Session", (), {
            "append_message": lambda self, msg: None,
        })()
        self.tool_schemas = []
        self.system_prompt = ""
        self.model = "test-model"
        self.cost_tracker = type("Cost", (), {
            "total_cost_usd": 0.0,
            "add_usage": lambda *args, **kwargs: None,
        })()

    def add_user_message(self, text):
        self.messages.append({"role": "user", "content": text})

    def _maybe_compact(self):
        return None


class TaskStateMachineTests(unittest.TestCase):
    def test_provider_timeout_does_not_persist_reasoning_only_assistant(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._modeling_task(directory, "timeout-thinking", [])
            task.user_id = ""

            def fake_stream_message(client, messages, system_prompt, **kwargs):
                yield {"type": "thinking_delta", "text": "未完成的推理"}
                yield {"type": "error",
                       "error": "模型流式响应长时间无数据，本轮已暂停，可继续执行",
                       "code": "LLM_STREAM_TIMEOUT",
                       "recoverable": True}

            fake_runtime = SimpleNamespace(stream_message=fake_stream_message)
            with patch.object(oc_codex_server.AGENT_RUNTIME, "get",
                              return_value=fake_runtime), \
                    patch.object(oc_codex_server, "persist_tasks"), \
                    patch.object(oc_codex_server, "_append_task_history"):
                task.stream_turn("继续", lambda _event: None)

            # The provider history keeps only the user message; the partial
            # reasoning is preserved as an audit event, never as assistant
            # provider history.
            self.assertEqual([m["role"] for m in task.conv.messages], ["user"])
            self.assertIn("thinking", [event["type"] for event in task.log])
            error = next(event for event in task.log
                         if event.get("type") == "error")
            self.assertEqual(error["code"], "LLM_STREAM_TIMEOUT")
            self.assertIn("本轮已暂停", error["error"])

    def test_timeout_continue_resumes_from_current_llm_step(self):
        # After a provider timeout the partial turn is discarded; the next
        # "继续运行" turn re-issues only the current LLM step from the last
        # valid checkpoint instead of replaying a broken assistant message.
        with tempfile.TemporaryDirectory() as directory:
            task = self._modeling_task(directory, "timeout-continue", [])
            task.user_id = ""

            def timeout_stream(client, messages, system_prompt, **kwargs):
                yield {"type": "thinking_delta", "text": "半截推理"}
                yield {"type": "text_delta", "text": "半截回答"}
                yield {"type": "error",
                       "error": "模型流式响应长时间无数据，本轮已暂停，可继续执行",
                       "code": "LLM_STREAM_TIMEOUT",
                       "recoverable": True}

            def resume_stream(client, messages, system_prompt, **kwargs):
                sent = [m for m in messages if m.get("role") == "assistant"]
                assert sent == [], f"partial assistant must not be resent: {sent}"
                yield {"type": "text_delta", "text": "从断点继续完成"}
                yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}

            fake_runtime = SimpleNamespace(stream_message=timeout_stream)
            with patch.object(oc_codex_server.AGENT_RUNTIME, "get",
                              return_value=fake_runtime), \
                    patch.object(oc_codex_server, "persist_tasks"), \
                    patch.object(oc_codex_server, "_append_task_history"):
                task.stream_turn("继续", lambda _event: None)
            self.assertEqual([m["role"] for m in task.conv.messages], ["user"])

            fake_runtime = SimpleNamespace(stream_message=resume_stream)
            with patch.object(oc_codex_server.AGENT_RUNTIME, "get",
                              return_value=fake_runtime), \
                    patch.object(oc_codex_server, "persist_tasks"), \
                    patch.object(oc_codex_server, "_append_task_history"):
                task.stream_turn("继续执行上一次未完成的任务，从中断位置继续。"
                                 "不要重复已经完成的步骤。", lambda _event: None)
            self.assertEqual([m["role"] for m in task.conv.messages],
                             ["user", "user", "assistant"])
            self.assertEqual(task.conv.messages[-1]["content"][0]["text"],
                             "从断点继续完成")

    def test_provider_timeout_fires_failed_callback_exactly_once(self):
        # A provider timeout must terminate the turn with a single FAILED
        # platform callback.  The shared-layer fix discards the partial
        # assistant but must never duplicate the lifecycle callback.
        with tempfile.TemporaryDirectory() as directory:
            task = oc_codex_server.Task(
                project="cb-once",
                cwd=directory,
                task_type="modeling",
                task_code="RM-CB-ONCE",
                repository_id="1",
                mission_context={
                    "taskType": "modeling",
                    "repositoryId": "1",
                    "taskCode": "RM-CB-ONCE",
                    "expectedFiles": [],
                },
                user_id="test",
                defer_runtime=True,
            )
            task.conv = _FakeConversation()

            def fake_stream_message(client, messages, system_prompt, **kwargs):
                yield {"type": "thinking_delta", "text": "推理中"}
                yield {"type": "error",
                       "error": "模型流式响应长时间无数据，本轮已暂停，可继续执行",
                       "code": "LLM_STREAM_TIMEOUT",
                       "recoverable": True}

            fake_runtime = SimpleNamespace(stream_message=fake_stream_message)
            calls = []
            real_callback = oc_codex_server.task_status_callback

            def counting_callback(task_obj, agent_status, **kwargs):
                calls.append((agent_status, kwargs.get("error_code")))
                return real_callback(task_obj, agent_status, **kwargs)

            with patch.object(oc_codex_server.AGENT_RUNTIME, "get",
                              return_value=fake_runtime), \
                    patch.object(oc_codex_server, "persist_tasks"), \
                    patch.object(oc_codex_server, "_append_task_history"), \
                    patch.object(oc_codex_server, "task_status_callback",
                                 side_effect=counting_callback):
                task.stream_turn("继续", lambda _event: None)

            failed = [c for c in calls if c[0] == "FAILED"]
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0][1], "AGENT_EXECUTION_FAILED")
            # The partial reasoning is not part of provider history.
            self.assertEqual([m["role"] for m in task.conv.messages], ["user"])

    def test_partial_text_timeout_is_audited_but_not_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._modeling_task(directory, "timeout-partial", [])
            task.user_id = ""

            def fake_stream_message(client, messages, system_prompt, **kwargs):
                yield {"type": "thinking_delta", "text": "推理中"}
                yield {"type": "text_delta", "text": "部分回答"}
                yield {"type": "error", "error": "read timeout", "code": "LLM_STREAM_TIMEOUT"}

            fake_runtime = SimpleNamespace(stream_message=fake_stream_message)
            with patch.object(oc_codex_server.AGENT_RUNTIME, "get",
                              return_value=fake_runtime), \
                    patch.object(oc_codex_server, "persist_tasks"), \
                    patch.object(oc_codex_server, "_append_task_history"):
                task.stream_turn("继续", lambda _event: None)

            self.assertEqual([m["role"] for m in task.conv.messages], ["user"])
            # The partial text is visible in the audit log but must not be
            # persisted as an assistant provider-history message.
            self.assertTrue(any(
                event.get("type") == "assistant" and "部分回答" in event.get("text", "")
                for event in task.log))
            self.assertFalse(any(
                m.get("role") == "assistant" for m in task.conv.messages))

    def test_completed_reasoning_only_turn_is_not_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._modeling_task(directory, "reasoning-only", [])
            task.user_id = ""

            def fake_stream_message(client, messages, system_prompt, **kwargs):
                yield {"type": "thinking_delta", "text": "只有推理没有输出"}
                yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}

            fake_runtime = SimpleNamespace(stream_message=fake_stream_message)
            with patch.object(oc_codex_server.AGENT_RUNTIME, "get",
                              return_value=fake_runtime), \
                    patch.object(oc_codex_server, "persist_tasks"), \
                    patch.object(oc_codex_server, "_append_task_history"):
                task.stream_turn("继续", lambda _event: None, conversational=True)

            self.assertEqual([m["role"] for m in task.conv.messages], ["user"])
            self.assertEqual(task.status, "idle")

    def test_provider_retry_notice_is_recorded_and_turn_continues(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._modeling_task(directory, "retry-notice", [])
            task.conv.profile.max_iterations = 5
            task.user_id = ""

            def fake_stream_message(client, messages, system_prompt, **kwargs):
                yield {"type": "provider_retry", "attempt": 2,
                       "text": "模型网关思考模式校验失败，已自动重试并继续执行"}
                yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}

            fake_runtime = SimpleNamespace(stream_message=fake_stream_message)
            with patch.object(oc_codex_server.AGENT_RUNTIME, "get",
                              return_value=fake_runtime), \
                    patch.object(oc_codex_server, "persist_tasks"), \
                    patch.object(oc_codex_server, "_append_task_history"):
                task.stream_turn("继续", lambda _event: None, conversational=True)

            self.assertEqual(task.status, "idle")
            self.assertTrue(any(
                event.get("type") == "provider_retry" for event in task.log))

    def test_modeling_guard_default_gate_retry_limit_is_ten(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ONTOLOGY_MODELING_MAX_GATE_RETRIES", None)
            guard = oc_codex_server.ModelingExecutionGuard()
        self.assertEqual(guard.max_gate_retries, 10)

    def test_modeling_guard_default_token_budget_is_one_hundred_million(self):
        with patch.dict(os.environ, {
            "ONTOLOGY_MODELING_MAX_TOKENS": "",
        }, clear=False):
            os.environ.pop("ONTOLOGY_MODELING_MAX_TOKENS", None)
            guard = oc_codex_server.ModelingExecutionGuard()
        self.assertEqual(guard.max_tokens, 100_000_000)

    def test_gate_blocker_detail_ignores_rule_indicator_warnings(self):
        checkpoint = {"issues": [
            SimpleNamespace(code="INSUFFICIENT_RULE_EVIDENCE", severity="WARNING",
                            message="规则证据不足"),
            SimpleNamespace(code="ENFORCED_WITHOUT_ENFORCEMENT_EVIDENCE", severity="WARNING",
                            message="强制证据缺失"),
            SimpleNamespace(code="UNSUPPORTED_FORMAL_INDICATOR", severity="WARNING",
                            message="指标口径未确认"),
            SimpleNamespace(code="FORMAL_OUTPUT_EMPTY", severity="ERROR",
                            message="正式输出为空"),
        ]}
        detail = oc_codex_server._gate_blocker_detail(checkpoint)
        self.assertNotIn("INSUFFICIENT_RULE_EVIDENCE", detail)
        self.assertNotIn("ENFORCED_WITHOUT_ENFORCEMENT_EVIDENCE", detail)
        self.assertNotIn("UNSUPPORTED_FORMAL_INDICATOR", detail)
        self.assertIn("FORMAL_OUTPUT_EMPTY", detail)

    def test_gate_blocker_detail_ignores_auto_resolved_warnings(self):
        checkpoint = {"issues": [
            SimpleNamespace(code="ASSET_PROCESSING_COVERAGE_MISSING", severity="WARNING",
                            message="输入资产缺少处理决策，已自动标记 processingDecision=UNKNOWN"),
            SimpleNamespace(code="INVALID_AGGREGATION_EDGE", severity="WARNING",
                            message="COMPOSITION 缺少证据，已自动降级为 REFERENCE"),
            SimpleNamespace(code="MISSING_COMPOSITION_OWNER", severity="ERROR",
                            message="COMPOSITION 引用了不存在的 source 或 owner"),
        ]}
        detail = oc_codex_server._gate_blocker_detail(checkpoint)
        self.assertNotIn("ASSET_PROCESSING_COVERAGE_MISSING", detail)
        self.assertNotIn("INVALID_AGGREGATION_EDGE", detail)
        self.assertIn("MISSING_COMPOSITION_OWNER", detail)

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

    def test_deferred_runtime_set_mission_context_materializes_conversation(self):
        # Regression: a platform callback can push mission context while a
        # deferred-runtime task still has conv=None.  set_mission_context must
        # materialize the conversation instead of raising
        # AttributeError: 'NoneType' object has no attribute 'model'.
        class FakeRuntime:
            class AgentProfile:
                def __init__(self, model, style):
                    self.model = model
                    self.style = style

            def Conversation(self, cwd, permission_mode, resume_session_id, profile):
                conv = _FakeConversation()
                conv.model = profile.model
                conv.permissions = SimpleNamespace(
                    _prompt_user=None,
                    mode="default",
                )
                return conv

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(oc_codex_server.AGENT_RUNTIME, "get", return_value=FakeRuntime()), \
                patch.object(oc_codex_server, "download_mission_files",
                             return_value=([], [])), \
                patch.object(oc_codex_server, "migrate_legacy_mission_inputs",
                             return_value=[]), \
                patch.object(oc_codex_server, "prepare_mission_spreadsheets",
                             return_value=([], [])), \
                patch.object(oc_codex_server, "prepare_mission_documents",
                             return_value=([], [])), \
                patch.object(oc_codex_server, "list_project_files",
                             return_value=[]), \
                patch.object(oc_codex_server, "load_private_goals_and_rules",
                             return_value=""):
            task = oc_codex_server.Task(
                project="mission-context-race",
                cwd=directory,
                task_type="modeling",
                mission_context={
                    "taskType": "modeling",
                    "repositoryId": "1",
                    "taskCode": "RM-RACE-001",
                    "expectedFiles": [],
                },
                user_id="test",
                defer_runtime=True,
            )
            with patch.object(type(task), "refresh_modeling_artifacts"):
                self.assertIsNone(task.conv)
                # The platform pushes context before the first streamed turn.
                task.set_mission_context({
                    "taskType": "modeling",
                    "repositoryId": "1",
                    "taskCode": "RM-RACE-001",
                    "expectedFiles": [],
                })
                self.assertIsNotNone(task.conv)
                self.assertIn("本体任务系统上下文", task.conv.system_prompt)
                # A second push with identical context is idempotent.
                task.set_mission_context({
                    "taskType": "modeling",
                    "repositoryId": "1",
                    "taskCode": "RM-RACE-001",
                    "expectedFiles": [],
                })

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

    def test_read_only_probe_does_not_consume_mutating_guard_budget(self):
        with patch.dict(os.environ, {"ONTOLOGY_MODELING_MAX_TOOL_CALLS": "1"}, clear=False):
            guard = oc_codex_server.ModelingExecutionGuard()
            self.assertEqual(guard.record_tool_call("Read", {"file_path": "schema.json"}), "")
            self.assertEqual(guard.record_tool_call("Bash", {"command": "rg -n tables schema.json"}), "")
            self.assertEqual(guard.read_only_tool_calls, 2)
            self.assertEqual(guard.mutating_tool_calls, 0)
            self.assertEqual(guard.record_tool_call("Write", {"file_path": "out.csv"}),
                             "MODEL_TOOL_CALL_LIMIT")
            self.assertEqual(guard.record_tool_call("Write", {"file_path": "out2.csv"}),
                             "MODEL_TOOL_CALL_LIMIT")

    def test_budget_pause_persists_checkpoint_and_is_marked_recoverable(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._modeling_task(directory, "budget-pause", ["business_objects.csv"])
            task.conv.profile.max_iterations = 5
            checkpoint = {
                "status": "FAILED",
                "issues": [type("Issue", (), {
                    "code": "MISSING_EVIDENCE",
                    "severity": "ERROR",
                    "message": "需要独立证据",
                })()],
            }
            with patch.object(oc_codex_server.ModelingExecutionGuard, "check",
                              return_value="MODEL_TOOL_CALL_LIMIT"), \
                    patch.object(task, "_stream_once", return_value="end_turn"), \
                    patch.object(oc_codex_server, "finalize_modeling_task",
                                 return_value=checkpoint) as finalize, \
                    patch.object(oc_codex_server, "persist_tasks"), \
                    patch.object(oc_codex_server, "_append_task_history"):
                task.stream_turn("开始建模", lambda _event: None, conversational=False)

            self.assertEqual(task.status, "blocked")
            self.assertEqual(task.modeling_block_reason, "MODEL_TOOL_CALL_LIMIT")
            self.assertEqual(task.run_result.get("status"), "BLOCKED")
            # A budget pause must persist the current stage checkpoint so a
            # retry resumes from the last PASSED stage instead of restarting.
            self.assertGreaterEqual(finalize.call_count, 1)
            guard_events = [event for event in task.log
                            if event.get("type") == "execution_guard"]
            self.assertTrue(guard_events)
            self.assertEqual(guard_events[-1].get("status"), "paused")
            self.assertTrue(guard_events[-1].get("recoverable"))

    def test_budget_limit_does_not_block_when_checkpoint_already_passed(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._modeling_task(directory, "budget-passed", ["business_objects.csv"])
            task.conv.profile.max_iterations = 5
            checkpoint = {"status": "PASSED", "issues": []}
            with patch.object(oc_codex_server.ModelingExecutionGuard, "check",
                              return_value="MODEL_TOKEN_BUDGET_EXCEEDED"), \
                    patch.object(task, "_stream_once", return_value="end_turn"), \
                    patch.object(oc_codex_server, "finalize_modeling_task",
                                 return_value=checkpoint), \
                    patch.object(oc_codex_server, "persist_tasks"), \
                    patch.object(oc_codex_server, "_append_task_history"):
                task.stream_turn("开始建模", lambda _event: None, conversational=False)

            self.assertEqual(task.status, "idle")
            self.assertNotEqual(task.run_result.get("status"), "BLOCKED")
            passed = [event for event in task.log
                      if event.get("type") == "execution_guard"
                      and event.get("status") == "passed"]
            self.assertTrue(passed)

    def test_gate_blocks_are_not_recoverable_pauses(self):
        for code in ("MODEL_GATE_RETRY_LIMIT",
                     "MODEL_GATE_REPEATED_WITHOUT_NEW_EVIDENCE"):
            self.assertFalse(oc_codex_server.is_recoverable_guard_pause(code))
        for code in ("MODEL_EXECUTION_TIMEOUT", "MODEL_TOOL_CALL_LIMIT",
                     "MODEL_TOKEN_BUDGET_EXCEEDED"):
            self.assertTrue(oc_codex_server.is_recoverable_guard_pause(code))
        self.assertFalse(oc_codex_server.is_recoverable_guard_pause(""))

    def test_dependency_and_environment_probes_do_not_consume_mutating_budget(self):
        with patch.dict(os.environ, {"ONTOLOGY_MODELING_MAX_TOOL_CALLS": "3"}, clear=False):
            guard = oc_codex_server.ModelingExecutionGuard()
            probes = [
                ("Bash", {"command": "python3 -c \"import sqlalchemy; print(sqlalchemy.__version__)\""}),
                ("Bash", {"command": "python3 -c \"import psycopg2\""}),
                ("Bash", {"command": "pip list | grep sqlalchemy"}),
                ("Bash", {"command": "which python3"}),
                ("Bash", {"command": "env | grep DATABASE"}),
                ("Bash", {"command": "python3 --version"}),
            ]
            for name, payload in probes:
                self.assertEqual(guard.record_tool_call(name, payload), "",
                                 msg=f"{payload!r} should be read-only")
            self.assertEqual(guard.mutating_tool_calls, 0)
            self.assertEqual(guard.read_only_tool_calls, len(probes))

    def test_destructive_python_one_liner_still_consumes_mutating_budget(self):
        with patch.dict(os.environ, {"ONTOLOGY_MODELING_MAX_TOOL_CALLS": "1"}, clear=False):
            guard = oc_codex_server.ModelingExecutionGuard()
            self.assertEqual(guard.record_tool_call(
                "Bash", {"command": "python3 -c \"import os; os.remove('x.csv')\""}),
                "MODEL_TOOL_CALL_LIMIT")
            self.assertEqual(guard.mutating_tool_calls, 1)

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
            guard_events = [event for event in task.log
                            if event.get("type") == "execution_guard"]
            self.assertTrue(guard_events)
            self.assertEqual(guard_events[-1].get("status"), "blocked")
            self.assertIn("MISSING_EVIDENCE", guard_events[-1].get("message", ""))

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

class ToolExecutionDedupTests(unittest.TestCase):
    """A tool_call_id must never execute twice across retry/continue."""

    def setUp(self):
        clear_tool_results()

    def _stub_conversation(self, messages):
        hooks = type("Hooks", (), {
            "run": lambda *args, **kwargs: type("HookResult", (), {
                "errors": [], "blocked": False, "reasons": [], "block_reason": ""})(),
        })()
        permissions = type("Permissions", (), {
            "check_permission": lambda *args, **kwargs: (True, ""),
        })()
        mcp = type("Mcp", (), {"is_mcp_tool": lambda *args: False, "call": lambda *args: None})()
        session = type("Session", (), {
            # The real session is a separate transcript; self.messages.append
            # already records the turn for the assertions below.
            "append_message": lambda self, msg: None,
        })()
        return type("Conv", (), {
            "messages": messages,
            "hooks": hooks,
            "permissions": permissions,
            "mcp": mcp,
            "session": session,
            "cwd": ".",
            "client": None,
            "agent_types": {},
        })()

    def test_same_tool_call_id_is_not_executed_twice(self):
        from unittest.mock import patch
        from open_claude import repl as repl_module

        messages = [{"role": "assistant", "content": [
            {"type": "tool_use", "id": "call-1", "name": "Write",
             "input": {"file_path": "x.txt", "content": "data"}},
        ]}]
        conv = self._stub_conversation(messages)
        executed = []
        with patch.object(repl_module, "execute_tool",
                          side_effect=lambda name, params, cwd: (
                              executed.append((name, params)) or "已写入")):
            Conversation._execute_pending_tools(conv)
        self.assertEqual(len(executed), 1)
        self.assertTrue(any(m.get("role") == "user" for m in messages))

        # The same turn is presented again (retry/continue): the stored real
        # result is reused and the write tool is NOT executed a second time.
        messages.append({"role": "assistant", "content": [
            {"type": "tool_use", "id": "call-1", "name": "Write",
             "input": {"file_path": "x.txt", "content": "data"}},
        ]})
        Conversation._execute_pending_tools(conv)
        self.assertEqual(len(executed), 1, "write tool must not run twice")
        results = [b for m in messages if m.get("role") == "user"
                   for b in m.get("content", []) if b.get("type") == "tool_result"]
        self.assertTrue(all(b.get("content") == "已写入" for b in results))

    def test_store_seeded_result_skips_execution_on_restore(self):
        from unittest.mock import patch
        from open_claude import repl as repl_module

        # Session restore seeds the store from the persisted transcript.
        remember_tool_result("call-9", "恢复的真实结果")
        messages = [{"role": "assistant", "content": [
            {"type": "tool_use", "id": "call-9", "name": "Bash",
             "input": {"command": "rm -rf data"}},
        ]}]
        conv = self._stub_conversation(messages)
        executed = []
        with patch.object(repl_module, "execute_tool",
                          side_effect=lambda name, params, cwd: (
                              executed.append((name, params)) or "不应执行")):
            Conversation._execute_pending_tools(conv)
        self.assertEqual(executed, [], "restored tool result must not re-execute")
        results = [b for m in messages if m.get("role") == "user"
                   for b in m.get("content", []) if b.get("type") == "tool_result"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["content"], "恢复的真实结果")


    def test_task_state_survives_store_reconstruction(self):
        with tempfile.TemporaryDirectory() as directory:
            first = TaskStore(directory)
            task = first.create("Persisted step")
            second = TaskStore(directory)
            self.assertEqual(second.get(task.id).subject, "Persisted step")


class TaskEventSyncTests(unittest.TestCase):
    """Stable event identity contract for the 47313 workbench."""

    def _task(self, directory, task_id="task-events"):
        task = oc_codex_server.Task(
            "p", directory, task_id=task_id, user_id="test")
        task.conv = _FakeConversation()
        return task

    def test_record_event_stamps_monotonic_persisted_seq(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            with patch.object(oc_codex_server, "persist_tasks"), \
                    patch.object(oc_codex_server, "_append_task_history"):
                first = task._record_event({"type": "user", "text": "a"})
                second = task._record_event({"type": "assistant", "text": "b"})
            self.assertEqual(first["seq"], 0)
            self.assertEqual(second["seq"], 1)
            self.assertEqual([event["seq"] for event in task.log], [0, 1])

    def test_record_event_dedupes_by_client_message_id(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            with patch.object(oc_codex_server, "persist_tasks"), \
                    patch.object(oc_codex_server, "_append_task_history"):
                first = task._record_event(
                    {"type": "user", "text": "继续", "clientMessageId": "cm-1"})
                replay = task._record_event(
                    {"type": "user", "text": "继续", "clientMessageId": "cm-1"})
                second = task._record_event(
                    {"type": "user", "text": "继续", "clientMessageId": "cm-2"})
            self.assertIs(replay, first)
            self.assertEqual(len(task.log), 2)
            self.assertEqual([event["seq"] for event in task.log], [0, 1])

    def test_stream_turn_echoes_user_event_with_client_message_id(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            task.user_id = ""
            emitted = []

            def fake_stream_message(client, messages, system_prompt, **kwargs):
                yield {"type": "done", "status": "idle"}

            fake_runtime = SimpleNamespace(stream_message=fake_stream_message)
            with patch.object(oc_codex_server.AGENT_RUNTIME, "get",
                              return_value=fake_runtime), \
                    patch.object(oc_codex_server, "persist_tasks"), \
                    patch.object(oc_codex_server, "_append_task_history"):
                task.stream_turn("继续", emitted.append, client_message_id="cm-echo")
            user_events = [event for event in task.log if event.get("type") == "user"]
            self.assertEqual(len(user_events), 1)
            self.assertEqual(user_events[0]["clientMessageId"], "cm-echo")
            self.assertIn("seq", user_events[0])
            streamed = [event for event in emitted if event.get("type") == "user"]
            self.assertEqual(len(streamed), 1)
            self.assertEqual(streamed[0]["clientMessageId"], "cm-echo")

    def test_restore_tasks_resumes_event_seq_after_restart(self):
        import oc_codex_server as web
        old_sandbox = web.SANDBOX_DIR
        old_state = web.TASKS_STATE_PATH
        old_enabled = web.WEB_TASK_PERSISTENCE_ENABLED
        old_tasks = web.TASKS
        try:
            with tempfile.TemporaryDirectory() as sandbox_dir:
                web.SANDBOX_DIR = sandbox_dir
                web.TASKS_STATE_PATH = os.path.join(sandbox_dir, ".web_tasks.json")
                os.makedirs(os.path.join(sandbox_dir, "p"), exist_ok=True)
                task = web.Task("p", os.path.join(sandbox_dir, "p"),
                                task_id="seq-restore", user_id="test")
                with patch.object(web, "_append_task_history"), \
                        patch.object(web, "persist_tasks"):
                    task._record_event({"type": "user", "text": "a"})
                    task._record_event({"type": "assistant", "text": "b"})
                rows = [{
                    **task.summary(), "log": task.log,
                    "missionContext": {}, "platformUploadedFiles": {},
                    "platformOutputPrefix": task.platform_output_prefix,
                    "platformLastError": task.platform_last_error,
                    "sessionId": "", "userId": task.user_id,
                    "workspace": task.workspace,
                    "taskWorkspace": task.task_workspace_relpath,
                }]
                with open(web.TASKS_STATE_PATH, "w", encoding="utf-8") as fh:
                    json.dump(rows, fh)
                web.TASKS = {}
                with patch.object(web, "_load_task_history",
                                  return_value=task.log), \
                        patch.object(web, "_seed_task_history",
                                     return_value=False), \
                        patch.object(web, "persist_tasks"):
                    web.restore_tasks()
                restored = web.TASKS.get("seq-restore")
                self.assertIsNotNone(restored)
                self.assertEqual(restored.event_seq, 2)
                with patch.object(web, "_append_task_history"), \
                        patch.object(web, "persist_tasks"):
                    third = restored._record_event({"type": "assistant", "text": "c"})
                self.assertEqual(third["seq"], 2)
                self.assertEqual([event["seq"] for event in restored.log], [0, 1, 2])
        finally:
            web.SANDBOX_DIR = old_sandbox
            web.TASKS_STATE_PATH = old_state
            web.TASKS = old_tasks
            web.configure_task_persistence(old_enabled)



if __name__ == "__main__":
    unittest.main()
