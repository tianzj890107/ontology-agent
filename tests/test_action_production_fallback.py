"""动作推断生产接入测试。

覆盖确定性兜底接入正式 finalize/export 链路后的行为：缺失/空/表头动作
产物自动补充、明确动作优先合并、服务字段保留、编码冲突规避、ACTION 与
expectedFiles 双门禁、无 BO 不生成、结构错误不被推断掩盖、任务隔离和
严格九字段输出。
"""
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

from open_claude.action_inference import ACTION_FIELDS  # noqa: E402
from open_claude.modeling_reliability import (  # noqa: E402
    ensure_actions_artifact,
    finalize_semantic_model,
)


def confirmed_bo(code, name):
    return {
        "candidateCode": code, "candidateName": name,
        "memberEntityIds": ["LE0001"], "confidence": "90", "decision": "CONFIRMED",
        **{f"r{i}": {"status": "PASS", "evidence": f"[R{i}_SOURCE] 证据"}
           for i in range(1, 6)},
    }


def le_row(code, name, bo_code, main="N"):
    return {"code": code, "name": name, "businessObjectCode": bo_code, "isMain": main}


def base_state():
    return {
        "businessObjectDecisions": [confirmed_bo("BO0001", "采购订单")],
        "logicalEntities": [
            le_row("LE0001", "采购订单", "BO0001", main="Y"),
            le_row("LE0002", "订单行", "BO0001"),
        ],
    }


def write_csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    path.write_bytes(buffer.getvalue().encode("utf-8-sig"))


def read_actions(path):
    if not path.is_file():
        return None
    rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
    return rows


def action_row(code, name, action_type, bo_code, english="createAction",
               description="明确动作描述", service=("", "", "")):
    protocol, node, service_name = service
    return [code, name, english, description, action_type, bo_code,
            protocol, node, service_name]


ACTION_HEADER = list(ACTION_FIELDS)


