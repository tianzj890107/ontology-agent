import sys
import csv
import tempfile
import unittest

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

from open_claude.modeling_rule_registry import (  # noqa: E402
    RULE_REGISTRY,
    V0001_RULES,
    normalize_logical_entity_main_flags,
    validate_audit_registry,
    validate_formal_rows,
    validate_v0001_state,
)
from open_claude.modeling_reliability import (  # noqa: E402
    validate_fk_coverage,
    validate_formal_attribute_inventory,
    validate_asset_processing_coverage,
    apply_asset_processing_coverage_defaults,
    write_all_attributes_csv,
)


class V0001RuleRegistryTests(unittest.TestCase):
    def test_registry_contains_all_49_rules_once(self):
        self.assertEqual(len(V0001_RULES), 49)
        self.assertEqual(set(RULE_REGISTRY), set(range(1, 50)))
        self.assertEqual(len({rule.number for rule in V0001_RULES}), 49)
        self.assertTrue(all(rule.check for rule in V0001_RULES))

    def test_candidate_does_not_receive_formal_completeness_checks(self):
        header = ["业务对象编码", "业务对象名称", "业务对象英文名", "业务对象定义", "数据类别"]
        rows = [["CO_CANDIDATE", "候选对象", "", "", ""]]
        self.assertEqual(validate_formal_rows("business_object_decisions.csv", header, rows), [])

    def test_formal_business_object_empty_definition_is_structural(self):
        # An empty definition is a deterministic format error: it cannot be
        # shipped inside a PASSED formal CSV.  Only a present-but-weak
        # definition stays a non-blocking quality WARNING.
        header = ["业务对象编码", "业务对象名称", "业务对象英文名", "业务对象定义", "数据类别"]
        rows = [["CO001", "正式对象", "", "", ""]]
        codes = {item.code for item in validate_formal_rows("business_objects.csv", header, rows)}
        self.assertIn("V0001_FORMAL_BUSINESS_OBJECT_DEFINITION_MISSING", codes)
        self.assertEqual(
            [item.severity for item in validate_formal_rows("business_objects.csv", header, rows)],
            ["ERROR"],
        )
        weak = validate_formal_rows("business_objects.csv", header,
                                    [["CO001", "正式对象", "", "正式对象", ""]])
        self.assertIn("V0001_DESCRIPTION_MISSING", {item.code for item in weak})
        self.assertEqual([item.severity for item in weak], ["WARNING"])

    def test_formal_business_object_missing_name_is_structural(self):
        header = ["业务对象编码", "业务对象名称", "业务对象英文名", "业务对象定义", "数据类别"]
        rows = [["CO001", "", "", "业务定义", ""]]
        codes = {item.code for item in validate_formal_rows("business_objects.csv", header, rows)}
        self.assertIn("V0001_FORMAL_BUSINESS_OBJECT_INCOMPLETE", codes)

    def test_formal_relation_rejects_missing_cardinality_and_many_to_many(self):
        header = ["关系编码", "源逻辑实体编码", "目标逻辑实体编码", "关系基数"]
        missing = validate_formal_rows("entity_relations.csv", header, [["REL1", "LE1", "LE2", ""]])
        self.assertIn("V0001_FORMAL_CARDINALITY_MISSING", {item.code for item in missing})
        many = validate_formal_rows("entity_relations.csv", header, [["REL2", "LE1", "LE2", "M:N"]])
        self.assertIn("V0001_FORMAL_MANY_TO_MANY", {item.code for item in many})

    def test_audit_identity_is_checked_without_promoting_candidates(self):
        state = {
            "businessObjectDecisions": [
                {"candidateCode": "CO1", "decision": "CANDIDATE"},
                {"candidateCode": "CO1", "decision": "CANDIDATE"},
            ],
            "relationDecisions": [],
        }
        findings = validate_audit_registry(state)
        self.assertEqual([item.code for item in findings], ["V0001_DUPLICATE_BUSINESS_OBJECT_CODE"])
        self.assertTrue(all(item.severity == "ERROR" for item in findings))

    def test_all_attributes_keeps_technical_pk_and_fk_evidence(self):
        state = {
            "allAttributes": [
                {"attributeCode": "AT_ID", "attributeName": "id", "sourceTable": "child",
                 "sourceColumn": "id", "isPhysicalKey": "Y", "isTechnical": "Y"},
                {"attributeCode": "AT_PARENT", "attributeName": "parent_id", "sourceTable": "child",
                 "sourceColumn": "parent_id", "isForeignKey": "Y", "isTechnical": "Y"},
                {"attributeCode": "AT_NAME", "attributeName": "名称", "sourceTable": "child",
                 "sourceColumn": "name", "isTechnical": "N"},
            ],
            "declaredForeignKeys": [{"relationDecisionId": "REL_CHILD_PARENT",
                                     "sourceEntity": "child", "targetEntity": "parent"}],
            "relationDecisions": [{"relationId": "REL_CHILD_PARENT", "sourceEntity": "child",
                                    "targetEntity": "parent", "relationType": "REFERENCE",
                                    "status": "CANDIDATE", "evidenceTypes": ["FOREIGN_KEY"]}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = write_all_attributes_csv(directory, state)
            with open(path, encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual({row["来源字段"] for row in rows}, {"id", "parent_id", "name"})
            by_field = {row["来源字段"]: row for row in rows}
            self.assertEqual(by_field["id"]["是否物理主键"], "Y")
            self.assertEqual(by_field["parent_id"]["是否外键"], "Y")
        self.assertEqual(validate_fk_coverage(state), [])

    def test_technical_attribute_is_not_allowed_in_formal_business_attributes(self):
        state = {"allAttributes": [{"attributeCode": "AT_ID", "attributeName": "id",
                                    "isTechnical": "Y"}]}
        header = ["逻辑实体编码", "业务属性编码", "业务属性名称"]
        blob = ("逻辑实体编码,业务属性编码,业务属性名称\nLE1,AT_ID,id\n").encode("utf-8")
        findings = validate_formal_attribute_inventory(blob, state)
        self.assertIn("TECHNICAL_ATTRIBUTE_IN_FORMAL_OUTPUT", {item.code for item in findings})

    def test_all_attributes_uses_canonical_collection_once(self):
        state = {
            "allAttributes": [
                {"logicalEntityCode": "LE1", "attributeCode": "AT1",
                 "sourceTable": "t", "sourceColumn": "id"},
                {"logicalEntityCode": "LE1", "attributeCode": "AT1",
                 "sourceTable": "t", "sourceColumn": "id"},
            ],
            # This is a filtered decision collection and must never be merged
            # into the physical inventory.
            "candidateAttributes": [
                {"logicalEntityCode": "LE1", "attributeCode": "AT1",
                 "sourceTable": "t", "sourceColumn": "id"},
                {"logicalEntityCode": "LE1", "attributeCode": "AT2",
                 "sourceTable": "t", "sourceColumn": "name"},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = write_all_attributes_csv(directory, state)
            with open(path, encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["属性编码"], "AT1")

    def test_existing_agent_inventory_is_not_overwritten_by_empty_checkpoint(self):
        state = {"allAttributes": [], "candidateAttributes": [
            {"attributeCode": "CANDIDATE", "sourceTable": "t", "sourceColumn": "candidate"}
        ]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "all_attributes.csv"
            path.write_text(
                "逻辑实体编码,逻辑实体名称,属性编码,属性名称,来源表,来源字段\n"
                "LE1,实体,AT1,名称,t,name\n", encoding="utf-8-sig")
            write_all_attributes_csv(directory, state)
            self.assertIn("AT1", path.read_text(encoding="utf-8-sig"))
            self.assertNotIn("CANDIDATE", path.read_text(encoding="utf-8-sig"))

    def test_formal_attributes_are_checked_against_persisted_inventory(self):
        state = {"allAttributes": []}
        blob = ("逻辑实体编码,业务属性编码,业务属性名称\nLE1,AT1,名称\n").encode()
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "all_attributes.csv").write_text(
                "逻辑实体编码,属性编码,属性名称,来源表,来源字段\n"
                "LE1,AT1,名称,t,name\n", encoding="utf-8-sig")
            findings = validate_formal_attribute_inventory(blob, state, directory)
        self.assertNotIn("FORMAL_ATTRIBUTE_NOT_IN_ALL_ATTRIBUTES",
                         {item.code for item in findings})

    def test_chinese_header_keys_are_projected_with_complete_attribute_codes(self):
        state = {"allAttributes": [
            {"逻辑实体编码": "LE1", "逻辑实体名称": "实体一", "属性编码": "AT1",
             "属性名称": "名称", "属性英文名称": "Name", "属性定义": "定义",
             "来源表": "t_order", "来源字段": "order_id", "数据类型": "VARCHAR",
             "数据长度": "32", "是否物理主键": "Y", "是否外键": "N",
             "是否技术字段": "N", "属性状态": "CONFIRMED", "证据": "来自建表语句"},
            {"逻辑实体编码": "LE1", "属性编码": "AT2", "属性名称": "状态",
             "来源表": "t_order", "来源字段": "status", "属性状态": "CANDIDATE"},
        ]}
        with tempfile.TemporaryDirectory() as directory:
            path = write_all_attributes_csv(directory, state)
            with open(path, encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 2)
        by_code = {row["属性编码"]: row for row in rows}
        self.assertEqual(by_code["AT1"]["属性名称"], "名称")
        self.assertEqual(by_code["AT1"]["属性英文名称"], "Name")
        self.assertEqual(by_code["AT1"]["属性定义"], "定义")
        self.assertEqual(by_code["AT1"]["属性状态"], "CONFIRMED")
        self.assertEqual(by_code["AT1"]["证据"], "来自建表语句")
        self.assertEqual(by_code["AT2"]["属性状态"], "CANDIDATE")

    def test_partial_state_does_not_overwrite_or_duplicate_agent_inventory(self):
        # The durable Agent-produced inventory is the union base: a partial
        # checkpoint (only one of three tables) must not shrink the file, and
        # overlapping rows must not be written twice.
        existing = (
            "逻辑实体编码,逻辑实体名称,属性编码,属性名称,来源表,来源字段\n"
            "LE1,实体,AT1,名称,t_a,id\n"
            "LE1,实体,AT2,名称,t_b,id\n"
            "LE1,实体,AT3,名称,t_c,id\n"
        )
        state = {"allAttributes": [
            {"logicalEntityCode": "LE1", "attributeCode": "AT1",
             "sourceTable": "t_a", "sourceColumn": "id"},
            {"logicalEntityCode": "LE1", "attributeCode": "AT4",
             "sourceTable": "t_d", "sourceColumn": "id"},
        ]}
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "all_attributes.csv").write_text(existing, encoding="utf-8-sig")
            path = write_all_attributes_csv(directory, state)
            with open(path, encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 4)
        self.assertEqual({row["来源表"] for row in rows},
                         {"t_a", "t_b", "t_c", "t_d"})
        self.assertEqual(len({row["来源表"] for row in rows}), 4)

    def test_merge_updates_same_identity_with_complete_code(self):
        existing = (
            "逻辑实体编码,逻辑实体名称,属性编码,属性名称,来源表,来源字段\n"
            "LE1,实体,,,t_a,id\n"
        )
        state = {"allAttributes": [
            {"logicalEntityCode": "LE1", "attributeCode": "AT1",
             "attributeName": "完整名称", "sourceTable": "t_a", "sourceColumn": "id"},
        ]}
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "all_attributes.csv").write_text(existing, encoding="utf-8-sig")
            path = write_all_attributes_csv(directory, state)
            with open(path, encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["属性编码"], "AT1")
        self.assertEqual(rows[0]["属性名称"], "完整名称")

    def test_formal_attributes_all_found_in_merged_inventory(self):
        state = {"allAttributes": [
            {"logicalEntityCode": "LE1", "attributeCode": "AT2",
             "sourceTable": "t_b", "sourceColumn": "id"},
        ]}
        blob = ("逻辑实体编码,业务属性编码,业务属性名称\n"
                "LE1,AT1,名称一\n"
                "LE1,AT2,名称二\n").encode("utf-8")
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "all_attributes.csv").write_text(
                "逻辑实体编码,属性编码,属性名称,来源表,来源字段\n"
                "LE1,AT1,名称一,t_a,id\n", encoding="utf-8-sig")
            write_all_attributes_csv(directory, state)
            findings = validate_formal_attribute_inventory(blob, state, directory)
        self.assertNotIn("FORMAL_ATTRIBUTE_NOT_IN_ALL_ATTRIBUTES",
                         {item.code for item in findings})

    def test_physical_id_is_not_promoted_to_logical_key_without_evidence(self):
        state = {"allAttributes": [{
            "logicalEntityCode": "LE1", "attributeCode": "AT_ID",
            "attributeName": "id", "isTechnical": "Y",
            "isPhysicalKey": "Y", "isLogicalKey": "Y",
        }]}
        blob = ("逻辑实体编码,业务属性编码,业务属性名称\n"
                "LE1,AT_ID,id\n").encode("utf-8")
        codes = {item.code for item in validate_formal_attribute_inventory(blob, state)}
        self.assertIn("PHYSICAL_KEY_NOT_PROVEN_LOGICAL_KEY", codes)
        findings = validate_formal_attribute_inventory(blob, state)
        key_issue = next(item for item in findings
                         if item.code == "PHYSICAL_KEY_NOT_PROVEN_LOGICAL_KEY")
        self.assertEqual(key_issue.severity, "WARNING")

    def test_missing_declarative_constraints_do_not_block(self):
        # Absence of PK/FK/UNIQUE declarations is evidence insufficiency, not
        # an invalid model.  A relation may still be classified from other
        # evidence, and an explicit FK that is not classified remains an error.
        self.assertEqual(validate_fk_coverage({}), [])
        state = {"tables": ["orders", "order_lines"],
                 "assetDecisions": [
                     {"tableName": "orders", "decision": "MODELED"},
                     {"tableName": "order_lines", "decision": "UNKNOWN"},
                 ]}
        self.assertEqual(validate_asset_processing_coverage(state), [])

    def test_asset_coverage_requires_processing_decision_not_formal_inclusion(self):
        state = {
            "tables": ["orders", "audit_log", "reference_codes"],
            "assetDecisions": [
                {"tableName": "orders", "decision": "MODELED"},
                {"tableName": "audit_log", "decision": "TECHNICAL"},
            ],
        }
        issues = validate_asset_processing_coverage(state)
        self.assertEqual([item.code for item in issues], ["ASSET_PROCESSING_COVERAGE_MISSING"])
        self.assertEqual(issues[0].severity, "WARNING")
        self.assertEqual(issues[0].details["missing"], ["reference_codes"])

    def test_asset_coverage_defaults_mark_unknown_and_are_idempotent(self):
        state = {
            "tables": ["orders", "reference_codes"],
            "assetDecisions": [{"tableName": "orders", "decision": "MODELED"}],
        }
        self.assertEqual(apply_asset_processing_coverage_defaults(state), ["reference_codes"])
        self.assertEqual(apply_asset_processing_coverage_defaults(state), [])
        decisions = {row["tableName"]: row for row in state["assetDecisions"]}
        self.assertEqual(decisions["reference_codes"]["processingDecision"], "UNKNOWN")
        self.assertIn("reference_codes", state["autoResolvedProcessingDecisions"])
        issues = validate_asset_processing_coverage(state)
        self.assertEqual([item.code for item in issues], ["ASSET_PROCESSING_COVERAGE_MISSING"])
        self.assertEqual(issues[0].severity, "WARNING")
        self.assertEqual(issues[0].details["missing"], ["reference_codes"])
        self.assertTrue(issues[0].details["autoResolved"])

    def test_asset_coverage_warning_does_not_block_final_gate(self):
        from open_claude.modeling_reliability import validate_modeling_stages
        state = {
            "tables": ["orders", "reference_codes"],
            "assetDecisions": [{"tableName": "orders", "decision": "MODELED"}],
        }
        with tempfile.TemporaryDirectory() as root:
            work = Path(root) / "mission-work"
            work.mkdir()
            output = Path(root) / "mission-output"
            output.mkdir()
            (output / "logical_entities.csv").write_text(
                "业务对象编码,逻辑实体编码,逻辑实体名称,逻辑实体定义,是否主逻辑实体\n"
                "CO1,LE1,逻辑实体1,定义,Y\n", encoding="utf-8")
            result = validate_modeling_stages(work, output,
                                              state, ["logical_entities.csv"])
            self.assertEqual(result["stages"][1]["status"], "PASSED")
            self.assertFalse(any(issue.severity == "ERROR" for issue in result["issues"]))

    def test_registry_matrix_covers_each_phase_and_output(self):
        from open_claude.modeling_rule_registry import registry_matrix

        matrix = registry_matrix()
        self.assertEqual({item["rule"] for item in matrix}, set(range(1, 50)))
        self.assertEqual({item["phase"] for item in matrix}, {"P0", "P1", "P2"})
        self.assertTrue({item["output"] for item in matrix} >= {
            "business_objects.csv", "logical_entities.csv",
            "business_attributes.csv", "entity_relations.csv",
        })

    def test_explicit_statuses_use_one_registry_dispatch(self):
        from open_claude.modeling_rule_registry import validate_v0001_state

        findings = validate_v0001_state({"ruleStatuses": {"1": "FAIL", "49": "FAIL"}})
        by_code = {item.code: item for item in findings}
        self.assertEqual(by_code["V0001_RULE_1_FAIL"].severity, "WARNING")
        self.assertEqual(by_code["V0001_RULE_49_FAIL"].severity, "ERROR")

    def test_main_flag_requires_a_business_object(self):
        header = ["业务对象编码", "逻辑实体编码", "逻辑实体名称", "是否主逻辑实体"]
        findings = validate_formal_rows(
            "logical_entities.csv", header,
            [[None, "LE1", "未归属实体", "Y"]],
        )
        self.assertIn("V0001_MAIN_FLAG_WITHOUT_BUSINESS_OBJECT",
                      {item.code for item in findings})

    def test_candidate_or_rejected_object_normalizes_main_flag_to_n(self):
        state = {"businessObjectDecisions": [
            {"candidateCode": "BO_REJECTED", "decision": "REJECTED"},
            {"candidateCode": "BO_CANDIDATE", "decision": "CANDIDATE"},
        ]}
        rows = [
            {"logicalEntityCode": "LE_REJECTED", "businessObjectCode": "BO_REJECTED",
             "mainFlag": "Y", "attributeName": "保留名称"},
            {"logicalEntityCode": "LE_CANDIDATE", "businessObjectCode": "BO_CANDIDATE",
             "mainFlag": "Y", "attributeName": "保留名称"},
        ]
        normalized = normalize_logical_entity_main_flags(rows, state)
        self.assertEqual([row["mainFlag"] for row in normalized], ["N", "N"])
        self.assertEqual([row["attributeName"] for row in normalized], ["保留名称", "保留名称"])
        header = ["业务对象编码", "逻辑实体编码", "逻辑实体名称", "是否主逻辑实体"]
        findings = validate_formal_rows(
            "logical_entities.csv", header,
            [["BO_REJECTED", "LE_REJECTED", "保留实体", "Y"]], state,
        )
        self.assertIn("V0001_MAIN_FLAG_WITHOUT_CONFIRMED_BUSINESS_OBJECT",
                      {item.code for item in findings})
        state_findings = validate_v0001_state({
            **state,
            "logicalEntityDecisions": [{
                "logicalEntityCode": "LE_REJECTED",
                "businessObjectCode": "BO_REJECTED",
                "mainFlag": "Y",
            }],
        })
        self.assertIn("V0001_MAIN_FLAG_WITHOUT_CONFIRMED_BUSINESS_OBJECT",
                      {item.code for item in state_findings})

    def test_state_validator_rejects_unassigned_main_flag(self):
        findings = validate_v0001_state({
            "logicalEntityDecisions": [{
                "logicalEntityCode": "LE_UNASSIGNED",
                "businessObjectCode": None,
                "mainFlag": "Y",
            }],
        })
        self.assertIn("V0001_MAIN_FLAG_WITHOUT_BUSINESS_OBJECT",
                      {item.code for item in findings})

    def test_duplicate_attribute_name_is_scoped_to_one_entity(self):
        header = ["逻辑实体编码", "业务属性编码", "业务属性名称", "业务属性定义"]
        findings = validate_formal_rows(
            "business_attributes.csv", header,
            [["LE1", "AT1", "金额", "订单金额"],
             ["LE1", "AT2", "金额", "订单金额"]],
        )
        self.assertEqual(
            [item.severity for item in findings if item.code == "V0001_DUPLICATE_FORMAL_NAME"],
            ["ERROR"],
        )

    def test_same_attribute_name_across_entities_is_allowed(self):
        header = ["逻辑实体编码", "业务属性编码", "业务属性名称", "业务属性定义"]
        findings = validate_formal_rows(
            "business_attributes.csv", header,
            [["LE1", "AT1", "金额", "金额"],
             ["LE2", "AT2", "金额", "金额"]],
        )
        self.assertFalse(any(item.code == "V0001_DUPLICATE_FORMAL_NAME" for item in findings))

    def test_cross_entity_same_name_with_different_semantics_is_warning(self):
        header = ["逻辑实体编码", "业务属性编码", "业务属性名称", "业务属性定义"]
        findings = validate_formal_rows(
            "business_attributes.csv", header,
            [["LE1", "AT1", "状态", "采购订单审批状态"],
             ["LE2", "AT2", "状态", "供应商冻结状态"]],
        )
        duplicate = [item for item in findings if item.code == "V0001_DUPLICATE_FORMAL_NAME"]
        self.assertEqual(len(duplicate), 1)
        self.assertEqual(duplicate[0].severity, "WARNING")

    def test_business_object_and_entity_name_duplicates_use_distinct_codes(self):
        # Rule 13 (business object name) and rule 22 (logical entity name) are
        # global-name rules.  They must never reuse the attribute-name rule
        # code V0001_DUPLICATE_FORMAL_NAME, which is scoped to logical-entity
        # attribute names only.
        header = ["业务对象编码", "业务对象名称", "业务对象定义"]
        findings = validate_formal_rows(
            "business_objects.csv", header,
            [["CO1", "客户", "定义A"],
             ["CO2", "客户", "定义B"]],
        )
        codes = {item.code for item in findings}
        self.assertIn("V0001_DUPLICATE_BUSINESS_OBJECT_NAME", codes)
        self.assertNotIn("V0001_DUPLICATE_FORMAL_NAME", codes)

        entity_header = ["业务对象编码", "逻辑实体编码", "逻辑实体名称", "逻辑实体定义"]
        findings = validate_formal_rows(
            "logical_entities.csv", entity_header,
            [["CO1", "LE1", "订单", "定义A"],
             ["CO1", "LE2", "订单", "定义B"]],
        )
        codes = {item.code for item in findings}
        self.assertIn("V0001_DUPLICATE_LOGICAL_ENTITY_NAME", codes)
        self.assertNotIn("V0001_DUPLICATE_FORMAL_NAME", codes)

    def test_state_duplicate_names_keep_distinct_codes_and_attribute_rule_is_entity_scoped(self):
        state = {
            "businessObjectDecisions": [
                {"candidateCode": "CO1", "candidateName": "客户", "decision": "CONFIRMED"},
                {"candidateCode": "CO2", "candidateName": "客户", "decision": "CONFIRMED"},
            ],
            "businessAttributes": [
                {"logicalEntityCode": "LE1", "attributeCode": "AT1",
                 "attributeName": "金额", "attributeDefinition": "订单金额"},
                {"logicalEntityCode": "LE2", "attributeCode": "AT2",
                 "attributeName": "金额", "attributeDefinition": "订单金额"},
            ],
        }
        findings = validate_v0001_state(state)
        codes = {item.code for item in findings}
        self.assertIn("V0001_DUPLICATE_BUSINESS_OBJECT_NAME", codes)
        # Cross-entity same-name attributes are allowed and must not produce
        # any V0001_DUPLICATE_FORMAL_NAME finding.
        self.assertNotIn("V0001_DUPLICATE_FORMAL_NAME", codes)

    def test_name_normalization_never_adds_entity_prefix(self):
        rows = [{"logicalEntityCode": "LE1", "attributeName": "金额", "mainFlag": "N"}]
        normalized = normalize_logical_entity_main_flags(rows, {})
        self.assertEqual(normalized[0]["attributeName"], "金额")


if __name__ == "__main__":
    unittest.main()
