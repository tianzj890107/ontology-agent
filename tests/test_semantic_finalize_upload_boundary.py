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
from open_claude.modeling_reliability import (  # noqa: E402
    finalize_semantic_model,
    load_validation_report,
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

            # A missing audit after finalize is a hard failure, not an upload-
            # time repair that silently recreates the missing decision ledger.
            (work / "business_object_decisions.csv").unlink()
            failed = finalize_semantic_model(
                work, state, output_dir=output,
                required_outputs=["business_objects.csv"],
            )
            self.assertEqual(failed["status"], "FAILED")
            self.assertFalse((work / "business_object_decisions.csv").exists())
            self.assertIn("MISSING_DECISION_AUDIT",
                          {issue.code for issue in failed["issues"]})

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
