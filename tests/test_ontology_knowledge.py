import unittest
import importlib.util
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

from open_claude.ontology_knowledge import knowledge_filename, load_static_knowledge, normalize_task_type


class StaticKnowledgeContractTests(unittest.TestCase):
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
        self.assertIn("本体元模型.xlsx", modeling)
        self.assertIn("本体元模型模板.xlsx", modeling)
        self.assertIn("本体建模步骤拆解.xlsx", modeling)
        self.assertIn("本体元模型.xlsx", (ROOT / "agent_knowledge" / "modeling" / "本体元模型.md").read_text(encoding="utf-8"))
        self.assertIn("本体元模型模板.xlsx", (ROOT / "agent_knowledge" / "modeling" / "本体元模型模板.md").read_text(encoding="utf-8"))
        data_model_rules = (ROOT / "agent_knowledge" / "modeling" / "数据模型建模规范-20260626.md").read_text(encoding="utf-8")
        self.assertIn("数据模型建模规范-20260626.xlsx", data_model_rules)
        self.assertIn("主逻辑实体唯一", data_model_rules)
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
        self.assertIn("智能建模任务.docx", composed)
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
        for name, module in zip(names, (repl, profile, api, config)):
            sys.modules[name] = module
        try:
            spec = importlib.util.spec_from_file_location(
                "oc_contract_server_test", ROOT / "open-claude" / "oc_codex_server.py")
            server = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(server)
            handler = object.__new__(server.Handler)
            self.assertEqual(handler._mission_from("1", "RM123456789", "modeling")["taskCode"],
                             "RM123456789")
            self.assertIsNone(handler._mission_from("1", "</script><script>alert(1)</script>", "modeling"))
            self.assertEqual(
                server.bind_mission_project("mission-1-RM123456789", "1", "RM123456789"),
                "mission-1-RM123456789",
            )
            self.assertIsNone(
                server.bind_mission_project("another-project", "1", "RM123456789")
            )
            self.assertEqual(
                server.normalize_expected_files([
                    {"filename": "logical_entities.csv"},
                    {"path": "x/entity_relations.csv"},
                ]),
                {"logical_entities.csv", "entity_relations.csv"},
            )
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
                mission_context = {"taskType": "modeling"}
                conv = types.SimpleNamespace(session=Session())

                def summary(self):
                    return {"id": "task-1", "project": "p", "status": "idle"}

            with tempfile.TemporaryDirectory() as tmp:
                server.TASKS = {"task-1": Task()}
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
