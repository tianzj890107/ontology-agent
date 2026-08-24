"""The v0.0.1 data-model rule registry.

This module is deliberately small and dependency free.  It is the single
catalogue for the 49 rules in ``数据模型建模规范v0.0.1`` and the entry point
for checks that can be made deterministically.  It does not promote a
candidate to a formal model: formal checks are applied only to rows that are
already being exported as formal output.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from open_claude.modeling_csv_contract import (
    logical_entity_assignment_statuses,
    validate_row_contract,
)


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


_MAIN_FLAG_KEYS = (
    "mainflag", "mainFlag", "isMain", "is_main", "mainEntity", "main_entity",
    "是否主逻辑实体",
)
_BUSINESS_OBJECT_KEYS = (
    "businessObjectCode", "business_object_code", "业务对象编码",
    "businessObjectId", "business_object_id", "candidateCode", "candidate_code",
)
_ENTITY_KEYS = (
    "logicalEntityCode", "logical_entity_code", "逻辑实体编码",
    "logicalEntity", "logical_entity", "entityId", "entity_id", "code", "id",
)
_ATTRIBUTE_NAME_KEYS = ("业务属性名称", "attributeName", "attribute_name", "name")
_ATTRIBUTE_DEFINITION_KEYS = (
    "业务属性定义", "attributeDefinition", "attribute_definition", "definition",
    "description", "说明",
)


def _nullable_text(value: Any) -> str:
    """Normalize empty/reference-null cells without changing business names."""
    value = _text(value)
    return "" if value.upper() in {"NONE", "NULL", "N/A", "NA", "-"} else value


def _row_value(row: Mapping[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        if key in row:
            value = _nullable_text(row.get(key))
            if value:
                return value
    return ""


def _confirmed_business_object_codes(state: Mapping[str, Any] | None) -> set[str]:
    if not isinstance(state, Mapping):
        return set()
    records = _records(state, (
        "businessObjectDecisions", "business_object_decisions",
        "businessObjects", "business_objects",
    ))
    confirmed = set()
    for record in records:
        status = _status(record.get("decision") or record.get("status") or
                         record.get("businessObjectStatus"))
        if status != "CONFIRMED":
            continue
        code = _row_value(record, ("candidateCode", "candidate_code", "businessObjectCode",
                                   "business_object_code", "业务对象编码", "code", "id"))
        if code:
            confirmed.add(code)
    return confirmed


def logical_entity_main_flag(row: Mapping[str, Any],
                             state: Mapping[str, Any] | None = None) -> str:
    """Derive the v0.0.1 main flag without promoting an unresolved entity.

    A logical entity remains in the model even when it has no formal Business
    Object.  Such an entity is never a main entity.  If a state supplies
    Business Object decisions, only CONFIRMED objects may retain an explicit
    ``Y``.  The function is intentionally a normalizer for generation/state
    producers; it never renames an entity or an attribute.
    """
    business_object = _row_value(row, _BUSINESS_OBJECT_KEYS)
    if not business_object:
        return "N"
    confirmed = _confirmed_business_object_codes(state)
    decision_records = _records(state or {}, ("businessObjectDecisions", "business_object_decisions")) \
        if isinstance(state, Mapping) else []
    if decision_records and business_object not in confirmed:
        return "N"
    if confirmed and business_object not in confirmed:
        return "N"
    assignment = _status(row.get("businessObjectAssignmentStatus") or
                         row.get("business_object_assignment_status") or
                         row.get("assignmentStatus") or
                         row.get("业务对象归属状态"))
    if assignment and assignment != "ASSIGNED":
        return "N"
    for key in _MAIN_FLAG_KEYS:
        if key in row and _text(row.get(key)):
            return "Y" if _status(row.get(key)) in {"Y", "YES", "TRUE", "1"} else "N"
    role = _status(row.get("role") or row.get("entityRole") or row.get("entity_role") or
                   row.get("type") or row.get("实体角色"))
    return "Y" if role in {
        "CANDIDATE_MAIN_ENTITY", "MASTER_DATA_ENTITY", "REFERENCE_DATA_ENTITY",
        "OBSERVATION_EVENT_ENTITY", "DOCUMENT_CONTENT_ENTITY", "RELATIONSHIP_ENTITY",
        "MAIN", "MAIN_ENTITY", "OWNER", "OWNER_ENTITY",
    } else "N"


def normalize_logical_entity_main_flags(rows: Iterable[Mapping[str, Any]],
                                         state: Mapping[str, Any] | None = None
                                         ) -> list[dict[str, Any]]:
    """Normalize generated logical-entity records while preserving all rows."""
    normalized = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        item = dict(row)
        flag = logical_entity_main_flag(item, state)
        present = False
        for key in _MAIN_FLAG_KEYS:
            if key in item:
                item[key] = flag
                present = True
        if not present:
            item["mainFlag"] = flag
        normalized.append(item)
    return normalized


def _attribute_entity(row: Mapping[str, Any]) -> str:
    return _row_value(row, _ENTITY_KEYS)


def _attribute_name(row: Mapping[str, Any]) -> str:
    return _row_value(row, _ATTRIBUTE_NAME_KEYS)


def _attribute_definition(row: Mapping[str, Any]) -> str:
    return re.sub(r"\s+", "", _row_value(row, _ATTRIBUTE_DEFINITION_KEYS))


def _definitions_are_clearly_different(left: str, right: str) -> bool:
    """Conservatively identify obvious same-name/different-meaning pairs."""
    if not left or not right or left == right or left in right or right in left:
        return False
    ratio = SequenceMatcher(None, left, right).ratio()
    common = len(set(left) & set(right)) / max(1, min(len(left), len(right)))
    return ratio < 0.55 and common < 0.65


def duplicate_formal_attribute_name_findings(rows: Iterable[Mapping[str, Any]]) -> list[RuleFinding]:
    """Apply v0.0.1's logical-entity-scoped attribute-name rule."""
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        entity = _attribute_entity(row)
        name = _attribute_name(row)
        if entity and name:
            groups.setdefault((entity, name), []).append(row)
    findings: list[RuleFinding] = []
    for (entity, name), duplicates in groups.items():
        if len(duplicates) > 1:
            findings.append(_finding(
                "V0001_DUPLICATE_FORMAL_NAME", ERROR,
                f"逻辑实体 {entity} 内业务属性名称 {name} 重复",
                39, "BUSINESS_ATTRIBUTE", f"{entity}:{name}",
                details={"scope": "logical_entity", "logicalEntity": entity,
                         "attributeName": name, "count": len(duplicates)},
            ))
    by_name: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    for (entity, name), values in groups.items():
        by_name.setdefault(name, []).extend((entity, row) for row in values)
    for name, values in by_name.items():
        entities = sorted({entity for entity, _ in values})
        if len(entities) < 2:
            continue
        for index, (left_entity, left) in enumerate(values):
            for right_entity, right in values[index + 1:]:
                if left_entity == right_entity:
                    continue
                left_definition = _attribute_definition(left)
                right_definition = _attribute_definition(right)
                if _definitions_are_clearly_different(left_definition, right_definition):
                    findings.append(_finding(
                        "V0001_DUPLICATE_FORMAL_NAME", WARNING,
                        f"不同逻辑实体的业务属性名称 {name} 定义明显不同，需核对同名异义",
                        39, "BUSINESS_ATTRIBUTE", name,
                        details={"scope": "cross_entity_semantic_review",
                                 "logicalEntities": [left_entity, right_entity],
                                 "attributeName": name},
                    ))
                    break
            else:
                continue
            break
    return findings


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
        findings.append(_finding("V0001_DUPLICATE_BUSINESS_OBJECT_NAME", ERROR,
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
    confirmed_business_objects = _confirmed_business_object_codes(state)
    business_object_decisions = _records(state, ("businessObjectDecisions", "business_object_decisions"))
    seen_main_flags: set[tuple[str, str, str]] = set()
    for row in entity_records:
        explicit_flag = _row_value(row, _MAIN_FLAG_KEYS).upper()
        if explicit_flag != "Y":
            continue
        entity_id = _row_value(row, _ENTITY_KEYS)
        business_object = _row_value(row, _BUSINESS_OBJECT_KEYS)
        marker = (entity_id, business_object, explicit_flag)
        if marker in seen_main_flags:
            continue
        seen_main_flags.add(marker)
        if not business_object:
            findings.append(_finding(
                "V0001_MAIN_FLAG_WITHOUT_BUSINESS_OBJECT", ERROR,
                f"逻辑实体 {entity_id or '(未命名)'} 未归属业务对象时不能为主逻辑实体",
                29, "LOGICAL_ENTITY", entity_id,
            ))
        elif ((business_object_decisions or confirmed_business_objects)
              and business_object not in confirmed_business_objects):
            findings.append(_finding(
                "V0001_MAIN_FLAG_WITHOUT_CONFIRMED_BUSINESS_OBJECT", ERROR,
                f"逻辑实体 {entity_id or '(未命名)'} 归属的业务对象 {business_object} 不是 CONFIRMED，不能为主逻辑实体",
                29, "LOGICAL_ENTITY", entity_id,
            ))
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
    # Business attribute names are unique within their logical entity, not
    # globally.  Keep this check on the formal/canonical attribute collection;
    # allAttributes may legitimately contain technical and candidate fields.
    findings.extend(duplicate_formal_attribute_name_findings(attributes))
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
                         state: Mapping[str, Any] | None = None,
                         references: Mapping[str, set[str]] | None = None) -> list[RuleFinding]:
    """Validate only rows that are about to enter a formal CSV.

    This function never examines candidates as if they were formal rows.  It
    is called by final-output validation, not by the upload syntax path.

    Deterministic per-row contract rules (required fields, booleans, enums,
    codes, uniqueness, conditional structure) come from the shared
    ``modeling_csv_contract`` registry so upload and finalize cannot drift.
    The checks below add the state-dependent/eligibility judgments (formal
    business-object decisions, main-flag ownership, logical keys) and the
    semantic-quality WARNINGs that deliberately never block.
    """
    name = _text(filename).lower().split("/")[-1]
    findings = []
    data = [dict(zip(header, row)) for row in rows if row and any(_text(v) for v in row)]
    artifact_type = _artifact_type_for(name)
    # Conditional business-object fields in logical_entities.csv are judged
    # against the audit state, never inferred from an empty CSV cell.
    assignment_statuses = (logical_entity_assignment_statuses(state)
                           if isinstance(state, Mapping) else None)
    for finding in validate_row_contract(filename, header, rows, references=references,
                                         assignment_statuses=assignment_statuses):
        code, rule_number = _contract_rule_mapping(name, finding)
        findings.append(_finding(code, finding.severity, finding.message, rule_number,
                                 artifact_type, finding.artifact_id,
                                 details={"field": finding.field, "row": finding.row}))
    if name == "business_objects.csv":
        # Empty definition is a deterministic format error handled by the
        # contract (V0001_FORMAL_BUSINESS_OBJECT_DEFINITION_MISSING).  A
        # present-but-weak definition stays a non-blocking quality WARNING.
        for row in data:
            object_name = _text(row.get("业务对象名称"))
            definition = _text(row.get("业务对象定义"))
            if object_name and definition and definition == object_name:
                findings.append(_finding("V0001_DESCRIPTION_MISSING", WARNING,
                                         f"正式业务对象 {_text(row.get('业务对象编码'))} 的业务定义与名称完全相同，质量不足",
                                         17, "BUSINESS_OBJECT", _text(row.get("业务对象编码"))))
    elif name == "logical_entities.csv":
        confirmed_business_objects = _confirmed_business_object_codes(state)
        decision_records = _records(state or {}, ("businessObjectDecisions", "business_object_decisions")) \
            if isinstance(state, Mapping) else []
        for row in data:
            entity_id = _row_value(row, ("逻辑实体编码", "logicalEntityCode", "code", "id"))
            business_object = _nullable_text(row.get("业务对象编码"))
            main_flag = _row_value(row, _MAIN_FLAG_KEYS).upper()
            if main_flag != "Y":
                continue
            if not business_object:
                continue
            if ((decision_records or confirmed_business_objects)
                    and business_object not in confirmed_business_objects):
                findings.append(_finding(
                    "V0001_MAIN_FLAG_WITHOUT_CONFIRMED_BUSINESS_OBJECT", ERROR,
                    f"逻辑实体 {entity_id or '(未命名)'} 归属的业务对象 {business_object} 不是 CONFIRMED，不能保留主逻辑实体标记",
                    29, "LOGICAL_ENTITY", entity_id,
                    details={"businessObjectCode": business_object,
                             "confirmedBusinessObjects": sorted(confirmed_business_objects),
                             "mainFlag": "Y"},
                ))
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
        for row in data:
            value = _text(row.get("业务属性名称"))
            if re.search(r"[&+/*-]", value):
                findings.append(_finding("V0001_ATTRIBUTE_SPECIAL_CHARACTER", WARNING,
                                         f"业务属性 {value} 含有不推荐的特殊字符", 42,
                                         "BUSINESS_ATTRIBUTE", value))
        findings.extend(duplicate_formal_attribute_name_findings(data))
    elif name in {"entity_relations.csv", "entity_relationships.csv"}:
        for row in data:
            identifier = _text(row.get("关系编码"))
            cardinality = _text(row.get("关系基数"))
            if cardinality == "M:N":
                findings.append(_finding("V0001_FORMAL_MANY_TO_MANY", ERROR,
                                         f"正式关系 {identifier} 不能直接使用 M:N，必须拆分关系实体", 49,
                                         "ENTITY_RELATION", identifier))
    return findings


_CONTRACT_REQUIRED_CODE_OVERRIDES = {
    "business_objects.csv": {
        "业务对象编码": "V0001_FORMAL_BUSINESS_OBJECT_INCOMPLETE",
        "业务对象名称": "V0001_FORMAL_BUSINESS_OBJECT_INCOMPLETE",
        "业务对象定义": "V0001_FORMAL_BUSINESS_OBJECT_DEFINITION_MISSING",
    },
    "entity_relations.csv": {
        "关系基数": "V0001_FORMAL_CARDINALITY_MISSING",
    },
    "entity_relationships.csv": {
        "关系基数": "V0001_FORMAL_CARDINALITY_MISSING",
    },
}

_CONTRACT_RULE_NUMBERS = {
    "business_objects.csv": 17,
    "logical_entities.csv": 34,
    "business_attributes.csv": 38,
    "entity_relations.csv": 47,
    "entity_relationships.csv": 47,
    "business_object_relations.csv": 43,
    "business_object_relationships.csv": 43,
    "object_relations.csv": 43,
    "statuses.csv": 10,
    "status.csv": 10,
    "business_object_statuses.csv": 10,
    "events.csv": 12,
    "event.csv": 12,
    "business_events.csv": 12,
    "business_rules.csv": 41,
    "rules.csv": 41,
    "terms.csv": 39,
    "business_terms.csv": 39,
    "metrics.csv": 36,
    "indicator.csv": 36,
    "indicators.csv": 36,
    "integration_report.csv": 17,
    "merged_elements.csv": 42,
    "pending_elements.csv": 42,
    "conflict_elements.csv": 42,
    "missing_elements.csv": 42,
}

_CONTRACT_ARTIFACT_TYPES = {
    "business_objects.csv": "BUSINESS_OBJECT",
    "logical_entities.csv": "LOGICAL_ENTITY",
    "business_attributes.csv": "BUSINESS_ATTRIBUTE",
    "entity_relations.csv": "ENTITY_RELATION",
    "entity_relationships.csv": "ENTITY_RELATION",
    "business_object_relations.csv": "BUSINESS_OBJECT_RELATION",
    "business_object_relationships.csv": "BUSINESS_OBJECT_RELATION",
    "object_relations.csv": "BUSINESS_OBJECT_RELATION",
    "statuses.csv": "STATUS",
    "status.csv": "STATUS",
    "business_object_statuses.csv": "STATUS",
    "events.csv": "EVENT",
    "event.csv": "EVENT",
    "business_events.csv": "EVENT",
    "business_rules.csv": "BUSINESS_RULE",
    "rules.csv": "BUSINESS_RULE",
    "terms.csv": "TERM",
    "business_terms.csv": "TERM",
    "metrics.csv": "INDICATOR",
    "indicator.csv": "INDICATOR",
    "indicators.csv": "INDICATOR",
    "integration_report.csv": "OUTPUT",
    "merged_elements.csv": "OUTPUT",
    "pending_elements.csv": "OUTPUT",
    "conflict_elements.csv": "OUTPUT",
    "missing_elements.csv": "OUTPUT",
}


def _artifact_type_for(filename: str) -> str:
    name = _text(filename).lower().split("/")[-1]
    return _CONTRACT_ARTIFACT_TYPES.get(name, "OUTPUT")


def _contract_rule_mapping(filename: str, finding) -> tuple[str, int]:
    name = _text(filename).lower().split("/")[-1]
    code = finding.code
    if code == "FORMAL_CONTRACT_REQUIRED_FIELD":
        code = (_CONTRACT_REQUIRED_CODE_OVERRIDES.get(name, {}).get(finding.field) or code)
    rule_number = _CONTRACT_RULE_NUMBERS.get(name, 42)
    return code, rule_number
