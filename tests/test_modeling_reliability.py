import sys
import csv
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

from open_claude.modeling_reliability import (  # noqa: E402
    CANDIDATE,
    COMPOSITION,
    CONFIRMED,
    EXTENSION,
    UNRESOLVED,
    BUSINESS_OBJECT_DECISION_HEADERS,
    BusinessRuleType,
    RuleEnforcement,
    aggregation_components,
    analyze_aggregation,
    business_object_decision_records,
    derive_business_object_decision,
    infer_business_object_rule_status,
    validate_business_object_decisions,
    business_rule_validation_issues,
    validate_business_rule,
    validate_formal_business_object_csv,
    write_business_object_decisions_csv,
    semantic_validation_issues,
    validate_formal_relation_csv,
)


RELATION_CSV = "关系编码,源逻辑实体编码,目标逻辑实体编码,关系分类\n"


def relation_csv(code: str) -> bytes:
    return (RELATION_CSV + f"{code},LE_AR,LE_CASH,TRANSFORMATION\n").encode("utf-8")


def entity(entity_id: str, role: str, **extra):
    return {"entityId": entity_id, "role": role, **extra}


def composition(relation_id: str, source: str, target: str,
                status: str = CONFIRMED, evidence_types=None, **extra):
    return {
        "relationId": relation_id,
        "sourceEntity": source,
        "targetEntity": target,
        "relationType": COMPOSITION,
        "status": status,
        "evidenceTypes": evidence_types or ["EXPLICIT_CONFIG"],
        "evidenceLevel": "STRONG",
        "provenance": ["mission-input/ownership.yaml"],
        **extra,
    }


def extension(relation_id: str, source: str, target: str):
    return {
        "relationId": relation_id,
        "sourceEntity": source,
        "targetEntity": target,
        "relationType": EXTENSION,
        "status": CONFIRMED,
        "evidenceTypes": ["EXPLICIT_CONFIG"],
        "evidenceLevel": "STRONG",
        "provenance": ["mission-input/ownership.yaml"],
    }


