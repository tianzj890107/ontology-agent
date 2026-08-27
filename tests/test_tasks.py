import json
import sys
import tempfile
import threading
import time
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

    def test_provider_timeout_keeps_platform_running_without_failed_callback(self):
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

            self.assertFalse([c for c in calls if c[0] == "FAILED"])
            self.assertEqual(task.platform_status, "RUNNING")
            self.assertEqual(task.run_result["status"], "PAUSED")
            # The partial reasoning is not part of provider history.
            self.assertEqual([m["role"] for m in task.conv.messages], ["user"])

    def test_deepseek_reasoning_protocol_error_is_recoverable(self):
        message = ("litellm.BadRequestError: DeepseekException - The "
                   "`reasoning_content` in the thinking mode must be passed back to the API")
        self.assertTrue(oc_codex_server.is_recoverable_provider_error(message))

    def test_run_result_accepts_callback_file_objects(self):
        task = SimpleNamespace(id="task-1", task_code="RM-1", mission_context={
            "expectedFiles": ["business_objects.csv", "logical_entities.csv"],
        })
        result = oc_codex_server.set_task_run_result(
            task, "ORCHESTRATION_FAILED",
            generated_artifacts=[
                {"filename": "business_objects.csv", "objectKey": "x/business_objects.csv"},
                {"name": "logical_entities.csv"},
                {"objectKey": "missing-name"},
            ],
        )
        self.assertEqual(result["generatedArtifacts"], [
            "business_objects.csv", "logical_entities.csv",
        ])

    def test_provider_balance_and_auth_errors_are_not_recoverable(self):
        self.assertFalse(oc_codex_server.is_recoverable_provider_error(
            "litellm.BadRequestError: DeepseekException - Insufficient Balance"))
        self.assertFalse(oc_codex_server.is_recoverable_provider_error(
            "authentication failed", "LLM_AUTH_ERROR"))

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
            (Path(directory) / "work").mkdir()
            (Path(directory) / "work" / "existing.csv").write_text(
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
            self.assertTrue((Path(directory) / "work").exists())
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

class TaskCancellationFlowTests(unittest.TestCase):
    """313: the coordinator cancellation token stops the model stream loop."""

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

    def test_cancelled_token_stops_turn_before_model_call(self):
        from open_claude.execution_coordinator import CancellationToken
        with tempfile.TemporaryDirectory() as directory:
            task = self._modeling_task(directory, "cancel-before", [])
            task.user_id = ""
            model_calls = []

            def fake_stream_message(client, messages, system_prompt, **kwargs):
                model_calls.append(True)
                yield {"type": "text_delta", "text": "never shown"}

            fake_runtime = SimpleNamespace(stream_message=fake_stream_message)
            token = CancellationToken()
            token.cancel("LEASE_LOST")
            with patch.object(oc_codex_server.AGENT_RUNTIME, "get",
                              return_value=fake_runtime),                     patch.object(oc_codex_server, "persist_tasks"),                     patch.object(oc_codex_server, "_append_task_history"):
                task.stream_turn("继续建模", lambda _event: None,
                                 cancellation_token=token)
            self.assertEqual(model_calls, [])
            self.assertEqual(task.status, "error")
            error = next(event for event in task.log
                         if event.get("type") == "error")
            self.assertTrue(error.get("recoverable"))

    def test_token_cancelled_mid_stream_stops_loop(self):
        from open_claude.execution_coordinator import CancellationToken
        with tempfile.TemporaryDirectory() as directory:
            task = self._modeling_task(directory, "cancel-mid", [])
            task.user_id = ""
            token = CancellationToken()

            def fake_stream_message(client, messages, system_prompt, **kwargs):
                yield {"type": "thinking_delta", "text": "推理中"}
                token.cancel("LEASE_LOST")
                yield {"type": "text_delta", "text": "这部分不得进入历史"}

            fake_runtime = SimpleNamespace(stream_message=fake_stream_message)
            with patch.object(oc_codex_server.AGENT_RUNTIME, "get",
                              return_value=fake_runtime),                     patch.object(oc_codex_server, "persist_tasks"),                     patch.object(oc_codex_server, "_append_task_history"):
                task.stream_turn("继续建模", lambda _event: None,
                                 cancellation_token=token)
            self.assertEqual(task.status, "error")
            # The event after the cancellation must never be recorded.
            self.assertNotIn("这部分不得进入历史",
                             [event.get("text", "") for event in task.log])


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


class TaskJournalPersistenceTests(unittest.TestCase):
    """P0-1: 47313 events live in a per-task append-only journal; the global
    .web_tasks.json snapshot stays a bounded summary."""

    def _task(self, directory, task_id="journal-task", user_id="test"):
        task = oc_codex_server.Task("p", directory, task_id=task_id, user_id=user_id)
        task.conv = _FakeConversation()
        return task

    def test_record_event_appends_journal_without_rewriting_snapshot_per_event(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            persist_calls = []
            with patch.object(oc_codex_server, "persist_tasks",
                              side_effect=lambda: persist_calls.append(1)), \
                    patch.object(oc_codex_server, "WEB_TASK_PERSISTENCE_ENABLED", True), \
                    patch.object(oc_codex_server, "TASK_HISTORY_DIR",
                                 os.path.join(directory, ".task_history")):
                for index in range(10_000):
                    task._record_event({"type": "thinking", "text": f"t{index}"})
                path = oc_codex_server._task_history_path(task.id)
                self.assertEqual(sum(1 for _ in open(path, encoding="utf-8")), 10_000)
            self.assertEqual(len(persist_calls), 0)
            self.assertLessEqual(len(task.log), oc_codex_server.EVENT_LOG_HOT_WINDOW * 2)
            self.assertEqual(task.event_seq, 10_000)

    def test_snapshot_is_bounded_and_does_not_contain_full_log(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            with patch.object(oc_codex_server, "WEB_TASK_PERSISTENCE_ENABLED", True), \
                    patch.object(oc_codex_server, "TASK_HISTORY_DIR",
                              os.path.join(directory, ".task_history")), \
                    patch.object(oc_codex_server, "TASKS_STATE_PATH",
                                 os.path.join(directory, ".web_tasks.json")), \
                    patch.object(oc_codex_server, "TASKS", {task.id: task}):
                for index in range(50):
                    task._record_event({"type": "thinking", "text": f"t{index}"})
                oc_codex_server.persist_tasks()
                with open(oc_codex_server.TASKS_STATE_PATH, encoding="utf-8") as fh:
                    rows = json.load(fh)
            row = next(item for item in rows if item["id"] == task.id)
            self.assertNotIn("log", row)
            self.assertEqual(row["eventSeq"], 50)

    def test_events_do_not_mix_across_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            task_a = self._task(directory, task_id="journal-a")
            task_b = self._task(directory, task_id="journal-b")
            with patch.object(oc_codex_server, "WEB_TASK_PERSISTENCE_ENABLED", True), \
                    patch.object(oc_codex_server, "TASK_HISTORY_DIR",
                              os.path.join(directory, ".task_history")):
                task_a._record_event({"type": "user", "text": "a0"})
                task_b._record_event({"type": "user", "text": "b0"})
                task_a._record_event({"type": "assistant", "text": "a1"})
                path_a = oc_codex_server._task_history_path(task_a.id)
                path_b = oc_codex_server._task_history_path(task_b.id)
                events_a = [json.loads(line) for line in open(path_a, encoding="utf-8")]
                events_b = [json.loads(line) for line in open(path_b, encoding="utf-8")]
            self.assertEqual([event["text"] for event in events_a], ["a0", "a1"])
            self.assertEqual([event["text"] for event in events_b], ["b0"])

    def test_seq_is_monotonic_and_resumes_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            with patch.object(oc_codex_server, "WEB_TASK_PERSISTENCE_ENABLED", True), \
                    patch.object(oc_codex_server, "TASK_HISTORY_DIR",
                              os.path.join(directory, ".task_history")):
                for index in range(5):
                    task._record_event({"type": "thinking", "text": f"t{index}"})
                restored = self._task(directory)
                restored.id = task.id
                restored.event_seq = 0
                path = oc_codex_server._task_history_path(task.id)
                last_seq = oc_codex_server._journal_last_valid_seq(
                    path, lock=oc_codex_server.TASK_HISTORY_LOCK)
                restored.event_seq = (int(last_seq) + 1) if last_seq is not None else 0
                next_event = restored._record_event({"type": "assistant", "text": "after"})
            self.assertEqual(next_event["seq"], 5)

    def test_client_message_id_is_idempotent_with_bounded_index(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            with patch.object(oc_codex_server, "WEB_TASK_PERSISTENCE_ENABLED", True), \
                    patch.object(oc_codex_server, "TASK_HISTORY_DIR",
                              os.path.join(directory, ".task_history")):
                first = task._record_event(
                    {"type": "user", "text": "继续", "clientMessageId": "cm-retry"})
                replay = task._record_event(
                    {"type": "user", "text": "继续", "clientMessageId": "cm-retry"})
                for index in range(oc_codex_server.EVENT_CLIENT_ID_INDEX_SIZE + 100):
                    task._record_event({"type": "thinking", "text": f"t{index}"})
                journal_len = sum(1 for _ in open(
                    oc_codex_server._task_history_path(task.id), encoding="utf-8"))
            self.assertIs(replay, first)
            self.assertEqual(journal_len, 1 + oc_codex_server.EVENT_CLIENT_ID_INDEX_SIZE + 100)
            self.assertLessEqual(len(task._client_message_ids),
                                 oc_codex_server.EVENT_CLIENT_ID_INDEX_SIZE)

    def test_truncated_last_line_is_recoverable(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            with patch.object(oc_codex_server, "WEB_TASK_PERSISTENCE_ENABLED", True), \
                    patch.object(oc_codex_server, "TASK_HISTORY_DIR",
                              os.path.join(directory, ".task_history")):
                for index in range(5):
                    task._record_event({"type": "thinking", "text": f"t{index}"})
                path = oc_codex_server._task_history_path(task.id)
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write('{"seq": 5, "type": "partial"')
                loaded = oc_codex_server._load_task_history(task.id)
                self.assertEqual([event["seq"] for event in loaded], [0, 1, 2, 3, 4])

    def test_legacy_snapshot_log_migrates_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            events = [{"type": "user", "text": f"m{i}", "seq": i} for i in range(5)]
            rows = [{
                **task.summary(), "log": events, "eventSeq": 5,
                "missionContext": {}, "platformUploadedFiles": {},
                "platformOutputPrefix": "", "platformLastError": "",
                "sessionId": "", "userId": task.user_id,
                "workspace": task.workspace, "taskWorkspace": "",
            }]
            with patch.object(oc_codex_server, "SANDBOX_DIR", directory), \
                    patch.object(oc_codex_server, "WEB_TASK_PERSISTENCE_ENABLED", True), \
                    patch.object(oc_codex_server, "TASK_HISTORY_DIR",
                                 os.path.join(directory, ".task_history")), \
                    patch.object(oc_codex_server, "TASKS_STATE_PATH",
                                 os.path.join(directory, ".web_tasks.json")), \
                    patch.object(oc_codex_server, "TASKS", {}), \
                    patch.object(oc_codex_server, "persist_tasks"):
                os.makedirs(os.path.join(directory, "p"), exist_ok=True)
                with open(oc_codex_server.TASKS_STATE_PATH, "w", encoding="utf-8") as fh:
                    json.dump(rows, fh)
                oc_codex_server.restore_tasks()
                restored = oc_codex_server.TASKS.get(task.id)
                self.assertIsNotNone(restored)
                self.assertEqual(restored.event_seq, 5)
                path = oc_codex_server._task_history_path(task.id)
                self.assertEqual(sum(1 for _ in open(path, encoding="utf-8")), 5)
                # Second restart must not re-import the snapshot log.
                oc_codex_server.TASKS = {}
                oc_codex_server.restore_tasks()
                restored2 = oc_codex_server.TASKS.get(task.id)
                self.assertEqual(restored2.event_seq, 5)
                self.assertEqual(
                    sum(1 for _ in open(path, encoding="utf-8")), 5)

    def test_restore_trusts_journal_seq_over_lagging_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            with patch.object(oc_codex_server, "WEB_TASK_PERSISTENCE_ENABLED", True), \
                    patch.object(oc_codex_server, "TASK_HISTORY_DIR",
                              os.path.join(directory, ".task_history")):
                for index in range(7):
                    task._record_event({"type": "thinking", "text": f"t{index}"})
                rows = [{
                    **task.summary(), "log": [], "eventSeq": 3,  # lagging
                    "missionContext": {}, "platformUploadedFiles": {},
                    "platformOutputPrefix": "", "platformLastError": "",
                    "sessionId": "", "userId": task.user_id,
                    "workspace": task.workspace, "taskWorkspace": "",
                }]
            with patch.object(oc_codex_server, "SANDBOX_DIR", directory), \
                    patch.object(oc_codex_server, "WEB_TASK_PERSISTENCE_ENABLED", True), \
                    patch.object(oc_codex_server, "TASK_HISTORY_DIR",
                                 os.path.join(directory, ".task_history")), \
                    patch.object(oc_codex_server, "TASKS_STATE_PATH",
                                 os.path.join(directory, ".web_tasks.json")), \
                    patch.object(oc_codex_server, "TASKS", {}), \
                    patch.object(oc_codex_server, "persist_tasks"):
                os.makedirs(os.path.join(directory, "p"), exist_ok=True)
                with open(oc_codex_server.TASKS_STATE_PATH, "w", encoding="utf-8") as fh:
                    json.dump(rows, fh)
                oc_codex_server.restore_tasks()
                restored = oc_codex_server.TASKS.get(task.id)
                self.assertIsNotNone(restored)
                self.assertEqual(restored.event_seq, 7)

    def test_restore_legacy_journal_without_seq_uses_event_positions(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            legacy_events = [
                {"type": "user", "text": "question"},
                {"type": "assistant", "text": "answer"},
                {"type": "done"},
            ]
            rows = [{
                **task.summary(), "log": [], "eventSeq": 0,
                "missionContext": {}, "platformUploadedFiles": {},
                "platformOutputPrefix": "", "platformLastError": "",
                "sessionId": "", "userId": task.user_id,
                "workspace": task.workspace, "taskWorkspace": "",
            }]
            with patch.object(oc_codex_server, "SANDBOX_DIR", directory), \
                    patch.object(oc_codex_server, "WEB_TASK_PERSISTENCE_ENABLED", True), \
                    patch.object(oc_codex_server, "TASK_HISTORY_DIR",
                                 os.path.join(directory, ".task_history")), \
                    patch.object(oc_codex_server, "TASKS_STATE_PATH",
                                 os.path.join(directory, ".web_tasks.json")), \
                    patch.object(oc_codex_server, "TASKS", {}), \
                    patch.object(oc_codex_server, "persist_tasks"):
                os.makedirs(os.path.join(directory, "p"), exist_ok=True)
                os.makedirs(oc_codex_server.TASK_HISTORY_DIR, exist_ok=True)
                with open(oc_codex_server.TASKS_STATE_PATH, "w", encoding="utf-8") as fh:
                    json.dump(rows, fh)
                with open(oc_codex_server._task_history_path(task.id), "w",
                          encoding="utf-8") as fh:
                    for event in legacy_events:
                        fh.write(json.dumps(event) + "\n")
                oc_codex_server.restore_tasks()
                restored = oc_codex_server.TASKS.get(task.id)
                self.assertIsNotNone(restored)
                self.assertEqual(restored.event_seq, 3)
                self.assertEqual(len(restored.log), 3)

    def test_working_snapshot_recovers_as_interrupted_and_retryable(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            rows = [{
                **task.summary(), "status": "working", "log": [], "eventSeq": 0,
                "activeExecutionId": "stale-execution",
                "missionContext": {}, "platformUploadedFiles": {},
                "platformOutputPrefix": "", "platformLastError": "",
                "sessionId": "", "userId": task.user_id,
                "workspace": task.workspace, "taskWorkspace": "",
            }]
            with patch.object(oc_codex_server, "SANDBOX_DIR", directory), \
                    patch.object(oc_codex_server, "WEB_TASK_PERSISTENCE_ENABLED", True), \
                    patch.object(oc_codex_server, "TASK_HISTORY_DIR",
                                 os.path.join(directory, ".task_history")), \
                    patch.object(oc_codex_server, "TASKS_STATE_PATH",
                                 os.path.join(directory, ".web_tasks.json")), \
                    patch.object(oc_codex_server, "TASKS", {}), \
                    patch.object(oc_codex_server, "persist_tasks"):
                os.makedirs(os.path.join(directory, "p"), exist_ok=True)
                with open(oc_codex_server.TASKS_STATE_PATH, "w", encoding="utf-8") as fh:
                    json.dump(rows, fh)
                oc_codex_server.restore_tasks()
                restored = oc_codex_server.TASKS.get(task.id)
                self.assertIsNotNone(restored)
                self.assertEqual(restored.status, "error")
                self.assertEqual(restored.active_execution_id, "")
                # A new execution is claimable after the interruption.
                execution_id, active_id = restored.claim_execution()
                self.assertTrue(execution_id)
                self.assertEqual(active_id, "")


class TaskEventPaginationTests(unittest.TestCase):
    """P0-2: 47313 uses absolute-position windows with the shared cursor
    protocol instead of returning the full journal."""

    def _task(self, directory, task_id="abc123", user_id="test"):
        task = oc_codex_server.Task("p", directory, task_id=task_id, user_id=user_id)
        task.conv = _FakeConversation()
        return task

    def _seed(self, task, count):
        with patch.object(oc_codex_server, "WEB_TASK_PERSISTENCE_ENABLED", True), \
                    patch.object(oc_codex_server, "TASK_HISTORY_DIR",
                          os.path.join(task.cwd, ".task_history")):
            for index in range(count):
                task._record_event({"type": "thinking", "text": f"t{index}"})
        return task.event_seq

    def test_tail_returns_only_last_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            total = self._seed(task, 500)
            self.assertEqual(total, 500)
            window = oc_codex_server._tail_task_events(task, 160)
            self.assertEqual(len(window), 160)
            self.assertEqual(window[0]["seq"], 340)
            self.assertEqual(window[-1]["seq"], 499)

    def test_before_pages_are_adjacent_without_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            total = self._seed(task, 1000)
            start, end = oc_codex_server._parse_event_window({"tail": ["1"], "limit": ["200"]}, total)
            first = oc_codex_server._read_task_event_window(task, start, end)
            prev_start, prev_end = oc_codex_server._parse_event_window(
                {"before": [str(start)], "limit": ["200"]}, total)
            second = oc_codex_server._read_task_event_window(task, prev_start, prev_end)
            self.assertEqual(end, 1000)
            self.assertEqual(prev_end, start)
            self.assertEqual([event["seq"] for event in first], list(range(800, 1000)))
            self.assertEqual([event["seq"] for event in second], list(range(600, 800)))

    def test_since_does_not_skip_or_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            total = self._seed(task, 100)
            start, end = oc_codex_server._parse_event_window({"since": ["95"]}, total)
            delta = oc_codex_server._read_task_event_window(task, start, end)
            self.assertEqual([event["seq"] for event in delta], [95, 96, 97, 98, 99])
            self.assertEqual(oc_codex_server._event_window_response(
                delta, start, end, total)["nextCursor"], 100)

    def test_window_response_absolute_cursor(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            total = self._seed(task, 300)
            start, end = oc_codex_server._parse_event_window(
                {"before": ["200"], "limit": ["80"]}, total)
            events = oc_codex_server._read_task_event_window(task, start, end)
            payload = oc_codex_server._event_window_response(
                events, start, end, total, scope_id=task.id, scope_key="taskId")
            self.assertEqual(payload["taskId"], task.id)
            self.assertEqual(payload["eventStart"], 120)
            self.assertEqual(payload["eventEnd"], 200)
            self.assertEqual(payload["eventTotal"], 300)
            self.assertEqual(payload["nextCursor"], payload["eventEnd"])
            self.assertTrue(payload["eventHasMore"])

    def test_limit_is_capped_at_safe_ceiling(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            total = self._seed(task, 1000)
            start, end = oc_codex_server._parse_event_window(
                {"tail": ["1"], "limit": ["9999"]}, total)
            self.assertEqual(end - start, 200)

    def test_get_task_detail_defaults_to_summary_without_full_log(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            self._seed(task, 300)
            handler = object.__new__(oc_codex_server.Handler)
            handler.path = f"/api/tasks/{task.id}"
            handler.headers = {}
            handler._requires_auth = lambda path: False
            handler._current_user = lambda: "test"
            handler._owned_task_for_detail = lambda task_id, repo="", code="": task
            response = []
            handler._send_json = lambda payload, status=200: response.append((status, payload))
            with patch.object(oc_codex_server, "WEB_TASK_PERSISTENCE_ENABLED", True), \
                    patch.object(oc_codex_server, "TASK_HISTORY_DIR",
                              os.path.join(directory, ".task_history")):
                handler.do_GET()
            self.assertEqual(response[0][0], 200)
            payload = response[0][1]
            self.assertEqual(payload["log"], [])
            self.assertEqual(payload["logTotal"], 300)
            self.assertEqual(payload["logStart"], 0)

    def test_get_task_detail_tail_is_limit_capped(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            self._seed(task, 300)
            handler = object.__new__(oc_codex_server.Handler)
            handler.path = f"/api/tasks/{task.id}?tail=1&limit=50"
            handler.headers = {}
            handler._requires_auth = lambda path: False
            handler._current_user = lambda: "test"
            handler._owned_task_for_detail = lambda task_id, repo="", code="": task
            response = []
            handler._send_json = lambda payload, status=200: response.append((status, payload))
            with patch.object(oc_codex_server, "WEB_TASK_PERSISTENCE_ENABLED", True), \
                    patch.object(oc_codex_server, "TASK_HISTORY_DIR",
                              os.path.join(directory, ".task_history")):
                handler.do_GET()
            payload = response[0][1]
            self.assertEqual(len(payload["log"]), 50)
            self.assertEqual(payload["log"][0]["seq"], 250)
            self.assertEqual(payload["logStart"], 250)
            self.assertEqual(payload["nextCursor"], 300)

    def test_get_task_list_never_returns_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            self._seed(task, 30)
            handler = object.__new__(oc_codex_server.Handler)
            handler.path = "/api/tasks"
            handler.headers = {}
            handler._requires_auth = lambda path: False
            handler._current_user = lambda: "test"
            handler._mission_task_user_matches = lambda t, user: True
            response = []
            handler._send_json = lambda payload, status=200: response.append((status, payload))
            with patch.object(oc_codex_server, "TASKS", {task.id: task}):
                handler.do_GET()
            items = response[0][1]["tasks"]
            self.assertEqual(len(items), 1)
            self.assertNotIn("log", items[0])
            self.assertNotIn("events", items[0])


class TaskExecutionClaimTests(unittest.TestCase):
    """P0-3: same-task execution uses a short atomic claim; the second request
    gets ACTIVE_RUN_EXISTS immediately instead of blocking."""

    def _task(self, directory, task_id="claim-task", user_id="test"):
        task = oc_codex_server.Task("p", directory, task_id=task_id, user_id=user_id)
        task.conv = _FakeConversation()
        return task

    def test_concurrent_claims_only_one_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            results = []
            barrier = threading.Barrier(2)

            def attempt():
                barrier.wait()
                results.append(task.claim_execution())

            threads = [threading.Thread(target=attempt) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
            winners = [execution_id for execution_id, active_id in results if execution_id]
            self.assertEqual(len(winners), 1)
            self.assertEqual(len(results), 2)
            rejected = [active_id for execution_id, active_id in results if not execution_id]
            self.assertEqual(rejected, [winners[0]])

    def test_release_clears_claim_and_old_finally_cannot_clear_new(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            first, _ = task.claim_execution()
            self.assertEqual(task.active_execution_id, first)
            task.release_execution(first)
            self.assertEqual(task.active_execution_id, "")
            second, _ = task.claim_execution()
            self.assertTrue(second)
            self.assertNotEqual(second, first)
            # A stale worker's finally from the first execution must never
            # clear the newer execution's claim.
            task.release_execution(first)
            self.assertEqual(task.active_execution_id, second)
            task.release_execution(second)
            self.assertEqual(task.active_execution_id, "")

    def test_exception_cleanup_releases_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            execution_id, _ = task.claim_execution()
            try:
                raise RuntimeError("boom")
            except RuntimeError:
                task.release_execution(execution_id)
            self.assertEqual(task.active_execution_id, "")
            new_id, _ = task.claim_execution()
            self.assertTrue(new_id)
            self.assertNotEqual(new_id, execution_id)

    def test_stream_turn_clears_its_own_claim_in_finally(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            task.user_id = ""
            execution_id, _ = task.claim_execution()
            emitted = []

            def fake_stream_message(client, messages, system_prompt, **kwargs):
                yield {"type": "text_delta", "text": "hi"}

            fake_runtime = SimpleNamespace(stream_message=fake_stream_message)
            with patch.object(oc_codex_server.AGENT_RUNTIME, "get",
                              return_value=fake_runtime), \
                    patch.object(oc_codex_server, "persist_tasks"), \
                    patch.object(oc_codex_server, "WEB_TASK_PERSISTENCE_ENABLED", True), \
                    patch.object(oc_codex_server, "TASK_HISTORY_DIR",
                                 os.path.join(directory, ".task_history")):
                task.stream_turn("hi", emitted.append, execution_id=execution_id)
            self.assertEqual(task.active_execution_id, "")
            self.assertEqual(task.status, "idle")

    def test_working_chat_request_gets_active_run_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            execution_id, _ = task.claim_execution()
            self.assertTrue(execution_id)
            # A chat attempt during the active execution must not start a
            # second Conversation turn: it is rejected by the same claim gate.
            again_id, active_id = task.claim_execution()
            self.assertEqual(again_id, "")
            self.assertEqual(active_id, execution_id)


class TaskHealthMetricsTests(unittest.TestCase):
    """313 /health must expose the unified coordinator metrics."""

    def test_health_reports_coordination_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            coordinator = oc_codex_server._ExecutionCoordinator(
                oc_codex_server._CoordinatorConfig(
                    backend="file", max_active=2, max_active_per_user=2,
                    max_queued_per_user=3, max_queued=5,
                    provider_concurrency=2, database_concurrency=2,
                    lease_dir=os.path.join(directory, ".leases")),
                oc_codex_server._TaskExecutionAdapter())
            try:
                handler = object.__new__(oc_codex_server.Handler)
                handler.path = "/health"
                handler.headers = {}
                response = []
                handler._send_json = lambda payload, status=200: response.append((status, payload))
                with patch.object(oc_codex_server, "EXECUTION_COORDINATOR", coordinator):
                    handler.do_GET()
                status, payload = response[0]
                self.assertEqual(status, 200)
                self.assertIn("concurrency", payload)
                self.assertIn("coordination", payload)
                coordination = payload["coordination"]
                self.assertEqual(coordination["backend"], "file")
                self.assertTrue(coordination["multiProcessSafe"])
                self.assertFalse(coordination["multiHostSafe"])
                # A file/local backend must never claim cluster-wide quotas.
                self.assertEqual(coordination["quotaScope"], "process")
                self.assertEqual(coordination["queueScope"], "process")
            finally:
                coordinator.shutdown()


class CoordinatorBackendConfigTests(unittest.TestCase):
    """313 coordinator backend selection (file | redis | none)."""

    def test_redis_backend_creates_redis_coordinator(self):
        import types
        from open_claude.execution_coordinator import _RedisBackend

        class _FakeRedisClient:
            def __init__(self, *args, **kwargs):
                pass

            @staticmethod
            def from_url(url, decode_responses=False):
                return _FakeRedisClient()

            def ping(self):
                return True

            def scan_iter(self, match=None, count=10):
                return iter(())

            def eval(self, script, numkeys, *args):
                return 1

        fake_redis = types.ModuleType("redis")
        fake_redis.Redis = _FakeRedisClient
        try:
            with patch.dict(os.environ, {
                "TASKS_COORDINATOR_BACKEND": "redis",
                "TASKS_REDIS_URL": "redis://127.0.0.1:6379/0",
                "TASKS_REDIS_PREFIX": "ontology:47313:",
                "TASKS_LEASE_STORE": "none",
            }, clear=False),                     patch.dict(sys.modules, {"redis": fake_redis}),                     patch.object(oc_codex_server, "TASK_LEASE_STORE", None):
                oc_codex_server.configure_execution_coordinator()
                coordinator = oc_codex_server.EXECUTION_COORDINATOR
                self.assertIsNotNone(coordinator)
                self.assertIsInstance(coordinator.backend, _RedisBackend)
                self.assertEqual(coordinator.config.backend, "redis")
                self.assertEqual(coordinator.config.redis_url,
                                 "redis://127.0.0.1:6379/0")
                self.assertEqual(coordinator.config.redis_prefix,
                                 "ontology:47313:")
                metrics = coordinator.metrics()["coordination"]
                self.assertEqual(metrics["backend"], "redis")
                self.assertTrue(metrics["multiHostSafe"])
                self.assertEqual(metrics["quotaScope"], "cluster")
                self.assertEqual(metrics["queueScope"], "cluster")
                coordinator.shutdown()
        finally:
            oc_codex_server.EXECUTION_COORDINATOR = None
            oc_codex_server.TASK_PROVIDER_SLOTS = None
            oc_codex_server.TASK_DATABASE_SLOTS = None

    def test_redis_backend_requires_url(self):
        with patch.dict(os.environ, {
            "TASKS_COORDINATOR_BACKEND": "redis",
            "TASKS_LEASE_STORE": "none",
        }, clear=False):
            with self.assertRaises(ValueError):
                oc_codex_server.configure_execution_coordinator()

    def test_none_backend_disables_coordinator(self):
        with patch.dict(os.environ, {
            "TASKS_COORDINATOR_BACKEND": "none",
        }, clear=False):
            oc_codex_server.configure_execution_coordinator()
            self.assertIsNone(oc_codex_server.EXECUTION_COORDINATOR)
            self.assertIsNone(oc_codex_server.TASK_PROVIDER_SLOTS)

    def test_redis_ping_failure_fails_startup(self):
        import types

        class _UnreachableClient:
            def __init__(self, *args, **kwargs):
                pass

            @staticmethod
            def from_url(url, decode_responses=False):
                return _UnreachableClient()

            def ping(self):
                raise ConnectionError("redis unreachable")

        fake_redis = types.ModuleType("redis")
        fake_redis.Redis = _UnreachableClient
        with patch.dict(os.environ, {
            "TASKS_COORDINATOR_BACKEND": "redis",
            "TASKS_REDIS_URL": "redis://127.0.0.1:6379/0",
            "TASKS_LEASE_STORE": "none",
        }, clear=False),                 patch.dict(sys.modules, {"redis": fake_redis}):
            with self.assertRaises(RuntimeError):
                oc_codex_server.configure_execution_coordinator()

    def test_redis_eval_failure_fails_startup(self):
        import types

        class _NoEvalClient:
            def __init__(self, *args, **kwargs):
                pass

            @staticmethod
            def from_url(url, decode_responses=False):
                return _NoEvalClient()

            def ping(self):
                return True

            def eval(self, script, numkeys, *args):
                raise ConnectionError("EVAL not supported")

            def scan_iter(self, match=None, count=10):
                return iter(())

        fake_redis = types.ModuleType("redis")
        fake_redis.Redis = _NoEvalClient
        with patch.dict(os.environ, {
            "TASKS_COORDINATOR_BACKEND": "redis",
            "TASKS_REDIS_URL": "redis://127.0.0.1:6379/0",
            "TASKS_LEASE_STORE": "none",
        }, clear=False),                 patch.dict(sys.modules, {"redis": fake_redis}):
            with self.assertRaises(RuntimeError) as ctx:
                oc_codex_server.configure_execution_coordinator()
            self.assertIn("EVAL", str(ctx.exception))

    def test_file_backend_does_not_require_redis_package(self):
        # A file/local coordinator must start without the redis package
        # installed; the redis import only happens for backend=redis.
        import types
        fake_redis = types.ModuleType("redis")
        try:
            with patch.dict(sys.modules, {"redis": fake_redis}), \
                    patch.dict(os.environ, {
                        "TASKS_COORDINATOR_BACKEND": "file",
                        "TASKS_LEASE_STORE": "none",
                    }, clear=False), \
                    patch.object(oc_codex_server, "TASK_LEASE_STORE", None):
                oc_codex_server.configure_execution_coordinator()
                coordinator = oc_codex_server.EXECUTION_COORDINATOR
                self.assertIsNotNone(coordinator)
                self.assertEqual(coordinator.config.backend, "file")
                coordinator.shutdown()
        finally:
            oc_codex_server.EXECUTION_COORDINATOR = None
            oc_codex_server.TASK_PROVIDER_SLOTS = None
            oc_codex_server.TASK_DATABASE_SLOTS = None


class _FakeWFile:
    def __init__(self, sink):
        self.sink = sink

    def write(self, data):
        self.sink.append(data)

    def flush(self):
        pass


class TaskSchedulerIntegrationTests(unittest.TestCase):
    """P1: bounded fair worker-pool admission wired into the send handler."""

    def _task(self, directory, task_id="sched-task", user_id="test"):
        task = oc_codex_server.Task("p", directory, task_id=task_id, user_id=user_id)
        task.conv = _FakeConversation()
        return task

    def _send_handler(self, task, body=None, wfile_sink=None):
        handler = object.__new__(oc_codex_server.Handler)
        handler.path = f"/api/tasks/{task.id}/send"
        handler.headers = {}
        handler._auth_cookie_to_set = ""
        handler._owned_task = lambda task_id, claim_legacy=True: task
        handler._read_body = lambda: body or {"message": "继续"}
        responses = []
        handler._send_json = lambda payload, status=200: responses.append((status, payload))
        if wfile_sink is not None:
            handler.wfile = _FakeWFile(wfile_sink)
            handler.send_response = lambda status: None
            handler.send_header = lambda name, value: None
            handler.end_headers = lambda: None
        return handler, responses

    def test_send_queue_full_returns_429_and_releases_claim(self):
        class _BlockingAdapter(oc_codex_server._TaskExecutionAdapter):
            def __init__(self):
                super().__init__()
                self.gate = threading.Event()

            def run_worker(self, execution_id, token):
                # Hold the worker so an admitted blocker keeps its slot
                # instead of releasing the claim asynchronously (which would
                # race with the queue-full assertion below).
                self.gate.wait(timeout=10)
                super().run_worker(execution_id, token)

        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            adapter = _BlockingAdapter()
            coordinator = oc_codex_server._ExecutionCoordinator(
                oc_codex_server._CoordinatorConfig(
                    backend="none", max_active=1, max_active_per_user=1,
                    max_queued_per_user=1, max_queued=1,
                    provider_concurrency=2, database_concurrency=2),
                adapter)
            try:
                # Occupy the active slot and the only queue slot so the send
                # below hits the global queue limit.
                first = coordinator.claim("blocker-1", "exec-b1", "other-user")
                self.assertEqual(first.decision, "admitted")
                second = coordinator.claim("blocker-2", "exec-b2", "other-user")
                self.assertEqual(second.decision, "queued")
                handler, responses = self._send_handler(task)
                with patch.object(oc_codex_server, "EXECUTION_COORDINATOR", coordinator), \
                        patch.object(oc_codex_server, "persist_tasks"):
                    handler._handle_send(task.id)
                self.assertEqual(len(responses), 1)
                status, payload = responses[0]
                self.assertEqual(status, 429)
                self.assertEqual(payload["code"], "GLOBAL_QUEUE_FULL")
                self.assertEqual(payload["taskId"], task.id)
                # The claim is released so the task is immediately retryable.
                self.assertEqual(task.active_execution_id, "")
            finally:
                adapter.gate.set()
                coordinator.shutdown()

    def test_send_queued_then_admitted_records_events_and_runs(self):
        class _BlockingAdapter(oc_codex_server._TaskExecutionAdapter):
            def __init__(self):
                super().__init__()
                self.gate = threading.Event()

            def run_worker(self, execution_id, token):
                self.gate.wait(timeout=10)
                super().run_worker(execution_id, token)

        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            adapter = _BlockingAdapter()
            coordinator = oc_codex_server._ExecutionCoordinator(
                oc_codex_server._CoordinatorConfig(
                    backend="none", max_active=1, max_active_per_user=1,
                    max_queued_per_user=10, max_queued=10,
                    provider_concurrency=2, database_concurrency=2),
                adapter)
            try:
                # Occupy the only worker slot so the send below must queue.
                blocker = coordinator.claim("blocker", "exec-b", "other-user")
                self.assertEqual(blocker.decision, "admitted")

                handler, responses = self._send_handler(task)
                calls = []

                def fake_stream_turn(text, emit, display_text=None,
                                     platform_authorization="",
                                     conversational=False,
                                     client_message_id="", execution_id="",
                                     **_kwargs):
                    calls.append({"text": text, "execution_id": execution_id})
                    emit({"type": "done", "status": "idle"})

                with patch.object(oc_codex_server, "EXECUTION_COORDINATOR", coordinator), \
                        patch.object(oc_codex_server, "persist_tasks"), \
                        patch.object(oc_codex_server, "_append_task_history"), \
                        patch.object(oc_codex_server, "TASKS", {task.id: task}), \
                        patch.object(task, "stream_turn", fake_stream_turn):
                    handler._handle_send(task.id)
                    # The handler returns 202 immediately with a queued status
                    # and never blocks the HTTP thread.
                    self.assertEqual(len(responses), 1)
                    status, payload = responses[0]
                    self.assertEqual(status, 202)
                    self.assertEqual(payload["taskId"], task.id)
                    self.assertEqual(payload["status"], "queued")
                    self.assertGreaterEqual(payload["queuePosition"], 1)
                    self.assertIn("nextCursor", payload)
                    # Let the blocker finish; the worker pool admits the
                    # task's execution and runs the fake turn.  The global
                    # TASKS patch must stay active while the background worker
                    # resolves the task.
                    adapter.gate.set()
                    deadline = time.time() + 10
                    while (not calls and time.time() < deadline):
                        time.sleep(0.01)
                    self.assertEqual(len(calls), 1)
                    self.assertTrue(calls[0]["execution_id"])
                    # The worker records run_started and releases the claim
                    # even though the fake stream_turn does not (the adapter
                    # does).
                    deadline = time.time() + 10
                    while (task.active_execution_id and time.time() < deadline):
                        time.sleep(0.01)
                    self.assertEqual(task.active_execution_id, "")
                    event_types = [event.get("type") for event in task.log]
                    self.assertIn("run_started", event_types)
                    self.assertIn("run_queued", event_types)
            finally:
                coordinator.shutdown()

    def test_queued_snapshot_recovers_as_interrupted_and_retryable(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            rows = [{
                **task.summary(), "status": "queued", "log": [], "eventSeq": 0,
                "activeExecutionId": "stale-execution",
                "missionContext": {}, "platformUploadedFiles": {},
                "platformOutputPrefix": "", "platformLastError": "",
                "sessionId": "", "userId": task.user_id,
                "workspace": task.workspace, "taskWorkspace": "",
            }]
            with patch.object(oc_codex_server, "SANDBOX_DIR", directory), \
                    patch.object(oc_codex_server, "WEB_TASK_PERSISTENCE_ENABLED", True), \
                    patch.object(oc_codex_server, "TASK_HISTORY_DIR",
                                 os.path.join(directory, ".task_history")), \
                    patch.object(oc_codex_server, "TASKS_STATE_PATH",
                                 os.path.join(directory, ".web_tasks.json")), \
                    patch.object(oc_codex_server, "TASKS", {}), \
                    patch.object(oc_codex_server, "persist_tasks"):
                os.makedirs(os.path.join(directory, "p"), exist_ok=True)
                with open(oc_codex_server.TASKS_STATE_PATH, "w", encoding="utf-8") as fh:
                    json.dump(rows, fh)
                oc_codex_server.restore_tasks()
                restored = oc_codex_server.TASKS.get(task.id)
                self.assertIsNotNone(restored)
                self.assertEqual(restored.status, "error")
                self.assertEqual(restored.active_execution_id, "")
                execution_id, active_id = restored.claim_execution()
                self.assertTrue(execution_id)
                self.assertEqual(active_id, "")

    def test_completion_gate_blocks_queued_task(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            task.status = "queued"
            issues = oc_codex_server.task_completion_gate(task)
            codes = [issue["code"] for issue in issues]
            self.assertIn("TASK_STATE_CONFLICT", codes)

    def test_completion_gate_allows_prior_failed_state_when_artifacts_are_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            task.status = "error"
            task.platform_status = "FAILED"
            task.mission_context = {"expectedFiles": ["business_objects.csv"]}
            task.platform_uploaded_files = {"business_objects.csv": {"sha256": "abc"}}
            issues = oc_codex_server.task_completion_gate(task)
            self.assertNotIn("TASK_STATE_CONFLICT", [issue["code"] for issue in issues])


if __name__ == "__main__":
    unittest.main()


class TaskAdapterFenceTests(unittest.TestCase):
    """313: platform RUNNING callbacks are fenced by the coordinator lease.

    A lease-lost or stale worker must never fire RUNNING/FAILED over a newer
    execution's platform state; the adapter guard stops the callback before
    it reaches the platform.
    """

    def _fenced_task(self, directory, task_id="fence-task"):
        task = oc_codex_server.Task(
            project="fence", cwd=directory, task_type="modeling",
            task_code="RM-FENCE", repository_id="1",
            mission_context={"taskType": "modeling",
                             "repositoryId": "1", "taskCode": "RM-FENCE",
                             "expectedFiles": []},
            user_id="test", defer_runtime=True)
        task.conv = _FakeConversation()
        task.platform_status = "PENDING"
        return task

    def test_run_started_callback_fires_once_and_is_fence_guarded(self):
        from open_claude.execution_lease import FileExecutionLeaseStore
        with tempfile.TemporaryDirectory() as directory:
            lease_dir = os.path.join(directory, "leases")
            lease_store = FileExecutionLeaseStore(lease_dir, lease_seconds=30)

            class _HoldingAdapter(oc_codex_server._TaskExecutionAdapter):
                def __init__(self):
                    super().__init__()
                    self.gate = threading.Event()

                def run_worker(self, task_id, token):
                    self.gate.wait(timeout=10)

            adapter = _HoldingAdapter()
            coordinator = oc_codex_server._ExecutionCoordinator(
                oc_codex_server._CoordinatorConfig(
                    backend="file", max_active=1, max_active_per_user=1,
                    max_queued_per_user=2, max_queued=2,
                    provider_concurrency=1, database_concurrency=1,
                    lease_seconds=30, heartbeat_seconds=0.05,
                    max_heartbeat_failures=2, lease_dir=lease_dir),
                adapter, lease_store=lease_store)
            try:
                task = self._fenced_task(directory)
                claim = coordinator.claim(task.id, "exec-1", task.user_id)
                self.assertEqual(claim.decision, "admitted")
                adapter.register("exec-1", task.id, "开始建模", "开始建模",
                                 False, "cm-1", "Bearer x",
                                 platform_execution=True)
                calls = []
                with patch.object(oc_codex_server, "EXECUTION_COORDINATOR",
                                  coordinator), \
                        patch.object(oc_codex_server, "TASKS",
                                     {task.id: task}), \
                        patch.object(oc_codex_server, "persist_tasks"), \
                        patch.object(oc_codex_server, "_append_task_history"), \
                        patch.object(oc_codex_server, "task_status_callback",
                                     side_effect=lambda *a, **k:
                                     calls.append(a[1]) or {"ok": True}):
                    # The worker's on_started fires the RUNNING callback once.
                    deadline = time.time() + 5
                    while not calls and time.time() < deadline:
                        time.sleep(0.01)
                    self.assertEqual(calls, ["RUNNING"])
                    self.assertEqual(task.platform_status, "RUNNING")
                    # A second on_started is idempotent (already RUNNING).
                    adapter.on_started(task.id)
                    self.assertEqual(calls, ["RUNNING"])
                    # A newer owner steals the lease; the stale worker's
                    # RUNNING callback must be blocked by the fence guard.
                    lease_store.release(task.id, "exec-1")
                    lease_store.try_claim(task.id, "other-instance", "exec-2",
                                          lease_seconds=30)
                    adapter.on_started(task.id)
                    self.assertEqual(calls, ["RUNNING"])
            finally:
                adapter.gate.set()
                coordinator.shutdown()


class TaskLifecycleGateTests(unittest.TestCase):
    """P1/P2 final acceptance: unified 313 lifecycle concurrency gate.

    queued/working (or a live execution claim) must block result uploads,
    complete/edit transitions and input replacement with HTTP 409
    ``EXECUTION_ACTIVE``; read-only paths are never affected.
    """

    def _task(self, directory, status="idle", active_execution_id="",
              platform_status="RUNNING"):
        task = oc_codex_server.Task(
            "p", directory, repository_id="repo-1", task_code="T-1",
            task_id="lifecycle-task", user_id="test",
            platform_status=platform_status)
        task.status = status
        task.active_execution_id = active_execution_id
        return task

    def _handler(self, task, body=None):
        handler = object.__new__(oc_codex_server.Handler)
        handler.headers = {"Authorization": "Bearer test"}
        handler.path = "/api/tasks/lifecycle-task/platform-status"
        handler._requires_auth = lambda path: False
        handler._current_user = lambda: "test"
        handler._read_body = lambda: body or {}
        handler._owned_task = lambda task_id: task
        handler._owned_task_for_detail = lambda task_id, repo="", code="": task
        response = []
        handler._send_json = lambda payload, status=200: response.append((status, payload))
        handler._write_uploaded_input = lambda *args, **kwargs: None
        return handler, response

    # -- MinIO result upload -------------------------------------------------

    def test_minio_upload_blocked_while_queued(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory, status="queued",
                              active_execution_id="exec-1")
            handler, response = self._handler(task, {
                "project": "p", "paths": ["out.csv"], "taskCode": "T-1",
                "repositoryId": "repo-1", "taskId": task.id,
            })
            with patch.object(oc_codex_server, "fileserver_put_object",
                              side_effect=AssertionError("must not upload")) as put, \
                    patch.object(oc_codex_server, "minio_config",
                                 return_value={"bucket": "b", "host": "h",
                                               "prefix": "x", "accessKey": "a",
                                               "secretKey": "s"}):
                handler._handle_minio_upload()
            status, payload = response[0]
            self.assertEqual(status, 409)
            self.assertEqual(payload["code"], "EXECUTION_ACTIVE")
            self.assertEqual(payload["taskId"], task.id)
            self.assertEqual(payload["executionId"], "exec-1")
            self.assertEqual(put.call_count, 0)

    def test_minio_upload_blocked_while_working(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory, status="working",
                              active_execution_id="exec-2")
            handler, response = self._handler(task, {
                "project": "p", "paths": ["out.csv"], "taskCode": "T-1",
                "repositoryId": "repo-1", "taskId": task.id,
            })
            with patch.object(oc_codex_server, "fileserver_put_object") as put:
                handler._handle_minio_upload()
            self.assertEqual(response[0][0], 409)
            self.assertEqual(response[0][1]["code"], "EXECUTION_ACTIVE")
            self.assertEqual(put.call_count, 0)

    # -- platform complete / edit --------------------------------------------

    def test_complete_blocked_while_queued_without_callback(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory, status="queued",
                              active_execution_id="exec-1")
            handler, response = self._handler(task, {"action": "complete"})
            with patch.object(oc_codex_server, "task_status_callback",
                              side_effect=AssertionError("must not callback")) as cb:
                handler._handle_platform_status(task.id)
            self.assertEqual(response[0][0], 409)
            self.assertEqual(response[0][1]["code"], "EXECUTION_ACTIVE")
            self.assertEqual(cb.call_count, 0)

    def test_complete_blocked_while_working(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory, status="working",
                              active_execution_id="exec-2")
            handler, response = self._handler(task, {"action": "complete"})
            with patch.object(oc_codex_server, "task_status_callback") as cb:
                handler._handle_platform_status(task.id)
            self.assertEqual(response[0][0], 409)
            self.assertEqual(response[0][1]["code"], "EXECUTION_ACTIVE")
            self.assertEqual(cb.call_count, 0)

    def test_edit_blocked_while_queued(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory, status="queued",
                              active_execution_id="exec-1",
                              platform_status="COMPLETED")
            handler, response = self._handler(task, {"action": "edit"})
            with patch.object(oc_codex_server, "reopen_completed_mission") as reopen:
                handler._handle_platform_status(task.id)
            self.assertEqual(response[0][0], 409)
            self.assertEqual(response[0][1]["code"], "EXECUTION_ACTIVE")
            self.assertEqual(reopen.call_count, 0)

    # -- input file replacement (browser upload) -----------------------------

    def test_input_replacement_blocked_while_queued(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory, status="queued",
                              active_execution_id="exec-1")
            handler, response = self._handler(task, {
                "project": "p", "repositoryId": "repo-1",
                "taskCode": "T-1", "taskId": task.id,
                "name": "input.csv", "data": "aGVsbG8=",
            })
            written = []
            handler._write_uploaded_input = lambda *args, **kwargs: written.append(args)
            with patch.object(oc_codex_server, "bind_mission_project",
                              return_value="p"), \
                    patch.object(oc_codex_server, "mission_task_cwd",
                                 return_value=directory):
                handler._handle_upload()
            self.assertEqual(response[0][0], 409)
            self.assertEqual(response[0][1]["code"], "EXECUTION_ACTIVE")
            self.assertEqual(written, [])

    # -- idle passes, stale activeExecutionId still blocks -------------------

    def test_idle_without_active_execution_passes_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory, status="idle",
                              active_execution_id="")
            self.assertIsNone(
                oc_codex_server.task_lifecycle_conflict(task, "变更任务状态"))
            # An idle task without an execution claim may complete.
            handler, response = self._handler(task, {"action": "complete"})
            with patch.object(oc_codex_server, "task_status_callback",
                              return_value={"ok": True}) as cb, \
                    patch.object(oc_codex_server, "build_completed_callback_payload",
                                 return_value=({"files": []}, None)):
                handler._handle_platform_status(task.id)
            self.assertEqual(response[0][0], 200)
            self.assertEqual(cb.call_count, 1)

    def test_complete_callback_failure_returns_structured_502(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory, status="idle",
                              active_execution_id="")
            handler, response = self._handler(task, {"action": "complete"})
            callback_file = {
                "filename": "business_objects.csv",
                "objectKey": "output/business_objects.csv",
                "previewUrl": "https://example.test/business_objects.csv",
            }
            with patch.object(oc_codex_server, "task_status_callback",
                              return_value={"ok": False, "error": "upstream rejected"}), \
                    patch.object(oc_codex_server, "build_completed_callback_payload",
                                 return_value=({"files": [callback_file]}, None)), \
                    patch.object(oc_codex_server, "persist_tasks"):
                handler._handle_platform_status(task.id)
            status, payload = response[0]
            self.assertEqual(status, 502)
            self.assertEqual(payload["code"], "PLATFORM_SUCCESS_CALLBACK_FAILED")
            self.assertIn("upstream rejected", payload["error"])
            self.assertEqual(task.run_result["generatedArtifacts"],
                             ["business_objects.csv"])

    def test_idle_status_with_active_execution_id_still_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory, status="idle",
                              active_execution_id="exec-1")
            conflict = oc_codex_server.task_lifecycle_conflict(
                task, "变更输入文件")
            self.assertIsNotNone(conflict)
            self.assertEqual(conflict["code"], "EXECUTION_ACTIVE")
            self.assertEqual(conflict["executionId"], "exec-1")


class AutoApproveFlowTests(unittest.TestCase):
    """47313 自动确认：execution/任务级服务端自动放行 + 审计 + 幂等。

    根因回归：202 后台执行只通过轮询回传 approval_request，旧前端自动确认
    只存在于 SSE 分支；服务端 execution 级自动放行使浏览器无关路径也可靠，
    同时保留完整 approval_request/approval_result 审计。
    """

    def _task(self, directory, task_id="abcd1234ef01", user_id="test"):
        task = oc_codex_server.Task("p", directory, task_id=task_id,
                                    user_id=user_id)
        task.conv = _FakeConversation()
        return task

    def _recording(self, task):
        events = []

        def rec(event):
            stamped = task._record_event(event)
            events.append(stamped)
            return stamped

        task._rec = rec
        return events

    @staticmethod
    def _run_prompt(task, outcome, command="ls"):
        outcome["ok"], outcome["err"] = task._web_prompt_user(
            "Bash", {"command": command})

    @staticmethod
    def _wait_pending(task, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if task.pending_approval:
                return task.pending_approval
            time.sleep(0.005)
        return None

    def _result_event(self, events):
        return next(event for event in events
                    if event["type"] == "approval_result")

    def test_execution_auto_approve_never_waits_and_records_automatic_result(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            events = self._recording(task)
            task._execution_auto_approve = True
            started = time.time()
            with patch.object(oc_codex_server, "_append_task_history"):
                ok, err = task._web_prompt_user("Bash", {"command": "ls"})
            self.assertTrue(ok)
            self.assertEqual(err, "")
            self.assertLess(time.time() - started, 2.0)
            self.assertEqual([event["type"] for event in events],
                             ["approval_request", "approval_result"])
            result = self._result_event(events)
            self.assertTrue(result["approved"])
            self.assertTrue(result["automatic"])
            self.assertIsNone(task.pending_approval)

    def test_task_level_auto_approve_releases_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            task.auto_approve = True
            events = self._recording(task)
            with patch.object(oc_codex_server, "_append_task_history"):
                ok, _ = task._web_prompt_user("Edit", {"file_path": "x.py"})
            self.assertTrue(ok)
            self.assertTrue(self._result_event(events)["automatic"])

    def test_manual_approval_still_waits_and_records_manual_result(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            events = self._recording(task)
            outcome = {}
            thread = threading.Thread(target=self._run_prompt,
                                      args=(task, outcome))
            with patch.object(oc_codex_server, "_append_task_history"):
                thread.start()
                pending = self._wait_pending(task)
                self.assertIsNotNone(pending)
                self.assertTrue(task.resolve_approval(pending["id"], True))
                thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertTrue(outcome["ok"])
            result = self._result_event(events)
            self.assertTrue(result["approved"])
            self.assertFalse(result.get("automatic"))

    def test_timeout_records_rejected_result_without_automatic_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            events = self._recording(task)
            old = os.environ.get("ONTOLOGY_APPROVAL_TIMEOUT_SECONDS")
            os.environ["ONTOLOGY_APPROVAL_TIMEOUT_SECONDS"] = "0.05"
            try:
                with patch.object(oc_codex_server, "_append_task_history"):
                    ok, err = task._web_prompt_user("Bash", {"command": "ls"})
            finally:
                if old is None:
                    os.environ.pop("ONTOLOGY_APPROVAL_TIMEOUT_SECONDS", None)
                else:
                    os.environ["ONTOLOGY_APPROVAL_TIMEOUT_SECONDS"] = old
            self.assertFalse(ok)
            self.assertIn("超时", err)
            result = self._result_event(events)
            self.assertFalse(result["approved"])
            self.assertTrue(result.get("timeout"))
            self.assertFalse(result.get("automatic"))

    def test_resolve_approval_is_idempotent_after_formal_result(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            events = self._recording(task)
            outcome = {}
            thread = threading.Thread(target=self._run_prompt,
                                      args=(task, outcome))
            with patch.object(oc_codex_server, "_append_task_history"):
                thread.start()
                pending = self._wait_pending(task)
                req_id = pending["id"]
                self.assertTrue(task.resolve_approval(req_id, True))
                thread.join(timeout=5)
                # 正式结果已产生后重复提交同一 id 视为幂等成功，不再报错。
                self.assertTrue(task.resolve_approval(req_id, True))
            self.assertFalse(thread.is_alive())
            results = [event for event in events
                       if event["type"] == "approval_result"
                       and event["id"] == req_id]
            self.assertEqual(len(results), 1)

    def test_auto_approve_current_resolves_pending_with_automatic_result(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            events = self._recording(task)
            outcome = {}
            thread = threading.Thread(target=self._run_prompt,
                                      args=(task, outcome))
            with patch.object(oc_codex_server, "_append_task_history"):
                thread.start()
                pending = self._wait_pending(task)
                self.assertIsNotNone(pending)
                self.assertTrue(task.auto_approve_current())
                thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertTrue(outcome["ok"])
            result = self._result_event(events)
            self.assertTrue(result["approved"])
            self.assertTrue(result["automatic"])

    def test_summary_exposes_safe_pending_approval_and_auto_approve(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            task.auto_approve = True
            summary = task.summary()
            self.assertTrue(summary["autoApprove"])
            self.assertIsNone(summary["pendingApproval"])
            task.pending_approval = {
                "id": "req-1", "tool": "Bash", "summary": "执行命令",
                "detail": "SECRET-COMMAND",
            }
            safe = task.pending_approval_safe()
            self.assertEqual(safe["id"], "req-1")
            self.assertEqual(safe["tool"], "Bash")
            self.assertEqual(safe["summary"], "执行命令")
            self.assertNotIn("detail", safe)
            self.assertNotIn("SECRET-COMMAND", json.dumps(safe))

    def test_auto_approve_endpoint_enables_and_resolves_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            events = self._recording(task)
            outcome = {}
            thread = threading.Thread(target=self._run_prompt,
                                      args=(task, outcome))
            handler = object.__new__(oc_codex_server.Handler)
            handler.path = f"/api/tasks/{task.id}/auto-approve"
            handler.headers = {}
            handler._requires_auth = lambda path: False
            handler._require_user = lambda: "test"
            handler._owned_task = lambda task_id: task
            handler._read_body = lambda: {"enabled": True}
            response = []
            handler._send_json = lambda payload, status=200: response.append(
                (status, payload))
            with patch.object(oc_codex_server, "_append_task_history"), \
                    patch.object(oc_codex_server, "persist_tasks"):
                thread.start()
                pending = self._wait_pending(task)
                self.assertIsNotNone(pending)
                handler.do_POST()
                thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertTrue(outcome["ok"])
            self.assertTrue(task.auto_approve)
            self.assertEqual(response[0][0], 200)
            payload = response[0][1]
            self.assertTrue(payload["autoApprove"])
            self.assertTrue(payload["resolved"])
            self.assertTrue(self._result_event(events)["automatic"])

    def test_auto_approve_endpoint_disable_restores_manual_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            task.auto_approve = True
            handler = object.__new__(oc_codex_server.Handler)
            handler.path = f"/api/tasks/{task.id}/auto-approve"
            handler.headers = {}
            handler._requires_auth = lambda path: False
            handler._require_user = lambda: "test"
            handler._owned_task = lambda task_id: task
            handler._read_body = lambda: {"enabled": False}
            response = []
            handler._send_json = lambda payload, status=200: response.append(
                (status, payload))
            with patch.object(oc_codex_server, "persist_tasks"):
                handler.do_POST()
            self.assertFalse(task.auto_approve)
            self.assertFalse(task._execution_auto_approve)
            self.assertEqual(response[0][0], 200)
            self.assertFalse(response[0][1]["resolved"])

    def test_auto_approve_does_not_leak_across_tasks_or_users(self):
        with tempfile.TemporaryDirectory() as directory:
            task_a = self._task(directory, task_id="aaaa00000001",
                               user_id="user-a")
            task_b = self._task(directory, task_id="bbbb00000002",
                               user_id="user-b")
            task_a.auto_approve = True
            self.assertFalse(task_b.auto_approve)
            self.assertFalse(task_b._execution_auto_approve)
            # 任务 B 未启用自动确认时仍进入人工等待流程。
            events_b = self._recording(task_b)
            outcome = {}
            thread = threading.Thread(target=self._run_prompt,
                                      args=(task_b, outcome))
            with patch.object(oc_codex_server, "_append_task_history"):
                thread.start()
                pending = self._wait_pending(task_b)
                self.assertIsNotNone(pending)
                self.assertTrue(task_b.resolve_approval(pending["id"], True))
                thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertTrue(outcome["ok"])
            self.assertFalse(self._result_event(events_b).get("automatic"))

    def test_auto_approve_persists_and_restores_per_task(self):
        import oc_codex_server as web
        old_sandbox = web.SANDBOX_DIR
        old_state = web.TASKS_STATE_PATH
        old_history = web.TASK_HISTORY_DIR
        old_enabled = web.WEB_TASK_PERSISTENCE_ENABLED
        old_tasks = web.TASKS
        try:
            with tempfile.TemporaryDirectory() as sandbox_dir:
                web.SANDBOX_DIR = sandbox_dir
                web.TASKS_STATE_PATH = os.path.join(
                    sandbox_dir, ".web_tasks.json")
                web.TASK_HISTORY_DIR = os.path.join(sandbox_dir, ".task_history")
                web.WEB_TASK_PERSISTENCE_ENABLED = True
                os.makedirs(os.path.join(sandbox_dir, "p"), exist_ok=True)
                enabled = web.Task("p", os.path.join(sandbox_dir, "p"),
                                   task_id="aa-restore-1", user_id="test",
                                   auto_approve=True)
                disabled = web.Task("p", os.path.join(sandbox_dir, "p"),
                                    task_id="aa-restore-2", user_id="test",
                                    auto_approve=False)
                with patch.object(web, "_append_task_history"):
                    enabled._record_event({"type": "user", "text": "a"})
                    disabled._record_event({"type": "user", "text": "b"})
                web.TASKS = {enabled.id: enabled, disabled.id: disabled}
                web.persist_tasks()
                web.TASKS = {}
                web.restore_tasks()
                restored = {t.id: t for t in web.TASKS.values()}
                self.assertTrue(restored[enabled.id].auto_approve)
                self.assertFalse(restored[disabled.id].auto_approve)
        finally:
            web.SANDBOX_DIR = old_sandbox
            web.TASKS_STATE_PATH = old_state
            web.TASK_HISTORY_DIR = old_history
            web.WEB_TASK_PERSISTENCE_ENABLED = old_enabled
            web.TASKS = old_tasks