class ActionProductionFallbackTests(unittest.TestCase):
    def _run_finalize(self, root, state, expected_files, parse_elements,
                       validate_artifact_schema=False):
        return finalize_semantic_model(
            Path(root) / "work", state, output_dir=Path(root) / "output",
            required_outputs=expected_files,
            validate_artifact_schema=validate_artifact_schema,
            context={"expectedFiles": expected_files,
                     "parseElements": parse_elements, "taskType": "modeling"})

    def test_missing_actions_csv_is_auto_generated(self):
        with tempfile.TemporaryDirectory() as root:
            result = self._run_finalize(root, base_state(),
                                        ["actions.csv"], ["ACTION"])
            path = Path(root) / "output" / "actions.csv"
            self.assertTrue(path.is_file())
            self.assertEqual(result["status"], "PASSED")
            rows = read_actions(path)
            self.assertGreaterEqual(len(rows), 3)
            codes = {row["业务对象编码"] for row in rows}
            self.assertEqual(codes, {"BO0001"})

    def test_empty_actions_csv_is_replaced(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "output"
            output.mkdir(parents=True, exist_ok=True)
            (output / "actions.csv").write_bytes(b"")
            self._run_finalize(root, base_state(), ["actions.csv"], ["ACTION"])
            rows = read_actions(output / "actions.csv")
            self.assertGreaterEqual(len(rows), 3)
            self.assertEqual(rows[0]["动作名称"], "创建采购订单")

    def test_header_only_actions_csv_is_replaced(self):
        with tempfile.TemporaryDirectory() as root:
            write_csv(Path(root) / "output" / "actions.csv", ACTION_HEADER, [])
            self._run_finalize(root, base_state(), ["actions.csv"], ["ACTION"])
            rows = read_actions(Path(root) / "output" / "actions.csv")
            self.assertGreaterEqual(len(rows), 3)

    def test_explicit_and_inferred_actions_merge(self):
        with tempfile.TemporaryDirectory() as root:
            write_csv(Path(root) / "output" / "actions.csv", ACTION_HEADER, [
                action_row("ACT000001", "创建采购订单", "新增", "BO0001",
                           service=("HTTP", "order-svc", "订单服务")),
            ])
            self._run_finalize(root, base_state(), ["actions.csv"], ["ACTION"])
            rows = read_actions(Path(root) / "output" / "actions.csv")
            by_name = {row["动作名称"]: row for row in rows}
            self.assertEqual(by_name["创建采购订单"]["协议"], "HTTP")
            self.assertEqual(by_name["创建采购订单"]["服务名称"], "订单服务")
            self.assertGreater(len(rows), 1)

    def test_explicit_service_fields_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            write_csv(Path(root) / "output" / "actions.csv", ACTION_HEADER, [
                action_row("ACT000010", "作废采购订单", "删除", "BO0001",
                           service=("HTTP", "order-svc", "订单服务")),
            ])
            self._run_finalize(root, base_state(), ["actions.csv"], ["ACTION"])
            rows = read_actions(Path(root) / "output" / "actions.csv")
            by_name = {row["动作名称"]: row for row in rows}
            self.assertEqual(by_name["作废采购订单"]["协议"], "HTTP")
            self.assertEqual(by_name["作废采购订单"]["服务节点"], "order-svc")
            # 推断动作的服务字段保持为空。
            self.assertEqual(by_name["修改采购订单"]["协议"], "")
            self.assertEqual(by_name["修改采购订单"]["服务名称"], "")

    def test_explicit_action_wins_over_inferred_duplicate(self):
        with tempfile.TemporaryDirectory() as root:
            write_csv(Path(root) / "output" / "actions.csv", ACTION_HEADER, [
                action_row("ACT000001", "创建采购订单", "新增", "BO0001"),
            ])
            self._run_finalize(root, base_state(), ["actions.csv"], ["ACTION"])
            rows = read_actions(Path(root) / "output" / "actions.csv")
            creates = [row for row in rows if row["动作名称"] == "创建采购订单"]
            self.assertEqual(len(creates), 1)
            self.assertEqual(creates[0]["动作编码"], "ACT000001")

    def test_legal_explicit_codes_preserved_and_new_codes_avoid_collision(self):
        with tempfile.TemporaryDirectory() as root:
            write_csv(Path(root) / "output" / "actions.csv", ACTION_HEADER, [
                action_row("ACT000001", "创建采购订单", "新增", "BO0001"),
                action_row("ACT000002", "修改采购订单", "修改", "BO0001"),
            ])
            self._run_finalize(root, base_state(), ["actions.csv"], ["ACTION"])
            rows = read_actions(Path(root) / "output" / "actions.csv")
            codes = [row["动作编码"] for row in rows]
            self.assertEqual(len(codes), len(set(codes)))
            self.assertIn("ACT000001", codes)
            self.assertIn("ACT000002", codes)
            self.assertNotIn("ACT000003", [row["动作编码"] for row in rows
                                           if row["动作名称"] == "创建采购订单"])

    def test_repeat_finalize_keeps_codes_stable(self):
        with tempfile.TemporaryDirectory() as root:
            self._run_finalize(root, base_state(), ["actions.csv"], ["ACTION"])
            first = read_actions(Path(root) / "output" / "actions.csv")
            self._run_finalize(root, base_state(), ["actions.csv"], ["ACTION"])
            second = read_actions(Path(root) / "output" / "actions.csv")
            self.assertEqual(first, second)

    def test_action_not_selected_does_not_generate(self):
        with tempfile.TemporaryDirectory() as root:
            self._run_finalize(root, base_state(),
                               ["actions.csv"], ["BUSINESS_OBJECT"])
            self.assertFalse((Path(root) / "output" / "actions.csv").exists())

    def test_expected_files_not_allowing_actions_does_not_generate(self):
        with tempfile.TemporaryDirectory() as root:
            state = base_state()
            with tempfile.TemporaryDirectory() as root2:
                work = Path(root2) / "work"
                output = Path(root2) / "output"
                work.mkdir()
                output.mkdir()
                ensure_actions_artifact(
                    work, output, state, ["business_objects.csv"],
                    {"parseElements": ["ACTION"], "expectedFiles": ["business_objects.csv"]})
                self.assertFalse((output / "actions.csv").exists())

    def test_no_business_object_means_no_actions(self):
        with tempfile.TemporaryDirectory() as root:
            self._run_finalize(root, {"logicalEntities": [le_row("LE1", "订单", "BO_X")]},
                               ["actions.csv"], ["ACTION"])
            self.assertFalse((Path(root) / "output" / "actions.csv").exists())

    def test_bo_without_le_still_generates_bo_actions(self):
        with tempfile.TemporaryDirectory() as root:
            state = {"businessObjectDecisions": [confirmed_bo("BO0001", "采购订单")]}
            self._run_finalize(root, state, ["actions.csv"], ["ACTION"])
            rows = read_actions(Path(root) / "output" / "actions.csv")
            self.assertEqual(len(rows), 3)
            self.assertEqual({row["动作名称"] for row in rows},
                             {"创建采购订单", "修改采购订单", "删除采购订单"})

    def test_le_actions_only_for_real_bo_ownership(self):
        with tempfile.TemporaryDirectory() as root:
            state = {
                "businessObjectDecisions": [confirmed_bo("BO0001", "采购订单")],
                "logicalEntities": [
                    le_row("LE0001", "采购订单", "BO0001", main="Y"),
                    le_row("LE0002", "订单行", "BO0001"),
                    le_row("LE999", "游离实体", "BO_NOT_EXIST"),
                ],
            }
            self._run_finalize(root, state, ["actions.csv"], ["ACTION"])
            rows = read_actions(Path(root) / "output" / "actions.csv")
            self.assertTrue(all(row["业务对象编码"] == "BO0001" for row in rows))
            names = {row["动作名称"] for row in rows}
            self.assertNotIn("新增游离实体", names)

    def test_invalid_header_is_not_masked_by_inference(self):
        with tempfile.TemporaryDirectory() as root:
            write_csv(Path(root) / "output" / "actions.csv", ["坏表头", "另一列"], [
                ["创建采购订单", "新增"],
            ])
            result = self._run_finalize(root, base_state(),
                                        ["actions.csv"], ["ACTION"],
                                        validate_artifact_schema=True)
            rows = read_actions(Path(root) / "output" / "actions.csv")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["坏表头"], "创建采购订单")
            self.assertEqual(result["status"], "FAILED")
            self.assertIn("FORMAL_OUTPUT_INVALID_SCHEMA",
                          {issue.code for issue in result["issues"]})

    def test_dangling_bo_reference_is_not_masked_by_inference(self):
        with tempfile.TemporaryDirectory() as root:
            write_csv(Path(root) / "output" / "actions.csv", ACTION_HEADER, [
                action_row("ACT000001", "创建幽灵订单", "新增", "BO_GHOST"),
            ])
            write_csv(Path(root) / "output" / "business_objects.csv",
                      ["业务对象编码", "业务对象名称", "业务对象定义"],
                      [["BO0001", "采购订单", "采购业务单据"]])
            result = self._run_finalize(root, base_state(),
                                        ["actions.csv", "business_objects.csv"],
                                        ["ACTION", "BUSINESS_OBJECT"])
            rows = read_actions(Path(root) / "output" / "actions.csv")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["业务对象编码"], "BO_GHOST")
            self.assertIn("FORMAL_REFERENCE_NOT_FOUND",
                          {issue.code for issue in result["issues"]})

    def test_unsupported_action_type_is_not_masked(self):
        with tempfile.TemporaryDirectory() as root:
            write_csv(Path(root) / "output" / "actions.csv", ACTION_HEADER, [
                action_row("ACT000001", "执行采购订单", "执行", "BO0001"),
            ])
            result = self._run_finalize(root, base_state(),
                                        ["actions.csv"], ["ACTION"])
            rows = read_actions(Path(root) / "output" / "actions.csv")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["动作类型"], "执行")
            self.assertTrue(any("V0001" in issue.code or "CONTRACT" in issue.code
                                or issue.code == "FORMAL_OUTPUT_INVALID_SCHEMA"
                                for issue in result["issues"]))

    def test_task_isolation_no_cross_task_data(self):
        with tempfile.TemporaryDirectory() as root:
            output_a = Path(root) / "a" / "output"
            output_b = Path(root) / "b" / "output"
            output_a.mkdir(parents=True)
            output_b.mkdir(parents=True)
            state_a = {"businessObjectDecisions": [confirmed_bo("BO_A", "订单A")]}
            state_b = {"businessObjectDecisions": [confirmed_bo("BO_B", "订单B")]}
            ensure_actions_artifact(Path(root) / "a" / "work", output_a, state_a,
                                    ["actions.csv"], {"parseElements": ["ACTION"]})
            ensure_actions_artifact(Path(root) / "b" / "work", output_b, state_b,
                                    ["actions.csv"], {"parseElements": ["ACTION"]})
            rows_a = read_actions(output_a / "actions.csv")
            rows_b = read_actions(output_b / "actions.csv")
            self.assertEqual({row["业务对象编码"] for row in rows_a}, {"BO_A"})
            self.assertEqual({row["业务对象编码"] for row in rows_b}, {"BO_B"})

    def test_output_strictly_nine_fields(self):
        with tempfile.TemporaryDirectory() as root:
            self._run_finalize(root, base_state(), ["actions.csv"], ["ACTION"])
            rows = list(csv.reader(io.StringIO(
                (Path(root) / "output" / "actions.csv").read_text(encoding="utf-8-sig"))))
            self.assertEqual(rows[0], list(ACTION_FIELDS))
            for row in rows[1:]:
                self.assertEqual(len(row), len(ACTION_FIELDS))


if __name__ == "__main__":
    unittest.main()