class ModelingEvidenceGateTests(unittest.TestCase):
    def test_cashflow_without_lineage_stays_unresolved_and_never_enters_formal_csv(self):
        state = {
            "entities": [{"entityId": "LE_CASH", "role": "DERIVED_ANALYTICAL_ENTITY"}],
            "relationDecisions": [
                {
                    "relationId": "REL_AR_CASH",
                    "sourceEntity": "LE_AR",
                    "targetEntity": "LE_CASH",
                    "relationType": "TRANSFORMATION",
                    "status": CANDIDATE,
                    "confidence": "MODERATE",
                    "evidenceTypes": ["LLM_SEMANTIC_INFERENCE"],
                    "needsConfirmation": True,
                },
                {
                    "relationId": "REL_AP_CASH",
                    "sourceEntity": "LE_AP",
                    "targetEntity": "LE_CASH",
                    "relationType": "TRANSFORMATION",
                    "status": UNRESOLVED,
                    "evidenceTypes": [],
                    "needsConfirmation": True,
                },
            ],
        }
        issues = semantic_validation_issues(state)
        self.assertTrue(any(issue.code == "MISSING_DERIVATION_LINEAGE"
                            and issue.severity == "WARNING" for issue in issues))
        issues = validate_formal_relation_csv(relation_csv("REL_AR_CASH"), state)
        self.assertEqual([issue.code for issue in issues], ["UNSUPPORTED_CONFIRMED_RELATION"])
        self.assertEqual(issues[0].as_dict()["fixClass"], "SEMANTIC_FIX")
        self.assertEqual(state["relationDecisions"][0]["status"], CANDIDATE)

    def test_strong_lineage_can_confirm_transformation(self):
        state = {"relationDecisions": [{
            "relationId": "REL000001",
            "sourceEntity": "LE_SOURCE",
            "targetEntity": "LE_TARGET",
            "relationType": "TRANSFORMATION",
            "status": CONFIRMED,
            "evidence": [{"type": "VIEW_SQL_LINEAGE", "source": "mission-input/view.sql"}],
            "evidenceLevel": "STRONG",
            "provenance": ["mission-input/view.sql"],
        }]}
        self.assertEqual(validate_formal_relation_csv(relation_csv("REL000001"), state), [])

    def test_name_similarity_and_confidence_do_not_confirm_relation(self):
        state = {"relationDecisions": [{
            "relationId": "REL000002",
            "status": CONFIRMED,
            "confidence": "HIGH",
            "evidenceTypes": ["TABLE_NAME"],
        }]}
        issues = validate_formal_relation_csv(relation_csv("REL000002"), state)
        self.assertEqual(issues[0].code, "UNSUPPORTED_CONFIRMED_RELATION")
        self.assertFalse(issues[0].auto_fixable)

    def test_two_independent_moderate_sources_can_cross_gate(self):
        state = {"relationDecisions": [{
            "relationId": "REL000003",
            "status": CONFIRMED,
            "evidenceTypes": ["JOINABILITY", "DOCUMENTATION"],
            "evidenceLevel": "MODERATE",
            "provenance": ["mission-input/sample.csv", "mission-input/design.md"],
        }]}
        self.assertEqual(validate_formal_relation_csv(relation_csv("REL000003"), state), [])

    def test_traceable_strong_fk_does_not_require_redundant_strong_label(self):
        state = {"relationDecisions": [{
            "relationId": "REL000003A",
            "sourceEntity": "LE_LINE",
            "targetEntity": "LE_ORDER",
            "relationType": "REFERENCE",
            "status": CONFIRMED,
            "evidenceTypes": ["FOREIGN_KEY"],
            "evidenceLevel": "MODERATE",
            "evidence": [{"type": "FOREIGN_KEY", "evidenceId": "FK_1",
                          "source": "mission-input/schema.sql"}],
        }]}
        self.assertEqual(validate_formal_relation_csv(relation_csv("REL000003A"), state), [])

    def test_structured_evidence_records_supply_provenance(self):
        state = {"relationDecisions": [{
            "relationId": "REL000003B",
            "sourceEntity": "LE_LINE",
            "targetEntity": "LE_ORDER",
            "relationType": "REFERENCE",
            "status": CONFIRMED,
            "evidence": [{"type": "FOREIGN_KEY", "evidenceId": "FK_2",
                          "path": "mission-input/schema.sql"}],
        }]}
        self.assertEqual(validate_formal_relation_csv(relation_csv("REL000003B"), state), [])

    def test_new_independent_evidence_allows_unknown_to_confirmed(self):
        state = {"relationDecisions": [{
            "relationId": "REL000004",
            "status": UNRESOLVED,
            "evidenceTypes": [],
        }]}
        self.assertTrue(validate_formal_relation_csv(relation_csv("REL000004"), state))
        state["relationDecisions"][0].update({
            "status": CONFIRMED,
            "evidenceTypes": ["FOREIGN_KEY"],
            "evidenceLevel": "STRONG",
            "provenance": ["mission-input/schema.sql"],
        })
        self.assertEqual(validate_formal_relation_csv(relation_csv("REL000004"), state), [])

    def test_retry_does_not_raise_confidence_without_state_change(self):
        state = {"relationDecisions": [{
            "relationId": "REL000005",
            "status": CANDIDATE,
            "confidence": "MODERATE",
            "evidenceTypes": ["BUSINESS_COMMON_SENSE"],
        }]}
        first = validate_formal_relation_csv(relation_csv("REL000005"), state)
        second = validate_formal_relation_csv(relation_csv("REL000005"), state)
        self.assertEqual([issue.code for issue in first], [issue.code for issue in second])
        self.assertEqual(state["relationDecisions"][0]["status"], CANDIDATE)

    def test_composition_and_main_entity_gaps_are_warnings_not_repairs(self):
        state = {
            "entities": [{"entityId": "LE_CHILD", "role": "DEPENDENT_ENTITY"}],
            "businessObjects": [{
                "businessObjectId": "BO_ORDER",
                "candidateMainEntities": ["LE_ORDER", "LE_ORDER_HEADER"],
            }],
            "relationDecisions": [],
        }
        issues = semantic_validation_issues(state)
        codes = {issue.code for issue in issues}
        self.assertIn("MISSING_COMPOSITION_OWNER", codes)
        self.assertIn("MAIN_LOGICAL_ENTITY_NEEDS_CONFIRMATION", codes)
        self.assertFalse(any(issue.auto_fixable for issue in issues))

    def test_insufficient_business_object_evidence_is_warning_not_blocking(self):
        state = {"businessObjectDecisions": [{
            "candidateCode": "CO_EVIDENCE_GAP",
            "candidateName": "证据不足对象",
            "confidence": "90",
            "r1": {"status": "PASS", "evidence": [{"type": "TABLE_NAME"}]},
            "r2": {"status": "PASS", "evidence": [{"type": "COLUMN_NAME"}]},
            "r3": {"status": "UNKNOWN", "evidence": "", "unknownReason": "待确认"},
            "r4": {"status": "PASS", "evidence": [{"type": "FIELD_SEMANTICS"}]},
            "r5": {"status": "PASS", "evidence": [{"type": "ROW_COUNT"}]},
        }]}
        issues = semantic_validation_issues(state)
        insufficient = [item for item in issues if item.code.startswith("INSUFFICIENT_")]
        self.assertTrue(insufficient)
        self.assertTrue(all(item.severity == "WARNING" for item in insufficient))

    def test_confirmed_relation_without_support_remains_error(self):
        state = {"relationDecisions": [{
            "relationId": "REL_UNSUPPORTED",
            "sourceEntity": "LE_A", "targetEntity": "LE_B",
            "relationType": "REFERENCE", "status": CONFIRMED,
            "evidenceTypes": [],
        }]}
        issues = semantic_validation_issues(state)
        issue = next(item for item in issues if item.code == "UNSUPPORTED_CONFIRMED_RELATION")
        self.assertEqual(issue.severity, "ERROR")


