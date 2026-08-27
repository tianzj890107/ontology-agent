"""Regression tests for the gate-action model.

Validator findings are split into four processing actions:
STRUCTURAL_BLOCKER / DETERMINISTIC_NORMALIZATION / FORMAL_ELIGIBILITY /
QUALITY_WARNING.  Only STRUCTURAL_BLOCKER may fail a stage and enter the
Agent repair loop; everything else is resolved server-side and the run
continues.  These tests pin that contract.
"""
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

import open_claude.modeling_reliability as reliability  # noqa: E402
from open_claude.modeling_reliability import (  # noqa: E402
    CANDIDATE,
    CONFIRMED,
    REFERENCE,
    TRANSFORMATION,
    UNRESOLVED,
    apply_business_object_normalization,
    apply_decision_summary_recompute,
    apply_evidence_isolation_cleanup,
    apply_fk_coverage_defaults,
    apply_mapping_dedup,
    apply_relation_eligibility_downgrades,
    apply_technical_attribute_exclusion,
    business_object_decision_records,
    finalize_semantic_model,
    is_structural_blocker,
    normalize_modeling_state,
    semantic_validation_issues,
    validate_business_object_decisions,
    validate_fk_coverage,
    validate_modeling_stages,
    write_decision_audits,
)
import oc_codex_server  # noqa: E402


def bo_candidate(code, name="对象", statuses=("PASS",) * 5, **extra):
    record = {
        "candidateCode": code,
        "candidateName": name,
        "memberEntityIds": ["LE001"],
        "confidence": "90",
    }
    for rule, status in zip(("r1", "r2", "r3", "r4", "r5"), statuses):
        record[rule] = {"status": status, "evidence": f"[{rule.upper()}_SOURCE] 证据"}
    record.update(extra)
    return record


def relation(relation_id, relation_type=REFERENCE, status=CONFIRMED,
             evidence_types=None, cardinality=None, **extra):
    record = {
        "relationId": relation_id,
        "sourceEntity": "LE_A",
        "targetEntity": "LE_B",
        "relationType": relation_type,
        "status": status,
        "evidenceTypes": evidence_types or [],
        "evidenceLevel": "STRONG",
        "provenance": ["input/schema.sql"],
    }
    if cardinality is not None:
        record["cardinality"] = cardinality
    record.update(extra)
    return record


class ActionClassificationTests(unittest.TestCase):
    def test_only_structural_blocker_fails(self):
        self.assertTrue(is_structural_blocker(
            reliability.ValidationIssue(code="FORMAL_OUTPUT_EMPTY", severity="ERROR",
                                        message="empty")))
        self.assertFalse(is_structural_blocker(
            reliability.ValidationIssue(code="UNSUPPORTED_CONFIRMED_RELATION", severity="ERROR",
                                        message="eligibility")))
        self.assertFalse(is_structural_blocker(
            reliability.ValidationIssue(code="V0001_DESCRIPTION_MISSING", severity="WARNING",
                                        message="quality")))
        self.assertFalse(is_structural_blocker(
            {"code": "CROSS_ENTITY_EVIDENCE", "severity": "ERROR", "message": "auto-fixed"}))
        self.assertTrue(is_structural_blocker(
            {"code": "DUPLICATE_RELATION_DECISION_ID", "severity": "ERROR",
             "message": "structural"}))

    def test_stage_and_finalize_only_fail_on_structural_blockers(self):
        state = {
            "tables": ["orders"],
            "relationDecisions": [
                relation("R_NO_EVIDENCE", evidence_types=[]),
                relation("R_MN", evidence_types=["FOREIGN_KEY"], cardinality="M:N"),
                relation("R_TRANSFORM", relation_type=TRANSFORMATION,
                         evidence_types=["FOREIGN_KEY"], cardinality="1:N"),
            ],
        }
        # The M:N relation keeps its relation entity marker in the audit.
        state["relationDecisions"][1]["needsRelationEntity"] = True
        with tempfile.TemporaryDirectory() as root:
            result = finalize_semantic_model(Path(root) / "work", state)
            self.assertEqual(result["status"], "PASSED")
            # Every downgraded relation stays in the audit as CANDIDATE (or a
            # reclassified REFERENCE for FK-backed transformations).
            persisted = json.loads((Path(root) / "work" / "modeling_state.json")
                                   .read_text(encoding="utf-8"))
            by_id = {item["relationId"]: item for item in persisted["relationDecisions"]}
            self.assertEqual(by_id["R_NO_EVIDENCE"]["status"], CANDIDATE)
            self.assertEqual(by_id["R_MN"]["status"], CANDIDATE)
            self.assertEqual(by_id["R_TRANSFORM"]["relationType"], REFERENCE)


