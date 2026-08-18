"""The v0.0.1 data-model rule registry.

This module is deliberately small and dependency free.  It is the single
catalogue for the 49 rules in ``数据模型建模规范v0.0.1`` and the entry point
for checks that can be made deterministically.  It does not promote a
candidate to a formal model: formal checks are applied only to rows that are
already being exported as formal output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


FORMAL = "FORMAL"
AUDIT = "AUDIT"
ERROR = "ERROR"
WARNING = "WARNING"
PASS = "PASS"
UNKNOWN = "UNKNOWN"
UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class RuleSpec:
    number: int
    output: str
    element: str
    name: str
    phase: str
    enforcement: str
    check: str
    note: str


@dataclass(frozen=True)
class RuleFinding:
    code: str
    severity: str
    message: str
    rule_number: int
    artifact_type: str
    artifact_id: str = ""
    details: Mapping[str, Any] = None


def _spec(number, output, element, name, phase, enforcement, check, note=""):
    return RuleSpec(number, output, element, name, phase, enforcement, check, note)


# The names and numbering intentionally mirror the v0.0.1 workbook.  The
# registry is data, not a second prose specification.
V0001_RULES = (
    _spec(1, "modeling_state", "主题域分类", "与BA对齐", "P1", "EVIDENCE", "topic_domain_alignment"),
    _spec(2, "modeling_state", "主题域分类", "全局唯一", "P2", "QUALITY", "unique_topic_domain"),
    _spec(3, "modeling_state", "主题域分类", "与BA对齐", "P1", "EVIDENCE", "topic_domain_alignment"),
    _spec(4, "modeling_state", "主题域分组", "全局唯一", "P2", "QUALITY", "unique_topic_group"),
    _spec(5, "modeling_state", "主题域", "与BA对齐", "P1", "EVIDENCE", "topic_domain_alignment"),
    _spec(6, "modeling_state", "主题域", "全局唯一", "P2", "QUALITY", "unique_topic_domain"),
    _spec(7, "business_objects.csv", "业务对象", "业务意义", "P1", "EVIDENCE", "business_object_evidence"),
    _spec(8, "business_objects.csv", "业务对象", "稳定身份", "P1", "EVIDENCE", "business_object_evidence"),
    _spec(9, "business_objects.csv", "业务对象", "相对独立并有一组实体描述", "P1", "EVIDENCE", "business_object_evidence"),
    _spec(10, "business_objects.csv", "业务对象", "生命周期和状态变化", "P1", "EVIDENCE", "business_object_evidence"),
    _spec(11, "business_objects.csv", "业务对象", "责任主体可确权", "P1", "EVIDENCE", "business_object_evidence"),
    _spec(12, "business_objects.csv", "业务对象", "可实例化", "P1", "EVIDENCE", "business_object_evidence"),
    _spec(13, "business_objects.csv", "业务对象", "名称唯一", "P2", "QUALITY", "name_policy"),
    _spec(14, "business_objects.csv", "业务对象", "名词命名", "P2", "QUALITY", "name_policy"),
    _spec(15, "business_objects.csv", "业务对象", "符合行规", "P2", "QUALITY", "name_policy"),
    _spec(16, "business_objects.csv", "业务对象", "编码唯一", "P0", "HARD_FORMAL", "unique_code"),
    _spec(17, "business_objects.csv", "业务对象", "描述内容完整", "P2", "QUALITY", "description_quality"),
    _spec(18, "logical_entities.csv", "逻辑实体", "一组属性集合", "P1", "EVIDENCE", "entity_attribute_set"),
    _spec(19, "logical_entities.csv", "逻辑实体", "遵循三范式", "P2", "QUALITY", "normal_form"),
    _spec(20, "logical_entities.csv", "逻辑实体", "剔除技术数据和衍生数据", "P1", "EVIDENCE", "technical_field_policy"),
    _spec(21, "logical_entities.csv", "逻辑实体", "关系实体归属原则", "P1", "EVIDENCE", "relationship_entity_ownership"),
    _spec(22, "logical_entities.csv", "逻辑实体", "名称唯一", "P2", "QUALITY", "name_policy"),
    _spec(23, "logical_entities.csv", "逻辑实体", "名词命名", "P2", "QUALITY", "name_policy"),
    _spec(24, "logical_entities.csv", "逻辑实体", "避免虚词", "P2", "QUALITY", "name_policy"),
    _spec(25, "logical_entities.csv", "逻辑实体", "符合行规", "P2", "QUALITY", "name_policy"),
    _spec(26, "logical_entities.csv", "逻辑实体", "关系实体命名规范", "P2", "QUALITY", "name_policy"),
    _spec(27, "logical_entities.csv", "逻辑实体", "剔除特定关键字", "P2", "QUALITY", "name_policy"),
    _spec(28, "logical_entities.csv", "逻辑实体", "编码唯一", "P0", "HARD_FORMAL", "unique_code"),
    _spec(29, "logical_entities.csv", "逻辑实体", "主逻辑实体唯一", "P0", "HARD_FORMAL", "single_main_entity"),
    _spec(30, "logical_entities.csv", "逻辑实体", "必须有主键", "P0", "HARD_FORMAL", "logical_primary_key"),
    _spec(31, "logical_entities.csv", "逻辑实体", "主键稳定", "P1", "EVIDENCE", "key_semantics"),
    _spec(32, "logical_entities.csv", "逻辑实体", "主键有业务含义", "P1", "EVIDENCE", "key_semantics"),
    _spec(33, "logical_entities.csv", "逻辑实体", "实体归属唯一", "P0", "HARD_FORMAL", "entity_assignment"),
    _spec(34, "logical_entities.csv", "逻辑实体", "描述内容完整", "P2", "QUALITY", "description_quality"),
    _spec(35, "business_attributes.csv", "业务属性", "原子性", "P2", "QUALITY", "attribute_atomicity"),
    _spec(36, "business_attributes.csv", "业务属性", "必要性", "P2", "QUALITY", "attribute_necessity"),
    _spec(37, "business_attributes.csv", "业务属性", "剔除技术字段", "P1", "EVIDENCE", "technical_field_policy"),
    _spec(38, "business_attributes.csv", "业务属性", "业务词汇", "P2", "QUALITY", "name_policy"),
    _spec(39, "business_attributes.csv", "业务属性", "名称贯标", "P2", "QUALITY", "name_policy"),
    _spec(40, "business_attributes.csv", "业务属性", "顾名思义", "P2", "QUALITY", "name_policy"),
    _spec(41, "business_attributes.csv", "业务属性", "词汇简练", "P2", "QUALITY", "name_policy"),
    _spec(42, "business_attributes.csv", "业务属性", "少用特殊字符", "P0", "HARD_FORMAL", "attribute_name_format"),
    _spec(43, "entity_relations.csv", "概念模型图", "避免孤岛", "P2", "QUALITY", "graph_isolation"),
    _spec(44, "entity_relations.csv", "概念模型图", "关系基数", "P1", "EVIDENCE", "cardinality"),
    _spec(45, "entity_relations.csv", "逻辑模型图", "与概念模型保持一致", "P1", "EVIDENCE", "concept_logical_consistency"),
    _spec(46, "entity_relations.csv", "逻辑模型图", "避免孤岛", "P2", "QUALITY", "graph_isolation"),
    _spec(47, "entity_relations.csv", "逻辑模型图", "关系基数", "P0", "HARD_FORMAL", "cardinality"),
    _spec(48, "entity_relations.csv", "逻辑模型图", "主外键依赖关系", "P0", "HARD_FORMAL", "foreign_key_mapping"),
    _spec(49, "entity_relations.csv", "逻辑模型图", "禁止M:N关系", "P0", "HARD_FORMAL", "no_many_to_many"),
)

RULE_REGISTRY = {rule.number: rule for rule in V0001_RULES}
RULES_BY_OUTPUT = {}
for _rule in V0001_RULES:
    RULES_BY_OUTPUT.setdefault(_rule.output, []).append(_rule.number)


def registry_matrix() -> list[dict[str, Any]]:
    return [
        {"rule": rule.number, "output": rule.output, "element": rule.element,
         "name": rule.name, "phase": rule.phase, "enforcement": rule.enforcement,
         "check": rule.check, "note": rule.note}
        for rule in V0001_RULES
    ]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _status(value: Any) -> str:
    return _text(value).upper().replace("-", "_")


def _finding(code: str, severity: str, message: str, number: int,
             artifact_type: str, artifact_id: str = "", details=None) -> RuleFinding:
    return RuleFinding(code, severity, message, number, artifact_type, artifact_id,
                       details or {})


def _records(state: Mapping[str, Any], keys: Iterable[str]) -> list[Mapping[str, Any]]:
    result = []
    for key in keys:
        value = state.get(key)
        if isinstance(value, Mapping):
            value = list(value.values())
        if isinstance(value, list):
            result.extend(item for item in value if isinstance(item, Mapping))
    return result


def _formal_row(row: Mapping[str, Any]) -> bool:
    status = _status(row.get("decision") or row.get("status") or row.get("metricStatus"))
    assignment = _status(row.get("businessObjectAssignmentStatus") or
                         row.get("business_object_assignment_status"))
    return bool(row.get("formalOutput") or row.get("formal_output") or
                status == "CONFIRMED" or assignment == "ASSIGNED")


def _unique(rows: Iterable[Mapping[str, Any]], fields: tuple[str, ...]) -> list[tuple[str, int]]:
    seen = {}
    duplicates = []
    for index, row in enumerate(rows, 1):
        value = next((_text(row.get(field)) for field in fields if _text(row.get(field))), "")
        if value and value in seen:
            duplicates.append((value, index))
        elif value:
            seen[value] = index
    return duplicates


def validate_audit_registry(state: Mapping[str, Any] | None) -> list[RuleFinding]:
    """Validate decision identity without applying formal-output completeness.

    Candidates remain valid audit records.  Only contradictory audit identity
    or explicit status data is rejected here; no missing business fact is
    synthesized.
    """
    if not isinstance(state, Mapping):
        return []
    findings = []
    for value, _ in _unique(_records(state, ("businessObjectDecisions", "business_object_decisions")),
                            ("candidateCode", "candidate_code", "code", "id")):
        findings.append(_finding("V0001_DUPLICATE_BUSINESS_OBJECT_CODE", ERROR,
                                 f"业务对象决策编码 {value} 重复", 16, "BUSINESS_OBJECT", value))
    for value, _ in _unique(_records(state, ("logicalEntityDecisions", "logical_entity_decisions", "entities")),
                            ("entityId", "logicalEntity", "logical_entity", "code", "id")):
        findings.append(_finding("V0001_DUPLICATE_LOGICAL_ENTITY_CODE", ERROR,
                                 f"逻辑实体决策编码 {value} 重复", 28, "LOGICAL_ENTITY", value))
    for value, _ in _unique(_records(state, ("relationDecisions", "relation_decisions")),
                            ("relationId", "relation_id", "relationDecisionId", "id")):
        findings.append(_finding("V0001_DUPLICATE_RELATION_CODE", ERROR,
                                 f"关系决策编码 {value} 重复", 48, "ENTITY_RELATION", value))
    return findings


def _explicit_registry_statuses(state: Mapping[str, Any]) -> dict[int, str]:
    """Read producer-supplied rule statuses without inferring missing ones.

    Producers may expose statuses as ``ruleStatuses`` or as a list of records
    carrying ``ruleNumber``/``status``.  This adapter gives every registry
    rule the same deterministic dispatch path while preserving UNKNOWN by
    omission: an absent status is not treated as FAIL or PASS.
    """
    result: dict[int, str] = {}
    containers = [state]
    for key in ("ruleStatuses", "rule_statuses", "v0001RuleStatuses", "v0001_rule_statuses"):
        raw = state.get(key)
        if isinstance(raw, Mapping):
            for number, value in raw.items():
                try:
                    number = int(number)
                except (TypeError, ValueError):
                    continue
                status = _status(value.get("status") if isinstance(value, Mapping) else value)
                if 1 <= number <= 49 and status:
                    result[number] = status
        elif isinstance(raw, list):
            containers.extend(item for item in raw if isinstance(item, Mapping))
    for record in containers[1:]:
        number = record.get("ruleNumber") or record.get("rule_number") or record.get("number")
        try:
            number = int(number)
        except (TypeError, ValueError):
            continue
        status = _status(record.get("status") or record.get("decision"))
        if 1 <= number <= 49 and status:
            result[number] = status
    return result


def validate_registered_rule_statuses(state: Mapping[str, Any] | None) -> list[RuleFinding]:
    """Validate all explicitly supplied v0.0.1 rule statuses via one path."""
    if not isinstance(state, Mapping):
        return []
    findings = []
    for number, status in sorted(_explicit_registry_statuses(state).items()):
        if status not in {PASS, "FAIL", UNKNOWN, UNRESOLVED}:
            findings.append(_finding("V0001_RULE_STATUS_INVALID", ERROR,
                                     f"v0.0.1 规则 {number} 状态 {status} 非法",
                                     number, RULE_REGISTRY[number].output,
                                     details={"status": status}))
            continue
        if status == "FAIL":
            rule = RULE_REGISTRY[number]
            severity = ERROR if rule.enforcement == "HARD_FORMAL" else WARNING
            findings.append(_finding(f"V0001_RULE_{number}_FAIL", severity,
                                     f"v0.0.1 规则 {number} 显式判定为 FAIL",
                                     number, rule.output,
                                     details={"enforcement": rule.enforcement,
                                              "phase": rule.phase}))
    return findings


def _explicit_status(record: Mapping[str, Any], *names: str) -> str:
    for name in names:
        if name in record:
            return _status(record.get(name))
    return ""


def validate_v0001_state(state: Mapping[str, Any] | None) -> list[RuleFinding]:
    """Dispatch state-level v0.0.1 checks without filling semantic gaps.

    A state record may carry an explicit evidence-backed status such as
    ``normalFormStatus`` or ``keySemanticsStatus``.  The registry validates
    that explicit decision; it never derives that status from a table name or
    from a missing field.  Candidate records are allowed to remain UNKNOWN or
    UNRESOLVED.
    """
    if not isinstance(state, Mapping):
        return []
    findings = list(validate_audit_registry(state))
    findings.extend(validate_registered_rule_statuses(state))

    bo_records = _records(state, ("businessObjectDecisions", "business_object_decisions"))
    confirmed_bo = [row for row in bo_records if _status(row.get("decision") or row.get("status")) == "CONFIRMED"]
    for value, _ in _unique(confirmed_bo, ("candidateName", "candidate_name", "name")):
        findings.append(_finding("V0001_DUPLICATE_FORMAL_NAME", ERROR,
                                 f"正式业务对象名称 {value} 重复", 13, "BUSINESS_OBJECT", value))
    for row in confirmed_bo:
        code = _text(row.get("candidateCode") or row.get("candidate_code") or row.get("code"))
        checks = (
            (7, ("businessMeaningStatus", "business_meaning_status"), "业务意义证据"),
            (8, ("identityStatus", "identity_status"), "稳定身份证据"),
            (9, ("independenceStatus", "independence_status"), "独立性证据"),
            (10, ("lifecycleStatus", "lifecycle_status"), "生命周期证据"),
            (11, ("ownerStatus", "owner_status", "governanceStatus"), "责任主体证据"),
            (12, ("instantiationStatus", "instantiation_status"), "可实例化证据"),
        )
        for number, names, label in checks:
            status = _explicit_status(row, *names)
            if status == "FAIL":
                findings.append(_finding(f"V0001_BUSINESS_OBJECT_RULE_{number}_FAIL", ERROR,
                                         f"正式业务对象 {code} 缺少或违反{label}", number,
                                         "BUSINESS_OBJECT", code))

    entity_records = _records(state, ("logicalEntityDecisions", "logical_entity_decisions", "entities"))
    formal_entities = [row for row in entity_records if _formal_row(row)]
    for value, _ in _unique(formal_entities, ("logicalEntity", "logical_entity", "entityId", "code", "id")):
        # The identity duplicate is already reported by validate_audit_registry;
        # this branch is intentionally reserved for a future formal-only code.
        if not value:
            findings.append(_finding("V0001_FORMAL_LOGICAL_ENTITY_CODE_MISSING", ERROR,
                                     "正式逻辑实体缺少稳定编码", 28, "LOGICAL_ENTITY"))
    for row in formal_entities:
        entity_id = _text(row.get("logicalEntity") or row.get("logical_entity") or
                           row.get("entityId") or row.get("code") or row.get("id"))
        for number, names, label in (
            (19, ("normalFormStatus", "normal_form_status"), "三范式"),
            (20, ("technicalDataStatus", "technical_data_status"), "技术/衍生数据排除"),
            (21, ("ownershipStatus", "ownership_status"), "关系实体归属"),
            (30, ("primaryKeyStatus", "primary_key_status"), "主键"),
            (31, ("keyStabilityStatus", "key_stability_status"), "主键稳定性"),
            (32, ("keySemanticsStatus", "key_semantics_status"), "主键业务含义"),
            (34, ("descriptionStatus", "description_status"), "实体描述"),
        ):
            if _explicit_status(row, *names) == "FAIL":
                severity = ERROR if number in {30, 33} else WARNING
                findings.append(_finding(f"V0001_LOGICAL_ENTITY_RULE_{number}_FAIL", severity,
                                         f"逻辑实体 {entity_id} 的{label}校验失败", number,
                                         "LOGICAL_ENTITY", entity_id))

    attributes = _records(state, ("businessAttributes", "business_attributes", "attributeDecisions"))
    for row in attributes:
        if not _formal_row(row):
            continue
        attribute_id = _text(row.get("attributeId") or row.get("businessAttributeId") or
                             row.get("code") or row.get("id"))
        for number, names, label in (
            (35, ("atomicityStatus", "atomicity_status"), "原子性"),
            (36, ("necessityStatus", "necessity_status"), "必要性"),
            (37, ("technicalFieldStatus", "technical_field_status"), "技术字段排除"),
        ):
            if _explicit_status(row, *names) == "FAIL":
                findings.append(_finding(f"V0001_ATTRIBUTE_RULE_{number}_FAIL", WARNING,
                                         f"业务属性 {attribute_id} 的{label}校验失败", number,
                                         "BUSINESS_ATTRIBUTE", attribute_id))

    relations = _records(state, ("relationDecisions", "relation_decisions"))
    for row in relations:
        if _status(row.get("status") or row.get("decision")) != "CONFIRMED":
            continue
        relation_id = _text(row.get("relationId") or row.get("relation_id") or
                            row.get("relationDecisionId") or row.get("id"))
        cardinality = _text(row.get("cardinality") or row.get("关系基数"))
        if cardinality == "M:N":
            findings.append(_finding("V0001_CONFIRMED_MANY_TO_MANY", ERROR,
                                     f"CONFIRMED 关系 {relation_id} 不能直接使用 M:N", 49,
                                     "ENTITY_RELATION", relation_id))
        if "cardinality" in row or "关系基数" in row:
            if not cardinality:
                findings.append(_finding("V0001_CONFIRMED_CARDINALITY_MISSING", ERROR,
                                         f"CONFIRMED 关系 {relation_id} 缺少关系基数", 47,
                                         "ENTITY_RELATION", relation_id))
        for number, names, label in (
            (44, ("conceptCardinalityStatus", "concept_cardinality_status"), "概念关系基数"),
            (45, ("conceptConsistencyStatus", "concept_consistency_status"), "概念/逻辑模型一致性"),
            (48, ("foreignKeyMappingStatus", "foreign_key_mapping_status"), "主外键依赖"),
        ):
            if _explicit_status(row, *names) == "FAIL":
                findings.append(_finding(f"V0001_RELATION_RULE_{number}_FAIL", ERROR,
                                         f"关系 {relation_id} 的{label}校验失败", number,
                                         "ENTITY_RELATION", relation_id))

    # P2 graph quality checks are advisory and only run when the caller has
    # actually supplied a graph.  An absent graph is not evidence of an
    # island, and this function never creates an edge to remove one.
    for key_name, artifact_type, rule_number in (
        ("businessObjectRelations", "BUSINESS_OBJECT", 43),
        ("business_object_relations", "BUSINESS_OBJECT", 43),
        ("entityRelations", "LOGICAL_ENTITY", 46),
        ("entity_relations", "LOGICAL_ENTITY", 46),
    ):
        graph = state.get(key_name)
        if not isinstance(graph, list) or not graph:
            continue
        nodes = set()
        connected = set()
        for relation in graph:
            if not isinstance(relation, Mapping):
                continue
            source = _text(relation.get("sourceEntity") or relation.get("source") or
                           relation.get("sourceBusinessObject"))
            target = _text(relation.get("targetEntity") or relation.get("target") or
                           relation.get("targetBusinessObject"))
            if source:
                nodes.add(source)
            if target:
                nodes.add(target)
            if source and target:
                connected.update((source, target))
        declared_nodes = state.get("businessObjects" if rule_number == 43 else "entities")
        if isinstance(declared_nodes, list):
            for node in declared_nodes:
                if isinstance(node, Mapping):
                    node_id = _text(node.get("businessObjectId") or node.get("entityId") or
                                    node.get("code") or node.get("id"))
                    if node_id:
                        nodes.add(node_id)
        for node in sorted(nodes - connected):
            findings.append(_finding("V0001_GRAPH_ISOLATION", WARNING,
                                     f"{artifact_type} {node} 是孤岛，不能为了消除孤岛自动创建关系",
                                     rule_number, artifact_type, node))
        break
    return findings


def validate_formal_rows(filename: str, header: list[str], rows: list[list[str]],
                         state: Mapping[str, Any] | None = None) -> list[RuleFinding]:
    """Validate only rows that are about to enter a formal CSV.

    This function never examines candidates as if they were formal rows.  It
    is called by final-output validation, not by the upload syntax path.
    """
    name = _text(filename).lower().split("/")[-1]
    findings = []
    data = [dict(zip(header, row)) for row in rows if row and any(_text(v) for v in row)]
    if name == "business_objects.csv":
        duplicates = _unique(data, ("业务对象编码",))
        for value, _ in duplicates:
            findings.append(_finding("V0001_DUPLICATE_FORMAL_CODE", ERROR,
                                     f"正式业务对象编码 {value} 重复", 16, "BUSINESS_OBJECT", value))
        for row in data:
            code = _text(row.get("业务对象编码"))
            if not _text(row.get("业务对象名称")) or not _text(row.get("业务对象定义")):
                findings.append(_finding("V0001_FORMAL_BUSINESS_OBJECT_INCOMPLETE", ERROR,
                                         f"正式业务对象 {code} 缺少名称或定义", 17, "BUSINESS_OBJECT", code))
        for value, _ in _unique(data, ("业务对象名称",)):
            findings.append(_finding("V0001_DUPLICATE_FORMAL_NAME", ERROR,
                                     f"正式业务对象名称 {value} 重复", 13, "BUSINESS_OBJECT", value))
        for row in data:
            if _text(row.get("业务对象名称")) and not _text(row.get("业务对象定义")):
                findings.append(_finding("V0001_DESCRIPTION_MISSING", ERROR,
                                         f"正式业务对象 {_text(row.get('业务对象编码'))} 缺少业务定义",
                                         17, "BUSINESS_OBJECT", _text(row.get("业务对象编码"))))
    elif name == "logical_entities.csv":
        for value, _ in _unique(data, ("逻辑实体编码",)):
            findings.append(_finding("V0001_DUPLICATE_FORMAL_CODE", ERROR,
                                     f"正式逻辑实体编码 {value} 重复", 28, "LOGICAL_ENTITY", value))
        for value, _ in _unique(data, ("逻辑实体名称",)):
            findings.append(_finding("V0001_DUPLICATE_FORMAL_NAME", ERROR,
                                     f"正式逻辑实体名称 {value} 重复", 22, "LOGICAL_ENTITY", value))
        groups = {}
        for row in data:
            key = _text(row.get("业务对象编码")) or _text(row.get("业务对象名称"))
            groups.setdefault(key, []).append(row)
        for key, group in groups.items():
            if key and sum(_text(row.get("是否主逻辑实体")).upper() == "Y" for row in group) != 1:
                findings.append(_finding("V0001_FORMAL_MAIN_ENTITY_COUNT", ERROR,
                                         f"正式业务对象 {key} 必须且只能有一个主逻辑实体", 29,
                                         "LOGICAL_ENTITY", key))
        # A missing key can only be judged when the corresponding formal
        # attribute records are available.  If metadata is absent we leave it
        # unresolved instead of inventing a key or failing the candidate.
        attributes = []
        if isinstance(state, Mapping):
            for key_name in ("businessAttributes", "business_attributes", "attributeDecisions"):
                value = state.get(key_name)
                if isinstance(value, list):
                    attributes.extend(item for item in value if isinstance(item, Mapping))
        if attributes:
            for row in data:
                entity_id = _text(row.get("逻辑实体编码"))
                related = [item for item in attributes
                           if _text(item.get("logicalEntityCode") or item.get("logical_entity_code") or
                                    item.get("逻辑实体编码")) == entity_id]
                if related and not any(_text(item.get("是否逻辑主键") or
                                             item.get("isLogicalKey") or
                                             item.get("is_logical_key")).upper() == "Y"
                                       for item in related):
                    findings.append(_finding("V0001_FORMAL_LOGICAL_KEY_MISSING", ERROR,
                                             f"正式逻辑实体 {entity_id} 没有逻辑主键", 30,
                                             "LOGICAL_ENTITY", entity_id))
    elif name == "business_attributes.csv":
        for value, _ in _unique(data, ("业务属性编码",)):
            findings.append(_finding("V0001_DUPLICATE_FORMAL_CODE", ERROR,
                                     f"正式业务属性编码 {value} 重复", 35, "BUSINESS_ATTRIBUTE", value))
        for row in data:
            value = _text(row.get("业务属性名称"))
            if re.search(r"[&+/*-]", value):
                findings.append(_finding("V0001_ATTRIBUTE_SPECIAL_CHARACTER", ERROR,
                                         f"业务属性 {value} 含有不允许的特殊字符", 42,
                                         "BUSINESS_ATTRIBUTE", value))
        for value, _ in _unique(data, ("业务属性名称",)):
            findings.append(_finding("V0001_DUPLICATE_FORMAL_NAME", WARNING,
                                     f"业务属性名称 {value} 重复，需核对是否同义或同名异义", 39,
                                     "BUSINESS_ATTRIBUTE", value))
    elif name in {"entity_relations.csv", "entity_relationships.csv"}:
        for value, _ in _unique(data, ("关系编码",)):
            findings.append(_finding("V0001_DUPLICATE_FORMAL_CODE", ERROR,
                                     f"正式关系编码 {value} 重复", 48, "ENTITY_RELATION", value))
        for row in data:
            identifier = _text(row.get("关系编码"))
            cardinality = _text(row.get("关系基数"))
            if not cardinality:
                findings.append(_finding("V0001_FORMAL_CARDINALITY_MISSING", ERROR,
                                         f"正式关系 {identifier} 缺少关系基数", 47,
                                         "ENTITY_RELATION", identifier))
            elif cardinality == "M:N":
                findings.append(_finding("V0001_FORMAL_MANY_TO_MANY", ERROR,
                                         f"正式关系 {identifier} 不能直接使用 M:N，必须拆分关系实体", 49,
                                         "ENTITY_RELATION", identifier))
    elif name in {"terms.csv", "business_terms.csv"}:
        for value, _ in _unique(data, ("术语编码",)):
            findings.append(_finding("V0001_DUPLICATE_FORMAL_CODE", ERROR,
                                     f"正式术语编码 {value} 重复", 39, "TERM", value))
    elif name in {"indicators.csv", "indicator.csv", "metrics.csv"}:
        for value, _ in _unique(data, ("指标编码",)):
            findings.append(_finding("V0001_DUPLICATE_FORMAL_CODE", ERROR,
                                     f"正式指标编码 {value} 重复", 36, "INDICATOR", value))
    return findings
