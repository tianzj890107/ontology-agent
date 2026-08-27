"""Upload-gate / completion-gate separation tests for modeling CSV uploads.

Covers the two production misjudgements:
1. entity_relations.csv legacy header aliases (源关联属性编码/目标关联属性编码)
   were reported as a bare "期望16列，实际16列" mismatch even though the
   column count was correct.
2. logical_entities.csv rows with an empty business-object code were rejected
   by the upload gate when work/modeling_state.json had no audit assignment
   status, even though the file itself was internally consistent.

The upload gate must be deterministic, file-internal and structural-only;
audit/semantic checks belong to the completion gate.  This file also covers
the per-file stage/code contract of /api/minio/upload and the frontend
behaviour of always rendering per-file results.
"""
import csv
import hashlib
import io
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

import oc_codex_server as server  # noqa: E402
from open_claude.modeling_csv_contract import (  # noqa: E402
    CONTRACTS,
    HEADER_NORMALIZATION_VERSION,
    ValidationPhase,
    header_mismatch_messages,
    normalize_csv_blob,
    normalize_header_cell,
    validate_row_contract,
)
from open_claude.modeling_rule_registry import validate_formal_rows  # noqa: E402
from open_claude.modeling_reliability import semantic_validation_issues  # noqa: E402

ENTITY_RELATIONS_HEADER = list(CONTRACTS["entity_relations.csv"].headers)
LOGICAL_ENTITIES_HEADER = list(CONTRACTS["logical_entities.csv"].headers)
BO_HEADER = list(CONTRACTS["business_objects.csv"].headers)
BUSINESS_ATTRIBUTES_HEADER = list(CONTRACTS["business_attributes.csv"].headers)

_UNAVAILABLE = object()  # sentinel: fetch_execution_context must return None