class EvidenceIsolationTests(unittest.TestCase):
    def test_cross_entity_evidence_removed_and_decision_recomputed(self):
        state = {"businessObjectDecisions": [bo_candidate("CO1")]}
        record = state["businessObjectDecisions"][0]
        record["memberEntityIds"] = ["LE001", "LE002"]
        record["r1"] = {"status": "PASS", "evidence": [
            {"type": "SAMPLE_DATA", "subjectId": "LE001"},
            {"type": "TABLE_NAME", "subjectId": "LE999"},
        ]}
        removed = apply_evidence_isolation_cleanup(state)
        self.assertEqual(removed, 1)
        evidence = record["r1"]["evidence"]
        self.assertEqual([item["subjectId"] for item in evidence], ["LE001"])
        self.assertNotIn("CROSS_ENTITY_EVIDENCE",
                         {issue.code for issue in semantic_validation_issues(state)})
        # Second pass is a no-op (idempotent).
        self.assertEqual(apply_evidence_isolation_cleanup(state), 0)

    def test_circular_evidence_removed_and_decision_recomputed(self):
        state = {"businessObjectDecisions": [bo_candidate(
            "CO1", member_ids=("LE001",))]}
        record = state["businessObjectDecisions"][0]
        record["r1"] = {"status": "PASS", "evidence": [
            {"type": "SAMPLE_DATA", "subjectId": "LE001"},
            {"type": "DERIVED_CLAIM", "subjectId": "LE001", "derivedClaim": True},
        ]}
        self.assertEqual(apply_evidence_isolation_cleanup(state), 1)
        evidence = record["r1"]["evidence"]
        self.assertEqual([item["type"] for item in evidence], ["SAMPLE_DATA"])
        self.assertNotIn("CIRCULAR_EVIDENCE",
                         {issue.code for issue in semantic_validation_issues(state)})


