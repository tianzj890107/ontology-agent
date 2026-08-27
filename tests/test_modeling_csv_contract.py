"""Regression tests for the shared formal-CSV field contract gate.

Covers: every required field blanked per file, whitespace-only values,
Chinese/English name separation, Y/N/enum/integer/code format errors,
in-file uniqueness, cross-file reference existence, formal-eligibility
exclusion (ineligible rows must block instead of shipping inside a PASSED
formal CSV), semantic WARNINGs that never block, upload/finalize consistency
for deterministic format errors, and the shared 47313/47314 code chain.
"""
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

import oc_codex_server  # noqa: E402
from open_claude.modeling_csv_contract import (  # noqa: E402
    CONTRACTS,
    validate_row_contract,
)
from open_claude.modeling_rule_registry import validate_formal_rows  # noqa: E402
from open_claude.modeling_reliability import finalize_semantic_model  # noqa: E402


def to_csv(header, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def upload_errors(filename, header, rows):
    blob = to_csv(header, rows)
    name = filename.lower()
    if name in oc_codex_server._MODELING_HEADERS:
        return oc_codex_server.validate_modeling_csv(filename, blob)
    return oc_codex_server.validate_integration_csv(filename, blob)


VALID_ROWS = {
    "business_objects.csv": (["业务对象编码", "业务对象名称", "业务对象英文名", "业务对象定义", "数据类别"],
                             ["BO0001", "采购订单", "purchase_order", "采购订单相关的业务对象定义", "事务数据"]),
    "logical_entities.csv": (["业务对象编码", "业务对象名称", "逻辑实体编码", "逻辑实体名称",
                              "逻辑实体英文名", "逻辑实体定义", "是否主逻辑实体", "数据类别"],
                             ["BO0001", "采购订单", "LE0001", "采购订单实体", "purchase_order_entity",
                              "采购订单业务实体定义", "Y", "事务数据"]),
    "business_attributes.csv": (["逻辑实体编码", "逻辑实体名称", "业务属性编码", "业务属性名称",
                                 "业务属性英文名称", "业务属性定义", "数据类型", "数据长度", "数据精度",
                                 "是否物理主键", "是否逻辑主键", "是否唯一", "是否非空", "是否页面显示",
                                 "是否层级编码", "是否层级名称"],
                                ["LE0001", "采购订单实体", "BA0001", "订单编码", "order_code",
                                 "订单的唯一业务标识", "文本", "50", "", "N", "Y", "Y", "Y", "N", "N", "N"]),
    "entity_relations.csv": (["关系编码", "源逻辑实体编码", "源逻辑实体名称", "目标逻辑实体编码",
                              "目标逻辑实体名称", "关系分类", "关系中文名称", "关系英文名称", "关系基数",
                              "关系描述", "源业务属性编码", "源关联属性英文名", "源关联属性中文名",
                              "目标业务属性编码", "目标关联属性英文名", "目标关联属性中文名"],
                             ["REL0001", "LE0001", "采购订单实体", "LE0002", "客户实体", "关联", "属于",
                              "belongs_to", "1:N", "采购订单属于客户", "", "", "", "", "", ""]),
    "business_object_relations.csv": (["关系编码", "源业务对象编码", "源业务对象名称", "关系类型",
                                       "关系英文名称", "关系中文名名称", "目标业务对象编码", "目标业务对象名称",
                                       "关系基数", "关系描述"],
                                      ["BOR0001", "BO0001", "采购订单", "依赖关系", "generates", "生成",
                                       "BO0002", "客户", "1:1", "采购订单生成客户"]),
    "statuses.csv": (["业务对象编码", "业务对象名称", "状态编码", "状态英文名", "状态中文名",
                      "状态含义", "触发条件", "是否终态", "是否主终态"],
                     ["BO0001", "采购订单", "ACTIVE", "Active", "生效", "采购订单已生效", "审批通过", "N", "N"]),
    "events.csv": (["事件编码", "事件名称", "事件中文名称", "事件含义", "触发结果"],
                   ["EV0001", "OrderApproved", "订单审批通过", "订单完成审批", "订单进入生效状态"]),
    "business_rules.csv": (["规则编码", "规则名称", "规则描述", "触发条件", "判断或结果", "处置动作"],
                           ["R0000001", "订单校验", "订单必须有效", "订单提交", "校验通过", "允许提交"]),
    "actions.csv": (["动作编码", "动作名称", "动作英文名", "动作描述", "动作类型", "业务对象编码",
                     "协议", "服务节点", "服务名称"],
                    ["ACT000001", "创建采购订单", "createPurchaseOrder", "创建采购订单业务对象",
                     "新增", "BO0001", "", "", ""]),
    "terms.csv": (["术语编码", "术语名称", "别名", "英文名", "缩略语", "术语定义"],
                  ["T0001", "订单", "", "Order", "", "订单是采购行为的业务载体"]),
    "metrics.csv": (["指标编码", "指标名称", "指标别名", "指标英文名", "指标定义", "计算公式", "统计口径",
                     "指标类型", "来源业务对象", "来源逻辑实体", "来源业务属性", "聚合类型", "时间维度",
                     "计算规则", "过滤条件"],
                    ["M0001", "订单数", "", "", "", "", "", "", "", "", "", "", "", "", ""]),
    "integration_report.csv": (["检核项", "问题类型", "涉及源模型", "处理结果", "说明"],
                               ["完整性", "缺失", '["RM001"]', "已修正", "补充了缺失定义"]),
    "merged_elements.csv": (["整合后名称", "元素类型", "原名称集合", "来源模型", "合并策略", "相似度"],
                            ["合同", "BUSINESS_OBJECT", '["合同A","合同B"]', '["RM001"]', "保留编码", "0.9"]),
    "pending_elements.csv": (["候选名称 A", "候选名称 B", "推荐名称", "元素类型", "来源模型", "相似度",
                              "待确认原因"],
                             ["合同A", "合同B", "合同", "BUSINESS_OBJECT", '["RM001"]', "0.6", "证据不足"]),
    "conflict_elements.csv": (["元素名称", "冲突类型", "来源模型", "冲突描述", "来源内容"],
                              ["合同", "同名不同义", '["RM001","RM002"]', "定义冲突", "原始定义摘要"]),
    "missing_elements.csv": (["元素名称", "元素类型", "来源模型", "缺失说明"],
                             ["合同", "BUSINESS_OBJECT", '["RM001"]', "缺少逻辑实体"]),
}

REQUIRED_BY_FILE = {
    "business_objects.csv": ["业务对象编码", "业务对象名称", "业务对象定义"],
    "logical_entities.csv": ["业务对象编码", "业务对象名称", "逻辑实体编码", "逻辑实体名称",
                             "逻辑实体定义", "是否主逻辑实体"],
    "business_attributes.csv": ["逻辑实体编码", "逻辑实体名称", "业务属性编码", "业务属性名称",
                                "业务属性定义", "数据类型", "是否物理主键", "是否逻辑主键", "是否唯一",
                                "是否非空", "是否页面显示", "是否层级编码", "是否层级名称"],
    "entity_relations.csv": ["关系编码", "源逻辑实体编码", "源逻辑实体名称", "目标逻辑实体编码",
                             "目标逻辑实体名称", "关系分类", "关系中文名称", "关系基数", "关系描述"],
    "business_object_relations.csv": ["关系编码", "源业务对象编码", "源业务对象名称", "关系类型",
                                      "关系中文名名称", "目标业务对象编码", "目标业务对象名称",
                                      "关系基数", "关系描述"],
    "statuses.csv": ["业务对象编码", "业务对象名称", "状态编码", "状态中文名", "状态含义",
                     "触发条件", "是否终态", "是否主终态"],
    "events.csv": ["事件编码", "事件名称", "事件中文名称", "事件含义", "触发结果"],
    "business_rules.csv": ["规则编码", "规则名称", "触发条件", "判断或结果", "处置动作"],
    "actions.csv": ["动作编码", "动作名称", "动作英文名", "动作描述", "动作类型", "业务对象编码"],
    "terms.csv": ["术语编码", "术语名称", "术语定义"],
    "metrics.csv": ["指标编码", "指标名称"],
    "integration_report.csv": ["检核项", "问题类型", "处理结果", "说明"],
    "merged_elements.csv": ["整合后名称", "元素类型", "原名称集合", "来源模型", "合并策略", "相似度"],
    "pending_elements.csv": ["候选名称 A", "候选名称 B", "元素类型", "来源模型", "相似度", "待确认原因"],
    "conflict_elements.csv": ["元素名称", "冲突类型", "来源模型", "冲突描述"],
    "missing_elements.csv": ["元素名称", "元素类型", "来源模型", "缺失说明"],
}


class RequiredFieldContractTests(unittest.TestCase):
    def test_every_required_field_blanked_fails_upload_and_finalize(self):
        for filename, (header, valid_row) in VALID_ROWS.items():
            for field in REQUIRED_BY_FILE[filename]:
                row = list(valid_row)
                row[header.index(field)] = ""
                with self.subTest(filename=filename, field=field):
                    self.assertTrue(upload_errors(filename, header, [row]),
                                    f"{filename} 必填字段 {field} 置空后上传校验必须失败")
                    findings = validate_formal_rows(filename, header, [row])
                    self.assertTrue(findings,
                                    f"{filename} 必填字段 {field} 置空后 finalize 校验必须失败")

    def test_whitespace_only_required_field_fails(self):
        for filename, (header, valid_row) in VALID_ROWS.items():
            for field in REQUIRED_BY_FILE[filename]:
                row = list(valid_row)
                row[header.index(field)] = "   "
                with self.subTest(filename=filename, field=field):
                    self.assertTrue(upload_errors(filename, header, [row]),
                                    f"{filename} {field} 纯空格后上传校验必须失败")
                    self.assertTrue(validate_formal_rows(filename, header, [row]))

    def test_header_only_files_remain_valid(self):
        for filename, (header, _) in VALID_ROWS.items():
            with self.subTest(filename=filename):
                self.assertEqual(upload_errors(filename, header, []), [],
                                f"{filename} 只有表头没有数据时上传校验必须合法")
                self.assertEqual(validate_formal_rows(filename, header, []), [])

    def test_valid_samples_keep_passing(self):
        for filename, (header, valid_row) in VALID_ROWS.items():
            with self.subTest(filename=filename):
                self.assertEqual(upload_errors(filename, header, [valid_row]), [],
                                f"{filename} 合法样例必须通过上传校验")
                self.assertEqual(validate_formal_rows(filename, header, [valid_row]), [],
                                f"{filename} 合法样例必须通过 finalize 校验")


class NameAndFormatContractTests(unittest.TestCase):
    def test_business_object_name_empty_fails(self):
        header, valid_row = VALID_ROWS["business_objects.csv"]
        row = list(valid_row)
        row[header.index("业务对象名称")] = ""
        self.assertTrue(upload_errors("business_objects.csv", header, [row]))
        codes = {item.code for item in validate_formal_rows("business_objects.csv", header, [row])}
        self.assertIn("V0001_FORMAL_BUSINESS_OBJECT_INCOMPLETE", codes)

    def test_attribute_name_with_latin_letters_fails(self):
        header, valid_row = VALID_ROWS["business_attributes.csv"]
        row = list(valid_row)
        row[header.index("业务属性名称")] = "订单Amount"
        self.assertTrue(upload_errors("business_attributes.csv", header, [row]))
        self.assertTrue(validate_formal_rows("business_attributes.csv", header, [row]))

    def test_english_name_in_english_column_passes(self):
        header, valid_row = VALID_ROWS["business_attributes.csv"]
        self.assertEqual(upload_errors("business_attributes.csv", header, [valid_row]), [])
        self.assertEqual(validate_formal_rows("business_attributes.csv", header, [valid_row]), [])

    def test_invalid_boolean_enum_integer_code_fail(self):
        cases = [
            ("logical_entities.csv", "是否主逻辑实体", "是"),
            ("entity_relations.csv", "关系分类", "错误分类"),
            ("entity_relations.csv", "关系基数", "1:9"),
            ("business_object_relations.csv", "关系类型", "不是类型"),
            ("business_attributes.csv", "数据类型", "VARCHAR"),
            ("business_attributes.csv", "数据长度", "-5"),
            ("business_attributes.csv", "业务属性英文名称", "order code"),
            ("business_rules.csv", "规则编码", "R000001"),
            ("actions.csv", "动作类型", "执行"),
            ("actions.csv", "动作编码", "ACT1"),
            ("actions.csv", "动作英文名", "create order"),
            ("merged_elements.csv", "相似度", "1.5"),
            ("merged_elements.csv", "元素类型", "NOPE"),
            ("merged_elements.csv", "原名称集合", "RM001"),
        ]
        for filename, field, bad_value in cases:
            header, valid_row = VALID_ROWS[filename]
            row = list(valid_row)
            row[header.index(field)] = bad_value
            with self.subTest(filename=filename, field=field, value=bad_value):
                self.assertTrue(upload_errors(filename, header, [row]))
                self.assertTrue(validate_formal_rows(filename, header, [row]))

    def test_status_primary_terminal_requires_terminal(self):
        header, valid_row = VALID_ROWS["statuses.csv"]
        row = list(valid_row)
        row[header.index("是否主终态")] = "Y"
        self.assertTrue(upload_errors("statuses.csv", header, [row]))
        self.assertTrue(validate_formal_rows("statuses.csv", header, [row]))

    def test_main_entity_must_be_unique_per_business_object(self):
        header, valid_row = VALID_ROWS["logical_entities.csv"]
        first = list(valid_row)
        second = list(valid_row)
        second[header.index("逻辑实体编码")] = "LE0002"
        second[header.index("逻辑实体名称")] = "采购明细实体"
        self.assertTrue(upload_errors("logical_entities.csv", header, [first, second]))
        codes = {item.code for item in validate_formal_rows(
            "logical_entities.csv", header, [first, second])}
        self.assertIn("V0001_FORMAL_MAIN_ENTITY_COUNT", codes)

    def test_duplicate_codes_fail(self):
        for filename, (header, valid_row) in VALID_ROWS.items():
            if filename == "integration_report.csv":
                # 检核报告没有稳定编码身份，不做文件内唯一校验。
                continue
            duplicate = list(valid_row)
            with self.subTest(filename=filename):
                findings = validate_formal_rows(filename, header, [valid_row, duplicate])
                self.assertTrue(any(item.code == "V0001_DUPLICATE_FORMAL_CODE"
                                    or item.code == "V0001_DUPLICATE_BUSINESS_OBJECT_NAME"
                                    or item.code == "V0001_DUPLICATE_LOGICAL_ENTITY_NAME"
                                    or item.code == "V0001_DUPLICATE_FORMAL_NAME"
                                    for item in findings),
                                f"{filename} 重复编码必须失败，实际 {[item.code for item in findings]}")


class CrossFileReferenceTests(unittest.TestCase):
    def test_entity_reference_missing_fails(self):
        header, valid_row = VALID_ROWS["logical_entities.csv"]
        row = list(valid_row)
        row[header.index("业务对象编码")] = "BO_MISSING"
        findings = validate_formal_rows(
            "logical_entities.csv", header, [row],
            references={"businessObjectCodes": {"BO0001"}})
        self.assertIn("FORMAL_REFERENCE_NOT_FOUND", {item.code for item in findings})

    def test_action_business_object_reference_fails(self):
        header, valid_row = VALID_ROWS["actions.csv"]
        row = list(valid_row)
        row[header.index("业务对象编码")] = "BO_MISSING"
        findings = validate_formal_rows(
            "actions.csv", header, [row],
            references={"businessObjectCodes": {"BO0001"}})
        self.assertIn("FORMAL_REFERENCE_NOT_FOUND", {item.code for item in findings})

    def test_relation_entity_and_attribute_references_fail(self):
        header, valid_row = VALID_ROWS["entity_relations.csv"]
        row = list(valid_row)
        row[header.index("目标逻辑实体编码")] = "LE_MISSING"
        findings = validate_formal_rows(
            "entity_relations.csv", header, [row],
            references={"logicalEntityCodes": {"LE0001", "LE0002"},
                        "businessAttributeCodes": set()})
        self.assertIn("FORMAL_REFERENCE_NOT_FOUND", {item.code for item in findings})

        row2 = list(valid_row)
        row2[header.index("源业务属性编码")] = "BA_MISSING"
        findings = validate_formal_rows(
            "entity_relations.csv", header, [row2],
            references={"logicalEntityCodes": {"LE0001", "LE0002"},
                        "businessAttributeCodes": {"BA0001"}})
        self.assertIn("FORMAL_REFERENCE_NOT_FOUND", {item.code for item in findings})

    def test_object_relation_and_status_references_fail(self):
        header, valid_row = VALID_ROWS["business_object_relations.csv"]
        row = list(valid_row)
        row[header.index("目标业务对象编码")] = "BO_MISSING"
        findings = validate_formal_rows(
            "business_object_relations.csv", header, [row],
            references={"businessObjectCodes": {"BO0001", "BO0002"}})
        self.assertIn("FORMAL_REFERENCE_NOT_FOUND", {item.code for item in findings})

        status_header, status_row = VALID_ROWS["statuses.csv"]
        bad_status = list(status_row)
        bad_status[status_header.index("业务对象编码")] = "BO_MISSING"
        findings = validate_formal_rows(
            "statuses.csv", status_header, [bad_status],
            references={"businessObjectCodes": {"BO0001"}})
        self.assertIn("FORMAL_REFERENCE_NOT_FOUND", {item.code for item in findings})


class FormalEligibilityGateTests(unittest.TestCase):
    def write_output(self, root, filename, header, rows):
        output = Path(root) / "output"
        output.mkdir(parents=True, exist_ok=True)
        (output / filename).write_bytes(to_csv(header, rows))
        return output

    def test_ineligible_attribute_row_blocks_finalize(self):
        state = {"businessAttributes": [
            {"业务属性编码": "BA0001", "逻辑实体编码": "LE0001", "formalStatus": "CANDIDATE"},
        ]}
        header, valid_row = VALID_ROWS["business_attributes.csv"]
        with tempfile.TemporaryDirectory() as root:
            output = self.write_output(root, "business_attributes.csv", header, [valid_row])
            result = finalize_semantic_model(
                Path(root) / "work", state, output_dir=output,
                required_outputs=["business_attributes.csv"],
                context={"expectedFiles": ["business_attributes.csv"], "taskType": "modeling"})
            self.assertEqual(result["status"], "FAILED")
            self.assertIn("FORMAL_OUTPUT_INELIGIBLE_ROW",
                          {issue.code for issue in result["issues"]})

    def test_ineligible_relation_row_blocks_finalize(self):
        state = {"relationDecisions": [{
            "relationId": "REL0001", "sourceEntity": "LE0001", "targetEntity": "LE0002",
            "relationType": "REFERENCE", "status": "CANDIDATE",
            "evidenceTypes": [], "evidenceLevel": "UNKNOWN",
        }]}
        header, valid_row = VALID_ROWS["entity_relations.csv"]
        with tempfile.TemporaryDirectory() as root:
            output = self.write_output(root, "entity_relations.csv", header, [valid_row])
            result = finalize_semantic_model(
                Path(root) / "work", state, output_dir=output,
                required_outputs=["entity_relations.csv"],
                context={"expectedFiles": ["entity_relations.csv"], "taskType": "modeling"})
            self.assertEqual(result["status"], "FAILED")
            self.assertIn("FORMAL_OUTPUT_INELIGIBLE_ROW",
                          {issue.code for issue in result["issues"]})

    def test_semantic_warnings_never_block(self):
        state = {
            "ruleDecisions": [{
                "ruleId": "R0000001", "ruleType": "INTEGRITY_CONSTRAINT",
                "decision": "CANDIDATE", "enforcement": "NOT_ENFORCED",
                "evidenceTypes": ["OBSERVED_PATTERN"], "provenance": ["profile.sql"],
                "sampleCount": 100, "violationCount": 0,
            }],
            "indicatorDecisions": [{
                "indicatorId": "M0001", "name": "订单数", "status": "CANDIDATE",
                "aggregationSemantics": "UNKNOWN",
            }],
        }
        rule_header, rule_row = VALID_ROWS["business_rules.csv"]
        metric_header, metric_row = VALID_ROWS["metrics.csv"]
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "output"
            output.mkdir(parents=True, exist_ok=True)
            (output / "business_rules.csv").write_bytes(to_csv(rule_header, [rule_row]))
            (output / "metrics.csv").write_bytes(to_csv(metric_header, [metric_row]))
            result = finalize_semantic_model(
                Path(root) / "work", state, output_dir=output,
                required_outputs=["business_rules.csv", "metrics.csv"],
                context={"expectedFiles": ["business_rules.csv", "metrics.csv"],
                         "taskType": "modeling"})
            self.assertEqual(result["status"], "PASSED")
            warning_codes = {issue.code for issue in result["issues"]
                             if issue.severity == "WARNING"}
            self.assertIn("UNCONFIRMED_RULE_IN_FORMAL_OUTPUT", warning_codes)
            self.assertIn("UNSUPPORTED_FORMAL_INDICATOR", warning_codes)
            self.assertFalse(any(issue.severity == "ERROR" for issue in result["issues"]))

    def test_weak_definition_is_warning_not_blocker(self):
        state = {"businessObjectDecisions": [{
            "candidateCode": "BO0001", "candidateName": "采购订单",
            "memberEntityIds": ["LE0001"], "confidence": "90",
            "r1": {"status": "PASS", "evidence": "[R1_SOURCE] 证据"},
            "r2": {"status": "PASS", "evidence": "[R2_SOURCE] 证据"},
            "r3": {"status": "PASS", "evidence": "[R3_SOURCE] 证据"},
            "r4": {"status": "PASS", "evidence": "[R4_SOURCE] 证据"},
            "r5": {"status": "PASS", "evidence": "[R5_SOURCE] 证据"},
        }]}
        header, valid_row = VALID_ROWS["business_objects.csv"]
        weak = list(valid_row)
        weak[header.index("业务对象定义")] = weak[header.index("业务对象名称")]
        with tempfile.TemporaryDirectory() as root:
            output = self.write_output(root, "business_objects.csv", header, [weak])
            result = finalize_semantic_model(
                Path(root) / "work", state, output_dir=output,
                required_outputs=["business_objects.csv"],
                context={"expectedFiles": ["business_objects.csv"], "taskType": "modeling"})
            self.assertEqual(result["status"], "PASSED")
            stage_codes = {code for row in result["stages"]
                           for code in (row.get("issueCodes") or [])}
            self.assertIn("V0001_DESCRIPTION_MISSING", stage_codes)


class UploadFinalizeConsistencyTests(unittest.TestCase):
    def test_upload_and_finalize_agree_on_format_errors(self):
        for filename, (header, valid_row) in VALID_ROWS.items():
            for field in REQUIRED_BY_FILE[filename]:
                row = list(valid_row)
                row[header.index(field)] = ""
                with self.subTest(filename=filename, field=field):
                    upload = upload_errors(filename, header, [row])
                    finalize = validate_formal_rows(filename, header, [row])
                    self.assertTrue(upload, "上传必须失败")
                    self.assertTrue(finalize, "finalize 必须失败")

    def test_upload_does_not_run_semantic_gate_but_runs_contract(self):
        header, valid_row = VALID_ROWS["business_objects.csv"]
        bad = list(valid_row)
        bad[header.index("业务对象定义")] = ""
        with tempfile.TemporaryDirectory() as root, \
                patch.object(oc_codex_server, "validate_modeling_evidence",
                             side_effect=AssertionError("upload must not run semantic gate")):
            errors = oc_codex_server.validate_modeling_upload_artifact(
                "business_objects.csv", to_csv(header, [bad]), root)
            self.assertTrue(errors)
            header_only = to_csv(VALID_ROWS["logical_entities.csv"][0], [])
            self.assertEqual(
                oc_codex_server.validate_modeling_upload_artifact(
                    "logical_entities.csv", header_only, root), [])

    def test_47313_and_47314_share_one_contract_chain(self):
        import standalone_modeling_server  # noqa: F401
        import open_claude.modeling_rule_registry as rule_registry
        header, valid_row = VALID_ROWS["business_objects.csv"]
        with patch.object(oc_codex_server, "validate_row_contract",
                          wraps=oc_codex_server.validate_row_contract) as web_mock:
            oc_codex_server.validate_modeling_csv("business_objects.csv",
                                                  to_csv(header, [valid_row]))
            self.assertTrue(web_mock.called)
        with patch.object(rule_registry, "validate_row_contract",
                          wraps=rule_registry.validate_row_contract) as finalize_mock:
            state = {"businessObjectDecisions": [{
                "candidateCode": "BO0001", "candidateName": "采购订单",
                "memberEntityIds": ["LE0001"], "confidence": "90",
                "r1": {"status": "PASS", "evidence": "[R1_SOURCE] 证据"},
                "r2": {"status": "PASS", "evidence": "[R2_SOURCE] 证据"},
                "r3": {"status": "PASS", "evidence": "[R3_SOURCE] 证据"},
                "r4": {"status": "PASS", "evidence": "[R4_SOURCE] 证据"},
                "r5": {"status": "PASS", "evidence": "[R5_SOURCE] 证据"},
            }]}
            with tempfile.TemporaryDirectory() as root:
                output = Path(root) / "output"
                output.mkdir(parents=True, exist_ok=True)
                (output / "business_objects.csv").write_bytes(to_csv(header, [valid_row]))
                finalize_semantic_model(
                    Path(root) / "work", state, output_dir=output,
                    required_outputs=["business_objects.csv"],
                    context={"expectedFiles": ["business_objects.csv"], "taskType": "modeling"})
                self.assertTrue(finalize_mock.called)
        # Both bindings point at the same shared function object, so the web
        # (47313) and standalone (47314) chains execute one contract.
        from open_claude.modeling_csv_contract import validate_row_contract as shared
        self.assertIs(oc_codex_server.validate_row_contract, shared)
        self.assertIs(rule_registry.validate_row_contract, shared)
        # The standalone service validates artifacts through the same finalize.
        from open_claude.modeling_reliability import finalize_semantic_model as shared_finalize
        self.assertIs(shared_finalize, finalize_semantic_model)


class ContractConfigConsistencyTests(unittest.TestCase):
    def test_contract_headers_match_server_header_maps(self):
        for name, expected in oc_codex_server._INTEGRATION_HEADERS.items():
            self.assertEqual(list(CONTRACTS[name].headers), expected, name)
        for name, expected in oc_codex_server._MODELING_HEADERS.items():
            self.assertEqual(list(CONTRACTS[name].headers), expected, name)

    def test_contract_references_declared_fields(self):
        for name, contract in CONTRACTS.items():
            for field in (*contract.required, *contract.boolean, *contract.enum,
                          *contract.non_negative_int, *contract.code_pattern,
                          *contract.chinese_name, *contract.english_identifier,
                          *contract.json_array, *contract.numeric_range):
                self.assertIn(field, contract.headers,
                              f"{name} 契约字段 {field} 不在表头中")
            for fields in contract.unique:
                for field in fields:
                    self.assertIn(field, contract.headers,
                                  f"{name} 唯一字段 {field} 不在表头中")
            for field, _index in contract.references:
                self.assertIn(field, contract.headers,
                              f"{name} 引用字段 {field} 不在表头中")


if __name__ == "__main__":
    unittest.main()