def to_csv(header, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def relation_row():
    return ["REL0001", "LE0001", "采购订单实体", "LE0002", "客户实体", "关联", "属于",
            "belongs_to", "1:N", "采购订单属于客户", "", "", "", "", "", ""]


def logical_entity_row(bo_code="BO0001", bo_name="采购订单", le_code="LE0001",
                       main="Y", le_name=None, le_en=None):
    le_name = le_name or "采购订单实体"
    le_en = le_en or "purchase_order_entity"
    return [bo_code, bo_name, le_code, le_name, le_en,
            "采购订单业务实体定义", main, "事务数据"]


def attribute_row(le_code="LE0001", le_name="采购订单实体", attr_code="ATTR0001",
                  attr_name="订单金额", en="order_amount", dtype="小数",
                  length="18", precision="2", main_physical="N", main_logical="N",
                  unique="N", not_null="N", page_display="N", hier_code="N", hier_name="N"):
    return [le_code, le_name, attr_code, attr_name, en, "业务属性定义", dtype,
            length, precision, main_physical, main_logical, unique, not_null,
            page_display, hier_code, hier_name]


class HeaderNormalizationTests(unittest.TestCase):
    def test_canonical_16_column_header_passes(self):
        self.assertEqual(
            server.validate_modeling_upload_artifact(
                "entity_relations.csv", to_csv(ENTITY_RELATIONS_HEADER, [relation_row()]), ""),
            [])

    def test_legacy_source_and_target_attribute_aliases_pass(self):
        legacy = list(ENTITY_RELATIONS_HEADER)
        legacy[10] = "源关联属性编码"
        legacy[13] = "目标关联属性编码"
        self.assertEqual(
            server.validate_modeling_upload_artifact(
                "entity_relations.csv", to_csv(legacy, [relation_row()]), ""),
            [])

    def test_compatible_header_is_normalized_to_canonical(self):
        legacy = list(ENTITY_RELATIONS_HEADER)
        legacy[10] = "源关联属性编码"
        legacy[13] = "目标关联属性编码"
        blob = to_csv(legacy, [relation_row()])
        normalized, notes, changed = normalize_csv_blob("entity_relations.csv", blob)
        self.assertTrue(changed)
        parsed = list(csv.reader(io.StringIO(normalized.decode("utf-8"), newline="")))
        self.assertEqual(parsed[0][10], "源业务属性编码")
        self.assertEqual(parsed[0][13], "目标业务属性编码")
        self.assertIn("源关联属性编码", "".join(notes))

    def test_upload_blob_uses_normalized_header(self):
        legacy = list(ENTITY_RELATIONS_HEADER)
        legacy[10] = "源关联属性编码"
        blob = to_csv(legacy, [relation_row()])
        normalized, _code, errors = server.validate_modeling_upload_artifact_detailed(
            "entity_relations.csv", blob)
        self.assertEqual(errors, [])
        parsed = list(csv.reader(io.StringIO(normalized.decode("utf-8"), newline="")))
        self.assertEqual(parsed[0][10], "源业务属性编码")
        # Normalization is deterministic and the upload hash is the normalized
        # blob's hash, which differs from the original file whenever an alias
        # was applied.
        normalized_again, _code, _errors = server.validate_modeling_upload_artifact_detailed(
            "entity_relations.csv", blob)
        self.assertEqual(hashlib.sha256(normalized).hexdigest(),
                         hashlib.sha256(normalized_again).hexdigest())
        self.assertNotEqual(hashlib.sha256(normalized).hexdigest(),
                            hashlib.sha256(blob).hexdigest())

    def test_utf8_bom_is_handled(self):
        blob = b"\xef\xbb\xbf" + to_csv(ENTITY_RELATIONS_HEADER, [relation_row()])
        self.assertEqual(
            server.validate_modeling_upload_artifact("entity_relations.csv", blob, ""), [])

    def test_trailing_whitespace_in_header_cell_is_normalized(self):
        header = list(ENTITY_RELATIONS_HEADER)
        header[1] = "源逻辑实体编码 "
        blob = to_csv(header, [relation_row()])
        normalized, notes, changed = normalize_csv_blob("entity_relations.csv", blob)
        self.assertTrue(changed)
        parsed = list(csv.reader(io.StringIO(normalized.decode("utf-8"), newline="")))
        self.assertEqual(parsed[0][1], "源逻辑实体编码")

    def test_zero_width_space_in_header_cell_is_removed(self):
        header = list(ENTITY_RELATIONS_HEADER)
        header[5] = "关系分类\u200b"
        blob = to_csv(header, [relation_row()])
        normalized, _notes, changed = normalize_csv_blob("entity_relations.csv", blob)
        self.assertTrue(changed)
        parsed = list(csv.reader(io.StringIO(normalized.decode("utf-8"), newline="")))
        self.assertEqual(parsed[0][5], "关系分类")

    def test_same_count_unknown_field_still_fails_with_precise_diff(self):
        bad = list(ENTITY_RELATIONS_HEADER)
        bad[10] = "源属性代码"
        errors = server.validate_modeling_upload_artifact(
            "entity_relations.csv", to_csv(bad, [relation_row()]), "")
        self.assertTrue(errors)
        joined = "；".join(errors)
        self.assertIn("第 11 列", joined)
        self.assertIn("源业务属性编码", joined)
        self.assertIn("源属性代码", joined)
        self.assertIn("缺失字段", joined)
        self.assertNotIn("期望 16 列，实际 16 列", joined)

    def test_reordered_header_reports_order_problem(self):
        reordered = [ENTITY_RELATIONS_HEADER[1], ENTITY_RELATIONS_HEADER[0]] + \
            list(ENTITY_RELATIONS_HEADER[2:])
        messages = header_mismatch_messages("entity_relations.csv",
                                            ENTITY_RELATIONS_HEADER, reordered)
        self.assertTrue(any("字段顺序" in message for message in messages))

    def test_missing_and_extra_columns_are_reported(self):
        messages = header_mismatch_messages("entity_relations.csv",
                                            ENTITY_RELATIONS_HEADER,
                                            ENTITY_RELATIONS_HEADER[:15])
        self.assertTrue(any("缺失字段" in message for message in messages))
        extra = list(ENTITY_RELATIONS_HEADER) + ["多余字段"]
        messages = header_mismatch_messages("entity_relations.csv",
                                            ENTITY_RELATIONS_HEADER, extra)
        self.assertTrue(any("未知字段" in message for message in messages))

    def test_id_name_description_temp_header_still_fails(self):
        errors = server.validate_modeling_upload_artifact(
            "entity_relations.csv", "id,name,description\n1,订单,描述\n".encode("utf-8"), "")
        self.assertTrue(errors)

    def test_error_message_has_column_and_values(self):
        bad = list(ENTITY_RELATIONS_HEADER)
        bad[10] = "错误列"
        messages = header_mismatch_messages("entity_relations.csv",
                                            ENTITY_RELATIONS_HEADER, bad)
        self.assertTrue(any("第 11 列" in message and "错误列" in message
                            for message in messages))


class LogicalEntityUploadRuleTests(unittest.TestCase):
    def _upload(self, blob):
        return server.validate_modeling_upload_artifact(
            "logical_entities.csv", blob, "/nonexistent/workspace")

    def test_bo_code_and_name_present_pass(self):
        self.assertEqual(
            self._upload(to_csv(LOGICAL_ENTITIES_HEADER,
                                [logical_entity_row()])), [])

    def test_empty_bo_with_empty_name_and_main_n_pass(self):
        row = logical_entity_row(bo_code="", bo_name="", main="N")
        self.assertEqual(self._upload(to_csv(LOGICAL_ENTITIES_HEADER, [row])), [])

    def test_empty_bo_without_modeling_state_passes(self):
        row = logical_entity_row(bo_code="", bo_name="", main="N")
        with tempfile.TemporaryDirectory() as root:
            # No work/modeling_state.json exists in this workspace.
            self.assertEqual(server.validate_modeling_upload_artifact(
                "logical_entities.csv", to_csv(LOGICAL_ENTITIES_HEADER, [row]), root), [])

    def test_empty_bo_without_decision_audit_passes(self):
        row = logical_entity_row(bo_code="", bo_name="", main="N")
        with tempfile.TemporaryDirectory() as root:
            work = Path(root) / "work"
            work.mkdir()
            # modeling_state.json exists but has no audit assignment status.
            (work / "modeling_state.json").write_text(
                json.dumps({"logicalEntities": []}), encoding="utf-8")
            self.assertEqual(server.validate_modeling_upload_artifact(
                "logical_entities.csv", to_csv(LOGICAL_ENTITIES_HEADER, [row]), root), [])

    def test_empty_bo_with_nonempty_name_fails(self):
        row = logical_entity_row(bo_code="", bo_name="采购订单", main="N")
        self.assertTrue(self._upload(to_csv(LOGICAL_ENTITIES_HEADER, [row])))

    def test_empty_bo_with_main_y_fails(self):
        row = logical_entity_row(bo_code="", bo_name="", main="Y")
        self.assertTrue(self._upload(to_csv(LOGICAL_ENTITIES_HEADER, [row])))

    def test_bo_code_present_but_name_empty_fails(self):
        row = logical_entity_row(bo_name="", main="N")
        self.assertTrue(self._upload(to_csv(LOGICAL_ENTITIES_HEADER, [row])))

    def test_invalid_main_flag_fails(self):
        row = logical_entity_row(main="是")
        self.assertTrue(self._upload(to_csv(LOGICAL_ENTITIES_HEADER, [row])))

    def test_duplicate_logical_entity_code_fails(self):
        first = logical_entity_row()
        second = logical_entity_row(le_code="LE0001", bo_name="采购订单")
        self.assertTrue(self._upload(to_csv(LOGICAL_ENTITIES_HEADER, [first, second])))

    def test_standalone_logical_entities_upload_is_allowed(self):
        # No business_objects.csv is uploaded in the same request.
        row = logical_entity_row(bo_code="", bo_name="", main="N")
        self.assertEqual(self._upload(to_csv(LOGICAL_ENTITIES_HEADER, [row])), [])

    def test_no_assignment_status_column_required_in_csv(self):
        row = logical_entity_row(bo_code="", bo_name="", main="N")
        blob = to_csv(LOGICAL_ENTITIES_HEADER, [row])
        self.assertNotIn("业务对象归属状态", blob.decode("utf-8"))
        self.assertEqual(self._upload(blob), [])


class CompletionGateRetentionTests(unittest.TestCase):
    def _empty_bo_row(self):
        return logical_entity_row(bo_code="", bo_name="", main="N")

    def test_upload_ok_but_finalize_blocks_missing_audit_status(self):
        blob = to_csv(LOGICAL_ENTITIES_HEADER, [self._empty_bo_row()])
        self.assertEqual(server.validate_modeling_upload_artifact(
            "logical_entities.csv", blob, ""), [])
        findings = validate_formal_rows("logical_entities.csv",
                                        LOGICAL_ENTITIES_HEADER,
                                        [self._empty_bo_row()])
        codes = {item.code for item in findings}
        self.assertIn("FORMAL_CONTRACT_ASSIGNMENT_STATUS_MISSING", codes)

    def test_upload_structural_only_never_reads_state(self):
        blob = to_csv(LOGICAL_ENTITIES_HEADER, [self._empty_bo_row()])
        with patch.object(server, "load_modeling_state",
                          side_effect=AssertionError("upload must not read state")):
            self.assertEqual(server.validate_modeling_upload_artifact(
                "logical_entities.csv", blob, "/tmp/whatever"), [])

    def test_unresolved_audit_lets_finalize_pass(self):
        state = {"logicalEntities": [{
            "逻辑实体编码": "LE0001", "业务对象编码": "",
            "businessObjectAssignmentStatus": "UNRESOLVED",
            "unresolvedReason": "证据不足，待确认",
        }]}
        assignments = server.logical_entity_assignment_statuses(state)
        self.assertEqual(assignments.get("LE0001"), "UNRESOLVED")
        findings = validate_formal_rows("logical_entities.csv",
                                        LOGICAL_ENTITIES_HEADER,
                                        [self._empty_bo_row()],
                                        state=state)
        self.assertFalse([item for item in findings
                          if item.code == "FORMAL_CONTRACT_ASSIGNMENT_STATUS_MISSING"])

    def test_not_applicable_without_reason_still_fails_completion(self):
        # Upload stays structural-only for an empty-BO row, but the completion
        # gate's audit check (semantic_validation_issues ->
        # validate_logical_entity_assignments) still requires NOT_APPLICABLE
        # classification/reason/evidence plus a REJECTED decision link.
        self.assertEqual(server.validate_modeling_upload_artifact(
            "logical_entities.csv", to_csv(LOGICAL_ENTITIES_HEADER,
                                           [self._empty_bo_row()]), ""), [])
        incomplete = {"logicalEntities": [{
            "logicalEntityId": "LE0001", "businessObjectCode": "",
            "businessObjectName": "", "businessObjectAssignmentStatus": "NOT_APPLICABLE",
            "mainFlag": "N",
        }]}
        codes = {issue.code for issue in semantic_validation_issues(incomplete)}
        self.assertIn("NOT_APPLICABLE_MISSING_AUDIT_EVIDENCE", codes)
        complete = {"logicalEntities": [{
            "logicalEntityId": "LE0001", "businessObjectCode": "",
            "businessObjectName": "", "businessObjectAssignmentStatus": "NOT_APPLICABLE",
            "mainFlag": "N",
            "exclusionCategory": "技术实体",
            "exclusionReason": "仅数据库技术表，不构成业务对象",
            "exclusionEvidence": "来自 DDL 分析与 R1 证据",
            "rejectedBusinessObjectCode": "BO-REJ-1",
        }], "businessObjectDecisions": [{
            "candidateCode": "BO-REJ-1", "candidateName": "技术表候选",
            "r1Decision": "FAIL", "memberEntityIds": ["LE0001"],
        }]}
        codes = {issue.code for issue in semantic_validation_issues(complete)}
        self.assertNotIn("NOT_APPLICABLE_MISSING_AUDIT_EVIDENCE", codes)
        self.assertNotIn("NOT_APPLICABLE_WITHOUT_REJECTED_DECISION", codes)


class _MinioHandlerHarness(unittest.TestCase):
    """Shared /api/minio/upload harness used by the behaviour test classes."""

    def _task(self, directory, task_id="upload-sep", task_code="RM-SEP-001"):
        task = server.Task(
            "project", directory, repository_id="1", task_code=task_code,
            task_id=task_id, user_id="test", platform_status="RUNNING")
        task.status = "idle"
        task.mission_context = {
            "taskType": "modeling", "parseElements": ["LOGICAL_ENTITY", "ENTITY_RELATION"],
            "expectedFiles": ["logical_entities.csv", "entity_relations.csv"],
            "outputPrefix": "ontology/1/modeling-tasks/RM-SEP-001/agent-output",
        }
        return task

    def _handler(self, task, directory, paths):
        handler = object.__new__(server.Handler)
        handler.headers = {"Authorization": "Bearer test"}
        handler._requires_auth = lambda path: False
        handler._current_user = lambda: "test"
        handler._owned_task = lambda task_id: task
        handler._read_body = lambda: {
            "project": "project", "paths": paths,
            "taskCode": task.task_code, "repositoryId": "1",
            "taskId": task.id, "taskType": "modeling",
        }
        handler._write_uploaded_input = lambda *args, **kwargs: None
        responses = []
        handler._send_json = lambda payload, status=200: responses.append((status, payload))
        originals = {
            "bind": server.bind_mission_project,
            "context": server.fetch_execution_context,
            "cwd": server.mission_task_cwd,
            "config": server.minio_config,
            "put": server.fileserver_put_object,
        }
        put_calls = []
        return handler, responses, originals, put_calls

    def _run(self, task, directory, paths, put=None, context=None):
        handler, responses, originals, put_calls = self._handler(task, directory, paths)
        try:
            server.bind_mission_project = lambda *args: "project"
            server.fetch_execution_context = (
                (lambda *args: None) if context is _UNAVAILABLE
                else lambda *args: context or dict(task.mission_context))
            server.mission_task_cwd = lambda *args: directory
            server.minio_config = lambda: {"bucket": "bucket"}
            server.fileserver_put_object = (
                put or (lambda cfg, key, blob, name, ctype: (
                    put_calls.append((key, blob)) or
                    {"objectKey": key, "previewUrl": "https://files.example/" + name})))
            handler._handle_minio_upload()
        finally:
            for name, value in originals.items():
                setattr(server, name, value)
        return responses, put_calls

    def _write_outputs(self, directory, legacy_relations=True):
        root = Path(directory)
        output = root / "output"
        output.mkdir(exist_ok=True)
        relations = list(ENTITY_RELATIONS_HEADER)
        if legacy_relations:
            relations[10] = "源关联属性编码"
            relations[13] = "目标关联属性编码"
        relations_blob = to_csv(relations, [relation_row()])
        (output / "entity_relations.csv").write_bytes(relations_blob)
        (output / "logical_entities.csv").write_bytes(
            to_csv(LOGICAL_ENTITIES_HEADER, [logical_entity_row()]))
        return relations_blob

    def _ready_task(self, directory):
        task = self._task(directory)
        work = Path(directory) / "work"
        work.mkdir(exist_ok=True)
        # Mirror the persisted modeling state so the upload handler's
        # set_mission_context sees the same input identity and does not
        # invalidate the semantic-finalize marker (production restores the
        # persisted state with the same fingerprint).
        # The handler derives the input identity from the execution-context
        # payload (taskCode key), which the fixture omits; mirror that exactly.
        fingerprint = server._modeling_input_fingerprint(task.mission_context, "")
        (work / "modeling_state.json").write_text(json.dumps({
            "schemaVersion": "1",
            "taskCode": task.task_code,
            "inputFingerprint": fingerprint,
            "requestedElements": ["LOGICAL_ENTITY", "ENTITY_RELATION"],
            "sourceFiles": [],
            "artifacts": {},
            "allAttributes": [],
            "relationDecisions": [],
            "businessObjectDecisions": [],
        }), encoding="utf-8")
        (work / "validation_report.json").write_text(
            json.dumps({"semantic_validation_status": "PASSED"}), encoding="utf-8")
        return task


class MinioUploadApiBehaviourTests(_MinioHandlerHarness):
    """Handler-level tests for /api/minio/upload per-file stage/code."""

    def test_one_bad_header_one_good_upload_partial_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            bad_header = list(ENTITY_RELATIONS_HEADER)
            bad_header[10] = "源属性代码"
            (output / "entity_relations.csv").write_bytes(to_csv(bad_header, [relation_row()]))
            (output / "logical_entities.csv").write_bytes(to_csv(
                LOGICAL_ENTITIES_HEADER, [logical_entity_row(bo_code="", bo_name="", main="N")]))
            task = self._task(directory)
            responses, put_calls = self._run(task, directory, [
                "output/entity_relations.csv", "output/logical_entities.csv"])
            status, payload = responses[-1]
            self.assertEqual(status, 200)
            self.assertEqual(payload["uploaded"], 1)
            self.assertEqual(payload["total"], 2)
            by_name = {item["name"]: item for item in payload["results"]}
            self.assertFalse(by_name["entity_relations.csv"]["ok"])
            self.assertEqual(by_name["entity_relations.csv"]["code"],
                             "UPLOAD_ARTIFACT_HEADER_INVALID")
            self.assertEqual(by_name["entity_relations.csv"]["stage"],
                             "STRUCTURAL_VALIDATION")
            self.assertTrue(by_name["logical_entities.csv"]["ok"])
            self.assertEqual(by_name["logical_entities.csv"]["stage"], "STORAGE")
            self.assertEqual(len(put_calls), 1)

    def test_normalized_header_blob_is_what_is_uploaded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            legacy = list(ENTITY_RELATIONS_HEADER)
            legacy[10] = "源关联属性编码"
            (output / "entity_relations.csv").write_bytes(to_csv(legacy, [relation_row()]))
            task = self._task(directory)
            responses, put_calls = self._run(task, directory, ["output/entity_relations.csv"])
            status, payload = responses[-1]
            self.assertEqual(status, 200)
            self.assertEqual(payload["uploaded"], 1)
            key, blob = put_calls[0]
            parsed = list(csv.reader(io.StringIO(blob.decode("utf-8"), newline="")))
            self.assertEqual(parsed[0][10], "源业务属性编码")
            self.assertEqual(payload["results"][0]["sha256"],
                             hashlib.sha256(blob).hexdigest())

    def test_all_fail_returns_422_with_per_file_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            bad = list(ENTITY_RELATIONS_HEADER)
            bad[10] = "源属性代码"
            (output / "entity_relations.csv").write_bytes(to_csv(bad, [relation_row()]))
            (output / "logical_entities.csv").write_bytes(to_csv(
                LOGICAL_ENTITIES_HEADER, [logical_entity_row(main="是")]))
            task = self._task(directory)
            responses, put_calls = self._run(task, directory, [
                "output/entity_relations.csv", "output/logical_entities.csv"])
            status, payload = responses[-1]
            self.assertEqual(status, 422)
            self.assertEqual(payload["uploaded"], 0)
            self.assertEqual(len(payload["results"]), 2)
            self.assertTrue(all(not item["ok"] for item in payload["results"]))
            self.assertEqual(len(put_calls), 0)

    def test_not_allowed_file_reports_artifact_not_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            (output / "debug.txt").write_text("x", encoding="utf-8")
            task = self._task(directory)
            responses, _ = self._run(task, directory, ["output/debug.txt"])
            status, payload = responses[-1]
            self.assertEqual(status, 422)
            self.assertEqual(payload["results"][0]["code"], "UPLOAD_ARTIFACT_NOT_ALLOWED")

    def test_fileserver_error_uses_storage_category(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            (output / "logical_entities.csv").write_bytes(to_csv(
                LOGICAL_ENTITIES_HEADER, [logical_entity_row()]))
            task = self._task(directory)

            def boom(*args):
                raise IOError("minio down")

            responses, _ = self._run(task, directory,
                                     ["output/logical_entities.csv"], put=boom)
            status, payload = responses[-1]
            self.assertEqual(status, 502)
            self.assertEqual(payload["uploaded"], 0)
            self.assertIs(payload["ok"], False)
            self.assertEqual(payload["code"], "UPLOAD_STORAGE_FAILED")
            self.assertIn("对象存储上传失败", payload["error"])
            item = payload["results"][0]
            self.assertFalse(item["ok"])
            self.assertEqual(item["stage"], "STORAGE")
            self.assertEqual(item["code"], "UPLOAD_STORAGE_FAILED")
            self.assertIn("对象存储上传失败", item["error"])

    def test_upload_success_but_completion_gate_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            (output / "logical_entities.csv").write_bytes(to_csv(
                LOGICAL_ENTITIES_HEADER, [logical_entity_row(bo_code="", bo_name="", main="N")]))
            (output / "business_objects.csv").write_bytes(to_csv(BO_HEADER, []))
            task = self._task(directory)
            responses, _ = self._run(task, directory, ["output/logical_entities.csv"])
            status, payload = responses[-1]
            self.assertEqual(status, 200)
            self.assertEqual(payload["uploaded"], 1)
            self.assertIs(payload["completionReady"], False)
            self.assertEqual(payload.get("completionCode"), "UPLOAD_COMPLETION_GATE_PENDING")
            self.assertTrue(payload["results"][0]["ok"])

    def test_task_running_still_409(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            task.status = "queued"
            task.active_execution_id = "exec-1"
            responses, _ = self._run(task, directory, ["output/logical_entities.csv"])
            self.assertEqual(responses[-1][0], 409)
            self.assertEqual(responses[-1][1]["code"], "EXECUTION_ACTIVE")

    def test_tasks_are_isolated(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            root_a = Path(first) / "output"
            root_a.mkdir()
            (root_a / "logical_entities.csv").write_bytes(to_csv(
                LOGICAL_ENTITIES_HEADER, [logical_entity_row()]))
            task = self._task(first)
            # A second task's directory must never be resolved; the handler
            # works only on the owning task's base.
            responses, put_calls = self._run(task, second, ["output/logical_entities.csv"])
            # File does not exist in task B's workspace -> per-file failure,
            # no object uploaded.
            self.assertEqual(put_calls, [])
            self.assertFalse(responses[-1][1]["results"][0]["ok"])
            self.assertEqual(responses[-1][1]["results"][0]["code"],
                             "UPLOAD_CONTEXT_UNAVAILABLE")

    def test_execution_context_unavailable_returns_explicit_error(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._task(directory)
            responses, put_calls = self._run(
                task, directory, ["output/logical_entities.csv"],
                context=_UNAVAILABLE)
            status, payload = responses[-1]
            self.assertEqual(status, 502)
            self.assertIn("execution-context", payload["error"])
            self.assertNotIn("MinIO", payload["error"])
            self.assertEqual(put_calls, [])


class MultiRowValidationTests(unittest.TestCase):
    """Every CSV data row must receive the full per-row structural check."""

    def _findings(self, filename, header, rows, phase=ValidationPhase.UPLOAD):
        return validate_row_contract(filename, header, rows, phase=phase)

    def test_first_row_invalid_boolean_last_row_valid(self):
        rows = [
            logical_entity_row(le_code="LE0001", main="X", le_name="采购订单实体"),
            logical_entity_row(le_code="LE0002", main="Y", le_name="采购订单明细实体"),
        ]
        findings = self._findings("logical_entities.csv", LOGICAL_ENTITIES_HEADER, rows)
        boolean_rows = [f for f in findings if f.code == "FORMAL_CONTRACT_BOOLEAN"]
        self.assertEqual([f.row for f in boolean_rows], [2])

    def test_middle_row_invalid_boolean(self):
        rows = [
            logical_entity_row(le_code="LE0001", main="Y", le_name="采购订单实体"),
            logical_entity_row(le_code="LE0002", main="X", le_name="采购订单明细实体"),
            logical_entity_row(le_code="LE0003", main="N", le_name="采购订单收货地址实体"),
        ]
        findings = self._findings("logical_entities.csv", LOGICAL_ENTITIES_HEADER, rows)
        boolean_rows = [f for f in findings if f.code == "FORMAL_CONTRACT_BOOLEAN"]
        self.assertEqual([f.row for f in boolean_rows], [3])

    def test_first_row_invalid_enum_last_row_valid(self):
        bad = relation_row()
        bad[5] = "非法分类"
        good = relation_row()
        good[0] = "REL0002"
        findings = self._findings("entity_relations.csv", ENTITY_RELATIONS_HEADER,
                                  [bad, good])
        enum_rows = [f for f in findings if f.code == "FORMAL_CONTRACT_ENUM"]
        self.assertEqual([f.row for f in enum_rows], [2])

    def test_first_row_invalid_code_pattern(self):
        bad = relation_row()
        bad[0] = "REL 0001"
        good = relation_row()
        good[0] = "REL0002"
        findings = self._findings("entity_relations.csv", ENTITY_RELATIONS_HEADER,
                                  [bad, good])
        code_rows = [f for f in findings if f.code == "FORMAL_CONTRACT_CODE_FORMAT"]
        self.assertEqual([f.row for f in code_rows], [2])

    def test_first_row_invalid_english_identifier(self):
        bad = attribute_row(en="order amount")
        good = attribute_row(attr_code="ATTR0002", en="order_total")
        findings = self._findings("business_attributes.csv", BUSINESS_ATTRIBUTES_HEADER,
                                  [bad, good])
        en_rows = [f for f in findings if f.code == "FORMAL_CONTRACT_ENGLISH_FORMAT"]
        self.assertEqual([f.row for f in en_rows], [2])

    def test_multiple_errors_on_different_rows_have_accurate_lines(self):
        bad_code = relation_row()
        bad_code[0] = "REL 0001"
        bad_enum = relation_row()
        bad_enum[0] = "REL0002"
        bad_enum[5] = "非法分类"
        findings = self._findings("entity_relations.csv", ENTITY_RELATIONS_HEADER,
                                  [bad_code, bad_enum])
        code_rows = [f.row for f in findings if f.code == "FORMAL_CONTRACT_CODE_FORMAT"]
        enum_rows = [f.row for f in findings if f.code == "FORMAL_CONTRACT_ENUM"]
        self.assertEqual(code_rows, [2])
        self.assertEqual(enum_rows, [3])

    def test_blank_rows_do_not_participate(self):
        rows = [
            logical_entity_row(le_code="LE0001", main="Y", le_name="采购订单实体"),
            [""] * len(LOGICAL_ENTITIES_HEADER),
            logical_entity_row(le_code="LE0002", main="N", le_name="采购订单明细实体"),
        ]
        findings = self._findings("logical_entities.csv", LOGICAL_ENTITIES_HEADER, rows)
        self.assertFalse([f for f in findings if f.row == 3])
        self.assertFalse(findings)

    def test_wrong_width_row_does_not_misjudge_following_rows(self):
        rows = [
            logical_entity_row(le_code="LE0001", main="Y", le_name="采购订单实体"),
            ["WRONG", "WIDTH", "ROW"],
            logical_entity_row(le_code="LE0002", main="N", le_name="采购订单明细实体"),
        ]
        errors = server.validate_modeling_upload_artifact(
            "logical_entities.csv", to_csv(LOGICAL_ENTITIES_HEADER, rows), "")
        self.assertTrue(any("第 3 行应有 8 列" in item for item in errors))
        self.assertFalse(any("LE0002" in item and "必填" in item for item in errors))

    def test_upload_empty_bo_main_y_first_row_fails(self):
        rows = [
            logical_entity_row(bo_code="", bo_name="", le_code="LE0001", main="Y",
                               le_name="未归属实体一"),
            logical_entity_row(bo_code="", bo_name="", le_code="LE0002", main="N",
                               le_name="未归属实体二"),
        ]
        findings = self._findings("logical_entities.csv", LOGICAL_ENTITIES_HEADER, rows)
        main_rows = [f for f in findings
                     if f.code == "V0001_MAIN_FLAG_WITHOUT_BUSINESS_OBJECT"]
        self.assertEqual([f.row for f in main_rows], [2])

    def test_upload_empty_bo_main_n_allowed(self):
        rows = [
            logical_entity_row(bo_code="", bo_name="", le_code="LE0001", main="N",
                               le_name="未归属实体一"),
            logical_entity_row(bo_code="", bo_name="", le_code="LE0002", main="N",
                               le_name="未归属实体二"),
        ]
        findings = self._findings("logical_entities.csv", LOGICAL_ENTITIES_HEADER, rows)
        self.assertFalse(findings)


class NormalizedHashCompletionTests(_MinioHandlerHarness):
    """Uploaded normalized blobs must complete via a re-normalized hash check."""

    def test_legacy_header_upload_then_completion_hash_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy_blob = self._write_outputs(root, legacy_relations=True)
            task = self._ready_task(root)
            responses, put_calls = self._run(
                task, root, ["output/entity_relations.csv", "output/logical_entities.csv"])
            status, payload = responses[-1]
            self.assertEqual(status, 200)
            self.assertEqual(payload["uploaded"], 2)
            rel = next(item for item in payload["results"]
                       if item["name"] == "entity_relations.csv")
            self.assertTrue(rel["ok"])
            self.assertTrue(rel["normalized"])
            self.assertEqual(rel["normalizationVersion"], HEADER_NORMALIZATION_VERSION)
            uploaded_blob = next(blob for key, blob in put_calls
                                 if key.endswith("entity_relations.csv"))
            self.assertEqual(rel["sha256"], hashlib.sha256(uploaded_blob).hexdigest())
            self.assertEqual(rel["sourceSha256"], hashlib.sha256(legacy_blob).hexdigest())
            self.assertNotEqual(rel["sha256"], rel["sourceSha256"])
            parsed = list(csv.reader(io.StringIO(uploaded_blob.decode("utf-8"), newline="")))
            self.assertEqual(parsed[0][10], "源业务属性编码")
            self.assertEqual(parsed[0][13], "目标业务属性编码")
            local_text = (root / "output" / "entity_relations.csv").read_text(encoding="utf-8")
            self.assertIn("源关联属性编码", local_text)
            # Records survive a JSON round-trip (restart / task restore).
            record = json.loads(json.dumps(task.platform_uploaded_files["entity_relations.csv"]))
            self.assertEqual(record["sha256"], rel["sha256"])
            self.assertEqual(record["sourceSha256"], rel["sourceSha256"])
            self.assertIs(record["normalized"], True)
            self.assertEqual(record["normalizationVersion"], HEADER_NORMALIZATION_VERSION)
            payload2, error = server.build_completed_callback_payload(task)
            self.assertIsNone(error)
            self.assertEqual(len(payload2.get("files") or []), 2)

    def test_data_edit_after_upload_fails_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_outputs(root, legacy_relations=True)
            task = self._ready_task(root)
            responses, _ = self._run(
                task, root, ["output/entity_relations.csv", "output/logical_entities.csv"])
            self.assertEqual(responses[-1][1]["uploaded"], 2)
            edited = [logical_entity_row()]
            edited[0][3] = "修改后的实体名称"
            (root / "output" / "logical_entities.csv").write_bytes(
                to_csv(LOGICAL_ENTITIES_HEADER, edited))
            payload, error = server.build_completed_callback_payload(task)
            self.assertIsNone(payload)
            self.assertIsNotNone(error)
            self.assertIn("logical_entities.csv", error)

    def test_unknown_header_after_upload_fails_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy_blob = self._write_outputs(root, legacy_relations=True)
            task = self._ready_task(root)
            responses, _ = self._run(
                task, root, ["output/entity_relations.csv", "output/logical_entities.csv"])
            self.assertEqual(responses[-1][1]["uploaded"], 2)
            unknown = list(ENTITY_RELATIONS_HEADER)
            unknown[10] = "源属性代码"
            (root / "output" / "entity_relations.csv").write_bytes(
                to_csv(unknown, [relation_row()]))
            self.assertNotEqual(
                hashlib.sha256(legacy_blob).hexdigest(),
                hashlib.sha256((root / "output" / "entity_relations.csv").read_bytes()).hexdigest())
            payload, error = server.build_completed_callback_payload(task)
            self.assertIsNone(payload)
            self.assertIn("entity_relations.csv", error)

    def test_canonical_header_upload_and_completion_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_outputs(root, legacy_relations=False)
            task = self._ready_task(root)
            responses, put_calls = self._run(
                task, root, ["output/entity_relations.csv", "output/logical_entities.csv"])
            status, payload = responses[-1]
            self.assertEqual(status, 200)
            self.assertEqual(payload["uploaded"], 2)
            rel = next(item for item in payload["results"]
                       if item["name"] == "entity_relations.csv")
            self.assertIs(rel["normalized"], False)
            self.assertEqual(rel["normalizationVersion"], "")
            uploaded_blob = next(blob for key, blob in put_calls
                                 if key.endswith("entity_relations.csv"))
            self.assertEqual(rel["sha256"], hashlib.sha256(uploaded_blob).hexdigest())
            payload2, error = server.build_completed_callback_payload(task)
            self.assertIsNone(error)
            self.assertEqual(len(payload2.get("files") or []), 2)

    def test_legacy_record_with_only_sha256_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir(exist_ok=True)
            work = root / "work"
            work.mkdir(exist_ok=True)
            legacy = list(ENTITY_RELATIONS_HEADER)
            legacy[10] = "源关联属性编码"
            legacy[13] = "目标关联属性编码"
            legacy_blob = to_csv(legacy, [relation_row()])
            (output / "entity_relations.csv").write_bytes(legacy_blob)
            le_blob = to_csv(LOGICAL_ENTITIES_HEADER, [logical_entity_row()])
            (output / "logical_entities.csv").write_bytes(le_blob)
            (work / "validation_report.json").write_text(
                json.dumps({"semantic_validation_status": "PASSED"}), encoding="utf-8")
            task = self._task(root)
            # Pre-normalization record: only sha256 (raw local hash).
            task.platform_uploaded_files = {
                "entity_relations.csv": {
                    "name": "entity_relations.csv", "key": "k/entity_relations.csv",
                    "objectKey": "k/entity_relations.csv",
                    "fileUrl": "https://files.example/entity_relations.csv",
                    "previewUrl": "https://files.example/entity_relations.csv",
                    "sha256": hashlib.sha256(legacy_blob).hexdigest(),
                },
                "logical_entities.csv": {
                    "name": "logical_entities.csv", "key": "k/logical_entities.csv",
                    "objectKey": "k/logical_entities.csv",
                    "fileUrl": "https://files.example/logical_entities.csv",
                    "previewUrl": "https://files.example/logical_entities.csv",
                    "sha256": hashlib.sha256(le_blob).hexdigest(),
                },
            }
            payload, error = server.build_completed_callback_payload(task)
            self.assertIsNone(error)
            self.assertEqual(len(payload.get("files") or []), 2)
            edited = [relation_row()]
            edited[0][9] = "上传后修改的关系描述"
            (output / "entity_relations.csv").write_bytes(to_csv(legacy, edited))
            payload, error = server.build_completed_callback_payload(task)
            self.assertIsNone(payload)
            self.assertIn("entity_relations.csv", error)


class CompletionReadyConsistencyTests(_MinioHandlerHarness):
    """result.completionReady and task.summary().completionReady must agree."""

    def test_upload_complete_semantic_passed_both_true(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_outputs(root, legacy_relations=False)
            task = self._ready_task(root)
            responses, _ = self._run(
                task, root, ["output/entity_relations.csv", "output/logical_entities.csv"])
            status, payload = responses[-1]
            self.assertEqual(status, 200)
            self.assertEqual(payload["uploaded"], 2)
            self.assertIs(payload["completionReady"], True)
            self.assertIs(payload["task"]["completionReady"], True)

    def test_upload_complete_semantic_failed_both_false(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_outputs(root, legacy_relations=False)
            task = self._task(root)  # no validation marker -> semantic not passed
            responses, _ = self._run(
                task, root, ["output/entity_relations.csv", "output/logical_entities.csv"])
            status, payload = responses[-1]
            self.assertEqual(status, 200)
            self.assertEqual(payload["uploaded"], 2)
            self.assertIs(payload["completionReady"], False)
            self.assertIs(payload["task"]["completionReady"], False)
            self.assertEqual(payload.get("completionCode"), "UPLOAD_COMPLETION_GATE_PENDING")

    def test_missing_files_both_false(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_outputs(root, legacy_relations=False)
            task = self._ready_task(root)
            responses, _ = self._run(
                task, root, ["output/logical_entities.csv"])
            status, payload = responses[-1]
            self.assertEqual(status, 200)
            self.assertEqual(payload["uploaded"], 1)
            self.assertIs(payload["completionReady"], False)
            self.assertIs(payload["task"]["completionReady"], False)

    def test_partial_upload_success_both_false(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir(exist_ok=True)
            bad = list(ENTITY_RELATIONS_HEADER)
            bad[10] = "源属性代码"
            (output / "entity_relations.csv").write_bytes(to_csv(bad, [relation_row()]))
            (output / "logical_entities.csv").write_bytes(
                to_csv(LOGICAL_ENTITIES_HEADER, [logical_entity_row()]))
            task = self._ready_task(root)
            responses, _ = self._run(
                task, root, ["output/entity_relations.csv", "output/logical_entities.csv"])
            status, payload = responses[-1]
            self.assertEqual(status, 200)
            self.assertEqual(payload["uploaded"], 1)
            self.assertEqual(payload["total"], 2)
            self.assertIs(payload["completionReady"], False)
            self.assertIs(payload["task"]["completionReady"], False)

    def test_state_conflict_not_completable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = self._task(root)
            task.status = "working"
            self.assertFalse(server.completion_ready_for_task(task))
            self.assertIs(task.summary()["completionReady"], False)

    def test_page_refresh_keeps_complete_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_outputs(root, legacy_relations=False)
            task = self._task(root)  # no validation marker
            task.platform_uploaded_files = {
                "entity_relations.csv": {
                    "name": "entity_relations.csv", "key": "k/entity_relations.csv",
                    "objectKey": "k/entity_relations.csv",
                    "fileUrl": "https://files.example/entity_relations.csv",
                    "previewUrl": "https://files.example/entity_relations.csv",
                    "sha256": "a" * 64,
                },
                "logical_entities.csv": {
                    "name": "logical_entities.csv", "key": "k/logical_entities.csv",
                    "objectKey": "k/logical_entities.csv",
                    "fileUrl": "https://files.example/logical_entities.csv",
                    "previewUrl": "https://files.example/logical_entities.csv",
                    "sha256": "b" * 64,
                },
            }
            self.assertIs(task.summary()["completionReady"], False)
            self._ready_task(root)
            self.assertIs(task.summary()["completionReady"], True)


class UserReportedScenarioTests(_MinioHandlerHarness):
    """The two production scenarios reported against the upload gate."""

    def _legacy_relations_blob(self):
        legacy = list(ENTITY_RELATIONS_HEADER)
        legacy[10] = "源关联属性编码"
        legacy[13] = "目标关联属性编码"
        return to_csv(legacy, [relation_row()])

    def test_legacy_16_column_entity_relations_uploads(self):
        errors = server.validate_modeling_upload_artifact(
            "entity_relations.csv", self._legacy_relations_blob(), "")
        self.assertEqual(errors, [])

    def test_empty_bo_logical_entities_le000020_000024_upload(self):
        rows = [logical_entity_row(bo_code="", bo_name="", le_code=f"LE0000{i}", main="N",
                                   le_name=f"待归属逻辑实体{i}")
                for i in range(20, 25)]
        errors = server.validate_modeling_upload_artifact(
            "logical_entities.csv", to_csv(LOGICAL_ENTITIES_HEADER, rows), "")
        self.assertEqual(errors, [])

    def test_same_task_completion_blocked_when_audit_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir(exist_ok=True)
            rows = [logical_entity_row(bo_code="", bo_name="", le_code=f"LE0000{i}", main="N",
                                       le_name=f"待归属逻辑实体{i}")
                    for i in range(20, 25)]
            (output / "logical_entities.csv").write_bytes(
                to_csv(LOGICAL_ENTITIES_HEADER, rows))
            (output / "entity_relations.csv").write_bytes(self._legacy_relations_blob())
            task = self._task(root)  # no audit/validation state
            responses, _ = self._run(task, root, [
                "output/logical_entities.csv", "output/entity_relations.csv"])
            status, payload = responses[-1]
            self.assertEqual(status, 200)
            self.assertEqual(payload["uploaded"], 2)
            self.assertIs(payload["completionReady"], False)
            self.assertEqual(payload.get("completionCode"), "UPLOAD_COMPLETION_GATE_PENDING")
            payload2, error = server.build_completed_callback_payload(task)
            self.assertIsNone(payload2)
            self.assertIn("语义校验", error)


class FrontendUploadFeedbackContractTests(unittest.TestCase):
    """Frontend source must render per-file results even with a top-level error."""

    def test_uploadToMinio_renders_per_file_issues_before_top_level_error(self):
        source = Path(ROOT / "frontend/src/main.jsx").read_text(encoding="utf-8")
        start = source.index("const uploadToMinio = async () =>")
        end = source.index("const changePlatformStatus")
        body = source[start:end]
        self.assertIn('const failed = (result.results || []).filter((item) => !item.ok)', body)
        self.assertIn('setUploadIssues(failed.map((item) => ({', body)
        self.assertIn('setUploadIssues(null);', body)
        self.assertIn('if (result.error && !failed.length) messageApi.error(result.error)', body)
        self.assertIn('if (result.completionReady === false)', body)
        self.assertNotIn('if (result.error) { messageApi.error(result.error); return; }', body)
        self.assertIn('typeof result.completionReady === "boolean"', body)
        self.assertIn('completionReady: finalReady', body)

    def test_upload_issue_modal_shows_stage_code_and_full_error(self):
        source = Path(ROOT / "frontend/src/main.jsx").read_text(encoding="utf-8")
        self.assertIn('title="上传结果明细"', source)
        self.assertIn('{issue.stage ? <Tag>{issue.stage}</Tag> : null}', source)
        self.assertIn('{issue.code ? <Tag color="red">{issue.code}</Tag> : null}', source)
        self.assertIn('className="upload-issue-error"', source)
        self.assertIn('className="upload-issue-list"', source)
        self.assertIn('key={`${issue.name}-${index}`}', source)

    def test_upload_distinguishes_format_from_storage_failure(self):
        source = Path(ROOT / "frontend/src/main.jsx").read_text(encoding="utf-8")
        self.assertIn('没有可上传的合法文件（${failed.length} 个文件校验失败，详见明细）', source)
        self.assertIn('但最终语义校验尚未通过；修复后请再点击“完成”。', source)


if __name__ == "__main__":
    unittest.main()
