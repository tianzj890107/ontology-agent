import csv
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

from open_claude.modeling_reliability import (  # noqa: E402
    CANDIDATE,
    COMPOSITION,
    CONFIRMED,
    DECISION_AUDIT_HEADERS,
    REFERENCE,
    REJECTED,
    UNRESOLVED,
    apply_aggregation_downgrades,
    aggregation_components,
    business_object_decision_records,
    decision_audit_coverage,
    semantic_validation_issues,
    validate_decision_audits,
    validate_formal_business_rule_csv,
    validate_fk_coverage,
    validate_uncertainty_preservation,
    write_decision_audits,
)


def bo(code, statuses, *, evidence=True, unknown_reason="待补充独立证据"):
    record = {"candidateCode": code, "candidateName": code, "memberEntityIds": ["LE_1"],
              "confidence": "90"}
    for name, status in zip(("r1", "r2", "r3", "r4", "r5"), statuses):
        record[name] = {"status": status, "evidence": "直接来源" if evidence else ""}
        if status == "UNKNOWN":
            record[name]["unknownReason"] = unknown_reason
    return record


def read_rows(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class PipelineDecisionAuditTests(unittest.TestCase):
    def test_all_decision_audits_are_forced_and_covered(self):
        state = {
            "businessObjectDecisions": [
                bo("CO1", ["PASS"] * 5),
                bo("CO2", ["PASS", "PASS", "PASS", "UNKNOWN", "PASS"]),
                bo("CO3", ["PASS", "FAIL", "PASS", "PASS", "PASS"]),
            ],
            "relationDecisions": [{
                "relationId": "REL1", "sourceEntity": "LE1", "targetEntity": "LE2",
                "relationType": "REFERENCE", "status": CANDIDATE,
                "evidenceTypes": ["FOREIGN_KEY"], "evidenceLevel": "STRONG",
            }],
            "ruleDecisions": [{"ruleId": "R1", "ruleType": "ALERT_DETECTION_RULE",
                               "sampleCount": 104, "hitCount": 46}],
            "indicatorDecisions": [{"indicatorId": "M1", "name": "转化率",
                                    "status": CANDIDATE}],
            "entities": [{"entityId": "LE1", "role": "UNCLASSIFIED_ENTITY",
                          "businessObjectAssignmentStatus": "UNRESOLVED",
                          "missingEvidence": "未确认归属"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            paths = write_decision_audits(directory, state)
            self.assertEqual(set(paths), {
                "all_attributes.csv",
                "business_object_decisions.csv", "relation_decisions.csv",
                "rule_decisions.csv", "indicator_decisions.csv",
                "logical_entity_decisions.csv",
                "validation_report.json", "modeling_state.json",
            })
            self.assertFalse((Path(directory) / "pending_confirmations.csv").exists())
            self.assertEqual(validate_decision_audits(directory, state), [])
            self.assertTrue(decision_audit_coverage(directory, state)["complete"])
            for filename, expected_header in DECISION_AUDIT_HEADERS.items():
                with open(Path(directory) / filename, encoding="utf-8-sig", newline="") as handle:
                    self.assertEqual(next(csv.reader(handle)), list(expected_header))
            with open(Path(directory) / "business_object_decisions.csv",
                      encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual({row["最终决策"] for row in rows}, {CONFIRMED, CANDIDATE, REJECTED})
            self.assertEqual(len(rows), 3)

    def test_missing_audit_file_is_error(self):
        with tempfile.TemporaryDirectory() as directory:
            state = {"businessObjectDecisions": [bo("CO1", ["PASS"] * 5)]}
            write_decision_audits(directory, state)
            (Path(directory) / "relation_decisions.csv").unlink()
            self.assertIn("MISSING_DECISION_AUDIT",
                          {issue.code for issue in validate_decision_audits(directory, state)})

    def test_unresolved_logical_entity_is_not_assigned(self):
        state = {"entities": [{"entityId": "LE_ANALYTICAL", "role": "DERIVED_ANALYTICAL_ENTITY",
                               "businessObjectAssignmentStatus": "UNRESOLVED",
                               "missingEvidence": "没有唯一业务对象来源"}]}
        self.assertFalse(any(issue.code == "INVALID_BUSINESS_OBJECT_ASSIGNMENT"
                             for issue in semantic_validation_issues(state)))
        with tempfile.TemporaryDirectory() as directory:
            write_decision_audits(directory, state)
            rows = read_rows(Path(directory) / "logical_entity_decisions.csv")
            self.assertEqual(rows[0]["业务对象编码"], "")
            self.assertEqual(rows[0]["业务对象归属状态"], "UNRESOLVED")

    def test_fk_does_not_upgrade_composition_or_transformation(self):
        state = {"relationDecisions": [
            {"relationId": "C1", "sourceEntity": "D", "targetEntity": "A",
             "relationType": "COMPOSITION", "status": CONFIRMED,
             "evidenceTypes": ["FOREIGN_KEY"], "evidenceLevel": "STRONG",
             "provenance": ["schema.sql"]},
            {"relationId": "T1", "sourceEntity": "A", "targetEntity": "B",
             "relationType": "TRANSFORMATION", "status": CONFIRMED,
             "evidenceTypes": ["FOREIGN_KEY"], "evidenceLevel": "STRONG",
             "provenance": ["schema.sql"]},
        ]}
        codes = {issue.code for issue in semantic_validation_issues(state)}
        self.assertIn("INVALID_AGGREGATION_EDGE", codes)
        self.assertIn("TRANSFORMATION_EVIDENCE_GATE", codes)
        issue = next(item for item in semantic_validation_issues(state)
                     if item.code == "INVALID_AGGREGATION_EDGE")
        self.assertEqual(issue.severity, "WARNING")

    def test_weak_composition_auto_downgrades_to_reference(self):
        state = {
            "entities": [
                {"entityId": "D", "role": "DEPENDENT_ENTITY"},
                {"entityId": "A", "role": "MAIN_ENTITY"},
            ],
            "relationDecisions": [
                {"relationId": "C1", "sourceEntity": "D", "targetEntity": "A",
                 "relationType": COMPOSITION, "status": CONFIRMED,
                 "evidenceTypes": ["FOREIGN_KEY"], "evidenceLevel": "STRONG",
                 "provenance": ["schema.sql"]},
            ],
        }
        self.assertEqual(apply_aggregation_downgrades(state), ["C1"])
        self.assertEqual(apply_aggregation_downgrades(state), [])
        record = state["relationDecisions"][0]
        self.assertEqual(record["relationType"], REFERENCE)
        self.assertEqual(record["downgradedFrom"], COMPOSITION)
        codes = {issue.code for issue in semantic_validation_issues(state)}
        self.assertIn("INVALID_AGGREGATION_EDGE", codes)
        issue = next(item for item in semantic_validation_issues(state)
                     if item.code == "INVALID_AGGREGATION_EDGE")
        self.assertEqual(issue.severity, "WARNING")
        self.assertEqual(issue.details["downgradedTo"], REFERENCE)
        self.assertTrue(issue.details["autoResolved"])
        self.assertFalse(any("C1" in component.relation_ids
                             for component in aggregation_components(state)))

    def test_weak_composition_alone_never_blocks_final_gate(self):
        state = {
            "entities": [
                {"entityId": "D", "role": "DEPENDENT_ENTITY"},
                {"entityId": "A", "role": "MAIN_ENTITY"},
            ],
            "relationDecisions": [
                {"relationId": "C1", "sourceEntity": "D", "targetEntity": "A",
                 "relationType": COMPOSITION, "status": CONFIRMED,
                 "evidenceTypes": ["FOREIGN_KEY"], "evidenceLevel": "STRONG",
                 "provenance": ["schema.sql"]},
            ],
        }
        with tempfile.TemporaryDirectory() as root:
            from open_claude.modeling_reliability import finalize_semantic_model
            result = finalize_semantic_model(Path(root) / "mission-work", state)
            self.assertEqual(result["status"], "PASSED")
            codes = {issue.code for issue in result["issues"]}
            self.assertIn("INVALID_AGGREGATION_EDGE", codes)
            self.assertFalse(any(issue.severity == "ERROR" for issue in result["issues"]))

    def test_view_filter_rule_with_direct_implementation_evidence_is_formal(self):
        state = {"ruleDecisions": [{
            "ruleId": "R_VIEW_FILTER",
            "ruleType": "ALERT_DETECTION_RULE",
            "evidenceTypes": ["VIEW_FILTER_LOGIC"],
            "provenance": ["mission-input/report.sql"],
            "sampleCount": 104,
            "hitCount": 46,
        }]}
        blob = "规则编码,规则名称\nR_VIEW_FILTER,库存预警\n".encode("utf-8")
        self.assertEqual(validate_formal_business_rule_csv(blob, state), [])

    def test_view_join_is_not_lineage(self):
        state = {"relationDecisions": [{
            "relationId": "T_JOIN", "sourceEntity": "A", "targetEntity": "B",
            "relationType": "TRANSFORMATION", "status": CONFIRMED,
            "evidenceTypes": ["VIEW_JOIN_EVIDENCE"], "evidenceLevel": "STRONG",
            "provenance": ["view.sql"],
        }]}
        self.assertIn("TRANSFORMATION_EVIDENCE_GATE",
                      {issue.code for issue in semantic_validation_issues(state)})

    def test_observed_zero_violation_rule_is_output_with_warning(self):
        state = {"ruleDecisions": [{"ruleId": "R_OBS", "ruleType": "INTEGRITY_CONSTRAINT",
                                    "sampleCount": 100, "violationCount": 0}]}
        blob = "规则编码,规则名称\nR_OBS,唯一性\n".encode()
        issues = validate_formal_business_rule_csv(blob, state)
        self.assertIn("UNCONFIRMED_RULE_IN_FORMAL_OUTPUT",
                      {issue.code for issue in issues if issue.severity == "WARNING"})
        self.assertEqual([issue.code for issue in issues if issue.severity == "ERROR"], [])

    def test_observed_pattern_confirmed_unknown_enforcement_is_formal(self):
        state = {"ruleDecisions": [{
            "ruleId": "R_PATTERN", "ruleType": "INTEGRITY_CONSTRAINT",
            "decision": CONFIRMED, "enforcement": "UNKNOWN",
            "evidenceTypes": ["OBSERVED_PATTERN"], "provenance": ["profile.sql"],
            "sampleCount": 1000, "violationCount": 0,
        }]}
        blob = "规则编码,规则名称\nR_PATTERN,唯一性模式\n".encode()
        self.assertEqual(validate_formal_business_rule_csv(blob, state), [])

    def test_confirmed_without_existence_evidence_is_warning_not_blocked(self):
        state = {"ruleDecisions": [{
            "ruleId": "R_NO_EVIDENCE", "ruleType": "INTEGRITY_CONSTRAINT",
            "decision": CONFIRMED, "enforcement": "ENFORCED",
        }]}
        blob = "规则编码,规则名称\nR_NO_EVIDENCE,无证据规则\n".encode()
        issues = validate_formal_business_rule_csv(blob, state)
        self.assertIn("UNCONFIRMED_RULE_IN_FORMAL_OUTPUT",
                      {issue.code for issue in issues if issue.severity == "WARNING"})
        self.assertEqual([issue.code for issue in issues if issue.severity == "ERROR"], [])

    def test_weak_rule_evidence_does_not_trigger_blocking_issues(self):
        state = {"ruleDecisions": [
            {"ruleId": "R_SOFT_1", "ruleType": "INTEGRITY_CONSTRAINT",
             "decision": CONFIRMED, "enforcement": "ENFORCED",
             "evidenceTypes": ["OBSERVED_PATTERN"], "provenance": ["profile.sql"],
             "sampleCount": 100, "violationCount": 0},
            {"ruleId": "R_SOFT_2", "ruleType": "CALCULATION_RULE",
             "decision": CONFIRMED, "enforcement": "UNKNOWN",
             "validationStatus": "VALIDATED",
             "evidenceTypes": ["OBSERVED_PATTERN"], "provenance": ["profile.sql"]},
        ]}
        issues = semantic_validation_issues(state)
        blocking = [issue for issue in issues if issue.severity == "ERROR"
                    and issue.artifact_type == "BUSINESS_RULE"]
        self.assertEqual(blocking, [])

    def test_weak_indicator_evidence_is_output_with_warning_only(self):
        from open_claude.modeling_reliability import validate_formal_indicator_csv
        state = {"indicatorDecisions": [
            {"indicatorId": "M_SOFT", "name": "转化率", "status": CANDIDATE,
             "aggregationSemantics": "UNKNOWN"},
            {"indicatorId": "M_OK", "name": "金额", "status": CONFIRMED,
             "aggregationSemantics": "SUM"},
        ]}
        blob = "指标编码,指标名称\nM_SOFT,转化率\nM_OK,金额\n".encode()
        issues = validate_formal_indicator_csv(blob, state)
        self.assertEqual([issue.code for issue in issues if issue.severity == "ERROR"], [])
        self.assertIn("UNSUPPORTED_FORMAL_INDICATOR",
                      {issue.code for issue in issues if issue.severity == "WARNING"})

    def test_claimed_enforced_without_evidence_is_downgraded(self):
        state = {"ruleDecisions": [{
            "ruleId": "R_CLAIMED", "ruleType": "INTEGRITY_CONSTRAINT",
            "decision": CONFIRMED, "enforcement": "ENFORCED",
            "evidenceTypes": ["OBSERVED_PATTERN"], "provenance": ["profile.sql"],
            "sampleCount": 100, "violationCount": 0,
        }]}
        with tempfile.TemporaryDirectory() as directory:
            write_decision_audits(directory, state)
            rows = read_rows(Path(directory) / "rule_decisions.csv")
        self.assertEqual(rows[0]["存在状态"], "OBSERVED_ONLY")
        self.assertIn(rows[0]["强制状态"], {"UNKNOWN", "NOT_ENFORCED"})
        self.assertNotEqual(rows[0]["强制状态"], "ENFORCED")

    def test_explicit_not_enforced_is_preserved_in_audit(self):
        state = {"ruleDecisions": [{
            "ruleId": "R_NE", "ruleType": "INTEGRITY_CONSTRAINT",
            "decision": CONFIRMED, "enforcement": "NOT_ENFORCED",
            "evidenceTypes": ["OBSERVED_PATTERN"], "provenance": ["profile.sql"],
            "sampleCount": 100, "violationCount": 0,
        }]}
        with tempfile.TemporaryDirectory() as directory:
            write_decision_audits(directory, state)
            rows = read_rows(Path(directory) / "rule_decisions.csv")
        self.assertEqual(rows[0]["强制状态"], "NOT_ENFORCED")

    def test_alert_hit_rate_does_not_mean_effectiveness(self):
        state = {"ruleDecisions": [{"ruleId": "R_ALERT", "ruleType": "ALERT_DETECTION_RULE",
                                    "sampleCount": 104, "hitCount": 46}]}
        with tempfile.TemporaryDirectory() as directory:
            write_decision_audits(directory, state)
            rows = read_rows(Path(directory) / "rule_decisions.csv")
        self.assertEqual(rows[0]["命中数量"], "46")
        self.assertEqual(rows[0]["有效性状态"], "UNKNOWN")
        self.assertEqual(rows[0]["处置状态"], "UNKNOWN")

    def test_ratio_metric_without_semantics_is_not_confirmed(self):
        state = {"indicatorDecisions": [{"indicatorId": "M_RATIO", "name": "转化率",
                                          "status": CONFIRMED, "formulaStatus": "CONFIRMED"}]}
        self.assertIn("METRIC_AGGREGATION_SEMANTICS_UNKNOWN",
                      {issue.code for issue in semantic_validation_issues(state)})

    def test_relation_identity_keeps_same_endpoints_separate(self):
        state = {"relationDecisions": [
            {"sourceEntity": "A", "targetEntity": "B", "relationType": "REFERENCE"},
            {"sourceEntity": "A", "targetEntity": "B", "relationType": "TRANSFORMATION"},
        ]}
        with tempfile.TemporaryDirectory() as directory:
            write_decision_audits(directory, state)
            rows = read_rows(Path(directory) / "relation_decisions.csv")
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["关系决策编码"], rows[1]["关系决策编码"])

    def test_audit_csv_omits_removed_columns(self):
        state = {
            "ruleDecisions": [{"ruleId": "R1", "sampleCount": 1}],
            "indicatorDecisions": [{"indicatorId": "M1", "grain": "row",
                                     "evidenceIds": ["E1"]}],
        }
        with tempfile.TemporaryDirectory() as directory:
            write_decision_audits(directory, state)
            for filename in DECISION_AUDIT_HEADERS:
                with open(Path(directory) / filename, encoding="utf-8-sig", newline="") as handle:
                    header = next(csv.reader(handle))
                self.assertNotIn("evidence_ids", header)
                self.assertNotIn("missing_evidence", header)
                self.assertNotIn("grain", header)

    def test_duplicate_explicit_relation_id_is_error(self):
        state = {"relationDecisions": [
            {"relationId": "R1", "sourceEntity": "A", "targetEntity": "B", "relationType": "REFERENCE"},
            {"relationId": "R1", "sourceEntity": "C", "targetEntity": "D", "relationType": "REFERENCE"},
        ]}
        self.assertIn("DUPLICATE_RELATION_DECISION_ID",
                      {issue.code for issue in semantic_validation_issues(state)})

    def test_fk_coverage_reports_unmapped_declaration(self):
        state = {"declaredForeignKeys": [{"id": "FK1", "sourceTable": "A", "targetTable": "B"}]}
        self.assertIn("FK_COVERAGE_MISSING", {issue.code for issue in validate_fk_coverage(state)})

    def test_unknown_to_confirmed_without_upgrade_evidence_is_error(self):
        state = {"relationDecisions": [{"relationId": "R1", "status": CONFIRMED,
                                        "previousStatus": UNRESOLVED}]}
        self.assertIn("UNSUPPORTED_STATUS_UPGRADE",
                      {issue.code for issue in validate_uncertainty_preservation(state)})

    def test_schema_requirement_does_not_create_relation(self):
        state = {"entities": [{"entityId": "LE_D", "role": "DERIVED_ANALYTICAL_ENTITY"}],
                 "relationDecisions": []}
        self.assertFalse(state["relationDecisions"])
        self.assertIn("MISSING_DERIVATION_LINEAGE",
                      {issue.code for issue in semantic_validation_issues(state)})

    def test_audit_writer_uses_standard_csv_quoting(self):
        state = {"businessObjectDecisions": [bo("CO,1", ["PASS"] * 5)]}
        state["businessObjectDecisions"][0]["candidateName"] = '含"引号\n换行'
        with tempfile.TemporaryDirectory() as directory:
            write_decision_audits(directory, state)
            rows = read_rows(Path(directory) / "business_object_decisions.csv")
        self.assertEqual(rows[0]["候选业务对象名称"], '含"引号\n换行')


if __name__ == "__main__":
    unittest.main()