class CompositionAggregationTests(unittest.TestCase):
    def test_reversed_composition_direction_does_not_pass_by_endpoint_membership(self):
        state = {
            "entities": [entity("LE_ORDER", "MAIN"), entity("LE_LINE", "DEPENDENT")],
            "relationDecisions": [composition("REL_REVERSED", "LE_ORDER", "LE_LINE")],
        }
        codes = {issue.code for issue in semantic_validation_issues(state)}
        self.assertIn("INVALID_COMPOSITION_DIRECTION", codes)
        self.assertFalse(any(set(component.entity_ids) == {"LE_ORDER", "LE_LINE"}
                             for component in aggregation_components(state)))

    def test_canonical_composition_direction_is_accepted(self):
        state = {
            "entities": [entity("LE_ORDER", "MAIN"), entity("LE_LINE", "DEPENDENT")],
            "relationDecisions": [composition("REL_CORRECT", "LE_LINE", "LE_ORDER")],
        }
        components = aggregation_components(state)
        self.assertEqual(len(components), 1)
        self.assertEqual(set(components[0].entity_ids), {"LE_ORDER", "LE_LINE"})
        self.assertEqual(components[0].main_entity_ids, ("LE_ORDER",))

    def test_owner_role_is_checked(self):
        state = {
            "entities": [entity("LE_LINE", "DEPENDENT"), entity("LE_PERIOD", "DERIVED_ANALYTICAL_ENTITY")],
            "relationDecisions": [composition("REL_BAD_OWNER", "LE_LINE", "LE_PERIOD")],
        }
        codes = {issue.code for issue in semantic_validation_issues(state)}
        self.assertIn("INVALID_COMPOSITION_TARGET_ROLE", codes)
        self.assertEqual(aggregation_components(state), [])

    def test_multiple_composition_owners_and_mains_are_conflicts(self):
        state = {
            "entities": [entity("LE_A", "MAIN"), entity("LE_B", "MAIN"), entity("LE_D", "DEPENDENT")],
            "relationDecisions": [
                composition("REL_D_A", "LE_D", "LE_A"),
                composition("REL_D_B", "LE_D", "LE_B"),
            ],
        }
        analysis = analyze_aggregation(state)
        codes = {issue.code for issue in analysis.issues}
        self.assertIn("MULTIPLE_COMPOSITION_OWNERS", codes)
        self.assertIn("MULTIPLE_MAIN_ENTITIES", codes)
        self.assertEqual(aggregation_components(state), [])
        self.assertEqual({"LE_A", "LE_B", "LE_D"}, set(analysis.components[0].entity_ids))

    def test_no_main_is_not_repaired(self):
        state = {
            "entities": [entity("LE_D1", "DEPENDENT"), entity("LE_D2", "DEPENDENT")],
            "relationDecisions": [composition("REL_D1_D2", "LE_D1", "LE_D2")],
        }
        codes = {issue.code for issue in semantic_validation_issues(state)}
        self.assertIn("MISSING_MAIN_ENTITY", codes)
        self.assertEqual(aggregation_components(state), [])

    def test_reference_does_not_join_business_object_components(self):
        state = {
            "entities": [
                entity("LE_ORDER", "MAIN"), entity("LE_LINE", "DEPENDENT"),
                entity("LE_CUSTOMER", "MAIN"),
            ],
            "relationDecisions": [
                composition("REL_LINE_ORDER", "LE_LINE", "LE_ORDER"),
                {
                    "relationId": "REL_ORDER_CUSTOMER",
                    "sourceEntity": "LE_ORDER", "targetEntity": "LE_CUSTOMER",
                    "relationType": "REFERENCE", "status": CONFIRMED,
                    "evidenceTypes": ["FOREIGN_KEY"], "evidenceLevel": "STRONG",
                    "provenance": ["mission-input/schema.sql"],
                },
            ],
        }
        components = aggregation_components(state)
        self.assertEqual({frozenset(component.entity_ids) for component in components}, {
            frozenset({"LE_ORDER", "LE_LINE"}), frozenset({"LE_CUSTOMER"}),
        })

    def test_candidate_composition_never_enters_formal_aggregation(self):
        state = {
            "entities": [entity("LE_A", "MAIN"), entity("LE_D", "DEPENDENT")],
            "relationDecisions": [composition(
                "REL_CANDIDATE", "LE_D", "LE_A", status=CANDIDATE)],
            "businessObjects": [{"aggregationRelationIds": ["REL_CANDIDATE"]}],
        }
        analysis = analyze_aggregation(state)
        codes = {issue.code for issue in analysis.issues}
        self.assertIn("UNRESOLVED_COMPOSITION_OWNER", codes)
        self.assertIn("CANDIDATE_EDGE_USED_FOR_FORMAL_AGGREGATION", codes)
        self.assertFalse(any("REL_CANDIDATE" in component.relation_ids
                             for component in aggregation_components(state)))

    def test_self_composition_is_rejected(self):
        state = {
            "entities": [entity("LE_A", "MAIN")],
            "relationDecisions": [composition("REL_SELF", "LE_A", "LE_A")],
        }
        self.assertIn("SELF_COMPOSITION", {issue.code for issue in semantic_validation_issues(state)})
        self.assertFalse(any("REL_SELF" in component.relation_ids
                             for component in aggregation_components(state)))

    def test_two_node_composition_cycle_is_rejected(self):
        state = {
            "entities": [entity("LE_A", "DEPENDENT"), entity("LE_B", "DEPENDENT")],
            "relationDecisions": [
                composition("REL_A_B", "LE_A", "LE_B"),
                composition("REL_B_A", "LE_B", "LE_A"),
            ],
        }
        codes = {issue.code for issue in semantic_validation_issues(state)}
        self.assertIn("COMPOSITION_CYCLE", codes)
        self.assertEqual(aggregation_components(state), [])

    def test_multi_node_composition_cycle_is_rejected(self):
        state = {
            "entities": [entity("LE_A", "DEPENDENT"), entity("LE_B", "DEPENDENT"), entity("LE_C", "MAIN")],
            "relationDecisions": [
                composition("REL_A_B", "LE_A", "LE_B"),
                composition("REL_B_C", "LE_B", "LE_C"),
                composition("REL_C_A", "LE_C", "LE_A"),
            ],
        }
        self.assertIn("COMPOSITION_CYCLE", {issue.code for issue in semantic_validation_issues(state)})
        self.assertEqual(aggregation_components(state), [])

    def test_nested_composition_is_valid_with_one_main(self):
        state = {
            "entities": [entity("LE_ROOT", "MAIN"), entity("LE_MIDDLE", "DEPENDENT"), entity("LE_LEAF", "DEPENDENT")],
            "relationDecisions": [
                composition("REL_MIDDLE_ROOT", "LE_MIDDLE", "LE_ROOT"),
                composition("REL_LEAF_MIDDLE", "LE_LEAF", "LE_MIDDLE"),
            ],
        }
        components = aggregation_components(state)
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0].main_entity_ids, ("LE_ROOT",))

    def test_sibling_dependents_can_share_one_owner(self):
        state = {
            "entities": [entity("LE_ROOT", "MAIN"), entity("LE_D1", "DEPENDENT"), entity("LE_D2", "DEPENDENT")],
            "relationDecisions": [
                composition("REL_D1_ROOT", "LE_D1", "LE_ROOT"),
                composition("REL_D2_ROOT", "LE_D2", "LE_ROOT"),
            ],
        }
        components = aggregation_components(state)
        self.assertEqual(len(components), 1)
        self.assertEqual(set(components[0].entity_ids), {"LE_ROOT", "LE_D1", "LE_D2"})

    def test_disconnected_composition_groups_stay_separate(self):
        state = {
            "entities": [
                entity("LE_A", "MAIN"), entity("LE_D1", "DEPENDENT"),
                entity("LE_B", "MAIN"), entity("LE_D2", "DEPENDENT"),
            ],
            "relationDecisions": [
                composition("REL_D1_A", "LE_D1", "LE_A"),
                composition("REL_D2_B", "LE_D2", "LE_B"),
                {
                    "relationId": "REL_A_B_REF", "sourceEntity": "LE_A",
                    "targetEntity": "LE_B", "relationType": "REFERENCE",
                    "status": CONFIRMED, "evidenceTypes": ["FOREIGN_KEY"],
                    "evidenceLevel": "STRONG", "provenance": ["mission-input/schema.sql"],
                },
            ],
        }
        self.assertEqual({frozenset(item.entity_ids) for item in aggregation_components(state)}, {
            frozenset({"LE_A", "LE_D1"}), frozenset({"LE_B", "LE_D2"}),
        })

    def test_extension_is_aggregation_edge_when_confirmed(self):
        state = {
            "entities": [entity("LE_A", "MAIN"), entity("LE_EXT", "DEPENDENT")],
            "relationDecisions": [extension("REL_EXTENSION", "LE_EXT", "LE_A")],
        }
        components = aggregation_components(state)
        self.assertEqual(len(components), 1)
        self.assertTrue(components[0].valid)

    def test_foreign_key_alone_does_not_prove_composition(self):
        state = {
            "entities": [entity("LE_A", "MAIN"), entity("LE_D", "DEPENDENT")],
            "relationDecisions": [composition(
                "REL_FK_ONLY", "LE_D", "LE_A", evidence_types=["FOREIGN_KEY"])],
        }
        codes = {issue.code for issue in semantic_validation_issues(state)}
        self.assertIn("INVALID_AGGREGATION_EDGE", codes)
        self.assertFalse(any("REL_FK_ONLY" in component.relation_ids
                             for component in aggregation_components(state)))