class BusinessObjectNormalizationTests(unittest.TestCase):
    def test_invalid_confidence_becomes_unknown(self):
        state = {"businessObjectDecisions": [bo_candidate("CO1", confidence="八十分")]}
        self.assertEqual(apply_business_object_normalization(state)["normalized"], 1)
        self.assertEqual(state["businessObjectDecisions"][0]["confidence"], "UNKNOWN")
        self.assertNotIn("INVALID_BUSINESS_OBJECT_CONFIDENCE",
                         {issue.code for issue in validate_business_object_decisions(state)})

    def test_numeric_confidence_is_normalized(self):
        state = {"businessObjectDecisions": [bo_candidate("CO1", confidence="0.5")]}
        apply_business_object_normalization(state)
        self.assertEqual(state["businessObjectDecisions"][0]["confidence"], "50%")

    def test_decision_count_mismatch_is_recomputed(self):
        state = {
            "businessObjectDecisions": [
                bo_candidate("CO1"),
                bo_candidate("CO2", statuses=("PASS", "PASS", "PASS", "UNKNOWN", "PASS")),
            ],
            "businessObjectDecisionSummary": {"CONFIRMED": 5, "CANDIDATE": 0, "REJECTED": 0},
        }
        apply_decision_summary_recompute(state)
        self.assertEqual(state["businessObjectDecisionSummary"],
                         {"CONFIRMED": 1, "CANDIDATE": 1, "REJECTED": 0})
        self.assertNotIn("BUSINESS_OBJECT_DECISION_COUNT_MISMATCH",
                         {issue.code for issue in validate_business_object_decisions(state)})

    def test_reported_decision_mismatch_recomputed_from_rules(self):
        state = {"businessObjectDecisions": [bo_candidate(
            "CO1", statuses=("PASS", "PASS", "PASS", "UNKNOWN", "PASS"),
            finalDecision="CONFIRMED")]}
        apply_business_object_normalization(state)
        self.assertEqual(state["businessObjectDecisions"][0]["finalDecision"], CANDIDATE)
        self.assertNotIn("BUSINESS_OBJECT_DECISION_MISMATCH",
                         {issue.code for issue in validate_business_object_decisions(state)})

    def test_confirmed_bo_without_unique_main_entity_downgrades(self):
        state = {
            "entities": [
                {"entityId": "LE001", "businessObjectCode": "CO1", "isMain": "Y"},
                {"entityId": "LE002", "businessObjectCode": "CO1", "isMain": "Y"},
            ],
            "businessObjectDecisions": [bo_candidate("CO1", memberEntityIds=["LE001", "LE002"])],
        }
        self.assertEqual(apply_business_object_normalization(state)["downgraded"], 1)
        record = business_object_decision_records(state)[0]
        self.assertEqual(record.decision, CANDIDATE)
        self.assertTrue(record.eligibility_downgraded)
        self.assertNotIn("BUSINESS_OBJECT_DECISION_MISMATCH",
                         {issue.code for issue in validate_business_object_decisions(state)})

    def test_logical_key_is_never_guessed(self):
        state = {"businessAttributes": [
            {"attributeId": "A1", "code": "ID", "logicalEntityCode": "LE001",
             "isPhysicalKey": "Y", "isLogicalKey": ""},
        ]}
        normalize_modeling_state(state)
        # No keySemantics/是否逻辑主键 was invented by the server.
        self.assertEqual(state["businessAttributes"][0].get("isLogicalKey", ""), "")
        self.assertIsNone(state["businessAttributes"][0].get("keySemantics"))


class RelationEligibilityTests(unittest.TestCase):
    def test_confirmed_relation_without_evidence_downgrades(self):
        state = {"relationDecisions": [relation("R1", evidence_types=[])]}
        self.assertEqual(apply_relation_eligibility_downgrades(state), ["R1"])
        self.assertEqual(state["relationDecisions"][0]["status"], CANDIDATE)
        self.assertNotIn("UNSUPPORTED_CONFIRMED_RELATION",
                         {issue.code for issue in semantic_validation_issues(state)})

    def test_transformation_without_evidence_downgrades(self):
        state = {"relationDecisions": [
            relation("T1", relation_type=TRANSFORMATION, evidence_types=["FOREIGN_KEY"]),
            relation("T2", relation_type=TRANSFORMATION, evidence_types=[]),
        ]}
        apply_relation_eligibility_downgrades(state)
        by_id = {item["relationId"]: item for item in state["relationDecisions"]}
        self.assertEqual(by_id["T1"]["relationType"], REFERENCE)
        self.assertEqual(by_id["T2"]["status"], CANDIDATE)
        self.assertNotIn("TRANSFORMATION_EVIDENCE_GATE",
                         {issue.code for issue in semantic_validation_issues(state)})

    def test_unknown_cardinality_never_formal(self):
        state = {"relationDecisions": [relation("R1", evidence_types=["FOREIGN_KEY"],
                                                cardinality="")]}
        apply_relation_eligibility_downgrades(state)
        self.assertEqual(state["relationDecisions"][0]["status"], CANDIDATE)

    def test_many_to_many_kept_as_candidate_with_relation_entity_marker(self):
        state = {"relationDecisions": [relation("R1", evidence_types=["FOREIGN_KEY"],
                                                cardinality="M:N")]}
        apply_relation_eligibility_downgrades(state)
        record = state["relationDecisions"][0]
        self.assertEqual(record["status"], CANDIDATE)
        self.assertTrue(record.get("needsRelationEntity"))


