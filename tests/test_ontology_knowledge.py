import unittest
import importlib.util
import json
import os
import tempfile
import zipfile
import base64
import hashlib
import hmac
import threading
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
        self.assertEqual(knowledge_filename("integration"), "integration/all_sourcesv0.0.1.md")
        self.assertEqual(normalize_task_type("DOCUMENT_MODELING"), "modeling")
        self.assertEqual(normalize_task_type("DATA_SOURCE_MODELING"), "modeling")
        self.assertEqual(normalize_task_type("INTEGRATION_TASK"), "integration")
        self.assertEqual(
            knowledge_filename("modeling", {"sourceMode": "DATABASE"}),
            "modeling/multi_source_datav0.0.1.md",
        )
        self.assertEqual(
            knowledge_filename("modeling", {"sourceMode": "DOCUMENT"}),
            "modeling/business_documentv0.0.1.md",
        )
        self.assertEqual(
            knowledge_filename("modeling", {"sourceMode": "unrecognized"}),
            "modeling/all_sourcesv0.0.1.md",
        )
        self.assertEqual(knowledge_filename("unknown"), "")

    def test_runtime_reads_markdown_only(self):
        modeling = load_static_knowledge(ROOT / "agent_knowledge", "modeling",
                                         {"sourceMode": "DATABASE"})
        integration = load_static_knowledge(ROOT / "agent_knowledge", "integration")
        self.assertIn("# 智能建模任务", modeling)
        self.assertIn("多源数据建模v0.0.1.docx", modeling)
        self.assertNotIn("业务文档本体建模v0.0.1.docx", modeling)
        self.assertIn("# 智能消歧与整合", integration)
        self.assertIn("智能消歧与整合规则v0.0.1.docx", integration)
        self.assertIn("智能消歧与整合模板v0.0.1.xlsx", integration)
        self.assertIn("Ontology平台模型编码规范v0.0.1.xlsx", integration)
        self.assertIn("REL000006", integration)
        self.assertIn("检核项", integration)
        self.assertIn("business_attributes.csv", integration)
        self.assertIn("关系编码", integration)
        self.assertIn("通用业务对象与逻辑实体识别规范v0.0.1.md", modeling)
        self.assertIn("唯一的核心判定规范", modeling)
        self.assertIn("COMPOSITION 和 EXTENSION", modeling)
        self.assertNotIn("自底向上业务对象识别规范_v3.md", modeling)
        self.assertIn("本体元模型v0.0.1.xlsx", modeling)
        self.assertIn("本体元模型模板v.0.0.1.xlsx", modeling)
        self.assertIn("Ontology平台模型编码规范v0.0.1.xlsx", modeling)
        self.assertIn("BO0005", modeling)
        self.assertIn("业务属性 | `AT` + 7 位流水码", modeling)
        self.assertIn("本体元模型模板（含样例数据）.xlsx", (ROOT / "agent_knowledge" / "modeling" / "本体元模型模板（含样例数据）.md").read_text(encoding="utf-8"))
        self.assertIn("是否逻辑主键", modeling)
        self.assertIn("当前不生成维度", modeling)
        self.assertIn("是否页面显示", modeling)
        self.assertIn("对象关系连接业务对象，实体关系连接逻辑实体", modeling)
        self.assertIn("普通类型、分类、布尔标志和处理结果不是生命周期状态", modeling)
        self.assertIn("普通数据行、静态属性、状态值本身不是事件", modeling)
        self.assertIn("数据长度", modeling)
        self.assertIn("规则编码,规则名称,规则描述,触发条件,判断或结果,处置动作", modeling)
        self.assertIn("动作元模型 v0.0.1", modeling)
        self.assertIn("动作编码, 动作名称, 动作英文名, 动作描述, 动作类型, 业务对象编码, 协议, 服务节点, 服务名称", modeling)
        self.assertIn("6 位流水码", modeling)
        self.assertIn("ACT000001", modeling)
        self.assertIn("明确证据优先，合理推断兜底", modeling)
        self.assertNotIn("本体元模型.xlsx", modeling)
        self.assertNotIn("本体元模型模板.xlsx", modeling)
        self.assertNotIn("本体建模步骤拆解.xlsx", modeling)
        self.assertEqual(modeling_skill_modules({}), ())
        self.assertEqual(
            modeling_skill_modules({"expectedFiles": ["metrics.csv"]}),
            (),
        )
        self.assertEqual(
            modeling_skill_modules({"parseElements": "BUSINESS_OBJECTTERMRULEMETRIC"}),
            (("TERM", "业务术语v0.0.1.md"), ("RULE", "业务规则v0.0.1.md"), ("METRIC", "指标v0.0.1.md")),
        )
        self.assertEqual(
            modeling_skill_modules({"parseElements": "BUSINESS_OBJECTACTION"}),
            (("ACTION", "动作v0.0.1.md"),),
        )
        specialized = load_static_knowledge(
            ROOT / "agent_knowledge", "modeling",
            {"sourceMode": "DATABASE", "parseElements": ["TERM", "RULE", "METRIC"],
             "expectedFiles": "terms.csvbusiness_rules.csvmetrics.csv"},
        )
        specialized_action = load_static_knowledge(
            ROOT / "agent_knowledge", "modeling",
            {"sourceMode": "DATABASE", "parseElements": ["ACTION"],
             "expectedFiles": "actions.csv"},
        )
        self.assertIn("建模专项技能：动作v0.0.1.md", specialized_action)
        self.assertIn("动作元模型 v0.0.1", specialized_action)
        self.assertIn("动作编码, 动作名称, 动作英文名, 动作描述, 动作类型, 业务对象编码, 协议, 服务节点, 服务名称", specialized_action)
        self.assertIn("建模专项技能：业务术语v0.0.1.md", specialized)
        self.assertIn("优先发现已有的人工语义资产", specialized)
        self.assertIn("建模专项技能：业务规则v0.0.1.md", specialized)
        self.assertIn("规则的存在与规则被强制是两件事", specialized)
        self.assertIn("建模专项技能：指标v0.0.1.md", specialized)
        self.assertIn("口径以实际执行的 SQL 为事实依据", specialized)
        metric_rules = (ROOT / "agent_knowledge" / "指标v0.0.1.md").read_text(encoding="utf-8")
        self.assertFalse(metric_rules.startswith("````"))
        self.assertIn("产出下限约束", metric_rules)
        self.assertIn("本体元模型v0.0.1.xlsx", (ROOT / "agent_knowledge" / "modeling" / "本体元模型v0.0.1.md").read_text(encoding="utf-8"))
        self.assertIn("本体元模型模板v.0.0.1.xlsx", (ROOT / "agent_knowledge" / "modeling" / "本体元模型模板v0.0.1.md").read_text(encoding="utf-8"))
        data_model_rules = (ROOT / "agent_knowledge" / "modeling" / "数据模型建模规范v0.0.1.md").read_text(encoding="utf-8")
        self.assertIn("数据模型建模规范v0.0.1.xlsx", data_model_rules)
        self.assertIn("主题域分类", data_model_rules)
        self.assertIn("数据模型建模规范v0.0.1.xlsx", modeling)
        self.assertNotIn("数据模型建模规范-20260626.xlsx", modeling)
        v6_rules = (ROOT / "agent_knowledge" / "modeling" / "通用业务对象与逻辑实体识别规范v0.0.1.md").read_text(encoding="utf-8")
        self.assertIn("通用业务对象与逻辑实体识别规范 v0.0.1", v6_rules)
        self.assertIn("业务对象判定标准", v6_rules)
        self.assertIn("UNKNOWN 闭环校验", v6_rules)
        self.assertIn("业务属性识别", v6_rules)
        self.assertIn("业务属性正式归属", v6_rules)
        v6_source = (ROOT / "agent_knowledge" / "通用业务对象与逻辑实体识别规范v0.0.1.md").read_text(encoding="utf-8")
        top_level_numbers = [
            int(line.split(". ", 1)[0].removeprefix("## "))
            for line in v6_source.splitlines() if line.startswith("## ") and ". " in line
        ]
        self.assertEqual(top_level_numbers, list(range(1, 22)))
        self.assertIn("## 6. 业务属性识别", v6_source)
        self.assertIn("## 7. 逻辑实体识别", v6_source)
        source_digest = hashlib.sha256(v6_source.encode("utf-8")).hexdigest()[:12]
        self.assertIn(f"SHA-256（前12位）：`{source_digest}`", v6_rules)
        integration_template = (ROOT / "agent_knowledge" / "integration" / "templatev0.0.1.md").read_text(encoding="utf-8")
        self.assertIn("智能消歧与整合模板v0.0.1.xlsx", integration_template)
        self.assertIn("推荐名称", integration_template)
        self.assertIn("business_rules.csv", integration_template)

    def test_modeling_source_files_are_specialized_and_composed_at_runtime(self):
        source_code = (ROOT / "agent_knowledge" / "modeling" / "source_codev0.0.1.md").read_text(encoding="utf-8")
        document = (ROOT / "agent_knowledge" / "modeling" / "business_documentv0.0.1.md").read_text(encoding="utf-8")
        self.assertIn("源代码本体建模v0.0.1.docx", source_code)
        self.assertNotIn("业务文档本体建模v0.0.1.docx", source_code)
        self.assertIn("业务文档本体建模v0.0.1.docx", document)
        self.assertNotIn("源代码本体建模v0.0.1.docx", document)

        composed = load_static_knowledge(ROOT / "agent_knowledge", "modeling",
                                         {"sourceMode": "SOURCE_CODE"})
        self.assertIn("通用业务对象与逻辑实体识别规范v0.0.1.md", composed)
        self.assertIn("源代码本体建模v0.0.1.docx", composed)
        self.assertNotIn("业务文档本体建模v0.0.1.docx", composed)

    def test_integration_output_contract_covers_expected_files(self):
        schema = (ROOT / "agent_knowledge" / "integration" / "output_schemav0.0.1.md").read_text(encoding="utf-8")
        for name in (
            "business_attributes.csv", "business_objects.csv", "business_rules.csv",
            "actions.csv", "business_object_relations.csv", "statuses.csv", "events.csv",
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
            delete_request = {}

            class DeleteResponse:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def read(self):
                    return b'{"success":true,"data":{"deleted":true}}'

            class DeleteOpener:
                def open(self, request, timeout=30):
                    delete_request["request"] = request
                    delete_request["timeout"] = timeout
                    return DeleteResponse()

            old_opener = server.urllib.request.build_opener
            try:
                server.urllib.request.build_opener = lambda *args, **kwargs: DeleteOpener()
                self.assertEqual(
                    server.fileserver_delete_object(
                        {"url": "https://files.example", "bucket": "ontology",
                         "secret_key": "secret", "access_key": "access"},
                        "ontology/1/integration-tasks/MI1/agent-output/ok.csv",
                    ),
                    {"deleted": True},
                )
            finally:
                server.urllib.request.build_opener = old_opener
            request = delete_request["request"]
            self.assertEqual(request.full_url, "https://files.example/sdk/object/delete")
            request_body = json.loads(request.data.decode("utf-8"))
            self.assertEqual(request_body, {
                "bucketName": "ontology",
                "objectKey": "ontology/1/integration-tasks/MI1/agent-output/ok.csv",
            })
            self.assertEqual(request.get_header("Content-type"), "application/json")
            self.assertEqual(delete_request["timeout"], 30)
            self.assertEqual(
                request.get_header("Authorization"),
                server._fileserver_auth("POST", "/sdk/object/delete", "secret", "access",
                                         body=request.data.decode("utf-8")),
            )
            reopen_task = types.SimpleNamespace(
                platform_status="COMPLETED",
                platform_uploaded_files={"ok.csv": {"objectKey": "ontology/1/integration-tasks/MI1/agent-output/ok.csv"}},
                platform_output_prefix="ontology/1/integration-tasks/MI1/agent-output",
                mission_context={"taskType": "integration", "outputPrefix": "ontology/1/integration-tasks/MI1/agent-output"},
                task_type="integration", task_code="MI1", platform_last_error="", platform_updated=0,
            )
            deleted_keys = []
            original_reopen = {
                "config": server.minio_config,
                "delete": server.fileserver_delete_object,
                "callback": server.task_status_callback,
                "persist": server.persist_tasks,
            }
            try:
                server.minio_config = lambda: {"bucket": "ontology"}
                server.fileserver_delete_object = lambda cfg, key: deleted_keys.append(key) or {}
                server.task_status_callback = lambda task, status, **kwargs: {"ok": True, "status": status}
                server.persist_tasks = lambda: None
                reopened, reopen_error = server.reopen_completed_mission(
                    reopen_task, authorization="Bearer token")
                self.assertTrue(reopened)
                self.assertIsNone(reopen_error)
                self.assertEqual(deleted_keys, ["ontology/1/integration-tasks/MI1/agent-output/ok.csv"])
                self.assertEqual(reopen_task.platform_status, "RUNNING")
                self.assertEqual(reopen_task.platform_uploaded_files, {})
            finally:
                server.minio_config = original_reopen["config"]
                server.fileserver_delete_object = original_reopen["delete"]
                server.task_status_callback = original_reopen["callback"]
                server.persist_tasks = original_reopen["persist"]

            original_tasks = server.TASKS
            original_bound = server.mission_bound_project
            try:
                existing = types.SimpleNamespace(
                    repository_id="1", task_code="RM1", user_id="u1", updated=10,
                )
                server.TASKS = {"existing": existing}
                server.mission_bound_project = lambda *args: "mission-1-RM1"
                self.assertIs(
                    server.create_task("", "1", "RM1", "modeling", "u1"),
                    existing,
                )
            finally:
                server.TASKS = original_tasks
                server.mission_bound_project = original_bound
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
            self.assertIn("是否页面显示", server.build_modeling_instructions({}))
            self.assertIn("Validator 是只读语义检查器", server.build_modeling_instructions({}))
            self.assertIn("Validator 的约束、错误、WARNING、重试次数", server.build_modeling_instructions({}))
            self.assertIn("只有 CONFIRMED 且有正式证据才能写入", server.build_modeling_instructions({}))
            self.assertIn("business_object_decisions.csv", server.build_modeling_instructions({}))
            self.assertIn("每一个实际评估的 Business Object candidate", server.build_modeling_instructions({}))
            self.assertIn("ALERT_DETECTION_RULE", server.build_modeling_instructions({}))
            self.assertIn("条件命中不是 violation", server.build_modeling_instructions({}))
            self.assertIn("TaskCreate 返回的本地 task id", server.build_modeling_instructions({}))
            orchestration_task = types.SimpleNamespace(
                id="run-1", task_code="RM1", task_type="modeling", status="idle",
                platform_status="RUNNING",
                mission_context={"taskType": "modeling", "expectedFiles": ["result.csv"]},
                platform_uploaded_files={}, modeling_plan={}, run_result={},
            )
            gate_issues = server.task_completion_gate(orchestration_task)
            self.assertIn("ARTIFACT_MISSING", {item["code"] for item in gate_issues})
            orchestration_task.platform_uploaded_files = {"result.csv": {"objectKey": "k", "sha256": "s"}}
            self.assertEqual(server.task_completion_gate(orchestration_task), [])
            server.set_task_run_result(orchestration_task, "ORCHESTRATION_FAILED",
                                        errors=["FINALIZATION_FAILED"])
            self.assertEqual(orchestration_task.run_result["status"], "ORCHESTRATION_FAILED")
            self.assertIn("source=component/dependent/child", server.build_modeling_instructions({}))
            self.assertIn("实体出现在 COMPOSITION 任意一端不等于合法", server.build_modeling_instructions({}))
            with tempfile.TemporaryDirectory() as modeling_tmp:
                work = Path(modeling_tmp) / "work"
                work.mkdir()
                (work / "modeling_state.json").write_text(json.dumps({
                    "entities": [
                        {"entityId": "LE_MAIN", "role": "MAIN"},
                        {"entityId": "LE_CHILD", "role": "DEPENDENT"},
                    ],
                    "relationDecisions": [{
                        "relationId": "REL_REVERSED",
                        "sourceEntity": "LE_MAIN", "targetEntity": "LE_CHILD",
                        "relationType": "COMPOSITION", "status": "CONFIRMED",
                        "evidenceTypes": ["EXPLICIT_CONFIG"],
                        "evidenceLevel": "STRONG",
                        "provenance": ["input/ownership.yaml"],
                    }],
                }), encoding="utf-8")
                evidence_issues = server.validate_modeling_evidence(
                    "business_objects.csv", b"", modeling_tmp)
                self.assertIn("INVALID_COMPOSITION_DIRECTION",
                              {item["code"] for item in evidence_issues})
            layered_instructions = server.build_modeling_instructions({
                "taskType": "modeling", "repositoryId": "1", "taskCode": "RM123456789",
                "parseElements": ["LOGICAL_ENTITY", "BUSINESS_ATTRIBUTE", "ENTITY_RELATION", "BUSINESS_OBJECT", "RULE", "METRIC"],
                "expectedFiles": ["logical_entities.csv", "business_attributes.csv", "entity_relations.csv", "business_objects.csv", "business_rules.csv", "metrics.csv"],
            })
            self.assertIn("logicalModelArtifact", layered_instructions)
            self.assertIn("候选属性 → 逻辑实体 → 正式业务属性 → 实体关系", layered_instructions)
            self.assertIn("businessObjectArtifact", layered_instructions)
            self.assertIn("repositoryId + taskCode + modelVersion + inputFingerprint", layered_instructions)
            skill_instructions = server.build_modeling_instructions(
                {"parseElements": ["TERM", "RULE", "METRIC"]})
            self.assertIn("业务术语v0.0.1.md", skill_instructions)
            self.assertIn("业务规则v0.0.1.md", skill_instructions)
            self.assertIn("指标v0.0.1.md", skill_instructions)
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
            with tempfile.TemporaryDirectory() as reference_tmp:
                reference_file = Path(reference_tmp) / "input" / "本体元模型3.xlsx"
                reference_file.parent.mkdir()
                reference_file.write_bytes(b"legacy-system-reference")
                references = server.ensure_mission_reference_files(reference_tmp)
                self.assertEqual(
                    references,
                    [
                        "input/Ontology平台模型编码规范v0.0.1.xlsx",
                        "input/本体元模型v0.0.1.xlsx",
                        "input/本体元模型模板v.0.0.1.xlsx",
                        "input/本体元模型模板v0.0.1（含样例数据）.xlsx",
                    ],
                )
                self.assertTrue((Path(reference_tmp) / references[0]).is_file())
                self.assertTrue((Path(reference_tmp) / references[1]).is_file())
                self.assertTrue((Path(reference_tmp) / references[2]).is_file())
                self.assertTrue((Path(reference_tmp) / references[3]).is_file())
                self.assertFalse(reference_file.exists())
                source_template = ROOT / "rules" / "本体元模型模板v.0.0.1.xlsx"
                copied_template = Path(reference_tmp) / "input" / source_template.name
                copied_template.write_bytes(b"0" * source_template.stat().st_size)
                server.ensure_mission_reference_files(reference_tmp)
                self.assertEqual(copied_template.read_bytes(), source_template.read_bytes())
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
            self.assertEqual(server.parse_element_for_file("indicators.csv"), "METRIC")
            self.assertEqual(server.normalize_parse_elements(["indicator"]), {"METRIC"})
            self.assertIn("indicators.csv", server.allowed_output_files(["METRIC"], ["indicators.csv"]))
            self.assertTrue(server.upstream_reports_completed("任务已成功，不能再次执行"))
            self.assertTrue(server.upstream_reports_completed("task already success"))
            self.assertFalse(server.upstream_reports_completed("integration task does not exist"))
            self.assertTrue(server.upstream_context_configuration_error("解析要素未配置输出文件: business_object"))
            self.assertFalse(server.upstream_context_configuration_error("认证失败: 访问Token不存在"))
            self.assertFalse(server.upstream_context_configuration_error("integration task does not exist"))
            server_source = (ROOT / "open-claude" / "oc_codex_server.py").read_text(encoding="utf-8")
            self.assertIn('"本体元模型模板v0.0.1（含样例数据）.xlsx"', server_source)
            self.assertIn("context_config_err or last_err", server_source)
            self.assertIn('"agentStatus": "SUCCESS"', server_source)
            self.assertIn('"MODELING_CONTEXT_INVALID"', server_source)
            self.assertIn('"MISSION_CONTEXT_UNAVAILABLE"', server_source)
            self.assertNotIn('client_context = data.get("missionContext")', server_source)
            self.assertIn("/platform-status", server_source)
            self.assertEqual(server.normalize_platform_status("SUCCESS"), "COMPLETED")
            self.assertEqual(server.normalize_platform_status("SUCCEED"), "COMPLETED")
            self.assertEqual(server.platform_status_from_payload({"agentStatus": "COMPLETED"}), "COMPLETED")
            self.assertEqual(server.platform_status_from_payload({"agentStatus": "SUCCEED"}), "COMPLETED")
            self.assertEqual(server._MODELING_HEADERS["business_terms.csv"], ["术语编码", "术语名称", "别名", "英文名", "缩略语", "术语定义"])
            self.assertEqual(server._MODELING_HEADERS["metrics.csv"][0], "指标编码")
            self.assertEqual(server._MODELING_HEADERS["business_rules.csv"], ["规则编码", "规则名称", "规则描述", "触发条件", "判断或结果", "处置动作"])
            self.assertEqual(server._MODELING_HEADERS["actions.csv"], ["动作编码", "动作名称", "动作英文名", "动作描述", "动作类型", "业务对象编码", "协议", "服务节点", "服务名称"])
            valid_action_csv = "动作编码,动作名称,动作英文名,动作描述,动作类型,业务对象编码,协议,服务节点,服务名称\nACT000001,创建采购订单,createPurchaseOrder,创建采购订单,新增,BO0001,,,\n"
            self.assertEqual(server.validate_modeling_csv("actions.csv", valid_action_csv.encode()), [])
            self.assertTrue(server.validate_modeling_csv(
                "actions.csv", valid_action_csv.replace("新增", "执行").encode()
            ))
            self.assertTrue(server.validate_modeling_csv(
                "actions.csv", valid_action_csv.replace("ACT000001", "ACT1").encode()
            ))
            valid_term_csv = "术语编码,术语名称,别名,英文名,缩略语,术语定义\nT001,订单,,Order,,业务术语\n"
            self.assertEqual(server.validate_modeling_csv("business_terms.csv", valid_term_csv.encode()), [])
            self.assertTrue(server.validate_modeling_csv("business_terms.csv", b"id,name,description\n1,x,y\n"))
            valid_metric_csv = "指标编码,指标名称,指标别名,指标英文名,指标定义,计算公式,统计口径,指标类型,来源业务对象,来源逻辑实体,来源业务属性,聚合类型,时间维度,计算规则,过滤条件\nM001,订单数,,,,,,,,,,,,,\n"
            self.assertEqual(server.validate_modeling_csv("metrics.csv", valid_metric_csv.encode()), [])
            valid_rule_csv = "规则编码,规则名称,规则描述,触发条件,判断或结果,处置动作\nR0000001,订单校验,订单必须有效,订单提交,校验通过,允许提交\n"
            self.assertEqual(server.validate_modeling_csv("business_rules.csv", valid_rule_csv.encode()), [])
            self.assertTrue(server.validate_modeling_csv(
                "business_rules.csv", valid_rule_csv.replace("R0000001", "R000001").encode()
            ))
            self.assertTrue(server.validate_modeling_csv(
                "rules.csv", (valid_rule_csv + "R0000001,重复规则,,,,\n").encode()
            ))
            self.assertEqual(server.parse_element_for_file("business_object_relations.csv"), "BUSINESS_OBJECT_RELATION")
            self.assertEqual(server.parse_element_for_file("statuses.csv"), "STATUS")
            self.assertEqual(server.parse_element_for_file("events.csv"), "EVENT")
            valid_object_relation = "关系编码,源业务对象编码,源业务对象名称,关系类型,关系英文名称,关系中文名名称,目标业务对象编码,目标业务对象名称,关系基数,关系描述\nREL000001,BO00001,合同,依赖关系,generates,生成,BO00002,订单,1:1,合同生成订单\n"
            self.assertEqual(server.validate_modeling_csv("business_object_relations.csv", valid_object_relation.encode()), [])
            valid_status = "业务对象编码,业务对象名称,状态编码,状态英文名,状态中文名,状态含义,触发条件,是否终态,是否主终态\nBO00001,合同,ACTIVE,Active,生效,合同已生效,审批通过,N,N\n"
            self.assertEqual(server.validate_modeling_csv("statuses.csv", valid_status.encode()), [])
            invalid_status = valid_status.replace(",N,N\n", ",N,Y\n")
            self.assertTrue(server.validate_modeling_csv("statuses.csv", invalid_status.encode()))
            valid_event = "事件编码,事件名称,事件中文名称,事件含义,触发结果\nE001,ContractApproved,合同审批通过,合同完成审批,合同进入生效状态\n"
            self.assertEqual(server.validate_modeling_csv("events.csv", valid_event.encode()), [])
            self.assertEqual(server.validate_integration_csv("business_object_relations.csv", valid_object_relation.encode()), [])
            self.assertEqual(server.validate_integration_csv("statuses.csv", valid_status.encode()), [])
            self.assertTrue(server.validate_integration_csv("statuses.csv", invalid_status.encode()))
            self.assertEqual(server.validate_integration_csv("events.csv", valid_event.encode()), [])
            term_plan = server.build_modeling_plan({
                "taskType": "DOCUMENT_MODELING", "repositoryId": "1", "taskCode": "RMTERM001",
                "modelVersion": "V6", "inputFingerprint": "input-a",
                "parseElements": ["TERM"], "expectedFiles": ["business_terms.csv"],
            })
            self.assertTrue(term_plan["valid"])
            self.assertEqual(term_plan["identity"]["key"], "1/RMTERM001/V6/input-a")
            self.assertEqual(server.modeling_context_contract_errors({
                "parseElements": ["TERM"], "expectedFiles": ["business_terms.csv"],
            }), [])
            self.assertTrue(server.modeling_context_contract_errors({
                "parseElements": ["TERM"], "expectedFiles": ["metrics.csv"],
            }))
            self.assertTrue(server.is_conversational_turn("谢谢，结果不错"))
            self.assertEqual(term_plan["artifacts"]["termArtifact"]["status"], "PENDING")
            document_context = server.normalize_modeling_context({
                "taskType": "DOCUMENT_MODELING", "repositoryId": "1", "taskCode": "RMDOC001",
                "document": {"fileSourceId": 25, "fileType": "DOCX", "objectKey": "ontology/1/input.docx"},
                "parseElements": ["LOGICAL_ENTITY", "BUSINESS_ATTRIBUTE", "ENTITY_RELATION"],
            })
            self.assertEqual(document_context["sourceMode"], "DOCUMENT")
            self.assertEqual(
                document_context["expectedFiles"],
                ["logical_entities.csv", "business_attributes.csv", "entity_relations.csv"],
            )
            contract = {item["parseElement"]: item for item in document_context["documentOutputContract"]}
            self.assertTrue(contract["LOGICAL_ENTITY"]["requested"])
            self.assertEqual(contract["LOGICAL_ENTITY"]["expectedFiles"], ["logical_entities.csv"])
            self.assertIn("manifest.json", server.build_modeling_instructions(document_context))
            self.assertIn("logical_entities.csv", server.build_modeling_instructions(document_context))
            self.assertEqual(
                server.normalize_modeling_context({
                    "document": {"fileType": "PDF", "objectKey": "ontology/1/input.pdf"},
                    "parseElements": ["TERM"],
                    "expectedFiles": ["business_terms.csv"],
                })["sourceMode"],
                "DOCUMENT",
            )
            # Document task smoke E2E: object-store download -> document bundle
            # -> model output -> MinIO upload and COMPLETED callback.
            with tempfile.TemporaryDirectory() as document_tmp:
                document_root = Path(document_tmp)
                document_input = document_root / "input"
                document_input.mkdir()
                from io import BytesIO
                package = BytesIO()
                with zipfile.ZipFile(package, "w") as zf:
                    zf.writestr("word/document.xml", '''<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>订单章节</w:t></w:r></w:p><w:p><w:r><w:t>订单用于记录采购。</w:t></w:r></w:p></w:body></w:document>''')
                source_bytes = package.getvalue()
                class DownloadResponse:
                    def __enter__(self):
                        return self
                    def __exit__(self, *args):
                        return False
                    def read(self, _limit):
                        return source_bytes
                class DownloadOpener:
                    def open(self, _request, timeout=60):
                        self.timeout = timeout
                        return DownloadResponse()
                old_opener = server.urllib.request.build_opener
                try:
                    server.urllib.request.build_opener = lambda *args, **kwargs: DownloadOpener()
                    downloaded, download_errors = server.download_mission_files(
                        {"preview_base": "https://files.example", "bucket": "ontology"},
                        document_context, document_tmp,
                    )
                finally:
                    server.urllib.request.build_opener = old_opener
                self.assertEqual(download_errors, [])
                downloaded_path = document_root / downloaded[0]["path"]
                self.assertTrue(downloaded_path.is_file())
                manifests, parse_errors = server.prepare_mission_documents(document_tmp)
                self.assertEqual(parse_errors, [])
                self.assertEqual(manifests[0]["format"], "docx")
                self.assertIn("订单章节", (document_root / manifests[0]["bundle"] / "content.md").read_text(encoding="utf-8"))
                output = document_root / "output"
                output.mkdir()
                (output / "logical_entities.csv").write_text(
                    "业务对象编码,业务对象名称,逻辑实体编码,逻辑实体名称,逻辑实体英文名,逻辑实体定义,是否主逻辑实体,数据类别\n"
                    "BO1,采购,LE1,采购订单,purchaseOrder,采购订单,Y,事务数据\n", encoding="utf-8")
                document_upload_context = server.normalize_modeling_context({
                    **document_context,
                    "parseElements": ["LOGICAL_ENTITY"],
                    "expectedFiles": ["logical_entities.csv"],
                    "outputPrefix": "ontology/1/modeling-tasks/RMDOC001/agent-output",
                })

                class DocumentUploadTask:
                    id = "document-upload-task"
                    project = "project"
                    repository_id = "1"
                    task_code = "RMDOC001"
                    task_type = "modeling"
                    user_id = "u1"
                    cwd = document_tmp
                    platform_status = "RUNNING"
                    platform_updated = 0
                    platform_last_error = ""
                    platform_output_prefix = ""
                    platform_uploaded_files = {}
                    platform_lock = threading.Lock()
                    status = "idle"
                    mission_context = document_upload_context
                    modeling_plan = {}

                    def set_mission_context(self, context):
                        self.mission_context = dict(context)

                    def record_uploaded_results(self, prefix, results):
                        server.Task.record_uploaded_results(self, prefix, results)

                    def refresh_modeling_artifacts(self):
                        self.modeling_plan = server.build_modeling_plan(self.mission_context, self.repository_id, self.task_code)

                    def summary(self):
                        return {"id": self.id, "platformStatus": self.platform_status,
                                "uploadedResultCount": len(self.platform_uploaded_files)}

                document_task = DocumentUploadTask()
                document_handler = object.__new__(server.Handler)
                document_responses, document_callbacks = [], []
                originals = {
                    "bind": server.bind_mission_project, "context": server.fetch_execution_context,
                    "cwd": server.mission_task_cwd, "config": server.minio_config,
                    "put": server.fileserver_put_object, "callback": server.task_status_callback,
                    "persist": server.persist_tasks,
                }
                try:
                    server.bind_mission_project = lambda *args: "project"
                    server.fetch_execution_context = lambda *args: {
                        **document_upload_context, "_platformStatus": "RUNNING",
                    }
                    server.mission_task_cwd = lambda *args: document_tmp
                    server.minio_config = lambda: {"bucket": "bucket"}
                    server.fileserver_put_object = lambda cfg, key, blob, name, ctype: {
                        "objectKey": key, "previewUrl": "https://files.example/" + name,
                    }
                    server.task_status_callback = lambda task, status, **kwargs: (
                        document_callbacks.append((status, kwargs.get("files"))) or {"ok": True})
                    server.persist_tasks = lambda: None
                    document_handler.headers = {}
                    document_handler._owned_task = lambda task_id: document_task if task_id == document_task.id else None
                    document_handler._current_user = lambda: "u1"
                    document_handler._send_json = lambda payload, status=200: document_responses.append((status, payload))
                    document_handler._read_body = lambda: {
                        "project": "project", "prefix": "ontology/1/modeling-tasks/RMDOC001/agent-output",
                        "taskCode": "RMDOC001", "repositoryId": "1", "taskId": document_task.id,
                        "taskType": "modeling", "paths": ["output/logical_entities.csv"],
                    }
                    # Modeling semantic validation is completed before upload;
                    # this fixture represents that persisted finalize marker.
                    server.write_decision_audits(Path(document_tmp) / "work", {})
                    server.finalize_semantic_model(
                        Path(document_tmp) / "work", {},
                        output_dir=Path(document_tmp) / "output",
                        required_outputs=[],
                    )
                    document_handler._handle_minio_upload()
                finally:
                    server.bind_mission_project = originals["bind"]
                    server.fetch_execution_context = originals["context"]
                    server.mission_task_cwd = originals["cwd"]
                    server.minio_config = originals["config"]
                    server.fileserver_put_object = originals["put"]
                    server.task_status_callback = originals["callback"]
                    server.persist_tasks = originals["persist"]
                self.assertEqual(document_callbacks, [])
                self.assertTrue(document_responses[-1][1]["callback"]["skipped"])
                self.assertIn("点击“完成”", document_responses[-1][1]["completionHint"])
                self.assertEqual(document_responses[-1][1]["uploaded"], 1)
            fingerprint_a = server._modeling_input_fingerprint({
                "dataSource": {"id": 12, "password": "one"}, "parseElements": ["TERM"]},
                "RMTERM001")
            fingerprint_b = server._modeling_input_fingerprint({
                "dataSource": {"id": 12, "password": "two"}, "parseElements": ["TERM"]},
                "RMTERM001")
            self.assertEqual(fingerprint_a, fingerprint_b)
            nested_fingerprint_a = server._modeling_input_fingerprint({
                "database": {"databaseSourceId": 12, "selectedTables": ["orders"]},
                "parseElements": ["TERM"],
            }, "RMTERM001")
            nested_fingerprint_b = server._modeling_input_fingerprint({
                "database": {"databaseSourceId": 12, "selectedTables": ["contracts"]},
                "parseElements": ["TERM"],
            }, "RMTERM001")
            self.assertNotEqual(nested_fingerprint_a, nested_fingerprint_b)
            with tempfile.TemporaryDirectory() as state_tmp:
                first_context = {
                    "taskCode": "RMTERM001", "parseElements": ["TERM"],
                    "expectedFiles": ["business_terms.csv"],
                    "document": {"objectKey": "ontology/1/input-a.docx"},
                }
                state_rel = server.ensure_mission_work_state(state_tmp, first_context)
                state_path = Path(state_tmp) / state_rel
                populated_state = json.loads(state_path.read_text(encoding="utf-8"))
                populated_state["generatedByAgent"] = True
                populated_state["artifacts"] = {"termArtifact": {"status": "READY"}}
                state_path.write_text(json.dumps(populated_state), encoding="utf-8")
                second_context = {
                    **first_context,
                    "document": {"objectKey": "ontology/1/input-b.docx"},
                }
                server.ensure_mission_work_state(state_tmp, second_context)
                current_state = json.loads(state_path.read_text(encoding="utf-8"))
                self.assertFalse(current_state["generatedByAgent"])
                self.assertNotEqual(
                    current_state["inputFingerprint"], populated_state["inputFingerprint"])
                archives = list((Path(state_tmp) / "work").glob("modeling_state.*.json"))
                self.assertTrue(archives)
            alias_status_task = types.SimpleNamespace(
                repository_id="1", task_code="RMTERM001", task_type="modeling",
                mission_context={"taskType": "modeling", "parseElements": ["RULE"],
                                 "expectedFiles": ["rules.csv"]},
                platform_uploaded_files={"rules.csv": {"objectKey": "rules.csv"}},
                modeling_plan={},
            )
            server.Task.refresh_modeling_artifacts(alias_status_task)
            self.assertEqual(
                alias_status_task.modeling_plan["artifacts"]["ruleArtifact"]["status"],
                "COMPLETED",
            )
            old_tasks = server.TASKS
            try:
                alias_status_task.user_id = "u1"
                alias_status_task.updated = 2
                server.TASKS = {"task-1": alias_status_task}
                context_without_type = dict(alias_status_task.mission_context)
                context_without_type.pop("taskType", None)
                refreshed_context = server.enrich_modeling_context(
                    context_without_type, "1", "RMTERM001")
                refreshed_context = server.enrich_mission_context_from_task(
                    refreshed_context, "1", "RMTERM001", "u1")
                self.assertEqual(
                    refreshed_context["modelingPlan"]["artifacts"]["ruleArtifact"]["status"],
                    "COMPLETED",
                )
            finally:
                server.TASKS = old_tasks
            object_plan = server.build_modeling_plan({
                "taskType": "modeling", "parseElements": ["BUSINESS_OBJECT"],
                "expectedFiles": ["business_objects.csv"],
            }, "1", "RM123456789")
            self.assertTrue(object_plan["valid"])
            self.assertEqual(object_plan["dependencyErrors"], [])
            # A platform context may omit ENTITY_RELATION while still asking
            # for the first-layer entity/attribute outputs and a downstream
            # business object.  The server should run relation recognition as
            # an internal prerequisite, without requiring an undeclared output
            # file or rejecting a follow-up question before the model call.
            inferred_relation_plan = server.build_modeling_plan({
                "taskType": "DOCUMENT_MODELING",
                "parseElements": ["LOGICAL_ENTITY", "BUSINESS_ATTRIBUTE", "BUSINESS_OBJECT"],
                "expectedFiles": ["logical_entities.csv", "business_attributes.csv", "business_objects.csv"],
            }, "1", "RM123456789")
            self.assertTrue(inferred_relation_plan["valid"])
            self.assertNotIn("ENTITY_RELATION", inferred_relation_plan["requestedElements"])
            self.assertEqual(inferred_relation_plan.get("implicitDependencies"), [])
            self.assertTrue(server.is_conversational_turn("你不用做了，问你点问题"))
            self.assertTrue(server.is_conversational_turn("为什么会失败？"))
            self.assertTrue(server.is_conversational_turn("别做了"))
            self.assertTrue(server.is_conversational_turn("帮我看看"))
            self.assertTrue(server.is_conversational_turn("先说说这个项目"))
            self.assertFalse(server.is_conversational_turn("继续做"))
            self.assertFalse(server.is_conversational_turn("请分析数据库并生成模型"))
            self.assertFalse(server.is_conversational_turn(
                "上一个问题是什么来着 反正你接着上一个问题继续做"))
            self.assertFalse(server.is_conversational_turn("接着上一个问题继续做"))
            self.assertFalse(server.is_conversational_turn(
                "请重新生成business_objects.csv文件内容"))
            self.assertTrue(server.is_conversational_turn("怎么建模"))
            self.assertTrue(server.is_conversational_turn("为什么执行会失败"))
            self.assertFalse(server.is_conversational_turn(
                "请直接开始执行当前任务", explicit_start=True))
            upload_gate_task = types.SimpleNamespace(
                repository_id="1", task_code="RM123456789",
                platform_uploaded_files={"logical_entities.csv": {"sha256": "x"}},
            )
            upload_gate_errors = server.modeling_upload_dependency_errors(
                upload_gate_task,
                {"taskType": "modeling", "parseElements": ["LOGICAL_ENTITY", "BUSINESS_ATTRIBUTE", "ENTITY_RELATION", "BUSINESS_OBJECT"],
                 "expectedFiles": ["logical_entities.csv", "business_attributes.csv", "entity_relations.csv", "business_objects.csv"]},
                ["output/business_objects.csv"],
            )
            self.assertEqual(upload_gate_errors, [])
            partial_contract_task = types.SimpleNamespace(
                repository_id="1", task_code="RM123456789",
                platform_uploaded_files={
                    "logical_entities.csv": {"sha256": "x"},
                    "business_attributes.csv": {"sha256": "y"},
                },
            )
            self.assertEqual(
                server.modeling_upload_dependency_errors(
                    partial_contract_task,
                    {"taskType": "DOCUMENT_MODELING",
                     "parseElements": ["LOGICAL_ENTITY", "BUSINESS_ATTRIBUTE", "BUSINESS_OBJECT"],
                     "expectedFiles": ["logical_entities.csv", "business_attributes.csv", "business_objects.csv"]},
                    ["output/business_objects.csv"],
                ),
                [],
            )
            complete_layers = server.build_modeling_plan({
                "taskType": "modeling",
                "parseElements": ["LOGICAL_ENTITY", "BUSINESS_ATTRIBUTE", "ENTITY_RELATION", "BUSINESS_OBJECT"],
                "expectedFiles": ["logical_entities.csv", "business_attributes.csv", "entity_relations.csv", "business_objects.csv"],
            }, "1", "RM123456789")
            self.assertTrue(complete_layers["valid"])
            expanded_logical = server.build_modeling_plan({
                "taskType": "modeling", "parseElements": ["LOGICAL_MODEL"],
                "expectedFiles": ["logical_entities.csv", "business_attributes.csv", "entity_relations.csv"],
            }, "1", "RM123456789")
            self.assertIn("CANDIDATE_ATTRIBUTE", expanded_logical["requestedElements"])
            self.assertTrue(expanded_logical["valid"])
            rule_without_object = server.build_modeling_plan({
                "taskType": "modeling", "parseElements": ["RULE"],
                "expectedFiles": ["business_rules.csv"],
            }, "1", "RM123456789")
            self.assertTrue(rule_without_object["valid"])
            rule_with_reference = server.build_modeling_plan({
                "taskType": "modeling", "parseElements": ["RULE"],
                "expectedFiles": ["business_rules.csv"],
                "artifactRefs": {"businessObjectArtifact": {"status": "COMPLETED", "artifactId": "bo-1"}},
            }, "1", "RM123456789")
            self.assertTrue(rule_with_reference["valid"])
            wrapped_context = server.normalize_execution_context({
                "taskStatus": "RUNNING",
                "executionContext": {"taskCode": "RM123456789", "outputPrefix": "ontology/1/out"},
            })
            self.assertEqual(wrapped_context["outputPrefix"], "ontology/1/out")
            self.assertEqual(wrapped_context["taskStatus"], "RUNNING")
            original_tasks, original_persist = server.TASKS, server.persist_tasks
            try:
                legacy_task = types.SimpleNamespace(
                    repository_id="1", task_code="RM123456789", user_id="local:old-browser",
                    conv=types.SimpleNamespace(model="old-model"),
                )
                server.TASKS = {"legacy": legacy_task}
                server.persist_tasks = lambda: None
                self.assertEqual(server.claim_legacy_mission_tasks("1", "RM123456789", "platform-user"), 1)
                self.assertEqual(legacy_task.user_id, "platform-user")
                unowned_task = types.SimpleNamespace(
                    repository_id="1", task_code="RM123456789", user_id="",
                    conv=types.SimpleNamespace(model="old-model"),
                )
                server.TASKS = {"unowned": unowned_task}
                self.assertEqual(server.claim_legacy_mission_tasks("1", "RM123456789", "platform-user"), 1)
                self.assertEqual(unowned_task.user_id, "platform-user")
            finally:
                server.TASKS, server.persist_tasks = original_tasks, original_persist
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
                    unclaimed = types.SimpleNamespace(user_id="")
                    self.assertFalse(server._mission_task_user_matches(unclaimed, "external-user"))
                    old_local_auth = os.environ.get("ONTOLOGY_ALLOW_LOCAL_DEV_AUTH")
                    try:
                        os.environ["ONTOLOGY_ALLOW_LOCAL_DEV_AUTH"] = "true"
                        self.assertTrue(server._mission_task_user_matches(unclaimed, "local:current-browser"))
                    finally:
                        if old_local_auth is None:
                            os.environ.pop("ONTOLOGY_ALLOW_LOCAL_DEV_AUTH", None)
                        else:
                            os.environ["ONTOLOGY_ALLOW_LOCAL_DEV_AUTH"] = old_local_auth
                    # A mission query must not turn a foreign task into a
                    # readable detail record.  The route helper performs the
                    # ownership check before validating the tuple.
                    owned_detail = types.SimpleNamespace(
                        repository_id="1", task_code="RM123456789", user_id="current-user",
                    )
                    detail_handler = object.__new__(server.Handler)
                    detail_handler._owned_task = lambda task_id: owned_detail
                    detail_responses = []
                    detail_handler._send_json = lambda payload, status=200: detail_responses.append((payload, status))
                    self.assertIsNone(detail_handler._owned_task_for_detail(
                        "task-1", "2", "RM123456789"))
                    self.assertEqual(detail_responses[-1][1], 403)
                    old_tasks_for_auth = server.TASKS
                    old_trust_proxy = os.environ.get("ONTOLOGY_TRUST_PROXY_AUTH")
                    try:
                        os.environ["ONTOLOGY_TRUST_PROXY_AUTH"] = "true"
                        server.TASKS = {"foreign": types.SimpleNamespace(
                            repository_id="1", task_code="RM123456789", user_id="other-user",
                        )}
                        foreign_handler = object.__new__(server.Handler)
                        foreign_handler.headers = {"X-User-Id": "current-user"}
                        foreign_responses = []
                        foreign_handler._send_json = lambda payload, status=200: foreign_responses.append((payload, status))
                        self.assertIsNone(foreign_handler._owned_task_for_detail(
                            "foreign", "1", "RM123456789"))
                        self.assertEqual(foreign_responses[-1][1], 403)
                    finally:
                        server.TASKS = old_tasks_for_auth
                        if old_trust_proxy is None:
                            os.environ.pop("ONTOLOGY_TRUST_PROXY_AUTH", None)
                        else:
                            os.environ["ONTOLOGY_TRUST_PROXY_AUTH"] = old_trust_proxy
                    legacy_input = Path(server.SCRIPT_DIR) / "mission-input"
                    legacy_input.mkdir(parents=True)
                    object_key = "bucket/source.xlsx"
                    suffix = hashlib.sha256(object_key.encode("utf-8")).hexdigest()[:8]
                    legacy_name = f"source-{suffix}.xlsx"
                    (legacy_input / legacy_name).write_bytes(b"legacy-input")
                    migrated = server.migrate_legacy_mission_inputs(
                        {"source": {"filename": "source.xlsx", "objectKey": object_key}},
                        str(task_dir), "ontology-workspace-1")
                    self.assertEqual(migrated, [f"input/{legacy_name}"])
                    self.assertTrue((task_dir / "input" / legacy_name).is_file())
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
                output = Path(task_tmp) / "output"
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
                server.finalize_semantic_model(
                    Path(task_tmp) / "work", {},
                    output_dir=output, required_outputs=["logical_entities.csv"],
                )
                partial_task = types.SimpleNamespace(
                    cwd=task_tmp,
                    task_code="RM123456789",
                    task_type="modeling",
                    mission_context={
                        "taskType": "modeling", "parseElements": ["LOGICAL_ENTITY", "ENTITY_RELATION"],
                        "expectedFiles": ["logical_entities.csv", "entity_relations.csv"],
                    },
                    platform_uploaded_files=completion_task.platform_uploaded_files,
                )
                _, partial_error = server.build_completed_callback_payload(partial_task)
                self.assertIn("请先上传全部结果文件后再确认完成", partial_error)
                completion, completion_error = server.build_completed_callback_payload(completion_task)
                self.assertIsNone(completion_error)
                self.assertEqual(completion["agentStatus"], "SUCCESS")
                self.assertEqual(completion["files"][0]["parseElement"], "LOGICAL_ENTITY")
                completion_task.platform_uploaded_files["logical_entities.csv"]["previewUrl"] = ""
                _, preview_error = server.build_completed_callback_payload(completion_task)
                self.assertIn("记录不完整", preview_error)
                completion_task.platform_uploaded_files["logical_entities.csv"]["previewUrl"] = "https://files.example/preview.csv"
                result_file.write_text("逻辑实体编码,逻辑实体名称\nLE1,已修改采购订单\n", encoding="utf-8")
                _, changed_error = server.build_completed_callback_payload(completion_task)
                self.assertIn("上传后已变更", changed_error)
            with tempfile.TemporaryDirectory() as upload_tmp:
                output = Path(upload_tmp) / "output"
                output.mkdir()
                logical = output / "logical_entities.csv"
                logical.write_text(
                    "业务对象编码,业务对象名称,逻辑实体编码,逻辑实体名称,逻辑实体英文名,逻辑实体定义,是否主逻辑实体,数据类别\n"
                    "BO1,采购,LE1,采购订单,purchaseOrder,采购订单,Y,事务数据\n",
                    encoding="utf-8",
                )
                business_attribute = output / "business_attributes.csv"
                business_attribute.write_text(
                    "逻辑实体编码,逻辑实体名称,业务属性编码,业务属性名称,业务属性英文名称,业务属性定义,数据类型,数据长度,数据精度,是否物理主键,是否逻辑主键,是否唯一,是否非空,是否页面显示,是否层级编码,是否层级名称\n"
                    "LE1,采购订单,BA1,订单号,orderNumber,订单标识,文本,50,,N,Y,Y,Y,N,N,N\n",
                    encoding="utf-8",
                )

                class UploadTask:
                    id = "upload-task"
                    project = "project"
                    repository_id = "1"
                    task_code = "RM123456789"
                    task_type = "modeling"
                    user_id = "u1"
                    cwd = upload_tmp
                    platform_status = "RUNNING"
                    platform_updated = 0
                    platform_last_error = ""
                    platform_output_prefix = ""
                    platform_uploaded_files = {}
                    platform_lock = threading.Lock()
                    status = "idle"
                    mission_context = {
                        "taskType": "modeling",
                        "parseElements": ["LOGICAL_ENTITY", "BUSINESS_ATTRIBUTE"],
                        "expectedFiles": ["logical_entities.csv", "business_attributes.csv"],
                        "outputPrefix": "ontology/1/modeling-tasks/RM123456789/agent-output",
                    }

                    def set_mission_context(self, context):
                        self.mission_context = dict(context)

                    def record_uploaded_results(self, prefix, results):
                        server.Task.record_uploaded_results(self, prefix, results)

                    def refresh_modeling_artifacts(self):
                        self.modeling_plan = server.build_modeling_plan(
                            self.mission_context, self.repository_id, self.task_code)

                    def summary(self):
                        return {"id": self.id, "platformStatus": self.platform_status,
                                "uploadedResultCount": len(self.platform_uploaded_files)}

                upload_task = UploadTask()
                server.finalize_semantic_model(
                    Path(upload_tmp) / "work", {},
                    output_dir=output,
                    required_outputs=upload_task.mission_context["expectedFiles"],
                )
                handler = object.__new__(server.Handler)
                responses, callback_statuses = [], []
                deleted_objects = []
                originals = {
                    "bind": server.bind_mission_project,
                    "context": server.fetch_execution_context,
                    "cwd": server.mission_task_cwd,
                    "config": server.minio_config,
                    "put": server.fileserver_put_object,
                    "delete": server.fileserver_delete_object,
                    "callback": server.task_status_callback,
                    "persist": server.persist_tasks,
                }
                try:
                    server.bind_mission_project = lambda *args: "project"
                    server.fetch_execution_context = lambda *args: {
                        **upload_task.mission_context, "_platformStatus": "RUNNING",
                    }
                    server.mission_task_cwd = lambda *args: upload_tmp
                    server.minio_config = lambda: {"bucket": "bucket"}
                    server.fileserver_put_object = lambda cfg, key, blob, name, ctype: {
                        "objectKey": key, "previewUrl": "https://files.example/" + name,
                    }
                    server.fileserver_delete_object = lambda cfg, key: deleted_objects.append(key) or {}
                    server.task_status_callback = lambda task, status, **kwargs: (
                        callback_statuses.append((status, kwargs.get("files"))) or {"ok": True})
                    server.persist_tasks = lambda: None
                    handler.headers = {}
                    handler._owned_task = lambda task_id: upload_task if task_id == upload_task.id else None
                    handler._current_user = lambda: "u1"
                    handler._send_json = lambda payload, status=200: responses.append((status, payload))
                    common = {
                        "project": "project", "prefix": "ontology/1/modeling-tasks/RM123456789/agent-output",
                        "taskCode": "RM123456789", "repositoryId": "1", "taskId": "upload-task", "taskType": "modeling",
                    }
                    handler._read_body = lambda: {**common, "paths": ["output/logical_entities.csv"]}
                    handler._handle_minio_upload()
                    self.assertTrue(responses[-1][1]["callback"]["skipped"])
                    self.assertEqual(callback_statuses, [])
                    handler._read_body = lambda: {**common, "paths": ["output/business_attributes.csv"]}
                    handler._handle_minio_upload()
                    self.assertEqual(callback_statuses, [])
                    self.assertEqual(upload_task.platform_status, "RUNNING")
                    self.assertIn("completionHint", responses[-1][1])
                    handler._read_body = lambda: {"action": "complete"}
                    handler._handle_platform_status(upload_task.id)
                    self.assertEqual([status for status, _ in callback_statuses], ["SUCCESS"])
                    self.assertEqual(upload_task.platform_status, "COMPLETED")
                    self.assertEqual(len(callback_statuses[0][1]), 2)
                    handler._handle_platform_status(upload_task.id)
                    self.assertEqual([status for status, _ in callback_statuses], ["SUCCESS"])
                    handler._read_body = lambda: {"action": "edit"}
                    handler._handle_platform_status(upload_task.id)
                    self.assertEqual([status for status, _ in callback_statuses], ["SUCCESS", "RUNNING"])
                    self.assertEqual(upload_task.platform_status, "RUNNING")
                    self.assertEqual(upload_task.platform_uploaded_files, {})
                    self.assertEqual(set(deleted_objects), {
                        "ontology/1/modeling-tasks/RM123456789/agent-output/logical_entities.csv",
                        "ontology/1/modeling-tasks/RM123456789/agent-output/business_attributes.csv",
                    })
                    upload_task.status = "working"
                    handler._read_body = lambda: {"action": "complete"}
                    handler._handle_platform_status(upload_task.id)
                    self.assertEqual(responses[-1][0], 409)
                    self.assertIn("仍在执行中", responses[-1][1]["error"])
                    self.assertEqual([status for status, _ in callback_statuses], ["SUCCESS", "RUNNING"])
                    upload_task.status = "idle"
                    upload_task.platform_lock.acquire()
                    try:
                        handler._read_body = lambda: {"action": "complete"}
                        handler._handle_platform_status(upload_task.id)
                    finally:
                        upload_task.platform_lock.release()
                    self.assertEqual(responses[-1][0], 409)
                    self.assertIn("正在变更", responses[-1][1]["error"])
                    self.assertEqual([status for status, _ in callback_statuses], ["SUCCESS", "RUNNING"])
                finally:
                    server.bind_mission_project = originals["bind"]
                    server.fetch_execution_context = originals["context"]
                    server.mission_task_cwd = originals["cwd"]
                    server.minio_config = originals["config"]
                    server.fileserver_put_object = originals["put"]
                    server.fileserver_delete_object = originals["delete"]
                    server.task_status_callback = originals["callback"]
                    server.persist_tasks = originals["persist"]
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
                "business_rules.csv", "规则编码,规则名称,规则描述,触发条件,判断或结果,处置动作\nR0000001,规则,描述,提交时,校验通过,允许提交\n".encode("utf-8")
            ), [])
            self.assertTrue(server.validate_integration_csv(
                "business_rules.csv", "规则编码,规则名称,规则描述,触发条件,判断或结果,处置动作\nR1,规则,描述,提交时,校验通过,允许提交\n".encode("utf-8")
            ))
            page_header = "逻辑实体编码,逻辑实体名称,业务属性编码,业务属性名称,业务属性英文名称,业务属性定义,数据类型,数据长度,数据精度,是否物理主键,是否逻辑主键,是否唯一,是否非空,是否页面显示,是否层级编码,是否层级名称\n"
            page_valid = page_header + (
                "LE1,采购订单,BA1,订单编码,orderCode,订单唯一标识,文本,50,,N,Y,Y,Y,N,N,N\n"
                "LE1,采购订单,BA2,订单名称,orderName,订单显示名称,文本,100,,N,N,N,Y,Y,N,N\n"
            )
            self.assertEqual(server.validate_modeling_csv("business_attributes.csv", page_valid.encode("utf-8")), [])
            self.assertEqual(server.validate_integration_csv("business_attributes.csv", page_valid.encode("utf-8")), [])
            logical_header = "业务对象编码,业务对象名称,逻辑实体编码,逻辑实体名称,逻辑实体英文名,逻辑实体定义,是否主逻辑实体,数据类别\n"
            logical_valid = logical_header + "BO1,采购订单,LE1,采购订单,purchaseOrder,采购订单,Y,事务数据\n"
            self.assertEqual(server.validate_modeling_csv("logical_entities.csv", logical_valid.encode("utf-8")), [])
            self.assertTrue(server.validate_modeling_csv(
                "logical_entities.csv",
                logical_valid.replace(",Y,事务数据", ",是,事务数据").encode("utf-8"),
            ))
            logical_two_primary = logical_header + (
                "BO1,采购订单,LE1,采购订单,purchaseOrder,采购订单,Y,事务数据\n"
                "BO1,采购订单,LE2,采购明细,purchaseOrderLine,采购明细,Y,事务数据\n"
            )
            self.assertTrue(server.validate_modeling_csv("logical_entities.csv", logical_two_primary.encode("utf-8")))
            page_invalid = page_valid.replace("订单名称,orderName,订单显示名称,文本,100,,N,N,N,Y,Y,N,N", "订单名称,orderName,订单显示名称,文本,100,,N,N,N,Y,N,N,N")
            self.assertTrue(server.validate_modeling_csv("business_attributes.csv", page_invalid.encode("utf-8")))
            self.assertTrue(server.validate_modeling_csv(
                "business_attributes.csv", (page_header + "LE1,采购订单,BA1\n").encode("utf-8")
            ))
            relation_header = "关系编码,源逻辑实体编码,源逻辑实体名称,目标逻辑实体编码,目标逻辑实体名称,关系分类,关系中文名称,关系英文名称,关系基数,关系描述,源业务属性编码,源关联属性英文名,源关联属性中文名,目标业务属性编码,目标关联属性英文名,目标关联属性中文名\n"
            bad_relation = relation_header + "R1,E1,订单,E2,客户,错误分类,属于,belongs,1:N,描述,BA1,orderCode,订单编码,BA2,customerCode,客户编码\n"
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

            with tempfile.TemporaryDirectory() as history_tmp:
                original_history_dir = server.TASK_HISTORY_DIR
                try:
                    server.TASK_HISTORY_DIR = history_tmp
                    task_id = "history-task"
                    events = [{"type": "user", "text": f"第 {i} 条"}
                              for i in range(10005)]
                    self.assertTrue(server._seed_task_history(task_id, events))
                    self.assertEqual(server._load_task_history(task_id), events)
                    server._append_task_history(task_id, {"type": "done", "status": "idle"})
                    self.assertEqual(len(server._load_task_history(task_id)), 10006)
                    # A second seed must never overwrite the append-only archive.
                    self.assertFalse(server._seed_task_history(task_id, [{"type": "user", "text": "旧"}]))
                finally:
                    server.TASK_HISTORY_DIR = original_history_dir
        finally:
            for name, original in originals.items():
                if original is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = original


if __name__ == "__main__":
    unittest.main()
