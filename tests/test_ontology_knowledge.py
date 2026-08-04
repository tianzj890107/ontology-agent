import unittest
import importlib.util
import json
import os
import tempfile
import zipfile
import base64
import hashlib
import hmac
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

from open_claude.ontology_knowledge import (
    knowledge_filename,
    load_static_knowledge,
    modeling_skill_modules,
    normalize_task_type,
)
from open_claude import config as open_claude_config
from open_claude.tools import execute_read


class StaticKnowledgeContractTests(unittest.TestCase):
    def test_malformed_config_and_token_limit_fallbacks(self):
        original_path = open_claude_config.get_config_path
        original_max = os.environ.get("CLAUDE_MAX_TOKENS")
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text("[1, 2, 3]", encoding="utf-8")
            open_claude_config.get_config_path = lambda: config_path
            try:
                self.assertEqual(open_claude_config.load_config(), {})
                os.environ["CLAUDE_MAX_TOKENS"] = "not-a-number"
                self.assertEqual(open_claude_config.get_max_tokens(), 32768)
                os.environ["CLAUDE_MAX_TOKENS"] = "-1"
                self.assertEqual(open_claude_config.get_max_tokens(), 32768)
            finally:
                open_claude_config.get_config_path = original_path
                if original_max is None:
                    os.environ.pop("CLAUDE_MAX_TOKENS", None)
                else:
                    os.environ["CLAUDE_MAX_TOKENS"] = original_max

    def test_task_modes_select_fixed_files(self):
        self.assertEqual(knowledge_filename("integration"), "integration/all_sources.md")
        self.assertEqual(normalize_task_type("DOCUMENT_MODELING"), "modeling")
        self.assertEqual(normalize_task_type("DATA_SOURCE_MODELING"), "modeling")
        self.assertEqual(normalize_task_type("INTEGRATION_TASK"), "integration")
        self.assertEqual(
            knowledge_filename("modeling", {"sourceMode": "DATABASE"}),
            "modeling/multi_source_data.md",
        )
        self.assertEqual(
            knowledge_filename("modeling", {"sourceMode": "DOCUMENT"}),
            "modeling/business_document.md",
        )
        self.assertEqual(
            knowledge_filename("modeling", {"sourceMode": "unrecognized"}),
            "modeling/all_sources.md",
        )
        self.assertEqual(knowledge_filename("unknown"), "")

    def test_runtime_reads_markdown_only(self):
        modeling = load_static_knowledge(ROOT / "agent_knowledge", "modeling",
                                         {"sourceMode": "DATABASE"})
        integration = load_static_knowledge(ROOT / "agent_knowledge", "integration")
        self.assertIn("# 智能建模任务", modeling)
        self.assertIn("多源数据建模.docx", modeling)
        self.assertNotIn("业务文档本体建模.docx", modeling)
        self.assertIn("# 智能消歧与整合", integration)
        self.assertIn("智能消歧与整合规则v0.1.docx", integration)
        self.assertIn("智能消歧与整合模板.xlsx", integration)
        self.assertIn("检核项", integration)
        self.assertIn("business_attributes.csv", integration)
        self.assertIn("关系编码", integration)
        self.assertIn("通用业务对象与逻辑实体识别规范_V6.md", modeling)
        self.assertIn("唯一的核心判定规范", modeling)
        self.assertIn("COMPOSITION 和 EXTENSION", modeling)
        self.assertNotIn("自底向上业务对象识别规范_v3.md", modeling)
        self.assertIn("本体元模型.xlsx", modeling)
        self.assertIn("本体元模型模板.xlsx", modeling)
        self.assertNotIn("本体建模步骤拆解.xlsx", modeling)
        self.assertEqual(modeling_skill_modules({}), ())
        self.assertEqual(
            modeling_skill_modules({"parseElements": "BUSINESS_OBJECTTERMRULEMETRIC"}),
            (("TERM", "业务术语.md"), ("RULE", "业务规则.md"), ("METRIC", "指标.md")),
        )
        specialized = load_static_knowledge(
            ROOT / "agent_knowledge", "modeling",
            {"sourceMode": "DATABASE", "expectedFiles": "terms.csvbusiness_rules.csvmetrics.csv"},
        )
        self.assertIn("建模专项技能：业务术语.md", specialized)
        self.assertIn("优先发现已有的人工语义资产", specialized)
        self.assertIn("建模专项技能：业务规则.md", specialized)
        self.assertIn("规则的存在与规则被强制是两件事", specialized)
        self.assertIn("建模专项技能：指标.md", specialized)
        self.assertIn("口径以实际执行的 SQL 为事实依据", specialized)
        self.assertIn("本体元模型.xlsx", (ROOT / "agent_knowledge" / "modeling" / "本体元模型.md").read_text(encoding="utf-8"))
        self.assertIn("本体元模型模板.xlsx", (ROOT / "agent_knowledge" / "modeling" / "本体元模型模板.md").read_text(encoding="utf-8"))
        data_model_rules = (ROOT / "agent_knowledge" / "modeling" / "数据模型建模规范-20260626.md").read_text(encoding="utf-8")
        self.assertIn("数据模型建模规范-20260626.xlsx", data_model_rules)
        self.assertIn("主逻辑实体唯一", data_model_rules)
        v6_rules = (ROOT / "agent_knowledge" / "modeling" / "通用业务对象与逻辑实体识别规范_V6.md").read_text(encoding="utf-8")
        self.assertIn("通用业务对象与逻辑实体识别规范 V6", v6_rules)
        self.assertIn("业务对象判定标准", v6_rules)
        self.assertIn("UNKNOWN 闭环校验", v6_rules)
        self.assertIn("业务属性识别", v6_rules)
        self.assertIn("业务属性正式归属", v6_rules)
        v6_source = (ROOT / "agent_knowledge" / "通用业务对象与逻辑实体识别规范_V6.md").read_text(encoding="utf-8")
        top_level_numbers = [
            int(line.split(". ", 1)[0].removeprefix("## "))
            for line in v6_source.splitlines() if line.startswith("## ") and ". " in line
        ]
        self.assertEqual(top_level_numbers, list(range(1, 22)))
        self.assertIn("## 6. 业务属性识别", v6_source)
        self.assertIn("## 7. 逻辑实体识别", v6_source)
        source_digest = hashlib.sha256(v6_source.encode("utf-8")).hexdigest()[:12]
        self.assertIn(f"SHA-256（前12位）：`{source_digest}`", v6_rules)
        integration_template = (ROOT / "agent_knowledge" / "integration" / "template.md").read_text(encoding="utf-8")
        self.assertIn("智能消歧与整合模板.xlsx", integration_template)
        self.assertIn("推荐名称", integration_template)
        self.assertIn("business_rules.csv", integration_template)

    def test_modeling_source_files_are_specialized_and_composed_at_runtime(self):
        source_code = (ROOT / "agent_knowledge" / "modeling" / "source_code.md").read_text(encoding="utf-8")
        document = (ROOT / "agent_knowledge" / "modeling" / "business_document.md").read_text(encoding="utf-8")
        self.assertIn("源代码本体建模.docx", source_code)
        self.assertNotIn("业务文档本体建模.docx", source_code)
        self.assertIn("业务文档本体建模.docx", document)
        self.assertNotIn("源代码本体建模.docx", document)

        composed = load_static_knowledge(ROOT / "agent_knowledge", "modeling",
                                         {"sourceMode": "SOURCE_CODE"})
        self.assertIn("通用业务对象与逻辑实体识别规范_V6.md", composed)
        self.assertIn("源代码本体建模.docx", composed)
        self.assertNotIn("业务文档本体建模.docx", composed)

    def test_integration_output_contract_covers_expected_files(self):
        schema = (ROOT / "agent_knowledge" / "integration" / "output_schema.md").read_text(encoding="utf-8")
        for name in (
            "business_attributes.csv", "business_objects.csv", "business_rules.csv",
            "conflict_elements.csv", "entity_relations.csv", "integration_report.csv",
            "logical_entities.csv", "merged_elements.csv", "missing_elements.csv",
            "pending_elements.csv",
        ):
            self.assertIn(name, schema)
        for header in ("业务对象编码", "逻辑实体编码", "业务属性编码", "关系编码",
                      "检核项", "整合后名称", "候选名称 A", "冲突类型", "缺失说明"):
            self.assertIn(header, schema)

    def test_static_knowledge_is_outside_task_sandbox(self):
        self.assertFalse((ROOT / "agent_knowledge").is_relative_to(
            ROOT / "open-claude" / "sandbox"))

    def test_generated_knowledge_has_no_credentials(self):
        for path in (ROOT / "agent_knowledge").rglob("*.md"):
            text = path.read_text(encoding="utf-8").lower()
            self.assertNotRegex(text, r"sk-[a-z0-9_-]{12,}")
            self.assertNotRegex(text, r"password\s*[:=]\s*\S{8,}")

    def test_backend_input_contracts_without_model_dependencies(self):
        """Exercise server validation helpers without constructing an Agent or API client."""
        names = ("open_claude.repl", "open_claude.profile", "open_claude.api",
                 "open_claude.config")
        originals = {name: sys.modules.get(name) for name in names}
        repl = types.ModuleType("open_claude.repl")
        repl.Conversation = object
        profile = types.ModuleType("open_claude.profile")
        profile.AgentProfile = object
        api = types.ModuleType("open_claude.api")
        api.stream_message = lambda *args, **kwargs: iter(())
        config = types.ModuleType("open_claude.config")
        config.AVAILABLE_MODELS = []
        config.PROVIDERS = {}
        config.get_api_key_for = lambda provider: None
        config.get_config_path = lambda: Path("/tmp/no-config")
        config.get_max_tokens = lambda: 1
        config.get_model = lambda: "test"
        config.get_model_provider = lambda model: "test"
        config.load_config = lambda: {}
        config.resolve_model = lambda model: model
        config.validate_inference_params = open_claude_config.validate_inference_params
        for name, module in zip(names, (repl, profile, api, config)):
            sys.modules[name] = module
        try:
            spec = importlib.util.spec_from_file_location(
                "oc_contract_server_test", ROOT / "open-claude" / "oc_codex_server.py")
            server = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(server)
            self.assertTrue(server.Handler._requires_auth("/api/meta"))
            self.assertTrue(server.Handler._requires_auth("/p/project/private.csv"))
            self.assertFalse(server.Handler._requires_auth("/"))
            original_params = dict(server.PARAM_DEFAULTS)
            try:
                with self.assertRaises(ValueError):
                    server.set_params({"temperature": 1.0, "max_tokens": "not-a-number"})
                self.assertEqual(server.PARAM_DEFAULTS, original_params)
                self.assertEqual(server.set_params({"temperature": "1.25", "thinking": "false"})["temperature"], 1.25)
                with self.assertRaises(ValueError):
                    server.set_params({"temperature": "nan"})
            finally:
                server.PARAM_DEFAULTS.clear()
                server.PARAM_DEFAULTS.update(original_params)
            self.assertIn("执行审计摘要", server.build_modeling_instructions({}))
            self.assertIn("唯一的核心判定规范", server.build_modeling_instructions({}))
            self.assertIn("COMPOSITION 和 EXTENSION", server.build_modeling_instructions({}))
            self.assertIn("候选业务属性", server.build_modeling_instructions({}))
            self.assertIn("属性归属", server.build_modeling_instructions({}))
            skill_instructions = server.build_modeling_instructions(
                {"parseElements": ["TERM", "RULE", "METRIC"]})
            self.assertIn("业务术语.md", skill_instructions)
            self.assertIn("业务规则.md", skill_instructions)
            self.assertIn("指标.md", skill_instructions)
            self.assertIn("规则文件名和章节标题", server.build_integration_instructions({}))
            self.assertEqual(
                server.build_tool_audit("Bash", {"command": "head -n 5 input.csv"})["severity"],
                "warning",
            )
            self.assertEqual(
                server.build_tool_audit("Read", {"file_path": "input.csv", "limit": 5})["severity"],
                "warning",
            )
            with tempfile.TemporaryDirectory() as tmp:
                xlsx = Path(tmp) / "input.xlsx"
                with zipfile.ZipFile(xlsx, "w") as zf:
                    zf.writestr("xl/workbook.xml", '''<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="物理表清单" sheetId="1" r:id="rId1"/></sheets></workbook>''')
                    zf.writestr("xl/_rels/workbook.xml.rels", '''<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="worksheet"/></Relationships>''')
                    zf.writestr("xl/worksheets/sheet1.xml", '''<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>表名</t></is></c><c r="B1" t="inlineStr"><is><t>说明</t></is></c></row><row r="2"><c r="A2" t="inlineStr"><is><t>采购订单</t></is></c><c r="B2" t="inlineStr"><is><t>业务表</t></is></c></row></sheetData></worksheet>''')
                manifest, error = server.extract_xlsx_to_csv(xlsx, Path(tmp) / "sheets")
                self.assertIsNone(error)
                self.assertEqual(manifest["sheets"][0]["rows"], 2)
                self.assertEqual(manifest["sheets"][0]["dataRows"], 1)
                csv_path = Path(tmp) / "sheets" / "01-物理表清单.csv"
                self.assertIn("采购订单", csv_path.read_text(encoding="utf-8"))
                binary = Path(tmp) / "binary.xlsx"
                binary.write_bytes(b"PK\x03\x04" + b"\x00" * 32)
                self.assertIn("不能使用 Read", execute_read({"file_path": str(binary)}, tmp))
            handler = object.__new__(server.Handler)
            self.assertEqual(handler._mission_from("1", "RM123456789", "modeling")["taskCode"],
                             "RM123456789")
            self.assertIsNone(handler._mission_from("1", "</script><script>alert(1)</script>", "modeling"))
            self.assertIsNone(handler._mission_from("1", "RM123456789/extra", "modeling"))
            self.assertEqual(
                server._forward_authorization("Bearer eyJhbGciOiJIUzI1NiJ9"),
                "Bearer eyJhbGciOiJIUzI1NiJ9",
            )
            self.assertEqual(server._forward_authorization("local:browser"), "")
            self.assertEqual(server._forward_authorization("Basic abc"), "")
            self.assertEqual(
                server.normalize_parse_elements("业务术语业务规则指标"),
                {"TERM", "RULE", "METRIC"},
            )
            self.assertEqual(server.parse_element_for_file("business_terms.csv"), "TERM")
            callback_calls = []
            original_callback = server.ontology_task_callback
            try:
                server.ontology_task_callback = lambda kind, code, repo, payload, user_id, authorization: (
                    callback_calls.append((kind, code, repo, payload, user_id, authorization)) or {"ok": True})
                callback_task = types.SimpleNamespace(
                    task_code="RM123456789", repository_id="1", task_type="modeling",
                    mission_context={}, user_id="u1",
                )
                server.task_status_callback(callback_task, "RUNNING", authorization="Bearer test")
                server.task_status_callback(callback_task, "FAILED", error_code="AGENT_EXECUTION_FAILED",
                                            error_message="boom")
                self.assertEqual([call[3]["agentStatus"] for call in callback_calls], ["RUNNING", "FAILED"])
                self.assertEqual(callback_calls[1][3]["errorCode"], "AGENT_EXECUTION_FAILED")
                self.assertEqual(callback_calls[0][5], "Bearer test")
            finally:
                server.ontology_task_callback = original_callback
            # Mission requests no longer accept a task-code-shaped project
            # directory.  The server resolves the shared workspace from
            # persisted task metadata (or creates a stable repository
            # workspace), so an unknown fake project is rejected.
            self.assertIsNone(
                server.bind_mission_project("mission-1-RM123456789", "1", "RM123456789")
            )
            self.assertIsNone(
                server.bind_mission_project("another-project", "1", "RM123456789")
            )
            with tempfile.TemporaryDirectory() as workspace_tmp:
                old_sandbox, old_tasks = server.SANDBOX_DIR, server.TASKS
                old_script_dir = server.SCRIPT_DIR
                try:
                    server.SANDBOX_DIR = workspace_tmp
                    server.TASKS = {}
                    server.SCRIPT_DIR = str(Path(workspace_tmp) / "legacy-open-claude")
                    workspace = Path(workspace_tmp) / "ontology-workspace-1"
                    task_dir = workspace / "tasks" / "RM123456789"
                    task_dir.mkdir(parents=True)
                    (workspace / "public.csv").write_text("id\n1\n", encoding="utf-8")
                    existing = types.SimpleNamespace(
                        repository_id="1", task_code="RM123456789", user_id="u1",
                        project="ontology-workspace-1", workspace="ontology-workspace-1",
                        cwd=str(task_dir), updated=1,
                    )
                    server.TASKS = {"task-1": existing}
                    self.assertEqual(
                        server.mission_task_cwd("", "1", "RM123456789", "task-1", "u1"),
                        str(task_dir),
                    )
                    self.assertIsNone(
                        server.mission_task_cwd("", "1", "RM123456789", "task-1", "u2")
                    )
                    existing.user_id = "local:previous-browser"
                    self.assertEqual(
                        server.mission_task_cwd("", "1", "RM123456789", "task-1", "local:current-browser"),
                        str(task_dir),
                    )
                    self.assertTrue(server._mission_task_user_matches(existing, "local:current-browser"))
                    self.assertFalse(server._mission_task_user_matches(existing, "external-user"))
                    legacy_input = Path(server.SCRIPT_DIR) / "mission-input"
                    legacy_input.mkdir(parents=True)
                    object_key = "bucket/source.xlsx"
                    suffix = hashlib.sha256(object_key.encode("utf-8")).hexdigest()[:8]
                    legacy_name = f"source-{suffix}.xlsx"
                    (legacy_input / legacy_name).write_bytes(b"legacy-input")
                    migrated = server.migrate_legacy_mission_inputs(
                        {"source": {"filename": "source.xlsx", "objectKey": object_key}},
                        str(task_dir), "ontology-workspace-1")
                    self.assertEqual(migrated, [f"mission-input/{legacy_name}"])
                    self.assertTrue((task_dir / "mission-input" / legacy_name).is_file())
                finally:
                    server.SANDBOX_DIR, server.TASKS, server.SCRIPT_DIR = old_sandbox, old_tasks, old_script_dir
            with tempfile.TemporaryDirectory() as auth_tmp:
                old_paths = (server._USER_KEYS_PATH, server._USER_SETTINGS_PATH,
                             server._AUTH_SECRET_PATH, server._USAGE_PATH)
                old_jwt_secret = os.environ.get("ONTOLOGY_JWT_SECRET")
                try:
                    server._USER_KEYS_PATH = str(Path(auth_tmp) / "keys.json")
                    server._USER_SETTINGS_PATH = str(Path(auth_tmp) / "settings.json")
                    server._AUTH_SECRET_PATH = str(Path(auth_tmp) / "cookie.secret")
                    server._USAGE_PATH = str(Path(auth_tmp) / "usage.json")
                    server.set_user_api_key("u1", "qwen", "key-one")
                    server.set_user_api_key("u2", "qwen", "key-two")
                    self.assertEqual(server.user_api_key("u1", "qwen"), "key-one")
                    self.assertEqual(server.user_api_key("u2", "qwen"), "key-two")
                    self.assertIsNone(server.user_api_key("u3", "qwen"))
                    old_provider, old_key_lookup = os.environ.get("LLM_PROVIDER"), server.get_api_key_for
                    try:
                        os.environ["LLM_PROVIDER"] = "team"
                        server.get_api_key_for = lambda provider: "team-test-key" if provider == "team" else None
                        self.assertEqual(server.user_api_key("u3", "team"), "team-test-key")
                        self.assertIsNone(server.user_api_key("u3", "qwen"))
                    finally:
                        server.get_api_key_for = old_key_lookup
                        if old_provider is None:
                            os.environ.pop("LLM_PROVIDER", None)
                        else:
                            os.environ["LLM_PROVIDER"] = old_provider
                    os.environ["ONTOLOGY_JWT_SECRET"] = "test-secret"
                    enc = lambda value: base64.urlsafe_b64encode(value).decode().rstrip("=")
                    header, payload = enc(b'{"alg":"HS256"}'), enc(b'{"sub":"u1"}')
                    signing = f"{header}.{payload}"
                    signature = enc(hmac.new(b"test-secret", signing.encode(), hashlib.sha256).digest())
                    token = f"{signing}.{signature}"
                    self.assertEqual(server.external_user_id({"Authorization": "Bearer " + token}), "u1")
                finally:
                    (server._USER_KEYS_PATH, server._USER_SETTINGS_PATH,
                     server._AUTH_SECRET_PATH, server._USAGE_PATH) = old_paths
                    if old_jwt_secret is None:
                        os.environ.pop("ONTOLOGY_JWT_SECRET", None)
                    else:
                        os.environ["ONTOLOGY_JWT_SECRET"] = old_jwt_secret
            self.assertEqual(
                server.normalize_expected_files([
                    {"filename": "logical_entities.csv"},
                    {"path": "x/entity_relations.csv"},
                ]),
                {"logical_entities.csv", "entity_relations.csv"},
            )
            with tempfile.TemporaryDirectory() as task_tmp:
                output = Path(task_tmp) / "mission-output"
                output.mkdir()
                result_file = output / "logical_entities.csv"
                result_file.write_text("逻辑实体编码,逻辑实体名称\nLE1,采购订单\n", encoding="utf-8")
                digest = hashlib.sha256(result_file.read_bytes()).hexdigest()
                completion_task = types.SimpleNamespace(
                    cwd=task_tmp,
                    task_code="RM123456789",
                    task_type="modeling",
                    mission_context={
                        "taskType": "modeling", "parseElements": ["LOGICAL_ENTITY"],
                        "expectedFiles": ["logical_entities.csv"],
                    },
                    platform_uploaded_files={"logical_entities.csv": {
                        "objectKey": "ontology/1/modeling-tasks/RM/agent-output/logical_entities.csv",
                        "previewUrl": "https://files.example/preview.csv", "sha256": digest,
                    }},
                )
                completion, completion_error = server.build_completed_callback_payload(completion_task)
                self.assertIsNone(completion_error)
                self.assertEqual(completion["agentStatus"], "COMPLETED")
                self.assertEqual(completion["files"][0]["parseElement"], "LOGICAL_ENTITY")
                result_file.write_text("逻辑实体编码,逻辑实体名称\nLE1,已修改采购订单\n", encoding="utf-8")
                _, changed_error = server.build_completed_callback_payload(completion_task)
                self.assertIn("上传后已变更", changed_error)
            bo_header = "业务对象编码,业务对象名称,业务对象英文名,业务对象定义,数据类别\n"
            self.assertEqual(
                server.validate_integration_csv(
                    "business_objects.csv",
                    (bo_header + 'BO1,采购订单,Purchase Order,"包含,头和行",事务数据\n').encode("utf-8"),
                ),
                [],
            )
            malformed = server.validate_integration_csv(
                "business_objects.csv",
                (bo_header + "BO1,采购订单,Purchase Order,包含,头和行,事务数据\n").encode("utf-8"),
            )
            self.assertTrue(malformed)
            self.assertTrue(server.validate_integration_csv(
                "business_rules.csv", "规则编码,规则名称,规则描述\nR1,规则,描述\n".encode("utf-8")
            ))
            self.assertEqual(server.validate_integration_csv(
                "business_rules.csv", "规则编码,规则名称,分类,规则描述,来源内容\nR1,规则,约束规则,描述,源模型\n".encode("utf-8")
            ), [])
            relation_header = "关系编码,源逻辑实体编码,源逻辑实体名称,目标逻辑实体编码,目标逻辑实体名称,关系分类编码,关系分类,关系中文名称,关系英文名称,关系基数,反向关系中文名称,反向关系英文名称,关系描述,源关联属性编码,源关联属性英文名,源关联属性中文名,目标关联属性编码,目标关联属性英文名,目标关联属性中文名\n"
            bad_relation = relation_header + "R1,E1,订单,E2,客户,REL,错误分类,属于,belongs,一对多,,,,,,,,,\n"
            self.assertTrue(server.validate_integration_csv("entity_relations.csv", bad_relation.encode("utf-8")))
            self.assertTrue(server.validate_modeling_csv(
                "business_objects.csv", "id,name,description\nBO1,订单,描述\n".encode("utf-8")
            ))
            empty = types.SimpleNamespace(conv=types.SimpleNamespace(messages=[]), log=[
                {"type": "model_switch", "from": "a", "to": "b"},
                {"type": "tool_use", "name": "Read"},
            ])
            self.assertFalse(server.Task.has_conversation(empty))
            started = types.SimpleNamespace(
                conv=types.SimpleNamespace(messages=[{"role": "user", "content": "开始任务"}]),
                log=[],
            )
            self.assertTrue(server.Task.has_conversation(started))
            class Session:
                session_id = "session-1"

            class Task:
                log = [{"type": "user", "text": "offline"}]
                repository_id = "1"
                task_code = "RM123456789"
                updated = 2
                mission_context = {"taskType": "modeling"}
                conv = types.SimpleNamespace(session=Session())

                def summary(self):
                    return {"id": "task-1", "project": "p", "status": "idle"}

            with tempfile.TemporaryDirectory() as tmp:
                server.TASKS = {"task-1": Task()}
                self.assertEqual(
                    server.cached_mission_context("1", "RM123456789"),
                    {"taskType": "modeling"},
                )
                server.TASKS_STATE_PATH = str(Path(tmp) / ".web_tasks.json")
                with ThreadPoolExecutor(max_workers=4) as pool:
                    list(pool.map(lambda _: server.persist_tasks(), range(12)))
                saved = json.loads(Path(server.TASKS_STATE_PATH).read_text(encoding="utf-8"))
                self.assertEqual(saved[0]["id"], "task-1")
                self.assertFalse(Path(server.TASKS_STATE_PATH + ".tmp").exists())
        finally:
            for name, original in originals.items():
                if original is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = original


if __name__ == "__main__":
    unittest.main()
