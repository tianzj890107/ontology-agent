"""Central per-row field contract for formal modeling CSVs (v0.0.1).

This module is the single data registry shared by the upload gate
(``oc_codex_server.validate_modeling_csv`` / ``validate_integration_csv``) and
the semantic finalize gate (``modeling_rule_registry.validate_formal_rows``).
Deterministic format rules — required fields, Y/N booleans, enum values,
integer/number formats, code patterns, in-file uniqueness, Chinese/English
name separation, JSON-array and similarity fields — are declared here once so
the two gates cannot drift.

Semantic judgments (R1-R5 evidence, evidence sufficiency, formal eligibility,
cross-file decision consistency) are deliberately not part of this registry.
Cross-file *reference existence* is declared here as a deterministic rule but
only evaluated when the caller supplies a reference index (finalize).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

# ---------------------------------------------------------------- dictionaries
RELATION_CATEGORIES = ("关联", "依赖", "继承", "组合", "聚合")
CARDINALITIES = ("1:1", "1:N", "N:1", "M:N")
DATA_TYPES = ("字符串", "整数", "小数", "日期", "布尔", "文本")
INDICATOR_TYPES = ("原子指标", "复合指标")
AGGREGATION_TYPES = ("求和", "计数", "平均值", "最大值", "最小值", "去重计数")
TIME_DIMENSIONS = ("日", "周", "月", "季", "年", "实时")
OBJECT_RELATION_TYPES = (
    "组合", "聚合", "分类", "关联", "依赖", "隶属", "等价",
    "组合关系", "聚合关系", "分类关系", "关联关系", "依赖关系", "隶属关系", "等价关系",
)
ELEMENT_TYPES = (
    "BUSINESS_OBJECT", "LOGICAL_ENTITY", "BUSINESS_ATTRIBUTE", "ENTITY_RELATION",
    "RULE", "BUSINESS_OBJECT_RELATION", "STATUS", "EVENT",
)
INTEGRATION_RESULT_TYPES = ("已合并", "已修正", "待确认", "冲突", "缺失", "无需处理")

# Finding codes.  The V0001_* codes below intentionally match the existing
# registry so finalize classification and tests stay stable.
REQUIRED_FIELD = "FORMAL_CONTRACT_REQUIRED_FIELD"
BOOLEAN = "FORMAL_CONTRACT_BOOLEAN"
ENUM = "FORMAL_CONTRACT_ENUM"
INTEGER = "FORMAL_CONTRACT_INTEGER"
CODE_FORMAT = "FORMAL_CONTRACT_CODE_FORMAT"
UNIQUE = "V0001_DUPLICATE_FORMAL_CODE"
CHINESE_NAME = "FORMAL_CONTRACT_CHINESE_NAME"
ENGLISH_FORMAT = "FORMAL_CONTRACT_ENGLISH_FORMAT"
JSON_ARRAY = "FORMAL_CONTRACT_JSON_ARRAY"
NUMERIC_RANGE = "FORMAL_CONTRACT_NUMERIC_RANGE"
CONDITION = "FORMAL_CONTRACT_CONDITION"
REFERENCE_NOT_FOUND = "FORMAL_REFERENCE_NOT_FOUND"
# Logical entities may legitimately carry no business object only when the
# audit state proves an explicit assignment status.  An empty code with no
# audit status is never silently legal.
ASSIGNMENT_STATUS_MISSING = "FORMAL_CONTRACT_ASSIGNMENT_STATUS_MISSING"
ASSIGNMENT_CONFLICT = "FORMAL_CONTRACT_ASSIGNMENT_CONFLICT"

ERROR = "ERROR"


@dataclass(frozen=True)
class ContractFinding:
    code: str
    severity: str
    message: str
    field: str = ""
    row: int = 0
    artifact_id: str = ""


@dataclass(frozen=True)
class CSVContract:
    filename: str
    headers: tuple[str, ...]
    required: tuple[str, ...] = ()
    boolean: tuple[str, ...] = ()
    enum: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    non_negative_int: tuple[str, ...] = ()
    code_pattern: Mapping[str, str] = field(default_factory=dict)
    unique: tuple[tuple[str, ...], ...] = ()
    chinese_name: tuple[str, ...] = ()
    english_identifier: tuple[str, ...] = ()
    json_array: tuple[str, ...] = ()
    numeric_range: Mapping[str, tuple[float | None, float | None]] = field(default_factory=dict)
    # Conditional structural rules (deterministic, header-aware).
    main_entity_count: bool = False          # logical_entities: one Y per business object
    main_flag_requires_business_object: bool = False
    assignment_status_aware: bool = False    # logical_entities: conditional BO code/name
    primary_terminal_implies_terminal: bool = False  # statuses: 主终态=Y -> 终态=Y
    page_display_rule: bool = False          # business_attributes
    # Cross-file reference fields: (column, index key).
    references: tuple[tuple[str, str], ...] = ()


# Logical-entity assignment statuses.  ``UNASSIGNED`` is kept only as a
# legacy alias with the old lenient behavior; new runs must use
# ``NOT_APPLICABLE`` (explicitly not a business object) or ``UNRESOLVED``
# (evidence insufficient).  An empty business-object code never derives
# NOT_APPLICABLE by itself.
LE_ASSIGNMENT_STATUS_ALIASES = {
    "ASSIGNED": "ASSIGNED",
    "NOT_APPLICABLE": "NOT_APPLICABLE",
    "NA": "NOT_APPLICABLE",
    "N_A": "NOT_APPLICABLE",
    "不适用": "NOT_APPLICABLE",
    "非业务对象": "NOT_APPLICABLE",
    "UNASSIGNED": "UNASSIGNED",
    "UNRESOLVED": "UNRESOLVED",
    "UNKNOWN": "UNRESOLVED",
    "PENDING": "UNRESOLVED",
}
LE_ASSIGNMENT_STATUSES = frozenset({"ASSIGNED", "NOT_APPLICABLE", "UNASSIGNED", "UNRESOLVED"})
_ASSIGNMENT_STATUS_KEYS = (
    "businessObjectAssignmentStatus", "business_object_assignment_status",
    "assignmentStatus", "业务对象归属状态",
)
_ASSIGNMENT_CODE_KEYS = ("businessObjectCode", "business_object_code", "业务对象编码")


def logical_entity_assignment_status(entity: Mapping[str, Any]) -> str:
    """Derive one logical entity's business-object assignment status.

    An explicit status wins.  Legacy state without a status falls back to the
    entity's business-object code: a present code means ASSIGNED, an empty
    code means UNRESOLVED.  An empty code is never interpreted as
    NOT_APPLICABLE without explicit audit evidence.
    """
    raw = ""
    for key in _ASSIGNMENT_STATUS_KEYS:
        if key in entity:
            raw = _key(entity.get(key))
            break
    status = LE_ASSIGNMENT_STATUS_ALIASES.get(raw)
    if status is not None:
        return status
    code = _nullable(next((entity.get(key) for key in _ASSIGNMENT_CODE_KEYS if key in entity), ""))
    return "ASSIGNED" if code else "UNRESOLVED"


def logical_entity_assignment_statuses(state: Mapping[str, Any] | None) -> dict[str, str]:
    """Map logical-entity codes to their assignment status for contract checks."""
    if not isinstance(state, Mapping):
        return {}
    result: dict[str, str] = {}
    containers: list[Any] = [state]
    artifacts = state.get("artifacts")
    if isinstance(artifacts, Mapping):
        containers.extend(value for value in artifacts.values() if isinstance(value, Mapping))
    seen: set[int] = set()
    while containers:
        container = containers.pop(0)
        if not isinstance(container, Mapping) or id(container) in seen:
            continue
        seen.add(id(container))
        for key in ("entities", "logicalEntities", "logical_entities", "entityDecisions"):
            value = container.get(key)
            if isinstance(value, Mapping):
                value = list(value.values())
            if not isinstance(value, list):
                continue
            for item in value:
                if not isinstance(item, Mapping):
                    continue
                entity_code = _text(item.get("logicalEntityCode") or item.get("logical_entity_code")
                                    or item.get("逻辑实体编码") or item.get("entityId")
                                    or item.get("entity_id") or item.get("code") or item.get("id"))
                if entity_code:
                    result[entity_code] = logical_entity_assignment_status(item)
    return result


_ALIASES = {
    "entity_relationships.csv": "entity_relations.csv",
    "business_object_relationships.csv": "business_object_relations.csv",
    "object_relations.csv": "business_object_relations.csv",
    "status.csv": "statuses.csv",
    "business_object_statuses.csv": "statuses.csv",
    "event.csv": "events.csv",
    "business_events.csv": "events.csv",
    "rules.csv": "business_rules.csv",
    "business_terms.csv": "terms.csv",
    "indicator.csv": "metrics.csv",
}


def canonical_filename(filename: str) -> str:
    name = str(filename or "").lower().split("/")[-1]
    return _ALIASES.get(name, name)


def contract_for(filename: str) -> CSVContract | None:
    return CONTRACTS.get(canonical_filename(filename))


def contract_headers(filename: str) -> tuple[str, ...] | None:
    contract = contract_for(filename)
    return tuple(contract.headers) if contract is not None else None


CONTRACTS: dict[str, CSVContract] = {
    "business_objects.csv": CSVContract(
        filename="business_objects.csv",
        headers=("业务对象编码", "业务对象名称", "业务对象英文名", "业务对象定义", "数据类别"),
        required=("业务对象编码", "业务对象名称", "业务对象定义"),
        unique=(("业务对象编码",), ("业务对象名称",)),
        chinese_name=("业务对象名称",),
        code_pattern={"业务对象编码": r"^[A-Za-z][A-Za-z0-9_]*$"},
    ),
    "logical_entities.csv": CSVContract(
        filename="logical_entities.csv",
        headers=("业务对象编码", "业务对象名称", "逻辑实体编码", "逻辑实体名称",
                 "逻辑实体英文名", "逻辑实体定义", "是否主逻辑实体", "数据类别"),
        # 业务对象编码/名称是条件必填：ASSIGNED 必填；NOT_APPLICABLE/UNRESOLVED
        # 必须留空。状态来自 modeling_state/决策审计，不在 CSV 中新增列。
        required=("逻辑实体编码", "逻辑实体名称",
                  "逻辑实体定义", "是否主逻辑实体"),
        boolean=("是否主逻辑实体",),
        unique=(("逻辑实体编码",), ("逻辑实体名称",)),
        chinese_name=("业务对象名称", "逻辑实体名称"),
        code_pattern={"业务对象编码": r"^[A-Za-z][A-Za-z0-9_]*$",
                      "逻辑实体编码": r"^[A-Za-z][A-Za-z0-9_]*$"},
        main_entity_count=True,
        main_flag_requires_business_object=True,
        assignment_status_aware=True,
        references=(("业务对象编码", "businessObjectCodes"),),
    ),
    "business_attributes.csv": CSVContract(
        filename="business_attributes.csv",
        headers=("逻辑实体编码", "逻辑实体名称", "业务属性编码", "业务属性名称",
                 "业务属性英文名称", "业务属性定义", "数据类型", "数据长度", "数据精度",
                 "是否物理主键", "是否逻辑主键", "是否唯一", "是否非空", "是否页面显示",
                 "是否层级编码", "是否层级名称"),
        required=("逻辑实体编码", "逻辑实体名称", "业务属性编码", "业务属性名称",
                  "业务属性定义", "数据类型", "是否物理主键", "是否逻辑主键", "是否唯一",
                  "是否非空", "是否页面显示", "是否层级编码", "是否层级名称"),
        boolean=("是否物理主键", "是否逻辑主键", "是否唯一", "是否非空", "是否页面显示",
                 "是否层级编码", "是否层级名称"),
        unique=(("业务属性编码",),),
        chinese_name=("业务属性名称",),
        english_identifier=("业务属性英文名称",),
        enum={"数据类型": DATA_TYPES},
        non_negative_int=("数据长度", "数据精度"),
        code_pattern={"逻辑实体编码": r"^[A-Za-z][A-Za-z0-9_]*$",
                      "业务属性编码": r"^[A-Za-z][A-Za-z0-9_]*$"},
        page_display_rule=True,
        references=(("逻辑实体编码", "logicalEntityCodes"),),
    ),
    "entity_relations.csv": CSVContract(
        filename="entity_relations.csv",
        headers=("关系编码", "源逻辑实体编码", "源逻辑实体名称", "目标逻辑实体编码",
                 "目标逻辑实体名称", "关系分类", "关系中文名称", "关系英文名称", "关系基数",
                 "关系描述", "源业务属性编码", "源关联属性英文名", "源关联属性中文名",
                 "目标业务属性编码", "目标关联属性英文名", "目标关联属性中文名"),
        required=("关系编码", "源逻辑实体编码", "源逻辑实体名称", "目标逻辑实体编码",
                  "目标逻辑实体名称", "关系分类", "关系中文名称", "关系基数", "关系描述"),
        enum={"关系分类": RELATION_CATEGORIES, "关系基数": CARDINALITIES},
        unique=(("关系编码",),),
        chinese_name=("源逻辑实体名称", "目标逻辑实体名称", "关系中文名称"),
        code_pattern={"关系编码": r"^[A-Za-z][A-Za-z0-9_]*$"},
        references=(("源逻辑实体编码", "logicalEntityCodes"),
                    ("目标逻辑实体编码", "logicalEntityCodes"),
                    ("源业务属性编码", "businessAttributeCodes"),
                    ("目标业务属性编码", "businessAttributeCodes")),
    ),
    "business_object_relations.csv": CSVContract(
        filename="business_object_relations.csv",
        headers=("关系编码", "源业务对象编码", "源业务对象名称", "关系类型", "关系英文名称",
                 "关系中文名名称", "目标业务对象编码", "目标业务对象名称", "关系基数", "关系描述"),
        required=("关系编码", "源业务对象编码", "源业务对象名称", "关系类型", "关系中文名名称",
                  "目标业务对象编码", "目标业务对象名称", "关系基数", "关系描述"),
        enum={"关系类型": OBJECT_RELATION_TYPES, "关系基数": CARDINALITIES},
        unique=(("关系编码",),),
        chinese_name=("源业务对象名称", "目标业务对象名称", "关系中文名名称"),
        code_pattern={"关系编码": r"^[A-Za-z][A-Za-z0-9_]*$",
                      "源业务对象编码": r"^[A-Za-z][A-Za-z0-9_]*$",
                      "目标业务对象编码": r"^[A-Za-z][A-Za-z0-9_]*$"},
        references=(("源业务对象编码", "businessObjectCodes"),
                    ("目标业务对象编码", "businessObjectCodes")),
    ),
    "statuses.csv": CSVContract(
        filename="statuses.csv",
        headers=("业务对象编码", "业务对象名称", "状态编码", "状态英文名", "状态中文名",
                 "状态含义", "触发条件", "是否终态", "是否主终态"),
        required=("业务对象编码", "业务对象名称", "状态编码", "状态中文名", "状态含义",
                  "触发条件", "是否终态", "是否主终态"),
        boolean=("是否终态", "是否主终态"),
        unique=(("业务对象编码", "状态编码"),),
        chinese_name=("业务对象名称", "状态中文名"),
        code_pattern={"业务对象编码": r"^[A-Za-z][A-Za-z0-9_]*$",
                      "状态编码": r"^[A-Za-z][A-Za-z0-9_]*$"},
        primary_terminal_implies_terminal=True,
        references=(("业务对象编码", "businessObjectCodes"),),
    ),
    "events.csv": CSVContract(
        filename="events.csv",
        headers=("事件编码", "事件名称", "事件中文名称", "事件含义", "触发结果"),
        required=("事件编码", "事件名称", "事件中文名称", "事件含义", "触发结果"),
        unique=(("事件编码",),),
        chinese_name=("事件中文名称",),
        code_pattern={"事件编码": r"^[A-Za-z][A-Za-z0-9_]*$"},
    ),
    "business_rules.csv": CSVContract(
        filename="business_rules.csv",
        headers=("规则编码", "规则名称", "规则描述", "触发条件", "判断或结果", "处置动作"),
        required=("规则编码", "规则名称", "触发条件", "判断或结果", "处置动作"),
        unique=(("规则编码",),),
        chinese_name=("规则名称",),
        code_pattern={"规则编码": r"^R\d{7}$"},
    ),
    "terms.csv": CSVContract(
        filename="terms.csv",
        headers=("术语编码", "术语名称", "别名", "英文名", "缩略语", "术语定义"),
        required=("术语编码", "术语名称", "术语定义"),
        unique=(("术语编码",),),
        chinese_name=("术语名称",),
        code_pattern={"术语编码": r"^[A-Za-z][A-Za-z0-9_]*$"},
    ),
    "metrics.csv": CSVContract(
        filename="metrics.csv",
        headers=("指标编码", "指标名称", "指标别名", "指标英文名", "指标定义", "计算公式",
                 "统计口径", "指标类型", "来源业务对象", "来源逻辑实体", "来源业务属性",
                 "聚合类型", "时间维度", "计算规则", "过滤条件"),
        required=("指标编码", "指标名称"),
        unique=(("指标编码",), ("指标名称",)),
        chinese_name=("指标名称",),
        enum={"指标类型": INDICATOR_TYPES,
              "聚合类型": AGGREGATION_TYPES,
              "时间维度": TIME_DIMENSIONS},
        code_pattern={"指标编码": r"^[A-Za-z][A-Za-z0-9_]*$"},
    ),
    "integration_report.csv": CSVContract(
        filename="integration_report.csv",
        headers=("检核项", "问题类型", "涉及源模型", "处理结果", "说明"),
        required=("检核项", "问题类型", "处理结果", "说明"),
        enum={"处理结果": INTEGRATION_RESULT_TYPES},
        json_array=("涉及源模型",),
    ),
    "merged_elements.csv": CSVContract(
        filename="merged_elements.csv",
        headers=("整合后名称", "元素类型", "原名称集合", "来源模型", "合并策略", "相似度"),
        required=("整合后名称", "元素类型", "原名称集合", "来源模型", "合并策略", "相似度"),
        enum={"元素类型": ELEMENT_TYPES},
        unique=(("整合后名称",),),
        json_array=("原名称集合", "来源模型"),
        numeric_range={"相似度": (0.0, 1.0)},
    ),
    "pending_elements.csv": CSVContract(
        filename="pending_elements.csv",
        headers=("候选名称 A", "候选名称 B", "推荐名称", "元素类型", "来源模型", "相似度",
                 "待确认原因"),
        required=("候选名称 A", "候选名称 B", "元素类型", "来源模型", "相似度", "待确认原因"),
        enum={"元素类型": ELEMENT_TYPES},
        unique=(("候选名称 A", "候选名称 B"),),
        json_array=("来源模型",),
        numeric_range={"相似度": (0.0, 1.0)},
    ),
    "conflict_elements.csv": CSVContract(
        filename="conflict_elements.csv",
        headers=("元素名称", "冲突类型", "来源模型", "冲突描述", "来源内容"),
        required=("元素名称", "冲突类型", "来源模型", "冲突描述"),
        enum={"冲突类型": ("同名不同义", "同义不同名", "类型冲突", "长度冲突", "主键冲突",
                           "关系冲突", "定义冲突")},
        unique=(("元素名称", "冲突类型"),),
        json_array=("来源模型",),
    ),
    "missing_elements.csv": CSVContract(
        filename="missing_elements.csv",
        headers=("元素名称", "元素类型", "来源模型", "缺失说明"),
        required=("元素名称", "元素类型", "来源模型", "缺失说明"),
        enum={"元素类型": ELEMENT_TYPES},
        unique=(("元素名称", "元素类型", "缺失说明"),),
    ),
}

# Alias entries share the canonical contract but need their own header map so
# both ``oc_codex_server`` header dicts and the validators resolve them.
for _alias, _canonical in _ALIASES.items():
    _contract = CONTRACTS[_canonical]
    CONTRACTS[_alias] = CSVContract(filename=_alias, headers=_contract.headers,
                                    required=_contract.required,
                                    boolean=_contract.boolean,
                                    enum=_contract.enum,
                                    non_negative_int=_contract.non_negative_int,
                                    code_pattern=_contract.code_pattern,
                                    unique=_contract.unique,
                                    chinese_name=_contract.chinese_name,
                                    english_identifier=_contract.english_identifier,
                                    json_array=_contract.json_array,
                                    numeric_range=_contract.numeric_range,
                                    main_entity_count=_contract.main_entity_count,
                                    main_flag_requires_business_object=_contract.main_flag_requires_business_object,
                                    assignment_status_aware=_contract.assignment_status_aware,
                                    primary_terminal_implies_terminal=_contract.primary_terminal_implies_terminal,
                                    page_display_rule=_contract.page_display_rule,
                                    references=_contract.references)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _nullable(value: Any) -> str:
    text = _text(value)
    return "" if text.upper() in {"NONE", "NULL", "N/A", "NA", "-"} else text


def _key(value: Any) -> str:
    return _text(value).upper().replace("-", "_").replace(" ", "_")


def _is_canonical_header(contract: CSVContract, header: Sequence[str]) -> bool:
    return tuple(header) == tuple(contract.headers)


def _row_dicts(header: Sequence[str], rows: Iterable[Sequence[str]]) -> list[tuple[int, Mapping[str, str]]]:
    result = []
    for index, row in enumerate(rows, 2):
        if not row:
            continue
        row = [str(value or "") for value in row]
        if len(row) != len(header):
            continue
        if not any(_text(value) for value in row):
            continue
        result.append((index, dict(zip(header, row))))
    return result


def build_reference_index(rows_by_file: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, set[str]]:
    """Collect formal codes from every formal CSV for cross-file reference checks."""
    index: dict[str, set[str]] = {
        "businessObjectCodes": set(),
        "logicalEntityCodes": set(),
        "businessAttributeCodes": set(),
    }
    for filename, rows in rows_by_file.items():
        name = canonical_filename(filename)
        contract = CONTRACTS.get(name)
        if contract is None:
            continue
        if name == "business_objects.csv":
            index["businessObjectCodes"].update(
                _nullable(row.get("业务对象编码")) for row in rows if _nullable(row.get("业务对象编码")))
        elif name == "logical_entities.csv":
            index["logicalEntityCodes"].update(
                _nullable(row.get("逻辑实体编码")) for row in rows if _nullable(row.get("逻辑实体编码")))
        elif name == "business_attributes.csv":
            index["businessAttributeCodes"].update(
                _nullable(row.get("业务属性编码")) for row in rows if _nullable(row.get("业务属性编码")))
    return index


def validate_row_contract(filename: str, header: Sequence[str], rows: Iterable[Sequence[str]],
                          *, references: Mapping[str, set[str]] | None = None,
                          assignment_statuses: Mapping[str, str] | None = None) -> list[ContractFinding]:
    """Run the deterministic per-row contract for one formal CSV.

    Header-aware rules (required fields, booleans, uniqueness, conditional
    structural rules) run whenever the column exists in the header.  Field
    dictionary rules (enums, integer/number formats, code patterns, name
    languages, JSON arrays, similarity ranges) are only applied when the file
    uses the canonical v0.0.1 header, so legacy simplified artifacts are not
    misjudged against dictionaries they do not declare.  Cross-file reference
    checks require an explicit ``references`` index (semantic finalize).
    """
    contract = contract_for(filename)
    if contract is None:
        return []
    findings: list[ContractFinding] = []
    canonical = _is_canonical_header(contract, header)
    data = _row_dicts(header, rows)
    if not data:
        return findings

    column_index = {name: index for index, name in enumerate(header)}
    for line_no, row in data:
        for field in contract.required:
            if field not in column_index:
                continue
            if not _nullable(row.get(field)):
                findings.append(ContractFinding(
                    code=REQUIRED_FIELD, severity=ERROR,
                    message=f"第 {line_no} 行 {field} 必填，不能为空", field=field, row=line_no,
                    artifact_id=_nullable(row.get(next((f for f in contract.required
                                                        if f in column_index and f != field), field))) or ""))
    # Conditional business-object fields for logical entities.  The formal CSV
    # has no assignment-status column; the audit state maps logical-entity
    # codes to ASSIGNED/NOT_APPLICABLE/UNRESOLVED.  Without an audit status an
    # empty code is an error (requirement: never infer NOT_APPLICABLE from an
    # empty code alone).  ASSIGNED rows must carry both code and name; the
    # other statuses must leave both empty.
    if (contract.assignment_status_aware and "逻辑实体编码" in column_index
            and any(column in column_index for column in
                    ("业务对象编码", "业务对象名称", "是否主逻辑实体"))):
        for line_no, row in data:
            entity_code = _nullable(row.get("逻辑实体编码"))
            if not entity_code:
                continue
            status = _nullable((assignment_statuses or {}).get(entity_code)).upper()
            bo_code = _nullable(row.get("业务对象编码"))
            bo_name = _nullable(row.get("业务对象名称"))
            main_flag = _nullable(row.get("是否主逻辑实体")).upper()
            if status == "ASSIGNED":
                if "业务对象编码" in column_index and not bo_code:
                    findings.append(ContractFinding(
                        code=REQUIRED_FIELD, severity=ERROR,
                        message=f"第 {line_no} 行逻辑实体 {entity_code} 状态为 ASSIGNED，业务对象编码必填",
                        field="业务对象编码", row=line_no, artifact_id=entity_code))
                if "业务对象名称" in column_index and not bo_name:
                    findings.append(ContractFinding(
                        code=REQUIRED_FIELD, severity=ERROR,
                        message=f"第 {line_no} 行逻辑实体 {entity_code} 状态为 ASSIGNED，业务对象名称必填",
                        field="业务对象名称", row=line_no, artifact_id=entity_code))
            elif status in {"NOT_APPLICABLE", "UNRESOLVED", "UNASSIGNED"}:
                if bo_code or bo_name:
                    findings.append(ContractFinding(
                        code=ASSIGNMENT_CONFLICT, severity=ERROR,
                        message=f"第 {line_no} 行逻辑实体 {entity_code} 归属状态为 {status}，"
                                "业务对象编码/名称必须留空",
                        field="业务对象编码", row=line_no, artifact_id=entity_code,
                        ))
            elif bo_code or bo_name:
                # No audit status known: the row behaves like ASSIGNED and
                # must carry the complete code/name pair.
                if "业务对象编码" in column_index and not bo_code:
                    findings.append(ContractFinding(
                        code=REQUIRED_FIELD, severity=ERROR,
                        message=f"第 {line_no} 行逻辑实体 {entity_code} 缺少业务对象编码",
                        field="业务对象编码", row=line_no, artifact_id=entity_code))
                if "业务对象名称" in column_index and not bo_name:
                    findings.append(ContractFinding(
                        code=REQUIRED_FIELD, severity=ERROR,
                        message=f"第 {line_no} 行逻辑实体 {entity_code} 缺少业务对象名称",
                        field="业务对象名称", row=line_no, artifact_id=entity_code))
            elif main_flag != "Y":
                # Empty code, empty name and no audit status: cannot be
                # silently treated as a legal NOT_APPLICABLE row.
                findings.append(ContractFinding(
                    code=ASSIGNMENT_STATUS_MISSING, severity=ERROR,
                    message=f"第 {line_no} 行逻辑实体 {entity_code} 业务对象编码为空，"
                            "但没有可审计的归属状态（ASSIGNED/NOT_APPLICABLE/UNRESOLVED）",
                    field="业务对象编码", row=line_no, artifact_id=entity_code))
    for field in contract.boolean:
        if field not in column_index:
            continue
        value = _nullable(row.get(field)).upper()
        if value not in {"Y", "N"}:
            findings.append(ContractFinding(
                code=BOOLEAN, severity=ERROR,
                message=f"第 {line_no} 行 {field} 必须为 Y 或 N，不能留空或使用其他值",
                field=field, row=line_no, artifact_id=_nullable(row.get(field))))
    if canonical:
        for field, allowed in contract.enum.items():
            if field not in column_index:
                continue
            value = _nullable(row.get(field))
            if value and value not in allowed:
                findings.append(ContractFinding(
                    code=ENUM, severity=ERROR,
                    message=f"第 {line_no} 行 {field}“{value}”不在契约字典 {list(allowed)} 中",
                    field=field, row=line_no, artifact_id=value))
        for field in contract.non_negative_int:
            if field not in column_index:
                continue
            value = _nullable(row.get(field))
            if value and not re.fullmatch(r"\d+", value):
                findings.append(ContractFinding(
                    code=INTEGER, severity=ERROR,
                    message=f"第 {line_no} 行 {field}“{value}”必须是非负整数",
                    field=field, row=line_no, artifact_id=value))
        for field, pattern in contract.code_pattern.items():
            if field not in column_index:
                continue
            value = _nullable(row.get(field))
            if value and not re.fullmatch(pattern, value):
                findings.append(ContractFinding(
                    code=CODE_FORMAT, severity=ERROR,
                    message=f"第 {line_no} 行 {field}“{value}”不符合编码格式 {pattern}",
                    field=field, row=line_no, artifact_id=value))
        for field in contract.chinese_name:
            if field not in column_index:
                continue
            value = _nullable(row.get(field))
            if value and re.search(r"[A-Za-z]", value):
                findings.append(ContractFinding(
                    code=CHINESE_NAME, severity=ERROR,
                    message=f"第 {line_no} 行 {field}“{value}”是中文名称，不能混入英文字母；英文内容应放入对应英文名称列",
                    field=field, row=line_no, artifact_id=value))
        for field in contract.english_identifier:
            if field not in column_index:
                continue
            value = _nullable(row.get(field))
            if value and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value):
                findings.append(ContractFinding(
                    code=ENGLISH_FORMAT, severity=ERROR,
                    message=f"第 {line_no} 行 {field}“{value}”不符合英文标识格式",
                    field=field, row=line_no, artifact_id=value))
        for field in contract.json_array:
            if field not in column_index:
                continue
            value = _nullable(row.get(field))
            if value:
                try:
                    parsed = json.loads(value)
                except ValueError:
                    parsed = None
                if not isinstance(parsed, list):
                    findings.append(ContractFinding(
                        code=JSON_ARRAY, severity=ERROR,
                        message=f"第 {line_no} 行 {field}“{value}”必须是合法 JSON 数组",
                        field=field, row=line_no, artifact_id=value))
        for field, (low, high) in contract.numeric_range.items():
            if field not in column_index:
                continue
            value = _nullable(row.get(field))
            if value:
                try:
                    number = float(value)
                except ValueError:
                    number = None
                if number is None or (low is not None and number < low) or (high is not None and number > high):
                    bounds = f"{low}~{high}" if low is not None and high is not None else "合法范围"
                    findings.append(ContractFinding(
                        code=NUMERIC_RANGE, severity=ERROR,
                        message=f"第 {line_no} 行 {field}“{value}”必须是 {bounds} 之间的数字",
                        field=field, row=line_no, artifact_id=value))

    if contract.main_entity_count and "是否主逻辑实体" in column_index:
        groups: dict[str, list[tuple[int, Mapping[str, str]]]] = {}
        for line_no, row in data:
            key = _nullable(row.get("业务对象编码")) or _nullable(row.get("业务对象名称"))
            if key:
                groups.setdefault(key, []).append((line_no, row))
        for key, entity_rows in groups.items():
            values = [_nullable(row.get("是否主逻辑实体")).upper() for _, row in entity_rows]
            if any(value not in {"Y", "N"} for value in values):
                # The invalid boolean is already a FORMAL_CONTRACT_BOOLEAN
                # finding; do not add a misleading main-entity count on top.
                continue
            count = sum(value == "Y" for value in values)
            if count != 1:
                findings.append(ContractFinding(
                    code="V0001_FORMAL_MAIN_ENTITY_COUNT", severity=ERROR,
                    message=f"正式业务对象 {key} 必须且只能有一个主逻辑实体，实际 {count} 个",
                    row=entity_rows[0][0], artifact_id=key))

    if contract.main_flag_requires_business_object and "是否主逻辑实体" in column_index:
        for line_no, row in data:
            business_object = _nullable(row.get("业务对象编码"))
            main_flag = _nullable(row.get("是否主逻辑实体")).upper()
            if main_flag == "Y" and not business_object:
                findings.append(ContractFinding(
                    code="V0001_MAIN_FLAG_WITHOUT_BUSINESS_OBJECT", severity=ERROR,
                    message=f"第 {line_no} 行未归属业务对象时是否主逻辑实体必须为 N",
                    row=line_no, artifact_id=_nullable(row.get("逻辑实体编码"))))

    if contract.primary_terminal_implies_terminal:
        for line_no, row in data:
            terminal = _nullable(row.get("是否终态")).upper()
            primary_terminal = _nullable(row.get("是否主终态")).upper()
            if primary_terminal == "Y" and terminal != "Y":
                findings.append(ContractFinding(
                    code="V0001_FORMAL_STATUS_PRIMARY_TERMINAL", severity=ERROR,
                    message=f"第 {line_no} 行是否主终态=Y 时是否终态也必须为 Y",
                    row=line_no, artifact_id=_nullable(row.get("状态编码"))))

    if contract.page_display_rule:
        _page_display_findings(contract, header, data, findings)

    for fields in contract.unique:
        seen: dict[tuple[str, ...], int] = {}
        for line_no, row in data:
            key = tuple(_nullable(row.get(field)) for field in fields)
            if not any(key):
                continue
            if key in seen:
                code = _unique_code_for(filename, fields)
                findings.append(ContractFinding(
                    code=code, severity=ERROR,
                    message=f"第 {line_no} 行 {'/'.join(fields)} {key} 与第 {seen[key]} 行重复",
                    field=fields[-1], row=line_no,
                    artifact_id=key[0] if len(fields) == 1 else key[0]))
            else:
                seen[key] = line_no

    if references is not None:
        for field, index_key in contract.references:
            if field not in column_index:
                continue
            for line_no, row in data:
                value = _nullable(row.get(field))
                if not value:
                    continue
                if value not in references.get(index_key, set()):
                    findings.append(ContractFinding(
                        code=REFERENCE_NOT_FOUND, severity=ERROR,
                        message=f"第 {line_no} 行 {field}“{value}”在正式输出中不存在，跨文件引用无效",
                        field=field, row=line_no, artifact_id=value))
    return findings


def _unique_code_for(filename: str, fields: tuple[str, ...]) -> str:
    name = canonical_filename(filename)
    if name == "business_objects.csv" and fields == ("业务对象名称",):
        return "V0001_DUPLICATE_BUSINESS_OBJECT_NAME"
    if name == "logical_entities.csv" and fields == ("逻辑实体名称",):
        return "V0001_DUPLICATE_LOGICAL_ENTITY_NAME"
    if name == "metrics.csv" and fields == ("指标名称",):
        return "V0001_DUPLICATE_FORMAL_NAME"
    return UNIQUE


def _page_display_findings(contract: CSVContract, header: Sequence[str],
                           data: list[tuple[int, Mapping[str, str]]],
                           findings: list[ContractFinding]) -> None:
    indexes = {name: index for index, name in enumerate(header)}
    required = ("逻辑实体编码", "逻辑实体名称", "业务属性名称", "是否逻辑主键", "是否页面显示")
    if any(name not in indexes for name in required):
        return
    groups: dict[str, list[tuple[int, Mapping[str, str]]]] = {}
    for line_no, row in data:
        entity = _nullable(row.get("逻辑实体编码")) or _nullable(row.get("逻辑实体名称"))
        if entity:
            groups.setdefault(entity, []).append((line_no, row))
    for entity_rows in groups.values():
        key_prefixes = set()
        for _, row in entity_rows:
            attr_name = _nullable(row.get("业务属性名称"))
            primary = _nullable(row.get("是否逻辑主键")).upper() == "Y"
            if primary and attr_name.endswith("编码"):
                key_prefixes.add(attr_name[:-2])
        expected_names = {f"{prefix}名称" for prefix in key_prefixes if prefix}
        for line_no, row in entity_rows:
            attr_name = _nullable(row.get("业务属性名称"))
            actual = _nullable(row.get("是否页面显示")).upper()
            expected = "Y" if attr_name in expected_names else "N"
            if actual in {"Y", "N"} and actual != expected:
                findings.append(ContractFinding(
                    code=CONDITION, severity=ERROR,
                    message=f"第 {line_no} 行“{attr_name}”是否页面显示应为 {expected}",
                    field="是否页面显示", row=line_no, artifact_id=attr_name))