class CoverageNormalizationTests(unittest.TestCase):
    def test_fk_coverage_auto_unresolved(self):
        state = {"declaredForeignKeys": [
            {"sourceEntity": "A", "targetEntity": "B"},
            {"sourceEntity": "C", "targetEntity": "D", "disposition": "TECHNICAL"},
        ]}
        self.assertEqual(apply_fk_coverage_defaults(state), 1)
        self.assertEqual(state["declaredForeignKeys"][0]["disposition"], "UNRESOLVED")
        self.assertNotIn("FK_COVERAGE_MISSING",
                         {issue.code for issue in validate_fk_coverage(state)})

    def test_mapping_exact_duplicate_removed_conflict_kept(self):
        state = {"mappingDefinitions": [
            {"key": "M1", "businessObjectCode": "BO1", "x": 1},
            {"key": "M1", "businessObjectCode": "BO1", "x": 1},
            {"key": "M1", "businessObjectCode": "BO1", "x": 2},
        ]}
        self.assertEqual(apply_mapping_dedup(state), 1)
        self.assertEqual(len(state["mappingDefinitions"]), 2)
        # Conflicting definitions under the same key still produce a
        # structural ERROR in the validator.
        issues = semantic_validation_issues(state)
        self.assertIn("DUPLICATE_MAPPING_DEFINITION", {issue.code for issue in issues})
        self.assertTrue(all(is_structural_blocker(issue) for issue in issues
                            if issue.code == "DUPLICATE_MAPPING_DEFINITION"))

    def test_audit_coverage_rebuilt_from_canonical_state(self):
        state = {"businessObjectDecisions": [bo_candidate("CO1")]}
        with tempfile.TemporaryDirectory() as root:
            work = Path(root) / "work"
            result = finalize_semantic_model(work, state)
            self.assertEqual(result["status"], "PASSED")
            self.assertNotIn("DECISION_AUDIT_COVERAGE",
                             {issue.code for issue in result["issues"]})
            # Delete an audit file; the next finalize rebuilds it instead of
            # failing the run on a coverage gap.
            (work / "relation_decisions.csv").unlink()
            result = finalize_semantic_model(work, load_modeling_state_or(work))
            self.assertEqual(result["status"], "PASSED")
            self.assertTrue((work / "relation_decisions.csv").is_file())


class TechnicalAttributeTests(unittest.TestCase):
    def test_explicit_technical_attribute_excluded(self):
        state = {"businessAttributes": [
            {"attributeId": "A1", "code": "ROW_ID", "logicalEntityCode": "LE001",
             "是否技术字段": "Y"},
        ]}
        self.assertEqual(apply_technical_attribute_exclusion(state), 1)
        record = state["businessAttributes"][0]
        self.assertEqual(record["formalStatus"], CANDIDATE)
        self.assertTrue(record.get("excludedFromFormal"))

    def test_logical_key_attribute_not_excluded_by_technical_marker(self):
        state = {"businessAttributes": [
            {"attributeId": "A1", "code": "ORDER_ID", "logicalEntityCode": "LE001",
             "是否技术字段": "Y", "isLogicalKey": "Y"},
        ]}
        self.assertEqual(apply_technical_attribute_exclusion(state), 0)
        self.assertNotIn("formalStatus", state["businessAttributes"][0])


