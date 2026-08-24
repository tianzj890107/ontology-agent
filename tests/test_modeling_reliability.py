import sys
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

import open_claude.modeling_reliability as reliability  # noqa: E402
from open_claude.modeling_reliability import (  # noqa: E402
    CANDIDATE,
    COMPOSITION,
    CONFIRMED,
    EXTENSION,
    REFERENCE,
    REJECTED,
    UNRESOLVED,
    BUSINESS_OBJECT_DECISION_HEADERS,
    BusinessRuleType,
    RuleEnforcement,
    aggregation_components,
    analyze_aggregation,
    apply_aggregation_downgrades,
    apply_not_applicable_normalization,
    business_object_decision_records,
    derive_business_object_decision,
    finalize_semantic_model,
    infer_business_object_rule_status,
    is_structural_blocker,
    normalize_modeling_state,
    validate_business_object_decisions,
    validate_business_object_evidence_consistency,
    business_rule_validation_issues,
    validate_business_rule,
    validate_formal_business_object_csv,
    write_business_object_decisions_csv,
    semantic_validation_issues,
    validate_formal_relation_csv,
    validate_modeling_stages,
    validate_logical_entity_assignments,
    VALIDATION_CACHE_VERSION,
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
        self.assertEqual([issue.code for issue in issues], ["FORMAL_OUTPUT_INELIGIBLE_ROW"])
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
        self.assertEqual(issues[0].code, "FORMAL_OUTPUT_INELIGIBLE_ROW")
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
        issue = next(item for item in semantic_validation_issues(state)
                     if item.code == "INVALID_AGGREGATION_EDGE")
        self.assertEqual(issue.severity, "WARNING")
        self.assertFalse(any("REL_FK_ONLY" in component.relation_ids
                             for component in aggregation_components(state)))

    def test_fk_composition_downgrade_keeps_stage_gate_passed(self):
        state = {
            "entities": [entity("LE_A", "MAIN"), entity("LE_D", "DEPENDENT")],
            "relationDecisions": [composition(
                "REL_FK_ONLY", "LE_D", "LE_A", evidence_types=["FOREIGN_KEY"])],
        }
        with tempfile.TemporaryDirectory() as root:
            work = Path(root) / "mission-work"
            work.mkdir()
            output = Path(root) / "mission-output"
            output.mkdir()
            (output / "entity_relations.csv").write_text(
                "关系编码,源逻辑实体编码,目标逻辑实体编码,关系分类,关系基数\n"
                "REL_FK_ONLY,LE_D,LE_A,REFERENCE,1:1\n", encoding="utf-8")
            result = validate_modeling_stages(work, output,
                                              state, ["entity_relations.csv"])
            self.assertEqual(result["stages"][7]["status"], "PASSED")
            self.assertFalse(any(issue.severity == "ERROR" for issue in result["issues"]))


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

    def test_confirmed_observed_pattern_unknown_enforcement_is_legal(self):
        state = {"ruleDecisions": [{
            "ruleId": "R_PATTERN", "ruleType": "INTEGRITY_CONSTRAINT",
            "decision": CONFIRMED, "enforcement": "UNKNOWN",
            "evidenceTypes": ["OBSERVED_PATTERN"], "provenance": ["profile.sql"],
            "sampleCount": 1000, "violationCount": 0,
        }]}
        issues = business_rule_validation_issues(state)
        self.assertEqual([issue.code for issue in issues if issue.severity == "ERROR"], [])
        self.assertNotIn("INSUFFICIENT_RULE_EVIDENCE", {issue.code for issue in issues})

    def test_enforced_claim_without_enforcement_evidence_is_warning(self):
        state = {"ruleDecisions": [{
            "ruleId": "R_CLAIMED", "ruleType": "INTEGRITY_CONSTRAINT",
            "decision": CONFIRMED, "enforcement": "ENFORCED",
            "evidenceTypes": ["OBSERVED_PATTERN"], "provenance": ["profile.sql"],
            "sampleCount": 100, "violationCount": 0,
        }]}
        issues = business_rule_validation_issues(state)
        self.assertIn("ENFORCED_WITHOUT_ENFORCEMENT_EVIDENCE",
                      {issue.code for issue in issues if issue.severity == "WARNING"})
        self.assertEqual([issue.code for issue in issues if issue.severity == "ERROR"], [])

    def test_validated_claim_without_validation_evidence_is_warning(self):
        state = {"ruleDecisions": [{
            "ruleId": "R_CLAIMED_VALIDATED", "ruleType": "INTEGRITY_CONSTRAINT",
            "decision": CONFIRMED, "enforcement": "UNKNOWN",
            "validationStatus": "VALIDATED",
            "evidenceTypes": ["OBSERVED_PATTERN"], "provenance": ["profile.sql"],
        }]}
        issues = business_rule_validation_issues(state)
        self.assertIn("VALIDATED_WITHOUT_VALIDATION_EVIDENCE",
                      {issue.code for issue in issues if issue.severity == "WARNING"})
        self.assertIn("INSUFFICIENT_RULE_EVIDENCE",
                      {issue.code for issue in issues if issue.severity == "WARNING"})
        self.assertEqual([issue.code for issue in issues if issue.severity == "ERROR"], [])

    def test_weak_rule_evidence_never_fails_stage_or_blocks_run(self):
        """INSUFFICIENT/ENFORCED/VALIDATED evidence gaps stay WARNING so the
        modeling stage passes and no retry/blocked/safety-valve can fire."""
        state = {"ruleDecisions": [
            {"ruleId": "R_WEAK_1", "ruleType": "INTEGRITY_CONSTRAINT",
             "decision": CONFIRMED, "enforcement": "ENFORCED",
             "evidenceTypes": ["OBSERVED_PATTERN"], "provenance": ["profile.sql"],
             "sampleCount": 100, "violationCount": 0},
            {"ruleId": "R_WEAK_2", "ruleType": "CALCULATION_RULE",
             "decision": CONFIRMED, "enforcement": "UNKNOWN",
             "validationStatus": "VALIDATED",
             "evidenceTypes": ["OBSERVED_PATTERN"], "provenance": ["profile.sql"]},
        ]}
        issues = semantic_validation_issues(state)
        self.assertEqual([issue.code for issue in issues if issue.severity == "ERROR"], [])
        self.assertTrue(any(issue.code == "INSUFFICIENT_RULE_EVIDENCE"
                            for issue in issues if issue.severity == "WARNING"))
        self.assertTrue(any(issue.code == "ENFORCED_WITHOUT_ENFORCEMENT_EVIDENCE"
                            for issue in issues if issue.severity == "WARNING"))

    def test_weak_rule_and_indicator_evidence_pass_modeling_stages(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / "work"
            output = Path(directory) / "output"
            work.mkdir()
            output.mkdir()
            state = {
                "ruleDecisions": [
                    {"ruleId": "R_SOFT", "ruleType": "INTEGRITY_CONSTRAINT",
                     "decision": CANDIDATE, "enforcement": "NOT_ENFORCED",
                     "evidenceTypes": ["OBSERVED_PATTERN"], "provenance": ["profile.sql"],
                     "sampleCount": 100, "violationCount": 0},
                ],
                "indicatorDecisions": [
                    {"indicatorId": "M_SOFT", "name": "转化率", "status": CANDIDATE,
                     "aggregationSemantics": "UNKNOWN"},
                ],
            }
            (work / "modeling_state.json").write_text(
                json.dumps(state, ensure_ascii=False), encoding="utf-8")
            (output / "business_rules.csv").write_text(
                "规则编码,规则名称\nR_SOFT,软证据规则\n", encoding="utf-8")
            (output / "metrics.csv").write_text(
                "指标编码,指标名称\nM_SOFT,转化率\n", encoding="utf-8")
            result = validate_modeling_stages(
                work, output, state,
                ["business_rules.csv", "metrics.csv"])
            failed_stages = [row for row in result["stages"]
                             if row.get("status") == "FAILED"]
            self.assertEqual(failed_stages, [],
                             f"weak rule/indicator evidence must not fail a stage: "
                             f"{[(row.get('stage'), row.get('issueCodes')) for row in result['stages']]}")

    def test_declared_constraint_with_source_can_be_enforced(self):
        state = {"ruleDecisions": [{
            "ruleId": "R_DECL", "ruleType": "INTEGRITY_CONSTRAINT",
            "decision": CONFIRMED, "enforcement": "ENFORCED",
            "evidenceTypes": ["DECLARED_CONSTRAINT"], "provenance": ["ddl.sql"],
            "sampleCount": 100, "violationCount": 0,
        }]}
        self.assertEqual([issue.code for issue in business_rule_validation_issues(state)], [])


class V0001DuplicateNameGateTests(unittest.TestCase):
    """Full-chain acceptance for the entity-scoped attribute-name rule."""

    CSV_HEADER = "逻辑实体编码,业务属性编码,业务属性名称,业务属性定义,是否页面显示\n"

    @staticmethod
    def _empty_state():
        return {"allAttributes": [], "businessAttributes": []}

    def _run_stage(self, csv_text):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            work = root / "mission-work"
            output = root / "mission-output"
            work.mkdir()
            output.mkdir()
            (output / "business_attributes.csv").write_text(csv_text, encoding="utf-8")
            result = validate_modeling_stages(
                work, output, self._empty_state(), ["business_attributes.csv"])
            row = next(item for item in result["stages"]
                       if item["stage"] == "BUSINESS_ATTRIBUTES")
            return row

    def test_same_entity_duplicate_attribute_name_fails_stage(self):
        row = self._run_stage(
            self.CSV_HEADER +
            "LE1,AT1,金额,订单金额,N\n"
            "LE1,AT2,金额,订单金额,N\n")
        self.assertEqual(row["status"], "FAILED")
        errors = [item for item in row.get("issues", [])
                  if item.get("code") == "V0001_DUPLICATE_FORMAL_NAME"
                  and item.get("severity") == "ERROR"]
        self.assertEqual(len(errors), 1)
        self.assertIn("LE1", errors[0].get("message", ""))

    def test_cross_entity_same_name_same_definition_passes_stage(self):
        row = self._run_stage(
            self.CSV_HEADER +
            "LE1,AT1,金额,订单金额,N\n"
            "LE2,AT2,金额,订单金额,N\n")
        self.assertEqual(row["status"], "PASSED")
        self.assertNotIn("V0001_DUPLICATE_FORMAL_NAME",
                         {item.get("code") for item in row.get("issues", [])})

    def test_cross_entity_same_name_different_definition_is_warning_and_passes_stage(self):
        row = self._run_stage(
            self.CSV_HEADER +
            "LE1,AT1,状态,采购订单审批状态,N\n"
            "LE2,AT2,状态,供应商冻结状态,N\n")
        # WARNING must not fail the stage or trigger a repair/retry window.
        self.assertEqual(row["status"], "PASSED")
        duplicate = [item for item in row.get("issues", [])
                     if item.get("code") == "V0001_DUPLICATE_FORMAL_NAME"]
        self.assertEqual(len(duplicate), 1)
        self.assertEqual(duplicate[0].get("severity"), "WARNING")

    def test_stage_cache_is_invalidated_by_validator_version(self):
        state = {"allAttributes": [{"来源字段": "id"}],
                 "logicalEntities": [{"code": "LE001"}]}
        with tempfile.TemporaryDirectory() as root,                 patch.object(reliability, "_stage_specific_issues", return_value=[]) as validate:
            root = Path(root)
            work = root / "mission-work"
            output = root / "mission-output"
            work.mkdir()
            output.mkdir()
            first = validate_modeling_stages(work, output, state, ["logical_entities.csv"])
            second = validate_modeling_stages(work, output, first["state"],
                                              ["logical_entities.csv"])
            self.assertEqual(validate.call_count, 5)
            self.assertEqual(second["events"], [])
            with patch.object(reliability, "VALIDATION_CACHE_VERSION", "older-validator"):
                third = validate_modeling_stages(work, output, second["state"],
                                                 ["logical_entities.csv"])
            # A deployed validator change invalidates stale checkpoints so a
            # previously cached FAILED stage cannot keep blocking a run.
            self.assertGreater(validate.call_count, 5)
            self.assertTrue(any(event.get("stage") == "INPUT_CONTEXT"
                                for event in third["events"]))


class BusinessObjectEvidenceConsistencyTests(unittest.TestCase):
    """规则 12（可实例化）的低过拟合证据一致性门禁正反例。

    覆盖：固定码表拒绝、主数据/0 行放行、规则配置行拒绝、规则定义放行、
    SQL 聚合视图拒绝、报告实例放行、名称含“报告”降 CANDIDATE、
    正反证据冲突保持 UNKNOWN、finalization 阻断、两服务共享同一门禁。
    """

    @staticmethod
    def _candidate(code, name, r5_status="PASS", r5_evidence="直接来源", *,
                   r5_types=None):
        r5 = {"status": r5_status, "evidence": r5_evidence}
        if r5_types:
            r5["evidenceTypes"] = list(r5_types)
        record = {
            "candidateCode": code, "candidateName": name,
            "memberEntityIds": ["LE001"], "confidence": "80",
            **{f"r{i}": {"status": "PASS",
                         "evidence": "有明确业务用途、稳定编号、独立生命周期和状态字段"}
               for i in range(1, 5)},
            "r5": r5,
        }
        return {"businessObjectDecisions": [record]}

    @staticmethod
    def _unknown_r5(code, name, r5_evidence, *, conflicts=""):
        record = {
            "candidateCode": code, "candidateName": name,
            "memberEntityIds": ["LE001"], "confidence": "90",
            **{f"r{i}": {"status": "PASS", "evidence": "直接来源"} for i in range(1, 5)},
            "r5": {"status": "UNKNOWN", "evidence": r5_evidence},
        }
        if conflicts:
            record["conflicts"] = conflicts
        return {"businessObjectDecisions": [record]}

    def test_fixed_code_table_reference_data_is_rejected(self):
        # 固定采购需求类型码表：有限、预置、仅分类、无业务行为 → R5 FAIL / REJECTED
        self.assertEqual(infer_business_object_rule_status(
            "r5", "固定码表，值域有限且可预置，仅分类标签，无业务行为"), "FAIL")
        decision = business_object_decision_records(self._unknown_r5(
            "CO_TYPE", "采购需求类型",
            "固定码表，值域有限且可预置，仅分类标签，无业务行为"))[0]
        self.assertEqual(decision.rules[4].status, "FAIL")
        self.assertEqual(decision.decision, REJECTED)

    def test_low_row_count_governed_master_data_is_not_rejected(self):
        # 可持续新增且独立治理的主数据：即使当前行数很少，也不能仅因数量有限而拒绝
        state = {"businessObjectDecisions": [{
            "candidateCode": "CO_MD", "candidateName": "供应商主数据",
            "memberEntityIds": ["LE001"], "confidence": "70", "rowCount": 3,
            **{f"r{i}": {"status": "PASS", "evidence": "直接来源"} for i in range(1, 5)},
            "r5": {"status": "UNKNOWN", "rowCount": 3,
                   "evidence": "当前样本仅 3 行，但由业务持续新增，有稳定业务编号、"
                               "主数据结构和可重复创建语义"},
        }]}
        decision = business_object_decision_records(state)[0]
        self.assertEqual(decision.rules[4].status, "PASS")
        self.assertEqual(decision.decision, CONFIRMED)
        self.assertEqual(validate_business_object_evidence_consistency(state), [])

    def test_zero_rows_with_stable_structure_do_not_fail_r5(self):
        # 0 行业务表但具有稳定业务编号和可重复创建结构：0 行不能单独导致 R5 FAIL
        zero = {"businessObjectDecisions": [{
            "candidateCode": "CO_ZERO", "candidateName": "零行主数据",
            "memberEntityIds": ["LE001"], "confidence": "70", "rowCount": 0,
            **{f"r{i}": {"status": "PASS", "evidence": "直接来源"} for i in range(1, 5)},
            "r5": {"status": "UNKNOWN", "rowCount": 0,
                   "evidence": "当前数据 0 行，但存在稳定业务编号、主数据结构和可重复创建语义"},
        }]}
        decision = business_object_decision_records(zero)[0]
        self.assertEqual(decision.rules[4].status, "PASS")
        self.assertEqual(validate_business_object_evidence_consistency(zero), [])

    def test_rule_configuration_row_is_not_a_business_object(self):
        # 规则条件配置行：无独立编号、版本和生命周期，不得成为业务对象
        self.assertEqual(infer_business_object_rule_status(
            "r5", "规则条件配置行，无独立编号、版本和生命周期，不能形成可区分实例"), "FAIL")
        decision = business_object_decision_records(self._unknown_r5(
            "CO_RULE_CFG", "规则条件配置行",
            "规则条件配置行，无独立编号、版本和生命周期，不能形成可区分实例"))[0]
        self.assertEqual(decision.rules[4].status, "FAIL")
        self.assertEqual(decision.decision, REJECTED)

    def test_governed_rule_definition_can_pass(self):
        # 有编号、版本、审批、发布、生效和停用的规则定义：不能被“规则”关键字误杀
        state = self._candidate(
            "CO_RULE_DEF", "采购规则定义", r5_evidence=(
                "规则定义有独立规则编号、规则版本，支持版本化、审批、发布、生效和停用流程"))
        decision = business_object_decision_records(state)[0]
        self.assertEqual(decision.rules[4].status, "PASS")
        self.assertEqual(decision.decision, CONFIRMED)
        self.assertEqual(validate_business_object_evidence_consistency(state), [])

    def test_sql_aggregate_view_is_rejected(self):
        # SQL 聚合报表/数据库视图：纯派生展示、无独立实例 → R5 FAIL
        self.assertEqual(infer_business_object_rule_status(
            "r5", "SQL 聚合视图，纯查询结果、统计展示，无独立实例"), "FAIL")
        decision = business_object_decision_records(self._unknown_r5(
            "CO_VIEW", "采购统计视图",
            "SQL 聚合视图，纯查询结果、统计展示，无独立实例"))[0]
        self.assertEqual(decision.rules[4].status, "FAIL")
        self.assertEqual(decision.decision, REJECTED)

    def test_report_instance_with_lifecycle_can_pass(self):
        # 有报告编号、报告期、编制、审批、发布、归档的报告实例：不能被“报告”关键字误杀
        state = self._candidate(
            "CO_REPORT_INST", "年度风险评估报告", r5_evidence=(
                "该次报告有唯一报告编号、报告期间，以及编制、审批、发布、归档独立生命周期"))
        decision = business_object_decision_records(state)[0]
        self.assertEqual(decision.rules[4].status, "PASS")
        self.assertEqual(decision.decision, CONFIRMED)
        self.assertEqual(validate_business_object_evidence_consistency(state), [])

    def test_report_name_without_evidence_is_candidate_not_rejected(self):
        # 名称包含“报告”但证据不足 → UNKNOWN/CANDIDATE，而不是直接 REJECTED
        state = self._unknown_r5("CO_REPORT_NAME", "采购报告",
                                 "名称包含报告，缺少实例化证据")
        decision = business_object_decision_records(state)[0]
        self.assertEqual(decision.rules[4].status, "UNKNOWN")
        self.assertEqual(decision.decision, CANDIDATE)
        self.assertEqual(validate_business_object_evidence_consistency(state), [])
        self.assertFalse(any(
            issue.code == "R5_PASS_WITH_EXPLICIT_COUNTER_EVIDENCE"
            for issue in semantic_validation_issues(state)))

    def test_name_keyword_only_triggers_review_not_rejection(self):
        # 名称含“字典/类型/规则/报表”只触发复核，不直接决定结论
        for name in ("采购需求类型字典", "折扣规则表", "月度统计报表"):
            state = self._unknown_r5(
                "CO_N" + str(abs(hash(name)) % 1000), name,
                "仅名称提示可能为码表/规则/报表，缺少实例化证据")
            decision = business_object_decision_records(state)[0]
            self.assertEqual(decision.rules[4].status, "UNKNOWN")
            self.assertEqual(decision.decision, CANDIDATE)
            self.assertEqual(validate_business_object_evidence_consistency(state), [])

    def test_conflicting_category_and_behavior_evidence_is_unknown(self):
        # 数据类别与行为证据冲突：保留 UNKNOWN 和冲突说明，不硬阻断
        state = self._unknown_r5(
            "CO_CONFLICT", "冲突候选",
            "固定码表但可新增业务实例，正反证据冲突",
            conflicts="固定码表 vs 可新增业务实例")
        decision = business_object_decision_records(state)[0]
        self.assertEqual(decision.rules[4].status, "UNKNOWN")
        self.assertEqual(decision.decision, CANDIDATE)
        self.assertTrue(decision.conflicts)
        self.assertEqual(validate_business_object_evidence_consistency(state), [])

    def test_finalization_gate_blocks_inconsistent_confirmed(self):
        # 反证明确仍保留 PASS/CONFIRMED：finalization gate 必须阻断
        state = self._candidate(
            "CO_FIXED", "采购需求类型",
            r5_evidence="该表是固定码表，码值数量有限且可预置，仅分类标签，无业务行为")
        with tempfile.TemporaryDirectory() as root:
            result = finalize_semantic_model(Path(root) / "mission-work", state)
        self.assertEqual(result["status"], "FAILED")
        blockers = [issue for issue in result["issues"]
                    if issue.code == "R5_PASS_WITH_EXPLICIT_COUNTER_EVIDENCE"]
        self.assertEqual(len(blockers), 1)
        self.assertTrue(is_structural_blocker(blockers[0]))

    def test_47313_and_47314_reach_identical_conclusions(self):
        # 47313 与 47314 对相同 modeling_state 得到一致结论（共享同一门禁）
        import oc_codex_server
        self.assertIs(oc_codex_server.semantic_validation_issues,
                      reliability.semantic_validation_issues)
        self.assertIs(oc_codex_server.finalize_semantic_model,
                      reliability.finalize_semantic_model)
        state = self._candidate(
            "CO_FIXED", "采购需求类型",
            r5_evidence="该表是固定码表，值域有限且可预置，仅分类标签，无业务行为")
        web_issues = oc_codex_server.semantic_validation_issues(state)
        self.assertIn("R5_PASS_WITH_EXPLICIT_COUNTER_EVIDENCE",
                      {issue.code for issue in web_issues})
        with tempfile.TemporaryDirectory() as root:
            standalone_result = oc_codex_server.finalize_semantic_model(
                Path(root) / "mission-work", state)
        self.assertEqual(standalone_result["status"], "FAILED")
        self.assertIn("R5_PASS_WITH_EXPLICIT_COUNTER_EVIDENCE",
                      {issue.code for issue in standalone_result["issues"]})


class NotApplicableAssignmentTests(unittest.TestCase):
    """非业务对象逻辑实体（NOT_APPLICABLE）与 ASSIGNED/UNRESOLVED 归属门禁。"""

    @staticmethod
    def _confirmed_bo(code="BO0001", entity="LE0001"):
        return {
            "candidateCode": code, "candidateName": "采购订单",
            "memberEntityIds": [entity], "confidence": "80", "decision": "CONFIRMED",
            **{f"r{i}": {"status": "PASS",
                         "evidence": "有明确业务用途、稳定编号、独立生命周期和状态字段"}
               for i in range(1, 5)},
            "r5": {"status": "PASS",
                   "evidence": "由业务活动持续产生，有稳定业务编号和可重复创建的单据结构"},
        }

    @staticmethod
    def _rejected_bo(code, entity, category_evidence):
        return {
            "candidateCode": code, "candidateName": "非业务对象候选",
            "memberEntityIds": [entity], "confidence": "60", "decision": "REJECTED",
            **{f"r{i}": {"status": "PASS", "evidence": "直接来源"} for i in range(1, 4)},
            "r4": {"status": "UNKNOWN", "evidence": "无独立生命周期证据"},
            "r5": {"status": "FAIL", "evidence": category_evidence},
        }

    @staticmethod
    def _not_applicable_entity(entity_id, *, category="基础数据", code=None):
        item = {
            "entityId": entity_id,
            "businessObjectAssignmentStatus": "NOT_APPLICABLE",
            "mainFlag": "N",
            "nonBusinessObjectCategory": category,
            "exclusionReason": "固定码表，值域有限且可预置，仅分类标签，无业务行为",
            "exclusionEvidence": "来源表码值数量有限且上线前预置，无业务行为与独立生命周期",
        }
        if code:
            item["rejectedBusinessObjectCode"] = code
        return item

    @staticmethod
    def _finalize_with_outputs(state, outputs):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            work = root / "mission-work"
            output = root / "mission-output"
            output.mkdir()
            for name, header, rows in outputs:
                with (output / name).open("w", encoding="utf-8", newline="") as handle:
                    csv.writer(handle, lineterminator="\n").writerows([header] + rows)
            result = finalize_semantic_model(
                work, state, output_dir=output,
                required_outputs=[name for name, _, _ in outputs])
            with (work / "logical_entity_decisions.csv").open(
                    encoding="utf-8-sig") as handle:
                logical_entity_audit = list(csv.DictReader(handle))
            with (work / "business_object_decisions.csv").open(
                    encoding="utf-8-sig") as handle:
                business_object_audit = list(csv.DictReader(handle))
            return result, logical_entity_audit, business_object_audit

    def test_four_non_business_object_categories_pass_finalize(self):
        # 基础数据/规则数据/参考数据/报告报表数据对应的非业务对象逻辑实体：
        # 编码/名称留空、主标志 N、NOT_APPLICABLE、有分类/原因/证据和 REJECTED
        # 决策时，最终门禁通过，且不产生任何占位业务对象。
        for category, r5_evidence in (
            ("基础数据", "固定码表，值域有限且可预置，仅分类标签，无业务行为"),
            ("规则数据", "规则条件配置行，无独立编号、版本和生命周期，不能形成可区分实例"),
            ("参考数据", "分类/标签型参考数据，值域有限且可预置，仅作分类参考，无业务行为"),
            ("报告报表数据", "报表模板/查询定义/统计展示快照，无独立业务实例"),
        ):
            with self.subTest(category=category):
                state = {
                    "businessObjectDecisions": [
                        self._confirmed_bo(),
                        self._rejected_bo("BO_REJ", "LE0002", r5_evidence),
                    ],
                    "entities": [
                        {"entityId": "LE0001", "businessObjectCode": "BO0001", "isMain": "Y"},
                        self._not_applicable_entity("LE0002", category=category, code="BO_REJ"),
                    ],
                }
                outputs = [
                    ("business_objects.csv",
                     ["业务对象编码", "业务对象名称", "业务对象英文名", "业务对象定义", "数据类别"],
                     [["BO0001", "采购订单", "purchase_order", "采购订单相关业务对象定义", "事务数据"]]),
                    ("logical_entities.csv",
                     ["业务对象编码", "业务对象名称", "逻辑实体编码", "逻辑实体名称",
                      "逻辑实体英文名", "逻辑实体定义", "是否主逻辑实体", "数据类别"],
                     [["BO0001", "采购订单", "LE0001", "采购订单实体", "purchase_order_entity",
                       "采购订单业务实体定义", "Y", "事务数据"],
                      ["", "", "LE0002", "采购需求类型", "purchase_requirement_type",
                       "采购需求类型码表逻辑实体", "N", category]]),
                ]
                result, logical_entity_audit, business_object_audit = \
                    self._finalize_with_outputs(state, outputs)
                self.assertEqual(
                    result["status"], "PASSED",
                    [issue.as_dict() for issue in result["issues"]])
                self.assertIn("NOT_APPLICABLE",
                              {row["业务对象归属状态"] for row in logical_entity_audit})
                self.assertIn("REJECTED",
                              {row["最终决策"] for row in business_object_audit})

    def test_confirmed_four_category_candidate_is_blocked(self):
        # 候选性质为互斥非业务对象类别仍 R5=PASS/CONFIRMED → 必须阻断
        state = {"businessObjectDecisions": [{
            "candidateCode": "CO_KIND", "candidateName": "采购需求类型",
            "candidateKind": "REFERENCE_DATA", "confidence": "80",
            "memberEntityIds": ["LE1"],
            **{f"r{i}": {"status": "PASS", "evidence": "直接来源"} for i in range(1, 5)},
            "r5": {"status": "PASS", "evidence": "存在业务编号可区分实例"},
        }]}
        issues = semantic_validation_issues(state)
        self.assertIn("CONFIRMED_WITH_NON_BUSINESS_OBJECT_KIND",
                      {issue.code for issue in issues})
        # 数据类别=基础数据 + 码表证据组合仍 PASS → 证据一致性门禁阻断
        state2 = {"businessObjectDecisions": [{
            "candidateCode": "CO_CAT", "candidateName": "采购需求类型",
            "数据类别": "基础数据", "confidence": "80", "memberEntityIds": ["LE1"],
            **{f"r{i}": {"status": "PASS", "evidence": "直接来源"} for i in range(1, 5)},
            "r5": {"status": "PASS", "evidence": "码值数量有限且可预置，仅分类标签"},
        }]}
        issues2 = semantic_validation_issues(state2)
        self.assertIn("R5_PASS_WITH_EXPLICIT_COUNTER_EVIDENCE",
                      {issue.code for issue in issues2})
        self.assertTrue(all(is_structural_blocker(issue)
                            for issue in issues + issues2))

    def test_not_applicable_main_flag_is_blocked(self):
        entity = self._not_applicable_entity("LE1", code="BO_REJ")
        entity["mainFlag"] = "Y"
        state = {"entities": [entity],
                 "businessObjectDecisions": [
                     self._rejected_bo("BO_REJ", "LE1",
                                       "固定码表，值域有限且可预置，仅分类标签，无业务行为")]}
        issues = semantic_validation_issues(state)
        self.assertIn("NOT_APPLICABLE_MAIN_FLAG", {issue.code for issue in issues})
        self.assertIn("V0001_MAIN_FLAG_WITHOUT_BUSINESS_OBJECT",
                      {issue.code for issue in issues})

    def test_not_applicable_with_business_object_code_is_blocked(self):
        state = {"entities": [{
            "entityId": "LE1", "businessObjectAssignmentStatus": "NOT_APPLICABLE",
            "businessObjectCode": "BO_X", "mainFlag": "N",
            "nonBusinessObjectCategory": "基础数据",
            "exclusionReason": "固定码表", "exclusionEvidence": "来源表码值可预置",
        }],
            "businessObjectDecisions": [
                self._rejected_bo("BO_X", "LE1",
                                  "固定码表，值域有限且可预置，仅分类标签，无业务行为")]}
        issues = semantic_validation_issues(state)
        self.assertIn("NOT_APPLICABLE_WITH_BUSINESS_OBJECT",
                      {issue.code for issue in issues})

    def test_not_applicable_missing_audit_evidence_is_blocked(self):
        state = {"entities": [{
            "entityId": "LE1", "businessObjectAssignmentStatus": "NOT_APPLICABLE",
            "mainFlag": "N", "rejectedBusinessObjectCode": "BO_REJ",
        }],
            "businessObjectDecisions": [
                self._rejected_bo("BO_REJ", "LE1",
                                  "固定码表，值域有限且可预置，仅分类标签，无业务行为")]}
        issues = semantic_validation_issues(state)
        self.assertIn("NOT_APPLICABLE_MISSING_AUDIT_EVIDENCE",
                      {issue.code for issue in issues})

    def test_not_applicable_without_rejected_decision_is_blocked(self):
        state = {"entities": [self._not_applicable_entity("LE1")]}
        issues = semantic_validation_issues(state)
        self.assertIn("NOT_APPLICABLE_WITHOUT_REJECTED_DECISION",
                      {issue.code for issue in issues})

    def test_assigned_without_code_is_blocked(self):
        state = {"entities": [{"entityId": "LE1",
                               "businessObjectAssignmentStatus": "ASSIGNED",
                               "mainFlag": "N"}]}
        issues = semantic_validation_issues(state)
        self.assertIn("MISSING_BUSINESS_OBJECT_ASSIGNMENT",
                      {issue.code for issue in issues})

    def test_assigned_referencing_non_confirmed_object_is_blocked(self):
        cases = {
            "CANDIDATE": {"r5": {"status": "UNKNOWN", "evidence": "缺少实例化证据"},
                          "confirmationQuestion": "请确认实例化证据"},
            "REJECTED": {},
        }
        for label, override in cases.items():
            record = self._rejected_bo("BO_X", "LE1",
                                       "固定码表，值域有限且可预置，仅分类标签，无业务行为")
            record.update(override)
            state = {"entities": [{
                "entityId": "LE1", "businessObjectAssignmentStatus": "ASSIGNED",
                "businessObjectCode": "BO_X", "mainFlag": "N"}],
                "businessObjectDecisions": [record]}
            with self.subTest(label=label):
                issues = semantic_validation_issues(state)
                self.assertIn("INVALID_BUSINESS_OBJECT_ASSIGNMENT",
                              {issue.code for issue in issues})
        missing = {"entities": [{
            "entityId": "LE1", "businessObjectAssignmentStatus": "ASSIGNED",
            "businessObjectCode": "BO_MISSING", "mainFlag": "N"}]}
        issues = semantic_validation_issues(missing)
        self.assertIn("INVALID_BUSINESS_OBJECT_ASSIGNMENT",
                      {issue.code for issue in issues})

    def test_unresolved_is_never_auto_converted_to_not_applicable(self):
        state = {"entities": [{
            "entityId": "LE1", "businessObjectAssignmentStatus": "UNRESOLVED",
            "missingEvidence": "缺少来源证据", "confirmationQuestion": "请确认归属",
        }]}
        normalize_modeling_state(state)
        entity = state["entities"][0]
        self.assertEqual(entity["businessObjectAssignmentStatus"], "UNRESOLVED")
        self.assertNotIn("NOT_APPLICABLE", entity.values())
        self.assertEqual(apply_not_applicable_normalization(state), 0)

    def test_legacy_entity_without_status_is_not_derived_not_applicable(self):
        state = {"entities": [{"entityId": "LE2"}]}
        normalize_modeling_state(state)
        self.assertNotEqual(state["entities"][0].get("businessObjectAssignmentStatus"),
                            "NOT_APPLICABLE")
        issues = validate_logical_entity_assignments(state)
        self.assertIn("MISSING_ASSIGNMENT_EVIDENCE", {issue.code for issue in issues})
        self.assertNotIn("NOT_APPLICABLE_WITHOUT_REJECTED_DECISION",
                         {issue.code for issue in issues})

    def test_not_applicable_auto_fix_only_with_evidence(self):
        # 有充分证据时：主标志 N、错误编码被清除并保留否决关联
        state = {"businessObjectDecisions": [
            self._rejected_bo("BO_REJ", "LE1",
                              "固定码表，值域有限且可预置，仅分类标签，无业务行为")],
            "entities": [{
                "entityId": "LE1", "businessObjectAssignmentStatus": "NOT_APPLICABLE",
                "businessObjectCode": "BO_REJ", "mainFlag": "Y",
                "nonBusinessObjectCategory": "基础数据",
                "exclusionReason": "固定码表", "exclusionEvidence": "来源表码值可预置",
            }]}
        self.assertEqual(apply_not_applicable_normalization(state), 1)
        entity = state["entities"][0]
        self.assertEqual(entity.get("mainFlag"), "N")
        self.assertNotIn("businessObjectCode", entity)
        self.assertEqual(entity.get("rejectedBusinessObjectCode"), "BO_REJ")

    def test_47313_and_47314_share_not_applicable_gate(self):
        import oc_codex_server
        self.assertIs(oc_codex_server.semantic_validation_issues,
                      reliability.semantic_validation_issues)
        self.assertIs(oc_codex_server.finalize_semantic_model,
                      reliability.finalize_semantic_model)
        state = {"entities": [self._not_applicable_entity("LE1", code="BO_REJ")],
                 "businessObjectDecisions": [
                     self._rejected_bo("BO_REJ", "LE1",
                                       "固定码表，值域有限且可预置，仅分类标签，无业务行为")]}
        web = oc_codex_server.semantic_validation_issues(state)
        standalone = reliability.semantic_validation_issues(state)
        self.assertEqual([issue.code for issue in web],
                         [issue.code for issue in standalone])


if __name__ == "__main__":
    unittest.main()
