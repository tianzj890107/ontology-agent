"""动作（Action）元模型推断与九字段输出契约测试。

覆盖：BO 级演示动作生成、LE 级代表性动作生成、明确证据优先、推断动作
描述/服务字段规则、去重与稳定编码、新旧模板兼容、任务隔离和九字段输出。
"""
import csv
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

from open_claude.action_inference import (  # noqa: E402
    ACTION_FIELDS,
    ACTION_TYPES,
    action_name_for,
    assign_action_codes,
    collect_bo_le,
    dedupe_actions,
    english_action_name,
    infer_actions,
    infer_bo_actions,
    infer_le_actions,
    normalize_action_type,
    parse_action_sheet,
    select_le_candidates,
    sort_actions,
    to_nine_field_rows,
    validate_bo_references,
)

BO = {"业务对象编码": "BO0001", "业务对象名称": "采购订单",
      "业务对象英文名": "purchase_order", "业务对象定义": "采购业务单据"}
BO2 = {"业务对象编码": "BO0002", "业务对象名称": "客户", "业务对象英文名": "customer"}
LE = {"业务对象编码": "BO0001", "逻辑实体编码": "LE0001", "逻辑实体名称": "采购订单行",
      "逻辑实体英文名": "purchase_order_line", "是否主逻辑实体": "N"}
LE_ADDRESS = {"业务对象编码": "BO0001", "逻辑实体编码": "LE0002", "逻辑实体名称": "收货地址",
              "是否主逻辑实体": "N"}
LE_TECH = {"业务对象编码": "BO0001", "逻辑实体编码": "LE0003", "逻辑实体名称": "操作日志",
           "是否主逻辑实体": "N"}


class ActionTypeNormalizationTests(unittest.TestCase):
    def test_chinese_and_english_enums_normalize(self):
        self.assertEqual(normalize_action_type("新增"), "新增")
        self.assertEqual(normalize_action_type("CREATE"), "新增")
        self.assertEqual(normalize_action_type("修改"), "修改")
        self.assertEqual(normalize_action_type("UPDATE"), "修改")
        self.assertEqual(normalize_action_type("删除"), "删除")
        self.assertEqual(normalize_action_type("DELETE"), "删除")
        self.assertEqual(normalize_action_type("执行"), "")
        self.assertEqual(normalize_action_type(""), "")
        self.assertEqual(normalize_action_type(None), "")

    def test_action_name_generation(self):
        self.assertEqual(action_name_for("采购订单", "新增"), "创建采购订单")
        self.assertEqual(action_name_for("采购订单", "修改"), "修改采购订单")
        self.assertEqual(action_name_for("采购订单", "删除"), "删除采购订单")
        self.assertEqual(action_name_for("采购订单行", "新增", le_level=True), "新增采购订单行")
        self.assertEqual(action_name_for("创建订单", "新增"), "创建订单")
        self.assertEqual(english_action_name("采购订单", "新增", object_english="purchase_order"),
                         "createPurchaseOrder")
        self.assertEqual(english_action_name("采购订单行", "新增", object_english="purchase_order_line",
                                             le_level=True), "addPurchaseOrderLine")


class ParseActionSheetTests(unittest.TestCase):
    def test_header_order_variation_and_nine_fields(self):
        rows = [
            ["动作名称", "动作类型", "业务对象编码", "动作描述", "动作编码", "动作英文名", "协议", "服务节点", "服务名称"],
            ["创建采购订单", "新增", "BO0001", "描述", "ACT000001", "createPurchaseOrder", "HTTP", "svc", "服务"],
        ]
        parsed = parse_action_sheet(rows)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(list(parsed[0].keys()), list(ACTION_FIELDS))
        self.assertEqual(parsed[0]["动作编码"], "ACT000001")
        self.assertEqual(parsed[0]["动作类型"], "新增")
        self.assertEqual(parsed[0]["协议"], "HTTP")

    def test_empty_and_missing_sheet_are_compatible(self):
        self.assertEqual(parse_action_sheet(None), [])
        self.assertEqual(parse_action_sheet([]), [])
        self.assertEqual(parse_action_sheet([["动作编码", "动作名称"]]), [])
        self.assertEqual(parse_action_sheet([[f"\ufeff{ACTION_FIELDS[0]}"] + list(ACTION_FIELDS[1:])]), [])

    def test_blank_rows_and_trailing_empty_columns_ignored(self):
        rows = [list(ACTION_FIELDS), [""] * 9, ["ACT000001", "创建采购订单", "", "", "新增", "BO0001", "", "", ""]]
        parsed = parse_action_sheet(rows)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["动作名称"], "创建采购订单")

    def test_mapping_rows_style_parse(self):
        parsed = parse_action_sheet({"动作编码": "ACT000001", "动作名称": "创建采购订单"})
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["动作描述"], "")


