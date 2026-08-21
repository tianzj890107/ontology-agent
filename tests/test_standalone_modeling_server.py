import base64
import csv
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "open-claude"))
import standalone_modeling_server  # noqa: E402
from standalone_modeling_server import (
    DEFAULT_ARTIFACTS,
    DEFAULT_MODELING_PROMPT,
    ActiveRunError,
    ClientInputError,
    ModelingRunManager,
    ModelingHandler,
    QueueLimitError,
    RunStore,
    StateTransitionError,
    _normalize_database_config,
)


class StandaloneModelingWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RunStore(self.tmp.name)

    def tearDown(self):
        self.store.close_managers()
        self.tmp.cleanup()

    @staticmethod
    def _confirmed_state(code="CO001"):
        return {"businessObjectDecisions": [{
            "candidateCode": code,
            "candidateName": "可确认对象",
            "memberEntityIds": ["LE001"],
            "confidence": "90",
            **{f"r{i}": {"status": "PASS", "evidence": f"R{i} evidence"}
               for i in range(1, 6)},
        }]}

    def _write_valid_business_objects(self, run):
        Path(run.root, "work", "modeling_state.json").write_text(
            json.dumps(self._confirmed_state(), ensure_ascii=False), encoding="utf-8")
        with Path(run.root, "output", "business_objects.csv").open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle, lineterminator="\n").writerows([
                ["业务对象编码", "业务对象名称", "业务对象英文名", "业务对象定义", "数据类别"],
                ["CO001", "可确认对象", "ConfirmedObject", "有直接证据", "业务"],
            ])

    def _manager(self):
        return ModelingRunManager(self.store)

    def test_database_config_allows_empty_password_only_when_explicit(self):
        config = {
            "host": "doris.example", "username": "admin", "password": "",
            "database": "ontology", "dbType": "MYSQL",
            "selectedSchemas": ["ontology_dev", "po"],
        }
        with self.assertRaises(ClientInputError):
            _normalize_database_config(config)
        config["allowEmptyPassword"] = True
        normalized = _normalize_database_config(config)
        self.assertEqual(normalized["password"], "")
        self.assertEqual(normalized["selectedSchemas"], ["ontology_dev", "po"])

    def _http_server(self, manager):
        ModelingHandler.manager = manager
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), ModelingHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return httpd

    @staticmethod
    def _post(httpd, path, payload):
        connection = HTTPConnection("127.0.0.1", httpd.server_port, timeout=3)
        body = json.dumps(payload).encode("utf-8")
        connection.request("POST", path, body=body,
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        connection.close()
        return response.status, data

    @staticmethod
    def _get(httpd, path):
        connection = HTTPConnection("127.0.0.1", httpd.server_port, timeout=3)
        connection.request("GET", path)
        response = connection.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        connection.close()
        return response.status, data

    def test_health_exposes_staged_readiness_and_on_demand_capabilities(self):
        httpd = self._http_server(self._manager())
        status, payload = self._get(httpd, "/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertIn("readiness", payload)
        self.assertIn("stages", payload["readiness"])
        self.assertEqual(payload["capabilities"]["database_metadata"], "on_demand")

    def test_runtime_workspace_is_one_isolated_input_work_output_space(self):
        run = self.store.create("DATABASE", "build ontology")
        self.store.put_files(run, [{"name": "input/schema.json", "content": '{"ok":true}'}])
        # work/output are runtime-owned namespaces; simulate the engine's
        # writes directly rather than using the untrusted input API.
        Path(run.root, "work/modeling_state.json").write_text('{"status":"UNKNOWN"}', encoding="utf-8")
        Path(run.root, "work/all_attributes.csv").write_text("属性编码\nAT1\n", encoding="utf-8")
        Path(run.root, "output/business_objects.csv").write_text("code\nBO1\n", encoding="utf-8")

        paths = {item["path"] for item in self.store.list_files(run)}
        self.assertEqual(paths, {"input/schema.json", "work/modeling_state.json",
                                 "work/all_attributes.csv", "output/business_objects.csv"})
        self.assertEqual(self.store.read_file(run, "work/modeling_state.json"), b'{"status":"UNKNOWN"}')
        self.assertEqual(self.store.read_file(run, "mission-output/business_objects.csv"), b"code\nBO1\n")

    def test_base64_input_and_path_traversal_are_handled(self):
        run = self.store.create("DOCUMENT", "parse")
        payload = base64.b64encode("中文输入".encode()).decode()
        self.store.put_files(run, [{"name": "input/source.txt", "contentBase64": payload}])
        self.assertEqual(self.store.read_file(run, "input/source.txt"), "中文输入".encode())
        with self.assertRaises(ValueError):
            self.store.put_files(run, [{"name": "input/../../outside.txt", "content": "no"}])
        with self.assertRaises(ValueError):
            self.store.read_file(run, "/etc/passwd")

    def test_runs_are_isolated(self):
        first = self.store.create("DATABASE", "first")
        second = self.store.create("DATABASE", "second")
        Path(first.root, "work/a.json").write_text("A", encoding="utf-8")
        Path(second.root, "work/b.json").write_text("B", encoding="utf-8")
        self.assertEqual({x["path"] for x in self.store.list_files(first)}, {"work/a.json"})
        self.assertEqual({x["path"] for x in self.store.list_files(second)}, {"work/b.json"})
        self.assertNotEqual(Path(first.root), Path(second.root))

    def test_file_listing_reuses_four_folder_display_contract(self):
        run = self.store.create("DATABASE", "file tree")
        root = Path(run.root)
        files = {
            "input/reference-v0.0.1.xlsx": "reference",
            "input/upload.csv": "input",
            "input/upload-sheets/manifest.json": "derived",
            "input/db_connection.py": "hidden",
            "work/business_object_decisions.csv": "decision",
            "work/all_attributes.csv": "all attributes",
            "work/modeling_state.json": "state",
            "work/db_metadata.json": "metadata",
            "work/pylibs/dependency.py": "runtime",
            "output/business_objects.csv": "output",
        }
        for rel, content in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        listed = {item["path"]: item["displayPath"] for item in self.store.list_files(run)}
        self.assertEqual(listed, {
            "input/reference-v0.0.1.xlsx": "root/input/reference-v0.0.1.xlsx",
            "input/upload.csv": "input/upload.csv",
            "input/upload-sheets/manifest.json": "root/work/upload-sheets/manifest.json",
            "work/business_object_decisions.csv": "work/business_object_decisions.csv",
            "work/all_attributes.csv": "work/all_attributes.csv",
            "work/modeling_state.json": "root/work/modeling_state.json",
            "work/db_metadata.json": "root/work/db_metadata.json",
            "output/business_objects.csv": "output/business_objects.csv",
        })

    def test_table_count_question_answers_without_starting_modeling(self):
        manager = self._manager()
        run = self.store.create("DATABASE", "建模")
        run.database_source_id = "0"
        with patch("standalone_modeling_server._list_database_source_tables", return_value={
            "schema": "ontology_dev",
            "tables": [
                {"schema": "ontology_dev", "name": "a", "type": "BASE TABLE"},
                {"schema": "ontology_dev", "name": "v", "type": "VIEW"},
            ],
        }):
            manager.execute(run, "继续回答现在有多少表，先别建模")
        self.assertEqual(run.status, "INPUT_READY")
        self.assertEqual(len(manager.threads), 0)
        answer = next(event for event in run.events if event.get("type") == "assistant")
        self.assertIn("共发现 2 个对象", answer["text"])
        self.assertIn("1 张物理表、1 个视图", answer["text"])

    def test_intent_classifier_distinguishes_question_from_explicit_modeling(self):
        manager = self._manager()
        self.assertTrue(manager._resolve_conversational_intent("数据库怎么连接？"))
        self.assertTrue(manager._resolve_conversational_intent("现在有多少张表"))
        self.assertTrue(manager._resolve_conversational_intent("帮我看看"))
        self.assertFalse(manager._resolve_conversational_intent("请开始建模", "auto"))
        self.assertFalse(manager._resolve_conversational_intent("请分析数据库并生成模型", "auto"))
        self.assertTrue(manager._resolve_conversational_intent("怎么建模"))
        self.assertFalse(manager._resolve_conversational_intent("怎么建模", "execute"))

    def test_question_turn_skips_semantic_finalize_and_returns_to_input_ready(self):
        manager = self._manager()
        run = self.store.create("DATABASE", "数据库怎么连接？")
        self.store.transition(run, "ANALYZING")
        manager.execution_modes[run.run_id] = (True, "INPUT_READY")

        class FakeTask:
            status = "idle"

            def __init__(self, *args, **kwargs):
                self.conv = SimpleNamespace(
                    model="test-model",
                    permissions=SimpleNamespace(mode="default"),
                    system_prompt="",
                )

            def stream_turn(self, text, emit, conversational=False):
                self.conversational = conversational
                emit({"type": "assistant", "text": "这是一个问题回答"})

        with patch("oc_codex_server.Task", FakeTask), \
                patch.object(manager, "validate", side_effect=AssertionError("question must not finalize")):
            manager._execute(run)

        self.assertEqual(run.status, "INPUT_READY")
        self.assertIn("query_finished", [event["type"] for event in run.events])
        self.assertNotIn("validation_finished", [event["type"] for event in run.events])

    def test_retry_reuses_session_and_sends_checkpoint_resume_prompt(self):
        manager = self._manager()
        run = self.store.create("DATABASE", "从当前阶段继续建模")
        run.resume_session_id = "session-before-retry"
        run.attempt_number = 2
        self.store.transition(run, "ANALYZING")
        manager.execution_modes[run.run_id] = (False, "FAILED")
        captured = {}

        class FakeTask:
            status = "blocked"
            modeling_block_reason = "CHECKPOINT_REQUIRED"

            def __init__(self, *args, **kwargs):
                captured["kwargs"] = kwargs
                self.conv = SimpleNamespace(
                    model="test-model",
                    permissions=SimpleNamespace(mode="default"),
                    system_prompt="",
                )

            def session_id(self):
                return "session-after-retry"

            def stream_turn(self, text, emit, conversational=False):
                captured["prompt"] = text

        with patch("oc_codex_server.Task", FakeTask):
            manager._execute(run)

        self.assertEqual(captured["kwargs"]["resume_session_id"], "session-before-retry")
        self.assertIn("不要从头执行", captured["prompt"])
        self.assertEqual(run.resume_session_id, "session-after-retry")
        self.assertEqual(run.status, "BLOCKED")

    def test_retry_resumes_from_persisted_stage_checkpoint_without_reprobe(self):
        manager = self._manager()
        run = self.store.create("DATABASE", "guard pause resume")
        run.resume_session_id = "session-before-retry"
        run.attempt_number = 2
        self.store.transition(run, "ANALYZING")
        manager.execution_modes[run.run_id] = (False, "BLOCKED")
        work = Path(run.root, "work")
        work.mkdir(parents=True, exist_ok=True)
        (work / "modeling_state.json").write_text(json.dumps({
            "validationStages": {
                "INPUT_CONTEXT": {"status": "PASSED", "signature": "s1"},
                "ASSET_INVENTORY": {"status": "PASSED", "signature": "s2"},
                "ALL_ATTRIBUTES": {"status": "FAILED", "signature": "s3"},
            }}, ensure_ascii=False), encoding="utf-8")
        captured = {}

        class FakeTask:
            status = "blocked"
            modeling_block_reason = "MODEL_TOOL_CALL_LIMIT"

            def __init__(self, *args, **kwargs):
                captured["kwargs"] = kwargs
                self.conv = SimpleNamespace(
                    model="test-model",
                    permissions=SimpleNamespace(mode="default"),
                    system_prompt="",
                )

            def session_id(self):
                return "session-after-retry"

            def stream_turn(self, text, emit, conversational=False):
                captured["prompt"] = text

        with patch("oc_codex_server.Task", FakeTask):
            manager._execute(run)

        # The retry continues from the first unfinished stage instead of
        # restarting: the persisted checkpoint identifies the last PASSED
        # stage and the continuation instruction forbids re-probing.
        self.assertEqual(run.checkpoint_stage, "ASSET_INVENTORY")
        self.assertIn("不要从头执行", captured["prompt"])
        self.assertIn("不要重复输入盘点、数据库连接验证或 schema 提取",
                      captured["prompt"])
        self.assertIn("只处理第一个未完成或失败的阶段", captured["prompt"])
        self.assertEqual(captured["kwargs"]["resume_session_id"], "session-before-retry")
        self.assertEqual(run.status, "BLOCKED")

    def test_provider_400_retry_keeps_original_checkpoint_and_session(self):
        manager = self._manager()
        run = self.store.create("DATABASE", "provider 400 resume")
        run.resume_session_id = "session-400"
        self.store.transition(run, "ANALYZING")
        manager.execution_modes[run.run_id] = (False, "INPUT_READY")
        work = Path(run.root, "work")
        work.mkdir(parents=True, exist_ok=True)
        (work / "modeling_state.json").write_text(json.dumps({
            "validationStages": {
                "INPUT_CONTEXT": {"status": "PASSED", "signature": "s1"},
                "ASSET_INVENTORY": {"status": "PASSED", "signature": "s2"},
            }}, ensure_ascii=False), encoding="utf-8")

        class FakeTask:
            status = "idle"

            def __init__(self, *args, **kwargs):
                self.conv = SimpleNamespace(
                    model="test-model",
                    permissions=SimpleNamespace(mode="always_allow"),
                    system_prompt="",
                )

            def session_id(self):
                return "session-400"

            def stream_turn(self, text, emit, conversational=False):
                emit({"type": "provider_retry", "attempt": 2,
                      "text": "模型网关思考模式校验失败，已自动重试并继续执行"})

        def fake_validate(run, internal=False):
            run.status = "SUCCEEDED"
            return {"semantic_validation_status": "PASSED"}

        with patch("oc_codex_server.Task", FakeTask), \
                patch.object(manager, "validate", side_effect=fake_validate):
            manager._execute(run)

        # The 400 was retried inside the same attempt: the original checkpoint
        # and provider session are retained, no fresh run/session is created.
        self.assertEqual(run.checkpoint_stage, "ASSET_INVENTORY")
        self.assertEqual(run.resume_session_id, "session-400")
        self.assertIn("provider_retry", [event["type"] for event in run.events])
        self.assertEqual(run.status, "SUCCEEDED")

    def test_resume_keeps_user_next_prompt_verbatim(self):
        manager = self._manager()
        run = self.store.create("DATABASE", "原始提示")
        run.resume_session_id = "session-resume"
        run.attempt_number = 2
        self.store.transition(run, "ANALYZING")
        manager.execution_modes[run.run_id] = (False, "FAILED")
        manager.execution_prompts[run.run_id] = "只处理和采购有关的表"
        captured = {}

        class FakeTask:
            status = "idle"

            def __init__(self, *args, **kwargs):
                self.conv = SimpleNamespace(
                    model="test-model",
                    permissions=SimpleNamespace(mode="default"),
                    system_prompt="",
                )

            def session_id(self):
                return "session-resume"

            def stream_turn(self, text, emit, conversational=False):
                captured["prompt"] = text

        def fake_validate(run, internal=False):
            run.status = "SUCCEEDED"
            return {"semantic_validation_status": "PASSED"}

        with patch("oc_codex_server.Task", FakeTask), \
                patch.object(manager, "validate", side_effect=fake_validate):
            manager._execute(run)

        # The user's own continuation text is preserved and only a short
        # checkpoint constraint is appended; the fixed resume prompt must not
        # overwrite it.
        self.assertIn("只处理和采购有关的表", captured["prompt"])
        self.assertIn("不要从头执行", captured["prompt"])
        self.assertEqual(run.resume_session_id, "session-resume")
        self.assertEqual(run.status, "SUCCEEDED")

    def test_shared_repair_code_between_47313_and_47314(self):
        # The standalone service and the web workbench must run the exact
        # same DeepSeek repair layer: the standalone worker drives the shared
        # oc_codex_server.Task (same Conversation/_stream_once), and both
        # route through openai_compat.sanitize_messages/to_openai_messages.
        from open_claude import openai_compat as shared_compat

        import inspect
        source = inspect.getsource(standalone_modeling_server)
        self.assertIn("from oc_codex_server import Task", source)
        # The shared Task path is the same object the 47313 server exposes.
        import oc_codex_server
        self.assertTrue(hasattr(oc_codex_server.Task, "stream_turn"))
        # api.stream_message (used by Task._stream_once) sanitizes before any
        # provider call, so both services share the same sanitizer instance.
        import open_claude.api as api
        self.assertIs(api.openai_compat.sanitize_messages,
                      shared_compat.sanitize_messages)
        self.assertTrue(callable(shared_compat.sanitize_messages))

    def test_resume_without_next_prompt_uses_default_resume_prompt(self):
        manager = self._manager()
        run = self.store.create("DATABASE", "继续建模")
        run.resume_session_id = "session-resume-2"
        run.attempt_number = 3
        self.store.transition(run, "ANALYZING")
        manager.execution_modes[run.run_id] = (False, "FAILED")
        captured = {}

        class FakeTask:
            status = "idle"

            def __init__(self, *args, **kwargs):
                self.conv = SimpleNamespace(
                    model="test-model",
                    permissions=SimpleNamespace(mode="default"),
                    system_prompt="",
                )

            def session_id(self):
                return "session-resume-2"

            def stream_turn(self, text, emit, conversational=False):
                captured["prompt"] = text

        def fake_validate(run, internal=False):
            run.status = "SUCCEEDED"
            return {"semantic_validation_status": "PASSED"}

        with patch("oc_codex_server.Task", FakeTask), \
                patch.object(manager, "validate", side_effect=fake_validate):
            manager._execute(run)

        self.assertIn("不要重复输入盘点、数据库连接验证或 schema 提取", captured["prompt"])
        self.assertIn("只处理第一个未完成或失败的阶段", captured["prompt"])
        # The default resume instruction must open with the exact continue
        # contract sentence from the shared requirement.
        self.assertTrue(captured["prompt"].startswith(
            "继续执行上一次未完成的任务，从中断位置继续。不要重复已经完成的步骤。"))

    def test_conversational_turn_sends_user_text_verbatim(self):
        manager = self._manager()
        run = self.store.create("DATABASE", "原提示")
        run.resume_session_id = "session-question"
        self.store.transition(run, "ANALYZING")
        manager.execution_modes[run.run_id] = (True, "INPUT_READY")
        manager.execution_prompts[run.run_id] = "这个表是什么意思？"
        captured = {}

        class FakeTask:
            status = "idle"

            def __init__(self, *args, **kwargs):
                self.conv = SimpleNamespace(
                    model="test-model",
                    permissions=SimpleNamespace(mode="default"),
                    system_prompt="",
                )

            def session_id(self):
                return "session-question"

            def stream_turn(self, text, emit, conversational=False):
                captured["prompt"] = text
                captured["conversational"] = conversational

        with patch("oc_codex_server.Task", FakeTask):
            manager._execute(run)

        self.assertEqual(captured["prompt"], "这个表是什么意思？")
        self.assertTrue(captured["conversational"])
        self.assertEqual(run.status, "INPUT_READY")

    def test_same_process_continue_reuses_task_instance(self):
        manager = self._manager()
        run = self.store.create("DATABASE", "复用任务")
        run.resume_session_id = "session-reuse"
        self.store.transition(run, "ANALYZING")
        manager.execution_modes[run.run_id] = (False, "FAILED")
        instances = []

        class FakeTask:
            status = "blocked"
            modeling_block_reason = "MODEL_TOOL_CALL_LIMIT"

            def __init__(self, *args, **kwargs):
                instances.append(self)
                self.conv = SimpleNamespace(
                    model="test-model",
                    permissions=SimpleNamespace(mode="default"),
                    system_prompt="",
                )

            def session_id(self):
                return "session-reuse"

            def stream_turn(self, text, emit, conversational=False):
                self.status = "blocked"

        with patch("oc_codex_server.Task", FakeTask):
            manager._execute(run)
            self.assertEqual(len(instances), 1)
            self.assertIs(manager.tasks[run.run_id], instances[0])
            # A second attempt in the same process reuses the in-memory
            # Task/Conversation instead of rebuilding the runtime.
            self.store.transition(run, "ANALYZING", allowed_from={"BLOCKED"})
            run.attempt_number = 2
            manager.execution_modes[run.run_id] = (False, "FAILED")
            manager._execute(run)
            self.assertEqual(len(instances), 1)
            self.assertIs(manager.tasks[run.run_id], instances[0])
        self.assertEqual(run.status, "BLOCKED")

    def test_input_api_cannot_write_runtime_namespaces(self):
        run = self.store.create("DATABASE", "input boundary")
        bad_paths = [
            "work/modeling_state.json", "output/business_objects.csv",
            "mission-work/a.json", "../output/a.csv", "/tmp/a.csv",
            "input/../../output/a.csv", "modeling_state.json",
        ]
        for name in bad_paths:
            with self.subTest(name=name):
                with self.assertRaises((ClientInputError, ValueError)):
                    self.store.put_files(run, [{"name": name, "content": "blocked"}])
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (Path(run.root) / "input" / "link").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(Exception):
            self.store.put_files(run, [{"name": "input/link/escape.txt", "content": "blocked"}])
        self.assertFalse((outside / "escape.txt").exists())

    def test_requested_artifacts_are_strictly_validated(self):
        manager = self._manager()
        try:
            missing = self.store.create("DATABASE", "missing", ["business_objects.csv"])
            report = manager.validate(missing)
            self.assertEqual(missing.status, "FAILED")
            self.assertEqual(report["semantic_validation_status"], "FAILED")
            self.assertIn("REQUESTED_ARTIFACT_MISSING",
                          {item["code"] for item in report["errors"]})

            partial = self.store.create("DATABASE", "partial", [
                "business_objects.csv", "logical_entities.csv"])
            self._write_valid_business_objects(partial)
            report = manager.validate(partial)
            self.assertEqual(partial.status, "FAILED")
            self.assertIn("REQUESTED_ARTIFACT_MISSING",
                          {item["code"] for item in report["errors"]})

            only_requested = self.store.create("DATABASE", "only requested", ["business_objects.csv"])
            self._write_valid_business_objects(only_requested)
            report = manager.validate(only_requested)
            self.assertEqual(report["semantic_validation_status"], "PASSED")
            self.assertEqual(only_requested.status, "SUCCEEDED")

            invalid_schema = self.store.create("DATABASE", "invalid schema", ["business_objects.csv"])
            Path(invalid_schema.root, "work", "modeling_state.json").write_text(
                json.dumps(self._confirmed_state(), ensure_ascii=False), encoding="utf-8")
            Path(invalid_schema.root, "output", "business_objects.csv").write_text(
                "not,a,business,object\n", encoding="utf-8")
            report = manager.validate(invalid_schema)
            self.assertEqual(invalid_schema.status, "FAILED")
            self.assertIn("FORMAL_OUTPUT_INVALID_SCHEMA",
                          {item["code"] for item in report["errors"]})
        finally:
            import oc_codex_server as web
            web.configure_task_persistence(True)

    def test_requested_artifact_contract_rejects_unknown_and_explicit_empty(self):
        before = {item.name for item in Path(self.tmp.name).iterdir()}
        with self.assertRaises(ClientInputError) as unknown:
            self.store.create("DATABASE", "bad", ["business_objects.csv", "unknown.csv"])
        self.assertEqual(unknown.exception.status, 422)
        self.assertEqual(unknown.exception.details["invalidArtifacts"], ["unknown.csv"])
        with self.assertRaises(ClientInputError):
            self.store.create("DATABASE", "empty", [])
        self.assertEqual({item.name for item in Path(self.tmp.name).iterdir()}, before)
        self.assertEqual(self.store.create("DATABASE", "default").requested_artifacts,
                         list(DEFAULT_ARTIFACTS))

    def test_empty_prompt_uses_built_in_v001_modeling_instruction(self):
        run = self.store.create("DATABASE", "")
        self.assertEqual(run.prompt, DEFAULT_MODELING_PROMPT)
        self.assertIn("v0.0.1", run.prompt)

    def test_create_with_title_persists_title_and_survives_reload(self):
        run = self.store.create("DATABASE", "采购建模要求", title="采购域建模")
        self.assertEqual(run.title, "采购域建模")
        self.assertEqual(run.as_dict()["title"], "采购域建模")
        blank = self.store.create("DATABASE", "无标题要求", title="   ")
        self.assertEqual(blank.title, "")
        reloaded_store = RunStore(self.tmp.name)
        try:
            reloaded = reloaded_store.runs.get(run.run_id)
            self.assertIsNotNone(reloaded)
            self.assertEqual(reloaded.title, "采购域建模")
            self.assertEqual(reloaded.prompt, "采购建模要求")
        finally:
            reloaded_store.close_managers()

    def test_external_validate_is_rejected_while_execute_is_analyzing(self):
        manager = self._manager()
        started = threading.Event()
        release = threading.Event()

        def blocked_execute(_run):
            started.set()
            self.assertTrue(release.wait(2))

        try:
            run = self.store.create("DATABASE", "concurrent validation")
            with patch.object(manager, "_execute", side_effect=blocked_execute):
                manager.execute(run)
                self.assertTrue(started.wait(2))
                self.assertEqual(run.status, "ANALYZING")
                with self.assertRaises(StateTransitionError):
                    manager.validate(run)
                self.assertEqual(run.status, "ANALYZING")
                release.set()
                manager.threads[run.run_id].join(timeout=2)
                self.assertFalse(manager.threads[run.run_id].is_alive())
        finally:
            release.set()
            import oc_codex_server as web
            web.configure_task_persistence(True)

    def test_http_external_validate_returns_409_during_execute(self):
        manager = self._manager()
        started = threading.Event()
        release = threading.Event()

        def blocked_execute(_run):
            started.set()
            self.assertTrue(release.wait(2))

        try:
            run = self.store.create("DATABASE", "HTTP concurrent validation")
            httpd = self._http_server(manager)
            with patch.object(manager, "_execute", side_effect=blocked_execute):
                manager.execute(run)
                self.assertTrue(started.wait(2))
                status, body = self._post(
                    httpd, f"/api/modeling-runs/{run.run_id}/validate", {})
                self.assertEqual(status, 409)
                self.assertEqual(body["code"], "INVALID_STATE_TRANSITION")
                self.assertEqual(run.status, "ANALYZING")
                release.set()
                manager.threads[run.run_id].join(timeout=2)
        finally:
            release.set()
            import oc_codex_server as web
            web.configure_task_persistence(True)

    def test_internal_validation_can_transition_from_analyzing(self):
        manager = self._manager()
        try:
            run = self.store.create("DATABASE", "internal validation", ["business_objects.csv"])
            self._write_valid_business_objects(run)
            self.store.transition(run, "ANALYZING")
            report = manager.validate(run, internal=True)
            self.assertEqual(report["semantic_validation_status"], "PASSED")
            self.assertEqual(run.status, "SUCCEEDED")
        finally:
            import oc_codex_server as web
            web.configure_task_persistence(True)

    def test_malformed_create_files_return_422_without_run_or_directory(self):
        manager = self._manager()
        httpd = self._http_server(manager)
        malformed = [
            {"files": {}},
            {"files": "abc"},
            {"files": ["abc"]},
            {"files": [123]},
            {"files": [None]},
            {"files": [[]]},
            {"files": [{"name": "valid.csv"}, "invalid"]},
        ]
        for payload in malformed:
            with self.subTest(payload=payload):
                before = {item.name for item in Path(self.tmp.name).iterdir()}
                status, body = self._post(httpd, "/api/modeling-runs", payload)
                self.assertEqual(status, 422)
                self.assertIn("error", body)
                self.assertEqual({item.name for item in Path(self.tmp.name).iterdir()}, before)
                self.assertEqual(len(self.store.runs), 0)

    def test_valid_create_writes_inputs_only_after_validation(self):
        manager = self._manager()
        httpd = self._http_server(manager)
        status, body = self._post(httpd, "/api/modeling-runs", {
            "requestedArtifacts": ["business_objects.csv"],
            "files": [{"name": "schema.json", "content": "{}"}],
        })
        self.assertEqual(status, 201)
        run = self.store.get(body["runId"])
        self.assertEqual(run.status, "INPUT_READY")
        self.assertEqual((Path(run.root) / "input/schema.json").read_text(), "{}")

    def test_database_context_reuses_legacy_task_connection_pipeline(self):
        manager = self._manager()
        httpd = self._http_server(manager)
        database = {
            "databaseSourceId": 12,
            "dbType": "POSTGRESQL",
            "host": "db.internal",
            "port": 5432,
            "database": "ontology",
            "username": "ontology_agent",
            "password": "encrypted-credential-placeholder",
            "sourceSchema": "public",
            "selectedTables": ["purchase_order"],
        }
        status, body = self._post(httpd, "/api/modeling-runs", {
            "sourceMode": "DATABASE",
            "prompt": "分析数据库并建立本体模型",
            "database": database,
            "requestedArtifacts": ["business_objects.csv"],
        })
        self.assertEqual(status, 201)
        self.assertTrue(body["databaseConfigured"])
        self.assertNotIn("database", body)
        run = self.store.get(body["runId"])
        context = manager._context(run)
        self.assertEqual(context["sourceMode"], "DATABASE")
        self.assertEqual(context["database"], database)
        self.assertEqual(context["database"]["password"], database["password"])

        recovered = RunStore(self.tmp.name).get(run.run_id)
        self.assertEqual(recovered.database, database)

    def test_invalid_database_context_is_rejected_before_run_creation(self):
        manager = self._manager()
        httpd = self._http_server(manager)
        before = {item.name for item in Path(self.tmp.name).iterdir()}
        status, body = self._post(httpd, "/api/modeling-runs", {
            "sourceMode": "DATABASE",
            "database": {"host": "db.internal", "username": "agent"},
        })
        self.assertEqual(status, 422)
        self.assertIn("missingFields", body)
        self.assertEqual({item.name for item in Path(self.tmp.name).iterdir()}, before)
        self.assertEqual(len(self.store.runs), 0)

    def test_requested_artifact_failures_have_no_orphan_run_directory(self):
        manager = self._manager()
        httpd = self._http_server(manager)
        for requested in (["not_exist.csv"], []):
            with self.subTest(requested=requested):
                before = {item.name for item in Path(self.tmp.name).iterdir()}
                status, body = self._post(httpd, "/api/modeling-runs", {
                    "requestedArtifacts": requested,
                })
                self.assertEqual(status, 422)
                self.assertIn("error", body)
                self.assertEqual({item.name for item in Path(self.tmp.name).iterdir()}, before)
                self.assertEqual(len(self.store.runs), 0)

    def test_state_machine_rejects_upload_execute_and_validate_races(self):
        manager = self._manager()
        try:
            run = self.store.create("DATABASE", "state machine")
            with patch.object(manager, "_execute", return_value=None):
                manager.execute(run)
                manager.threads[run.run_id].join(timeout=2)
            self.assertEqual(run.status, "ANALYZING")
            with self.assertRaises(StateTransitionError):
                self.store.put_files(run, [{"name": "input/new.json", "content": "blocked"}])
            with self.assertRaises(StateTransitionError):
                manager.execute(run)
            with self.assertRaises(StateTransitionError):
                manager.validate(run)
            self.assertEqual(run.status, "ANALYZING")

            validating = self.store.create("DATABASE", "validating")
            self.store.transition(validating, "VALIDATING")
            with self.assertRaises(StateTransitionError):
                self.store.put_files(validating, [{"name": "input/new.json", "content": "blocked"}])

            ready = self.store.create("DATABASE", "ready", ["business_objects.csv"])
            self._write_valid_business_objects(ready)
            manager.validate(ready)
            self.assertEqual(ready.status, "SUCCEEDED")
            with self.assertRaises(StateTransitionError):
                self.store.put_files(ready, [{"name": "input/new.json", "content": "blocked"}])
        finally:
            import oc_codex_server as web
            web.configure_task_persistence(True)

    def test_events_and_interrupted_states_recover_after_restart(self):
        run = self.store.create("DATABASE", "recover")
        self.store.append_event(run, "run_started", message="started")
        self.store.transition(run, "ANALYZING")
        recovered = RunStore(self.tmp.name)
        restored = recovered.get(run.run_id)
        self.assertEqual(restored.status, "FAILED")
        self.assertEqual(len(restored.events), 2)
        self.assertEqual(restored.events[0]["type"], "run_started")
        self.assertEqual(restored.events[-1]["reason"], "SERVER_RESTARTED_DURING_ANALYSIS")

        run2 = recovered.create("DATABASE", "recover validation")
        recovered.transition(run2, "VALIDATING")
        recovered_again = RunStore(self.tmp.name)
        restored2 = recovered_again.get(run2.run_id)
        self.assertEqual(restored2.status, "FAILED")
        self.assertEqual(restored2.error, "SERVER_RESTARTED_DURING_VALIDATION")

    def test_event_journal_keeps_index_small_and_recovers_events(self):
        run = self.store.create("DATABASE", "journal")
        for index in range(4):
            self.store.append_event(run, "thinking", text=str(index))
        index_payload = json.loads((Path(self.tmp.name) / ".runs.json").read_text(encoding="utf-8"))
        self.assertNotIn("events", index_payload[0])
        journal = Path(run.root) / ".events.jsonl"
        self.assertEqual(len(journal.read_text(encoding="utf-8").splitlines()), 4)
        recovered = RunStore(self.tmp.name).get(run.run_id)
        self.assertEqual([event["text"] for event in recovered.events], ["0", "1", "2", "3"])

    def test_runs_are_admitted_up_to_configured_concurrency_limit(self):
        manager = ModelingRunManager(self.store, max_active_runs=2)
        first = self.store.create("DATABASE", "first active")
        second = self.store.create("DATABASE", "second active")
        with patch.object(manager, "_execute", return_value=None):
            manager.execute(first)
            manager.threads[first.run_id].join(timeout=2)
            manager.execute(second)
            manager.threads[second.run_id].join(timeout=2)
        self.assertEqual(first.status, "ANALYZING")
        self.assertEqual(second.status, "ANALYZING")

    def test_runs_beyond_limit_wait_in_queue(self):
        manager = ModelingRunManager(self.store, max_active_runs=1)
        first = self.store.create("DATABASE", "first queued")
        second = self.store.create("DATABASE", "second queued")
        started = threading.Event()
        release = threading.Event()

        def blocked_execute(_run):
            started.set()
            self.assertTrue(release.wait(2))

        with patch.object(manager, "_execute", side_effect=blocked_execute):
            manager.execute(first)
            self.assertTrue(started.wait(2))
            manager.execute(second)
            self.assertEqual(second.status, "QUEUED")
            self.assertEqual([event["type"] for event in second.events], ["run_queued"])
            release.set()
            manager.threads[first.run_id].join(timeout=2)
            manager.threads[second.run_id].join(timeout=2)
        self.assertEqual(second.status, "ANALYZING")
        self.assertEqual([event["type"] for event in second.events], ["run_queued", "run_started"])

    def test_failed_run_can_be_executed_again(self):
        manager = self._manager()
        run = self.store.create("DATABASE", "retry failed run")
        self.store.transition(run, "FAILED", error="previous attempt failed")
        with patch.object(manager, "_execute", return_value=None):
            manager.execute(run)
            manager.threads[run.run_id].join(timeout=2)
        self.assertEqual(run.status, "ANALYZING")

    def test_per_user_active_limit_is_three_and_fourth_is_queued(self):
        manager = ModelingRunManager(self.store, max_active_runs=10,
                                     max_active_per_user=3,
                                     max_queued_per_user=3,
                                     heartbeat_seconds=0.05)
        release = threading.Event()
        started = threading.Event()
        active_count = 0
        active_lock = threading.Lock()

        def blocked(_run):
            nonlocal active_count
            with active_lock:
                active_count += 1
                if active_count == 3:
                    started.set()
            release.wait(2)

        runs = [self.store.create("DATABASE", f"u1-{i}", user_id="u1") for i in range(4)]
        with patch.object(manager, "_execute", side_effect=blocked):
            for run in runs:
                manager.execute(run)
            self.assertTrue(started.wait(2))
            self.assertEqual([run.status for run in runs[:3]], ["ANALYZING"] * 3)
            self.assertEqual(runs[3].status, "QUEUED")
            release.set()
            for run in runs:
                manager.threads[run.run_id].join(3)
        manager.close()

    def test_global_tenth_active_and_eleventh_queued(self):
        manager = ModelingRunManager(self.store, max_active_runs=10,
                                     max_active_per_user=10, max_queued_per_user=3)
        release = threading.Event()
        started = threading.Event()
        count = 0
        count_lock = threading.Lock()

        def blocked(_run):
            nonlocal count
            with count_lock:
                count += 1
                if count == 10:
                    started.set()
            release.wait(3)

        runs = [self.store.create("DATABASE", str(i), user_id=f"u{i}") for i in range(11)]
        with patch.object(manager, "_execute", side_effect=blocked):
            for run in runs:
                manager.execute(run)
            self.assertTrue(started.wait(3))
            self.assertEqual(sum(run.status == "ANALYZING" for run in runs), 10)
            self.assertEqual(runs[-1].status, "QUEUED")
            release.set()
            for run in runs:
                manager.threads[run.run_id].join(3)
        manager.close()

    def test_global_queue_cap_is_independent_from_per_user_cap(self):
        manager = ModelingRunManager(self.store, max_active_runs=1,
                                     max_active_per_user=1, max_queued_per_user=3,
                                     max_queued_runs=50)
        release = threading.Event()
        active = self.store.create("DATABASE", "active", user_id="active")
        with patch.object(manager, "_execute", side_effect=lambda _run: release.wait()):
            manager.execute(active)
            deadline = time.time() + 2
            while active.status != "ANALYZING" and time.time() < deadline:
                time.sleep(0.01)
            queued = [self.store.create("DATABASE", str(i), user_id=f"u{i}")
                      for i in range(51)]
            for run in queued[:50]:
                manager.execute(run)
            with self.assertRaises(QueueLimitError) as error:
                manager.execute(queued[50])
            self.assertEqual(error.exception.code, "GLOBAL_QUEUE_FULL")
            release.set()
        manager.close()

    def test_user_queue_limit_returns_explicit_429_semantics(self):
        manager = ModelingRunManager(self.store, max_active_runs=1,
                                     max_active_per_user=1, max_queued_per_user=3,
                                     max_queued_runs=50)
        release = threading.Event()
        first = self.store.create("DATABASE", "active", user_id="u1")
        with patch.object(manager, "_execute", side_effect=lambda _run: release.wait()):
            manager.execute(first)
            deadline = time.time() + 2
            while first.status != "ANALYZING" and time.time() < deadline:
                time.sleep(0.01)
            queued = [self.store.create("DATABASE", str(i), user_id="u1") for i in range(4)]
            for run in queued[:3]:
                manager.execute(run)
            with self.assertRaises(QueueLimitError) as error:
                manager.execute(queued[3])
            self.assertEqual(error.exception.code, "USER_QUEUE_LIMIT_REACHED")
            release.set()
        manager.close()

    def test_repository_snapshot_is_shared_and_idempotency_is_stable(self):
        first = self.store.create("DATABASE", "same", user_id="u1", idempotency_key="k1")
        duplicate = self.store.create("DATABASE", "different", user_id="u1", idempotency_key="k1")
        self.assertIs(first, duplicate)
        restarted = RunStore(self.tmp.name)
        self.assertEqual(restarted.get(first.run_id).user_id, "u1")
        self.assertTrue((Path(self.tmp.name) / ".runs.sqlite3").exists())

    def test_online_user_capacity_is_bounded_at_one_hundred(self):
        manager = ModelingRunManager(self.store, max_active_runs=10)
        for index in range(100):
            manager.touch_user(f"user-{index}")
        with self.assertRaises(QueueLimitError) as error:
            manager.touch_user("user-100")
        self.assertEqual(error.exception.code, "ONLINE_USER_LIMIT_REACHED")
        manager.close()

    def test_lease_expiry_is_recovered_without_stuck_running_state(self):
        manager = ModelingRunManager(self.store, max_active_runs=1, lease_seconds=1)
        run = self.store.create("DATABASE", "lease", user_id="u1")
        self.store.transition(run, "QUEUED")
        self.store.transition(run, "CLAIMED")
        run.worker_id = "lost-worker"
        run.lease_expires_at = time.time() - 1
        manager._recover_expired_leases()
        self.assertEqual(run.status, "FAILED")
        self.assertEqual(run.error, "WORKER_LEASE_EXPIRED")
        self.assertTrue(any(event["type"] == "worker_lost" for event in run.events))
        manager.close()

    def test_queued_cancel_cannot_be_claimed(self):
        manager = ModelingRunManager(self.store, max_active_runs=1)
        run = self.store.create("DATABASE", "cancel", user_id="u1")
        self.store.transition(run, "QUEUED")
        self.store.request_cancel(run)
        self.assertEqual(run.status, "CANCELLED")
        with self.assertRaises(StateTransitionError):
            manager.execute(run)
        manager.close()

    def test_standalone_adapter_never_changes_legacy_web_tasks_snapshot(self):
        import oc_codex_server as web
        old_path = web.TASKS_STATE_PATH
        old_enabled = web.WEB_TASK_PERSISTENCE_ENABLED
        old_tasks = web.TASKS
        snapshot = Path(self.tmp.name) / ".web_tasks.json"
        sentinel = b'[{"id":"legacy","status":"running"}]'
        snapshot.write_bytes(sentinel)
        try:
            web.TASKS_STATE_PATH = str(snapshot)
            web.TASKS = {}
            manager = ModelingRunManager(self.store)
            web.persist_tasks()
            self.assertEqual(snapshot.read_bytes(), sentinel)
            self.assertFalse((Path(self.tmp.name) / ".task_history").exists())
            self.assertIsNotNone(manager)
        finally:
            web.TASKS_STATE_PATH = old_path
            web.TASKS = old_tasks
            web.configure_task_persistence(old_enabled)


if __name__ == "__main__":
    unittest.main()