class QualityWarningTests(unittest.TestCase):
    def test_empty_definition_is_a_structural_blocker(self):
        # A completely empty business-object definition is a deterministic
        # format error and must block, unlike weak-but-present definitions
        # which stay QUALITY_WARNING.
        state = {"businessObjectDecisions": [bo_candidate("CO1")]}
        blob = ("业务对象编码,业务对象名称,业务对象英文名,业务对象定义,数据类别\n"
                "CO1,确认对象,,,\n").encode("utf-8")
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "output"
            output.mkdir(parents=True, exist_ok=True)
            (output / "business_objects.csv").write_bytes(blob)
            result = finalize_semantic_model(
                Path(root) / "work", state, output_dir=output,
                required_outputs=["business_objects.csv"],
                context={"expectedFiles": ["business_objects.csv"], "taskType": "modeling"})
            self.assertEqual(result["status"], "FAILED")
            codes = {issue.code for issue in result["issues"]}
            self.assertIn("V0001_FORMAL_BUSINESS_OBJECT_DEFINITION_MISSING", codes)

    def test_weak_definition_stays_quality_warning(self):
        # A definition that is present but adds no information is a quality
        # WARNING and never consumes gate retries or blocks the run.
        state = {"businessObjectDecisions": [bo_candidate("CO1")]}
        blob = ("业务对象编码,业务对象名称,业务对象英文名,业务对象定义,数据类别\n"
                "CO1,确认对象,,确认对象,\n").encode("utf-8")
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "output"
            output.mkdir(parents=True, exist_ok=True)
            (output / "business_objects.csv").write_bytes(blob)
            result = finalize_semantic_model(
                Path(root) / "work", state, output_dir=output,
                required_outputs=["business_objects.csv"],
                context={"expectedFiles": ["business_objects.csv"], "taskType": "modeling"})
            self.assertEqual(result["status"], "PASSED")
            stage_codes = {code for row in result["stages"]
                           for code in (row.get("issueCodes") or [])}
            self.assertIn("V0001_DESCRIPTION_MISSING", stage_codes)

    def test_attribute_special_character_is_warning(self):
        state = {"businessAttributes": [
            {"attributeId": "A1", "属性编码": "A1", "业务属性编码": "A1",
             "属性名称": "金额&数量", "业务属性名称": "金额&数量",
             "逻辑实体编码": "LE001", "是否页面显示": "Y"},
        ]}
        blob = ("逻辑实体编码,业务属性编码,业务属性名称,是否页面显示\n"
                "LE001,A1,金额&数量,Y\n").encode("utf-8")
        with tempfile.TemporaryDirectory() as root:
            work = Path(root) / "work"
            output = Path(root) / "output"
            output.mkdir(parents=True, exist_ok=True)
            (output / "business_attributes.csv").write_bytes(blob)
            result = finalize_semantic_model(
                work, state, output_dir=output,
                required_outputs=["business_attributes.csv"],
                context={"expectedFiles": ["business_attributes.csv"], "taskType": "modeling"})
            self.assertEqual(result["status"], "PASSED")
            stage_codes = {code for row in result["stages"]
                           for code in (row.get("issueCodes") or [])}
            self.assertIn("V0001_ATTRIBUTE_SPECIAL_CHARACTER", stage_codes)