def business_candidate(code, name, statuses, *, confidence="60",
                       reported=None, member_ids=("LE001",), evidence=None,
                       unknown_reasons=None):
    evidence = evidence or {rule: f"[{rule.upper()}_SOURCE] 可追溯业务证据"
                            for rule in ("r1", "r2", "r3", "r4", "r5")}
    unknown_reasons = unknown_reasons or {}
    record = {
        "candidateCode": code,
        "candidateName": name,
        "businessObjectEnglishName": "",
        "memberEntityIds": list(member_ids),
        "confidence": confidence,
    }
    for rule, status in zip(("r1", "r2", "r3", "r4", "r5"), statuses):
        record[rule] = {"status": status, "evidence": evidence.get(rule, "")}
        if rule in unknown_reasons:
            record[rule]["unknownReason"] = unknown_reasons[rule]
    if reported is not None:
        record["decision"] = reported
    return record


class BusinessObjectDecisionTests(unittest.TestCase):
    def test_positive_evidence_is_not_defaulted_to_unknown(self):
        evidence = {
            "r1": "有明确业务用途与治理责任",
            "r2": "存在稳定业务编号和唯一业务标识",
            "r3": "可独立创建、管理、查询和审批",
            "r4": "存在生命周期和状态字段",
        }
        for rule, text in evidence.items():
            self.assertEqual(infer_business_object_rule_status(rule, text), "PASS")

    def test_explicit_negative_evidence_is_fail(self):
        self.assertEqual(
            infer_business_object_rule_status("r3", "依赖父对象存在，不能独立管理"),
            "FAIL",
        )

    def test_truly_missing_evidence_remains_unknown(self):
        self.assertEqual(infer_business_object_rule_status("r1", ""), "UNKNOWN")

    def test_zero_rows_with_complete_structure_can_pass_r5(self):
        state = {"businessObjectDecisions": [{
            "candidateCode": "CO_ZERO_READY", "candidateName": "结构完整对象",
            "confidence": "80", "r5": {
                "status": "UNKNOWN",
                "evidence": "当前数据 0 行，但存在稳定业务编号、单据结构、独立生命周期和可重复创建语义",
            },
            **{f"r{i}": {"status": "PASS", "evidence": "直接来源证据"}
               for i in range(1, 5)},
        }]}
        record = business_object_decision_records(state)[0]
        self.assertEqual(record.rules[4].status, "PASS")
        self.assertEqual(record.decision, CONFIRMED)

    def test_zero_rows_without_structure_remains_unknown(self):
        state = {"businessObjectDecisions": [{
            "candidateCode": "CO_ZERO_EMPTY", "candidateName": "无样本对象",
            "confidence": "40", "r5": {
                "status": "UNKNOWN", "rowCount": 0,
                "evidence": "当前数据 0 行，缺少实际实例样本",
            },
            **{f"r{i}": {"status": "PASS", "evidence": "直接来源证据"}
               for i in range(1, 5)},
        }]}
        record = business_object_decision_records(state)[0]
        self.assertEqual(record.rules[4].status, "UNKNOWN")
        self.assertEqual(record.decision, CANDIDATE)

    def test_static_finite_value_domain_fails_r5(self):
        self.assertEqual(
            infer_business_object_rule_status("r5", "固定码表，属于静态有限值域"),
            "FAIL",
        )

    def test_deterministic_decision_ignores_confidence(self):
        self.assertEqual(derive_business_object_decision("PASS", "PASS", "PASS", "UNKNOWN", "PASS"), CANDIDATE)
        self.assertEqual(derive_business_object_decision("PASS", "PASS", "PASS", "PASS", "PASS"), CONFIRMED)
        self.assertEqual(derive_business_object_decision("PASS", "FAIL", "PASS", "UNKNOWN", "PASS"), "REJECTED")

    def test_compact_rule_status_and_conclusion_are_normalized(self):
        state = {"businessObjectDecisions": [{
            "code": "CO0001", "name": "已确认对象", "conclusion": "CONFIRMED",
            "confidence": "90", **{f"r{i}": "P" for i in range(1, 6)},
            **{f"r{i}Evidence": f"R{i} 的直接来源" for i in range(1, 6)},
        }]}
        record = business_object_decision_records(state)[0]
        self.assertEqual(record.decision, CONFIRMED)
        self.assertEqual(record.confidence, "90%")
        self.assertEqual(validate_business_object_decisions(state), [])

    def test_qualitative_confidence_is_not_converted_to_a_number(self):
        state = {"businessObjectDecisions": [business_candidate(
            "CO0001", "旧格式对象", ["PASS"] * 5, confidence="HIGH")]}
        record = business_object_decision_records(state)[0]
        self.assertEqual(record.confidence, "HIGH")
        self.assertIn("INVALID_BUSINESS_OBJECT_CONFIDENCE",
                      {issue.code for issue in validate_business_object_decisions(state)})

    def test_all_candidates_are_exported_and_formal_output_only_confirms(self):
        state = {"businessObjectDecisions": [
            business_candidate("CO0002", "候选对象", ["PASS", "PASS", "PASS", "UNKNOWN", "PASS"],
                               confidence="90", unknown_reasons={"r4": "没有独立生命周期证据"}),
            business_candidate("CO0001", "确认对象", ["PASS"] * 5, confidence="60"),
            business_candidate("CO0003", "驳回对象", ["PASS", "PASS", "FAIL", "UNKNOWN", "PASS"],
                               unknown_reasons={"r4": "无额外资料"}),
        ]}
        with tempfile.TemporaryDirectory() as directory:
            path = write_business_object_decisions_csv(directory, state)
            with open(path, encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([row["候选业务对象编码"] for row in rows], ["CO0001", "CO0002", "CO0003"])
            self.assertEqual({row["最终决策"] for row in rows}, {CONFIRMED, CANDIDATE, "REJECTED"})
            self.assertEqual(list(rows[0]), list(BUSINESS_OBJECT_DECISION_HEADERS))
            for removed in ("业务对象英文名称", "候选主逻辑实体编码", "候选主逻辑实体名称",
                            "包含逻辑实体编码", "冲突", "未知项", "建议确认角色", "决策说明"):
                self.assertNotIn(removed, rows[0])
            self.assertRegex(rows[0]["置信度"], r"^\d+(?:\.\d+)?%$")
            formal = ("业务对象编码,业务对象名称,业务对象英文名,业务对象定义,数据类别\n"
                      "CO0001,确认对象,,,\n").encode("utf-8")
            self.assertEqual(validate_formal_business_object_csv(formal, state), [])
            invalid = ("业务对象编码,业务对象名称,业务对象英文名,业务对象定义,数据类别\n"
                       "CO0002,候选对象,,,\n").encode("utf-8")
            self.assertIn("BUSINESS_OBJECT_DECISION_MISMATCH",
                          {issue.code for issue in validate_formal_business_object_csv(invalid, state)})

    def test_unknown_has_reason_question_and_high_confidence_stays_candidate(self):
        state = {"businessObjectDecisions": [business_candidate(
            "CO0001", "生命周期待确认", ["PASS", "PASS", "PASS", "UNKNOWN", "PASS"],
            confidence="90", unknown_reasons={"r4": "未发现状态、版本或生失效证据"})]}
        records = business_object_decision_records(state)
        self.assertEqual(records[0].decision, CANDIDATE)
        self.assertTrue(records[0].rules[3].evidence)
        self.assertTrue(records[0].unknowns)
        self.assertTrue(records[0].confirmation_question)
        self.assertEqual(validate_business_object_decisions(state), [])

    def test_reported_decision_is_checked_but_not_trusted(self):
        state = {"businessObjectDecisions": [business_candidate(
            "CO0001", "矛盾候选", ["PASS", "PASS", "PASS", "UNKNOWN", "PASS"],
            reported="CONFIRMED", unknown_reasons={"r4": "证据不足"})]}
        issues = validate_business_object_decisions(state)
        self.assertIn("BUSINESS_OBJECT_DECISION_MISMATCH", {issue.code for issue in issues})

    def test_confirmed_requires_each_rule_evidence(self):
        evidence = {rule: "真实来源" for rule in ("r1", "r2", "r3", "r4", "r5")}
        evidence["r5"] = ""
        state = {"businessObjectDecisions": [business_candidate(
            "CO0001", "证据不全", ["PASS"] * 5, evidence=evidence)]}
        self.assertIn("MISSING_BUSINESS_OBJECT_EVIDENCE",
                      {issue.code for issue in validate_business_object_decisions(state)})

    def test_unknown_without_unknown_reason_is_rejected_by_validator(self):
        state = {"businessObjectDecisions": [business_candidate(
            "CO0001", "未知原因缺失", ["PASS", "PASS", "PASS", "UNKNOWN", "PASS"])]}
        self.assertIn("MISSING_BUSINESS_OBJECT_UNKNOWN_REASON",
                      {issue.code for issue in validate_business_object_decisions(state)})

    def test_csv_uses_standard_quoting_and_preserves_other_work_files(self):
        state = {"businessObjectDecisions": [business_candidate(
            "CO0001", '含逗号、引号"和换行', ["PASS"] * 5,
            evidence={rule: "来源, \"列\"\n第二行" for rule in ("r1", "r2", "r3", "r4", "r5")})]}
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "keep.json"
            marker.write_text("keep", encoding="utf-8")
            path = write_business_object_decisions_csv(directory, state)
            self.assertTrue(marker.exists())
            with open(path, encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["候选业务对象名称"], '含逗号、引号"和换行')
            self.assertIn("第二行", rows[0]["R1证据"])

    def test_fixture_counts_are_recoverable(self):
        records = []
        for index in range(19):
            records.append(business_candidate(f"CO{index + 1:04d}", f"confirmed-{index}", ["PASS"] * 5))
        for index in range(6):
            records.append(business_candidate(f"CO{index + 20:04d}", f"candidate-{index}",
                                               ["PASS", "PASS", "PASS", "UNKNOWN", "PASS"],
                                               unknown_reasons={"r4": "待确认"}))
        for index in range(27):
            records.append(business_candidate(f"CO{index + 26:04d}", f"rejected-{index}",
                                               ["PASS", "FAIL", "PASS", "PASS", "PASS"]))
        state = {"businessObjectDecisions": records}
        with tempfile.TemporaryDirectory() as directory:
            path = write_business_object_decisions_csv(directory, state)
            with open(path, encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        counts = {status: sum(row["最终决策"] == status for row in rows)
                  for status in (CONFIRMED, CANDIDATE, "REJECTED")}
        self.assertEqual((len(rows), counts), (52, {CONFIRMED: 19, CANDIDATE: 6, "REJECTED": 27}))


class BusinessRuleTypeValidationTests(unittest.TestCase):
    def test_alert_hits_are_not_integrity_violations(self):
        result = validate_business_rule({
            "ruleId": "R_ALERT",
            "ruleType": BusinessRuleType.ALERT_DETECTION_RULE.value,
            "sampleCount": 104,
            "hitCount": 46,
        })
        self.assertEqual(result.hit_count, 46)
        self.assertAlmostEqual(result.hit_rate, 46 / 104)
        self.assertIsNone(result.violation_count)
        self.assertNotEqual(result.enforcement, RuleEnforcement.ENFORCED.value)

    def test_alert_high_hit_rate_does_not_reject(self):
        result = validate_business_rule({
            "ruleId": "R_ALERT_HIGH",
            "ruleType": "ALERT_DETECTION_RULE",
            "sampleCount": 100,
            "hitCount": 80,
        })
        self.assertEqual(result.validation_status, "VALIDATED")
        self.assertEqual(result.hit_count, 80)

    def test_integrity_zero_violations_does_not_prove_enforcement(self):
        result = validate_business_rule({
            "ruleId": "R_INTEGRITY",
            "ruleType": "INTEGRITY_CONSTRAINT",
            "sampleCount": 100,
            "violationCount": 0,
        })
        self.assertEqual(result.violation_count, 0)
        self.assertEqual(result.violation_rate, 0)
        self.assertNotEqual(result.enforcement, RuleEnforcement.ENFORCED.value)

    def test_calculation_uses_match_and_mismatch_semantics(self):
        result = validate_business_rule({
            "ruleId": "R_CALC",
            "ruleType": "CALCULATION_RULE",
            "evaluatedCount": 100,
            "matchCount": 98,
            "mismatchCount": 2,
        })
        self.assertEqual((result.evaluated_count, result.match_count, result.mismatch_count), (100, 98, 2))
        self.assertEqual(result.violation_count, None)

    def test_unknown_type_needs_classification_and_never_defaults_to_constraint(self):
        result = validate_business_rule({"ruleId": "R_UNKNOWN", "ruleType": "NOT_SURE",
                                         "sampleCount": 100, "violationCount": 1})
        self.assertEqual(result.rule_type, BusinessRuleType.UNKNOWN.value)
        self.assertEqual(result.validator, "none")
        issues = business_rule_validation_issues({"ruleDecisions": [{
            "ruleId": "R_UNKNOWN", "ruleType": "NOT_SURE"}]})
        self.assertIn("UNKNOWN_RULE_TYPE", {issue.code for issue in issues})

    def test_transition_without_history_and_outcome_without_result_are_unresolved(self):
        transition = validate_business_rule({"ruleId": "R_STATE", "ruleType": "STATE_TRANSITION_RULE",
                                              "currentState": "DRAFT"})
        eligibility = validate_business_rule({"ruleId": "R_ELIGIBLE", "ruleType": "ELIGIBILITY_RULE",
                                              "conditionHitCount": 80})
        self.assertEqual(transition.validation_status, "INSUFFICIENT_EVIDENCE")
        self.assertEqual(eligibility.validation_status, "INSUFFICIENT_EVIDENCE")


if __name__ == "__main__":
    unittest.main()
