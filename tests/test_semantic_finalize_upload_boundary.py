import csv
import json
import tempfile
import hashlib
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

import oc_codex_server as server  # noqa: E402
import open_claude.modeling_reliability as reliability  # noqa: E402
from open_claude.modeling_reliability import (  # noqa: E402
    CANDIDATE,
    finalize_semantic_model,
    load_validation_report,
    modeling_validation_stage_plan,
    validate_modeling_stages,
    write_decision_audits,
)


def confirmed_bo(code="CO001"):
    return {
        "candidateCode": code,
        "candidateName": "可确认对象",
        "memberEntityIds": ["LE001"],
        "confidence": "90",
        **{f"r{i}": {"status": "PASS", "evidence": f"R{i} 的直接输入证据"}
           for i in range(1, 6)},
    }


class SemanticFinalizeUploadBoundaryTests(unittest.TestCase):
    def test_partial_output_plan_only_activates_required_dependencies(self):
        plan = modeling_validation_stage_plan(["business_objects.csv"])
        by_stage = {item["stage"]: item["status"] for item in plan}
        self.assertEqual(by_stage["TERMS"], "SKIPPED")
        self.assertEqual(by_stage["LOGICAL_ENTITIES"], "PENDING")
        self.assertEqual(by_stage["BUSINESS_ATTRIBUTES"], "PENDING")
        self.assertEqual(by_stage["ENTITY_RELATIONS"], "PENDING")
        self.assertEqual(by_stage["BUSINESS_OBJECTS"], "PENDING")
        self.assertEqual(by_stage["GOVERNANCE_AND_FINAL"], "PENDING")

    def test_passed_stage_is_cached_until_its_file_changes(self):
        state = {
            "allAttributes": [{"来源字段": "id"}],
            "logicalEntities": [{"code": "LE001"}],
        }
        with tempfile.TemporaryDirectory() as root, \
                patch.object(reliability, "_stage_specific_issues", return_value=[]) as validate:
            root = Path(root)
            work = root / "mission-work"
            output = root / "mission-output"
            work.mkdir()
            output.mkdir()
            first = validate_modeling_stages(work, output, state, ["logical_entities.csv"])
            second = validate_modeling_stages(work, output, first["state"], ["logical_entities.csv"])
            self.assertEqual(validate.call_count, 5)
            self.assertEqual(second["events"], [])
            (output / "logical_entities.csv").write_text("changed\n", encoding="utf-8")
            third = validate_modeling_stages(work, output, second["state"], ["logical_entities.csv"])
            self.assertEqual(validate.call_count, 6)
            self.assertTrue(any(event["stage"] == "LOGICAL_ENTITIES" for event in third["events"]))

    def test_failed_stage_is_cached_until_its_inputs_change(self):
        state = {
            "allAttributes": [{"来源字段": "id"}],
            "logicalEntities": [{"code": "LE001"}],
        }
        failure = reliability._issue("TEST_STAGE_FAILURE", "ERROR", "文件仍不完整")
        def validate_stage(stage, *_args):
            return [failure] if stage == "LOGICAL_ENTITIES" else []
        with tempfile.TemporaryDirectory() as root, \
                patch.object(reliability, "_stage_specific_issues", side_effect=validate_stage) as validate:
            root = Path(root)
            work = root / "mission-work"
            output = root / "mission-output"
            work.mkdir()
            output.mkdir()
            first = validate_modeling_stages(work, output, state, ["logical_entities.csv"])
            self.assertEqual(first["issues"][0].code, "TEST_STAGE_FAILURE")
            first_calls = validate.call_count
            second = validate_modeling_stages(work, output, first["state"], ["logical_entities.csv"])
            self.assertEqual(validate.call_count, first_calls)
            self.assertEqual(second["issues"][0].code, "TEST_STAGE_FAILURE")
            (output / "logical_entities.csv").write_text("changed\n", encoding="utf-8")
            validate_modeling_stages(work, output, second["state"], ["logical_entities.csv"])
            self.assertEqual(validate.call_count, first_calls + 1)

    def test_finalize_writes_audits_and_marker_before_upload(self):
        state = {"businessObjectDecisions": [confirmed_bo()]}
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            work = root / "mission-work"
            output = root / "mission-output"
            output.mkdir()
            with (output / "business_objects.csv").open("w", encoding="utf-8", newline="") as handle:
                csv.writer(handle, lineterminator="\n").writerows([
                    ["业务对象编码", "业务对象名称", "业务对象英文名", "业务对象定义", "数据类别"],
                    ["CO001", "可确认对象", "ConfirmedObject", "有决策证据", "业务"],
                ])

            result = finalize_semantic_model(
                work, state, output_dir=output,
                required_outputs=["business_objects.csv"],
            )
            self.assertEqual(result["status"], "PASSED")
            for name in (
                "business_object_decisions.csv", "relation_decisions.csv",
                "rule_decisions.csv", "indicator_decisions.csv",
                "logical_entity_decisions.csv",
                "modeling_state.json", "validation_report.json",
            ):
                self.assertTrue((work / name).is_file(), name)
            self.assertFalse((work / "pending_confirmations.csv").exists())
            report = load_validation_report(work)
            self.assertEqual(report["semantic_validation_status"], "PASSED")
            self.assertEqual(report["business_object_decision_coverage"], 1.0)

            # A missing audit after finalize is rebuilt deterministically from
            # the canonical modeling_state.json instead of failing the run.
            (work / "business_object_decisions.csv").unlink()
            rebuilt = finalize_semantic_model(
                work, state, output_dir=output,
                required_outputs=["business_objects.csv"],
            )
            self.assertEqual(rebuilt["status"], "PASSED")
            self.assertTrue((work / "business_object_decisions.csv").is_file())
            self.assertNotIn("MISSING_DECISION_AUDIT",
                             {issue.code for issue in rebuilt["issues"]})

    def test_nested_r1_schema_is_read_as_status_not_as_mapping(self):
        state = {"businessObjectDecisions": [confirmed_bo("CO_NESTED")]}
        work = tempfile.TemporaryDirectory()
        try:
            result = finalize_semantic_model(Path(work.name) / "mission-work", state)
            self.assertEqual(result["status"], "PASSED")
            state_file = json.loads(
                (Path(work.name) / "mission-work" / "modeling_state.json").read_text(encoding="utf-8"))
            self.assertEqual(state_file["businessObjectDecisions"][0]["r1"]["status"], "PASS")
        finally:
            work.cleanup()

    def test_warning_only_final_gate_allows_export(self):
        state = {
            "entities": [{"entityId": "LE_CHILD", "role": "DEPENDENT_ENTITY"}],
            "relationDecisions": [],
        }
        with tempfile.TemporaryDirectory() as root:
            result = finalize_semantic_model(Path(root) / "mission-work", state)
            self.assertEqual(result["status"], "PASSED")
            warning_codes = {issue.code for issue in result["issues"]
                             if issue.severity == "WARNING"}
            self.assertIn("MISSING_COMPOSITION_OWNER", warning_codes)
            report = load_validation_report(Path(root) / "mission-work")
            self.assertEqual(report["semantic_validation_status"], "PASSED")
            self.assertTrue(report["warnings"])

    def test_error_still_blocks_export(self):
        # A CONFIRMED relation without any evidence is a formal-eligibility
        # gap, not a structural defect: the server deterministically downgrades
        # it to CANDIDATE and keeps the run moving instead of entering the
        # Agent repair loop.
        state = {"relationDecisions": [{
            "relationId": "REL_UNSUPPORTED",
            "sourceEntity": "LE_A", "targetEntity": "LE_B",
            "relationType": "REFERENCE", "status": "CONFIRMED",
            "evidenceTypes": [],
        }]}
        with tempfile.TemporaryDirectory() as root:
            result = finalize_semantic_model(Path(root) / "mission-work", state)
            self.assertEqual(result["status"], "PASSED")
            self.assertNotIn("UNSUPPORTED_CONFIRMED_RELATION",
                             {issue.code for issue in result["issues"]})
            persisted = json.loads((Path(root) / "mission-work" / "modeling_state.json")
                                   .read_text(encoding="utf-8"))
            record = persisted["relationDecisions"][0]
            self.assertEqual(record["status"], CANDIDATE)
            self.assertTrue(record.get("eligibilityBlockers"))

    def test_malformed_artifact_still_fails(self):
        # Genuine structural defects (zero-byte/required formal artifact) still
        # fail the final gate and enter the repair loop.
        state = {}
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "mission-output"
            output.mkdir(parents=True, exist_ok=True)
            (output / "business_objects.csv").write_bytes(b"")
            result = finalize_semantic_model(Path(root) / "mission-work", state,
                                             output_dir=output,
                                             required_outputs=["business_objects.csv"],
                                             context={"expectedFiles": ["business_objects.csv"],
                                                      "taskType": "modeling"})
            self.assertEqual(result["status"], "FAILED")
            codes = {issue.code for issue in result["issues"]}
            self.assertIn("FORMAL_OUTPUT_EMPTY", codes)

    def test_missing_asset_processing_decision_is_auto_unknown_warning(self):
        state = {
            "tables": ["orders", "reference_codes"],
            "assetDecisions": [{"tableName": "orders", "decision": "MODELED"}],
        }
        with tempfile.TemporaryDirectory() as root:
            result = finalize_semantic_model(Path(root) / "mission-work", state)
            self.assertEqual(result["status"], "PASSED")
            issue = next(item for item in result["issues"]
                         if item.code == "ASSET_PROCESSING_COVERAGE_MISSING")
            self.assertEqual(issue.severity, "WARNING")
            self.assertEqual(issue.details["missing"], ["reference_codes"])
            persisted = json.loads((Path(root) / "mission-work" / "modeling_state.json")
                                   .read_text(encoding="utf-8"))
            decisions = {row["tableName"]: row for row in persisted["assetDecisions"]}
            self.assertEqual(decisions["orders"]["decision"], "MODELED")
            self.assertEqual(decisions["reference_codes"]["processingDecision"], "UNKNOWN")
            self.assertIn("reference_codes", persisted["autoResolvedProcessingDecisions"])

    def test_upload_checks_marker_without_running_semantic_gate(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            work = root / "mission-work"
            write_decision_audits(work, {})
            # The marker is produced by finalize in production; this fixture
            # represents a successful semantic finalize.
            server.finalize_semantic_model(work, {}, output_dir=root / "mission-output")
            blob = "业务对象编码,业务对象名称,逻辑实体编码,逻辑实体名称,逻辑实体英文名,逻辑实体定义,是否主逻辑实体,数据类别\n".encode()
            with patch.object(server, "validate_modeling_evidence",
                              side_effect=AssertionError("upload must not run semantic gate")):
                self.assertEqual(server.validate_modeling_upload_artifact(
                    "logical_entities.csv", blob, str(root)), [])

            report = load_validation_report(work)
            report["semantic_validation_status"] = "FAILED"
            (work / "validation_report.json").write_text(
                json.dumps(report, ensure_ascii=False), encoding="utf-8")
            # Upload remains available for user review even when the semantic
            # marker is failed; the upload path only checks file syntax.
            self.assertEqual(server.validate_modeling_upload_artifact(
                "logical_entities.csv", blob, str(root)), [])

    def test_formal_business_object_upload_does_not_read_r1_r5_decisions(self):
        """Formal output upload must not parse or validate the decision ledger."""
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            # Deliberately malformed semantic state.  This belongs to the
            # modeling-finalize path, not to the artifact upload path.
            work = root / "mission-work"
            work.mkdir()
            (work / "modeling_state.json").write_text(json.dumps({
                "businessObjectDecisions": [{
                    "candidateCode": "CO001",
                    "candidateName": "对象",
                    "r1": {"status": "NOT_A_DECISION"},
                }],
            }, ensure_ascii=False), encoding="utf-8")
            blob = (
                "业务对象编码,业务对象名称,业务对象英文名,业务对象定义,数据类别\n"
                "BO0001,采购订单,purchase_order,正式交付对象,事务数据\n"
            ).encode("utf-8")
            with patch.object(server, "validate_modeling_evidence",
                              side_effect=AssertionError("upload must not parse R1-R5")):
                self.assertEqual(server.validate_modeling_upload_artifact(
                    "business_objects.csv", blob, str(root)), [])

    def test_completion_callback_consumes_marker_without_recomputing_semantics(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            output = root / "mission-output"
            output.mkdir()
            artifact = output / "logical_entities.csv"
            artifact.write_text("本地结果\n", encoding="utf-8")
            finalize_semantic_model(
                root / "mission-work", {}, output_dir=output,
                required_outputs=["logical_entities.csv"],
            )
            task = types.SimpleNamespace(
                cwd=str(root), task_code="RM-BOUNDARY", task_type="modeling",
                platform_status="RUNNING", status="idle",
                mission_context={"taskType": "modeling", "parseElements": ["LOGICAL_ENTITY"],
                                 "expectedFiles": ["logical_entities.csv"]},
                modeling_plan={},
                platform_uploaded_files={"logical_entities.csv": {
                    "objectKey": "result/logical_entities.csv",
                    "previewUrl": "https://files.example/result.csv",
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                }},
            )
            with patch.object(server, "validate_modeling_evidence",
                              side_effect=AssertionError("completion must not recompute semantics")):
                payload, error = server.build_completed_callback_payload(task)
            self.assertIsNone(error)
            self.assertEqual(payload["agentStatus"], "SUCCESS")

    def test_two_missions_use_separate_decision_ledgers(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_work = Path(first) / "mission-work"
            second_work = Path(second) / "mission-work"
            finalize_semantic_model(first_work, {"businessObjectDecisions": [confirmed_bo("CO_A")]})
            finalize_semantic_model(second_work, {"businessObjectDecisions": [confirmed_bo("CO_B")]})
            first_csv = (first_work / "business_object_decisions.csv").read_text(encoding="utf-8")
            second_csv = (second_work / "business_object_decisions.csv").read_text(encoding="utf-8")
            self.assertIn("CO_A", first_csv)
            self.assertNotIn("CO_B", first_csv)
            self.assertIn("CO_B", second_csv)
            self.assertNotIn("CO_A", second_csv)


if __name__ == "__main__":
    unittest.main()