class StructuralBlockerTests(unittest.TestCase):
    def test_malformed_csv_still_fails(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "output"
            output.mkdir(parents=True, exist_ok=True)
            (output / "business_objects.csv").write_bytes(b"\xff\xfe broken")
            result = finalize_semantic_model(
                Path(root) / "work", {},
                output_dir=output, required_outputs=["business_objects.csv"],
                context={"expectedFiles": ["business_objects.csv"], "taskType": "modeling"})
            self.assertEqual(result["status"], "FAILED")
            self.assertIn("FORMAL_OUTPUT_INVALID_SCHEMA",
                          {issue.code for issue in result["issues"]})

    def test_duplicate_code_still_fails(self):
        state = {"relationDecisions": [
            relation("R1", evidence_types=["FOREIGN_KEY"], cardinality="1:N"),
            relation("R1", evidence_types=["FOREIGN_KEY"], cardinality="1:N"),
        ]}
        with tempfile.TemporaryDirectory() as root:
            result = validate_modeling_stages(
                Path(root) / "work", Path(root) / "output", state,
                required_outputs=["business_objects.csv"])
            self.assertIn("DUPLICATE_RELATION_DECISION_ID",
                          {issue.code for issue in result["issues"]})
            stage = next(row for row in result["stages"]
                         if row["stage"] == "ENTITY_RELATIONS")
            self.assertEqual(stage["status"], "FAILED")


class GateRetryTests(unittest.TestCase):
    def test_non_structural_issues_never_consume_gate_retries(self):
        guard = oc_codex_server.ModelingExecutionGuard()
        checkpoint = {"issues": [
            reliability.ValidationIssue(code="UNSUPPORTED_CONFIRMED_RELATION",
                                        severity="ERROR", message="eligibility"),
            reliability.ValidationIssue(code="ASSET_PROCESSING_COVERAGE_MISSING",
                                        severity="WARNING", message="auto-unknown"),
        ]}
        self.assertEqual(guard.observe_gate(checkpoint, "sig-a"), "")
        self.assertEqual(guard.observe_gate(checkpoint, "sig-a"), "")
        self.assertEqual(guard.gate_retries, 0)

    def test_same_semantic_issue_never_triggers_repeated_safety_valve(self):
        guard = oc_codex_server.ModelingExecutionGuard()
        semantic_only = {"issues": [
            reliability.ValidationIssue(code="UNSUPPORTED_CONFIRMED_RELATION",
                                        severity="ERROR", message="eligibility"),
        ]}
        # Two identical observations with no new evidence: the guard treats
        # this as nothing-to-repair rather than a repeated structural blocker.
        self.assertEqual(guard.observe_gate(semantic_only, "same-evidence"), "")
        self.assertEqual(guard.observe_gate(semantic_only, "same-evidence"), "")
        self.assertEqual(guard.gate_retries, 0)

    def test_structural_blockers_still_hit_repeated_safety_valve(self):
        guard = oc_codex_server.ModelingExecutionGuard()
        structural = {"issues": [
            reliability.ValidationIssue(code="FORMAL_OUTPUT_EMPTY", severity="ERROR",
                                        message="empty"),
        ]}
        self.assertEqual(guard.observe_gate(structural, "same-evidence"), "")
        self.assertEqual(guard.observe_gate(structural, "same-evidence"),
                         "MODEL_GATE_REPEATED_WITHOUT_NEW_EVIDENCE")
        self.assertEqual(guard.gate_retries, 1)

    def test_gate_signature_ignores_non_structural_issues(self):
        checkpoint = {"issues": [
            reliability.ValidationIssue(code="UNSUPPORTED_CONFIRMED_RELATION",
                                        severity="ERROR", message="eligibility"),
            reliability.ValidationIssue(code="FORMAL_OUTPUT_EMPTY", severity="ERROR",
                                        message="empty"),
        ]}
        self.assertEqual(
            oc_codex_server._modeling_gate_signature(checkpoint),
            oc_codex_server._modeling_gate_signature(
                {"issues": [reliability.ValidationIssue(
                    code="FORMAL_OUTPUT_EMPTY", severity="ERROR", message="empty")]}))


class CacheTests(unittest.TestCase):
    def test_stale_failed_cache_does_not_block_normalized_state(self):
        state = {
            "tables": ["orders"],
            "validationStages": {
                "ASSET_INVENTORY": {
                    "status": "FAILED",
                    "signature": "stale-failed-signature",
                    "issues": [],
                },
            },
        }
        with tempfile.TemporaryDirectory() as root:
            result = validate_modeling_stages(
                Path(root) / "work", Path(root) / "output", state,
                required_outputs=["business_objects.csv"])
            stage = next(row for row in result["stages"]
                         if row["stage"] == "ASSET_INVENTORY")
            self.assertEqual(stage["status"], "PASSED")
            self.assertNotIn("cached", stage)

    def test_normalization_changes_stage_signature(self):
        with tempfile.TemporaryDirectory() as root:
            work = Path(root) / "work"
            output = Path(root) / "output"
            work.mkdir(parents=True)
            output.mkdir(parents=True)
            raw = {"tables": ["orders"]}
            normalized = {"tables": ["orders"]}
            normalize_modeling_state(normalized)
            raw_sig = reliability._stage_signature(
                "ASSET_INVENTORY", work, output, raw, ["business_objects.csv"])
            norm_sig = reliability._stage_signature(
                "ASSET_INVENTORY", work, output, normalized, ["business_objects.csv"])
            self.assertNotEqual(raw_sig, norm_sig)


def load_modeling_state_or(work_dir):
    from open_claude.modeling_reliability import load_modeling_state
    return load_modeling_state(work_dir) or {}


if __name__ == "__main__":
    unittest.main()