class BusinessObjectActionTests(unittest.TestCase):
    def test_single_bo_without_evidence_generates_three_demo_actions(self):
        actions = infer_actions([BO])
        self.assertEqual(len(actions), 3)
        self.assertEqual([a["动作类型"] for a in actions], ["新增", "修改", "删除"])
        self.assertEqual([a["业务对象编码"] for a in actions], ["BO0001"] * 3)
        self.assertEqual([a["动作编码"] for a in actions], ["ACT000001", "ACT000002", "ACT000003"])
        for action in actions:
            self.assertIn("演示候选动作", action["动作描述"])
            self.assertEqual(action["协议"], "")
            self.assertEqual(action["服务节点"], "")
            self.assertEqual(action["服务名称"], "")

    def test_multiple_bos_generate_actions_with_correct_bo_codes(self):
        actions = infer_actions([BO, BO2])
        self.assertEqual(len(actions), 6)
        codes = [a["业务对象编码"] for a in actions]
        self.assertEqual(codes, ["BO0001"] * 3 + ["BO0002"] * 3)
        self.assertEqual([a["动作名称"] for a in actions[:3]],
                         ["创建采购订单", "修改采购订单", "删除采购订单"])
        self.assertEqual([a["动作名称"] for a in actions[3:]],
                         ["创建客户", "修改客户", "删除客户"])

    def test_english_names_stable_and_lower_camel(self):
        first = infer_actions([BO])
        second = infer_actions([BO])
        self.assertEqual([a["动作英文名"] for a in first],
                         ["createPurchaseOrder", "updatePurchaseOrder", "deletePurchaseOrder"])
        self.assertEqual(first, second)

    def test_repeat_run_stable_order_and_codes(self):
        run1 = infer_actions([BO, BO2], [LE])
        run2 = infer_actions([BO, BO2], [LE])
        self.assertEqual(run1, run2)
        self.assertEqual([a["动作编码"] for a in run1],
                         [f"ACT{i:06d}" for i in range(1, len(run1) + 1)])


class LogicalEntityActionTests(unittest.TestCase):
    def test_bo_with_order_line_generates_le_actions(self):
        actions = infer_actions([BO], [LE])
        le_actions = [a for a in actions if "订单行" in a["动作名称"]]
        self.assertEqual(len(le_actions), 3)
        for action in le_actions:
            self.assertEqual(action["业务对象编码"], "BO0001")
            self.assertIn("采购订单行", action["动作名称"])
            self.assertIn("采购订单行", action["动作描述"])
            self.assertNotIn("逻辑实体编码", action)
            self.assertIn("演示候选动作", action["动作描述"])

    def test_le_level_english_uses_add_verb(self):
        actions = infer_actions([BO], [LE])
        le_actions = [a for a in actions if a["动作类型"] == "新增" and "订单行" in a["动作名称"]]
        self.assertEqual(le_actions[0]["动作英文名"], "addPurchaseOrderLine")

    def test_technical_entities_do_not_get_full_three_action_sets(self):
        actions = infer_actions([BO], [LE, LE_ADDRESS, LE_TECH])
        names = [a["动作名称"] for a in actions]
        self.assertNotIn("新增操作日志", names)
        self.assertIn("新增收货地址", names)

    def test_unassigned_le_generates_no_action(self):
        orphan = dict(LE)
        orphan["业务对象编码"] = ""
        actions = infer_actions([BO], [orphan])
        self.assertEqual([a["动作名称"] for a in actions], ["创建采购订单", "修改采购订单", "删除采购订单"])

    def test_le_candidate_selection_prefers_operable_entities(self):
        selected = select_le_candidates([LE_ADDRESS, LE_TECH, LE], limit=2)
        self.assertEqual([s["逻辑实体名称"] for s in selected], ["收货地址", "采购订单行"])


class ExplicitEvidencePriorityTests(unittest.TestCase):
    def test_explicit_action_wins_and_inferred_duplicate_removed(self):
        explicit = [{"动作编码": "ACT000100", "动作名称": "创建采购订单",
                     "动作英文名": "createPurchaseOrder", "动作描述": "来自真实 API",
                     "动作类型": "CREATE", "业务对象编码": "BO0001",
                     "协议": "HTTP", "服务节点": "order-svc", "服务名称": "订单服务"}]
        actions = infer_actions([BO], [LE], explicit_actions=explicit)
        names = [a["动作名称"] for a in actions]
        self.assertEqual(names.count("创建采购订单"), 1)
        kept = next(a for a in actions if a["动作名称"] == "创建采购订单")
        self.assertEqual(kept["动作编码"], "ACT000100")
        self.assertEqual(kept["协议"], "HTTP")
        self.assertEqual(kept["服务节点"], "order-svc")
        self.assertEqual(kept["服务名称"], "订单服务")

    def test_inferred_service_fields_stay_empty(self):
        actions = infer_actions([BO])
        for action in actions:
            self.assertEqual((action["协议"], action["服务节点"], action["服务名称"]), ("", "", ""))


class DedupeAndSortTests(unittest.TestCase):
    def test_dedupe_by_bo_type_name(self):
        duplicate = dict(BO)
        duplicate["业务对象名称"] = "采购订单"
        actions = infer_bo_actions(BO) + infer_bo_actions(duplicate)
        deduped = dedupe_actions(actions)
        self.assertEqual(len(deduped), 3)

    def test_sort_orders_by_bo_type_then_name(self):
        actions = [{"业务对象编码": "BO0002", "动作类型": "删除", "动作名称": "删除客户"},
                   {"业务对象编码": "BO0001", "动作类型": "修改", "动作名称": "修改采购订单"},
                   {"业务对象编码": "BO0001", "动作类型": "新增", "动作名称": "创建采购订单"}]
        ordered = sort_actions(actions)
        self.assertEqual([a["动作名称"] for a in ordered],
                         ["创建采购订单", "修改采购订单", "删除客户"])

    def test_assign_codes_is_stable_and_sequential(self):
        actions = infer_bo_actions(BO)
        coded = assign_action_codes(actions, start=7)
        self.assertEqual([a["动作编码"] for a in coded], ["ACT000007", "ACT000008", "ACT000009"])


class BoundaryAndIsolationTests(unittest.TestCase):
    def test_no_business_object_means_no_actions(self):
        self.assertEqual(infer_actions([]), [])
        self.assertEqual(infer_actions([], [LE]), [])

    def test_bo_without_le_still_generates_bo_actions(self):
        actions = infer_actions([BO], [])
        self.assertEqual(len(actions), 3)

    def test_total_action_count_capped(self):
        bos = [{"业务对象编码": f"BO{i:04d}", "业务对象名称": f"业务对象{i}"} for i in range(1, 30)]
        les = [{"业务对象编码": f"BO{i:04d}", "逻辑实体编码": f"LE{i:04d}",
                "逻辑实体名称": f"业务对象{i}明细行"} for i in range(1, 30)]
        actions = infer_actions(bos, les, max_total=50)
        self.assertLessEqual(len(actions), 50)
        bo_level = [a for a in actions if "明细行" not in a["动作名称"]]
        self.assertEqual(len(bo_level), 50)  # 30 BOs would exceed cap; keep BO-level actions first

    def test_task_isolation_no_cross_task_codes(self):
        task_a = infer_actions([BO])
        task_b = infer_actions([BO2])
        self.assertEqual([a["动作编码"] for a in task_a], ["ACT000001", "ACT000002", "ACT000003"])
        self.assertEqual([a["动作编码"] for a in task_b], ["ACT000001", "ACT000002", "ACT000003"])
        self.assertNotIn("BO0002", {a["业务对象编码"] for a in task_a})

    def test_output_strictly_nine_fields(self):
        actions = infer_actions([BO], [LE])
        rows = to_nine_field_rows(actions)
        for row in rows:
            self.assertEqual(len(row), len(ACTION_FIELDS))
        buffer = io.StringIO()
        csv.writer(buffer, lineterminator="\n").writerows([list(ACTION_FIELDS), *rows])
        self.assertTrue(buffer.getvalue().startswith("动作编码,动作名称,动作英文名"))

    def test_bo_reference_validation(self):
        actions = infer_actions([BO])
        self.assertEqual(validate_bo_references(actions, ["BO0001"]), [])
        issues = validate_bo_references(actions, ["BO9999"])
        self.assertEqual(len(issues), 3)
        self.assertEqual({item["业务对象编码"] for item in issues}, {"BO0001"})

    def test_collect_bo_le_index_only_counts_explicit_ownership(self):
        index = collect_bo_le([LE, {"业务对象编码": "", "逻辑实体编码": "X1", "逻辑实体名称": "未归属"}])
        self.assertEqual(list(index.keys()), ["BO0001"])
        self.assertEqual(len(index["BO0001"]), 1)


if __name__ == "__main__":
    unittest.main()
