"""Evidence-gated semantic checks for ontology modeling outputs.

The model may keep hypotheses and unresolved gaps in the task's private
``modeling_state.json``.  Only a relation decision that has independently
supported evidence may cross into the formal relation CSV.  Validation in
this module is deliberately read-only: it returns structured issues and
never edits a model or creates a relation.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import tempfile
from enum import Enum
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


CONFIRMED = "CONFIRMED"
CANDIDATE = "CANDIDATE"
UNRESOLVED = "UNRESOLVED"
REJECTED = "REJECTED"
DECISION_STATES = {CONFIRMED, CANDIDATE, UNRESOLVED, REJECTED}
STRUCTURAL_FIX = "STRUCTURAL_FIX"
SEMANTIC_FIX = "SEMANTIC_FIX"

COMPOSITION = "COMPOSITION"
EXTENSION = "EXTENSION"
REFERENCE = "REFERENCE"
TRANSFORMATION = "TRANSFORMATION"
AGGREGATION_RELATION_TYPES = frozenset({COMPOSITION, EXTENSION})

STRONG_EVIDENCE = {
    "FOREIGN_KEY",
    "DECLARED_CONSTRAINT",
    "VIEW_DERIVATION_LINEAGE",
    "VIEW_CALCULATION_LOGIC",
    "ETL_SQL_LINEAGE",
    "CODE_REFERENCE",
    "EXPLICIT_CONFIG",
    "EXISTING_ONTOLOGY",
    "VIEW_SQL_LINEAGE",  # legacy alias; new state should use typed VIEW_* evidence
}
# Kept as a compatibility alias for old state files.  It is deliberately not
# treated as derivation evidence: a JOIN proves query association, not that a
# source was transformed into a target.
LEGACY_LINEAGE_EVIDENCE = {"VIEW_SQL_LINEAGE"}
VIEW_JOIN_EVIDENCE = "VIEW_JOIN_EVIDENCE"
VIEW_DERIVATION_LINEAGE = "VIEW_DERIVATION_LINEAGE"
VIEW_CALCULATION_LOGIC = "VIEW_CALCULATION_LOGIC"
VIEW_FILTER_LOGIC = "VIEW_FILTER_LOGIC"
MODERATE_EVIDENCE = {
    "JOINABILITY",
    "MULTIPLE_FIELD_ALIGNMENT",
    "DATA_PATTERN",
    "DOCUMENTATION",
}
WEAK_EVIDENCE = {
    "TABLE_NAME",
    "COLUMN_NAME",
    "LLM_SEMANTIC_INFERENCE",
    "BUSINESS_COMMON_SENSE",
}
EVIDENCE_REQUIRED_FOR_RELATION = tuple(sorted(STRONG_EVIDENCE | MODERATE_EVIDENCE))
COMPOSITION_SEMANTIC_EVIDENCE = frozenset({
    "EXPLICIT_CONFIG", "EXISTING_ONTOLOGY", "CODE_REFERENCE", "DOCUMENTATION",
})

RULE_EXISTENCE_STATUSES = frozenset({
    "DECLARED", "ENFORCED", "IMPLEMENTED", "OBSERVED_ONLY", "INFERRED", "UNVERIFIED",
})
RULE_EFFECTIVENESS_STATUSES = frozenset({"PASS", "FAIL", "UNKNOWN", "UNRESOLVED"})
METRIC_AGGREGATION_SEMANTICS = frozenset({
    "ADDITIVE", "SEMI_ADDITIVE", "NON_ADDITIVE", "RATIO_OF_SUMS",
    "WEIGHTED_AVERAGE", "SNAPSHOT", "UNKNOWN",
})
LE_ASSIGNMENT_STATUSES = frozenset({"ASSIGNED", "UNASSIGNED", "UNRESOLVED"})

DECISION_AUDIT_TEMPLATE_VERSION = "v0.0.1"

DECISION_AUDIT_FILES = (
    "business_object_decisions.csv",
    "relation_decisions.csv",
    "rule_decisions.csv",
    "indicator_decisions.csv",
    "logical_entity_decisions.csv",
    "validation_report.json",
    "modeling_state.json",
)

BUSINESS_OBJECT_RULE_STATUSES = frozenset({"PASS", "FAIL", "UNKNOWN"})
BUSINESS_OBJECT_DECISION_HEADERS = (
    "候选业务对象编码", "候选业务对象名称", "最终决策",
    "R1状态", "R1证据", "R2状态", "R2证据",
    "R3状态", "R3证据", "R4状态", "R4证据", "R5状态", "R5证据",
    "确认问题", "置信度",
)
BUSINESS_OBJECT_RULES = ("r1", "r2", "r3", "r4", "r5")


class BusinessRuleType(str, Enum):
    INTEGRITY_CONSTRAINT = "INTEGRITY_CONSTRAINT"
    ELIGIBILITY_RULE = "ELIGIBILITY_RULE"
    CALCULATION_RULE = "CALCULATION_RULE"
    STATE_TRANSITION_RULE = "STATE_TRANSITION_RULE"
    ALERT_DETECTION_RULE = "ALERT_DETECTION_RULE"
    DECISION_RULE = "DECISION_RULE"
    UNKNOWN = "UNKNOWN"


class RuleEnforcement(str, Enum):
    ENFORCED = "ENFORCED"
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


class RuleValidationStatus(str, Enum):
    VALIDATED = "VALIDATED"
    SUPPORTED = "SUPPORTED"
    UNRESOLVED = "UNRESOLVED"
    CONFLICTED = "CONFLICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NEEDS_CLASSIFICATION = "NEEDS_CLASSIFICATION"


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: str
    message: str
    artifact_type: str = ""
    artifact_id: str = ""
    evidence_required: tuple[str, ...] = field(default_factory=tuple)
    fix_class: str = SEMANTIC_FIX
    auto_fixable: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "artifactType": self.artifact_type,
            "artifactId": self.artifact_id,
            "evidenceRequired": list(self.evidence_required),
            "fixClass": self.fix_class,
            "autoFixable": self.auto_fixable,
            "details": dict(self.details),
        }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _key(value: Any) -> str:
    return _text(value).upper().replace("-", "_").replace(" ", "_")


def _status(value: Any) -> str:
    normalized = _key(value)
    return {
        "INFERRED": CANDIDATE,
        "PROPOSED": CANDIDATE,
        "UNKNOWN": UNRESOLVED,
        "PENDING": UNRESOLVED,
        "REJECT": REJECTED,
    }.get(normalized, normalized)


def evidence_type(value: Any) -> str:
    if isinstance(value, Mapping):
        value = (value.get("type") or value.get("evidenceType")
                 or value.get("kind") or value.get("sourceType") or "")
    return _key(value)


def evidence_types(decision: Mapping[str, Any]) -> set[str]:
    values: list[Any] = []
    for key in ("evidence", "evidences", "evidenceTypes", "evidence_types", "proof"):
        value = decision.get(key)
        if isinstance(value, list):
            values.extend(value)
        elif value:
            values.append(value)
    direct = decision.get("evidenceType") or decision.get("evidence_type")
    if direct:
        values.append(direct)
    return {item for item in (evidence_type(value) for value in values) if item}


def _evidence_records(decision: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return structured evidence records without promoting labels to facts."""
    records: list[Mapping[str, Any]] = []
    for key in ("evidence", "evidences", "proof"):
        value = decision.get(key)
        if isinstance(value, Mapping):
            records.append(value)
        elif isinstance(value, list):
            records.extend(item for item in value if isinstance(item, Mapping))
    return records


def evidence_ids(decision: Mapping[str, Any]) -> list[str]:
    values = decision.get("evidenceIds") or decision.get("evidence_ids") or []
    if not isinstance(values, list):
        values = [values] if values else []
    result = [_text(value) for value in values if _text(value)]
    for record in _evidence_records(decision):
        value = (record.get("evidenceId") or record.get("evidence_id")
                 or record.get("id") or record.get("ref"))
        if _text(value) and _text(value) not in result:
            result.append(_text(value))
    return sorted(result)


def evidence_families(decision: Mapping[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("evidenceFamilies", "evidence_families", "evidenceFamily"):
        value = decision.get(key)
        values.extend(value if isinstance(value, list) else [value] if value else [])
    values.extend(record.get("evidenceFamily") or record.get("family")
                  for record in _evidence_records(decision))
    return sorted({_key(value) for value in values if _text(value)})


def evidence_independence_groups(decision: Mapping[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("independenceGroups", "independence_groups", "independenceGroup"):
        value = decision.get(key)
        values.extend(value if isinstance(value, list) else [value] if value else [])
    values.extend(record.get("independenceGroup") or record.get("independence_group")
                  for record in _evidence_records(decision))
    return sorted({_text(value) for value in values if _text(value)})


def _independent_evidence_count(decision: Mapping[str, Any]) -> int:
    groups = evidence_independence_groups(decision)
    if groups:
        return len(set(groups))
    # Legacy records have no explicit family/group.  Distinct provenance
    # locators are the conservative fallback; repeated labels from one source
    # are never counted twice.
    refs = _provenance_refs(decision)
    return len(set(refs))


def _relation_identity(relation: Mapping[str, Any], fallback: str = "") -> str:
    explicit = _relation_id(relation, "")
    if explicit:
        return explicit
    payload = "|".join((
        _relation_endpoint(relation, True), _relation_endpoint(relation, False),
        _relation_type(relation),
        _text(relation.get("sourceAttribute") or relation.get("source_attribute")),
        _text(relation.get("targetAttribute") or relation.get("target_attribute")),
    ))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return _text(f"REL_{digest}") or fallback


def _provenance_refs(decision: Mapping[str, Any]) -> list[str]:
    """Extract traceable evidence references from a relation decision.

    An evidence label such as ``FOREIGN_KEY`` is only a claim made by the
    agent.  A formal relation also needs a pointer to the observed source so
    that the decision can be audited and independently re-checked.
    """
    values: list[Any] = []
    for key in (
        "provenance", "provenances", "evidenceSource", "evidenceSources",
        "evidenceRef", "evidenceRefs", "sourceRef", "sourceRefs",
    ):
        value = decision.get(key)
        if isinstance(value, list):
            values.extend(value)
        elif value:
            values.append(value)

    refs: list[str] = []
    for value in values:
        if isinstance(value, Mapping):
            value = (
                value.get("ref") or value.get("path") or value.get("source")
                or value.get("uri") or value.get("location") or value.get("id")
            )
        value = _text(value)
        if value and value not in refs:
            refs.append(value)
    return refs


def _evidence_level(decision: Mapping[str, Any]) -> str:
    return _key(decision.get("evidenceLevel") or decision.get("evidence_level")
                or decision.get("level"))


def has_formal_evidence(decision: Mapping[str, Any]) -> bool:
    """Return whether evidence types meet the semantic relation threshold.

    One independently strong source is sufficient.  Moderate evidence needs
    at least two different evidence categories.  Confidence text alone,
    including HIGH or a numeric score, never crosses the gate.
    """
    types = evidence_types(decision)
    level = _evidence_level(decision)
    if not level or not _provenance_refs(decision):
        return False
    if types & STRONG_EVIDENCE:
        return level == "STRONG"
    return (len(types & MODERATE_EVIDENCE) >= 2
            and _independent_evidence_count(decision) >= 2
            and level in {"MODERATE", "STRONG"})


def has_transformation_evidence(decision: Mapping[str, Any]) -> bool:
    types = evidence_types(decision)
    direct = types & {
        "ETL_SQL_LINEAGE", VIEW_DERIVATION_LINEAGE, VIEW_CALCULATION_LOGIC,
        "CODE_REFERENCE", "EXPLICIT_CONFIG", "BUSINESS_DOCUMENT",
        "DATA_CONTRACT", "WORKFLOW_DEFINITION",
    }
    # Legacy state files used VIEW_SQL_LINEAGE.  Keep them readable for
    # backward compatibility; new JOIN evidence must use VIEW_JOIN_EVIDENCE
    # and therefore does not enter this set.
    if "VIEW_SQL_LINEAGE" in types and _text(decision.get("lineageKind") or decision.get("lineage_kind")) in {
            "", "DERIVATION", "TRANSFORMATION"}:
        direct.add("VIEW_SQL_LINEAGE")
    return bool(direct) and has_formal_evidence(decision)


def has_composition_evidence(decision: Mapping[str, Any]) -> bool:
    """Require ownership semantics in addition to generic relation evidence."""
    return has_formal_evidence(decision) and bool(
        evidence_types(decision) & COMPOSITION_SEMANTIC_EVIDENCE)


def _iter_relation_decisions(state: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    """Read the canonical relation decision list and compatible state aliases."""
    found: list[Mapping[str, Any]] = []
    containers: list[Any] = [state]
    artifacts = state.get("artifacts")
    if isinstance(artifacts, Mapping):
        containers.extend(artifacts.values())
    while containers:
        container = containers.pop(0)
        if not isinstance(container, Mapping):
            continue
        for key in (
            "relationDecisions", "relation_decisions", "entityRelations",
            "entity_relations", "relations", "decisions",
        ):
            value = container.get(key)
            if isinstance(value, list):
                found.extend(item for item in value if isinstance(item, Mapping))
            elif isinstance(value, Mapping):
                found.extend(item for item in value.values() if isinstance(item, Mapping))
        for key in ("entityRelationArtifact", "entity_relation", "ENTITY_RELATION"):
            value = container.get(key)
            if isinstance(value, Mapping):
                containers.append(value)
    return found


def relation_decision_index(state: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    if not isinstance(state, Mapping):
        return {}
    index: dict[str, Mapping[str, Any]] = {}
    for position, decision in enumerate(_iter_relation_decisions(state)):
        relation_id = _relation_identity(decision, f"REL_{position:06d}")
        if relation_id:
            # Keep the first definition visible.  A separate validator reports
            # the duplicate instead of allowing a later record to silently
            # replace an earlier semantic decision.
            index.setdefault(relation_id, decision)
    return index


def duplicate_relation_decision_ids(state: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(state, Mapping):
        return []
    counts: dict[str, int] = defaultdict(int)
    for position, decision in enumerate(_iter_relation_decisions(state)):
        counts[_relation_identity(decision, f"REL_{position:06d}")] += 1
    return sorted(identifier for identifier, count in counts.items() if count > 1)


@dataclass(frozen=True)
class RoleCapabilities:
    """Capabilities used by ownership and business-object aggregation."""

    can_be_component: bool = False
    can_be_owner: bool = False
    can_be_main: bool = False


# The V6 role vocabulary is centralized here.  Aliases are accepted only at
# this boundary so generators, aggregators and validators cannot each invent
# their own interpretation of a logical-entity role.
_ROLE_ALIASES = {
    "MAIN": "CANDIDATE_MAIN_ENTITY",
    "MAIN_ENTITY": "CANDIDATE_MAIN_ENTITY",
    "OWNER": "CANDIDATE_MAIN_ENTITY",
    "OWNER_ENTITY": "CANDIDATE_MAIN_ENTITY",
    "COMPONENT": "DEPENDENT_ENTITY",
    "CHILD": "DEPENDENT_ENTITY",
    "DEPENDENT": "DEPENDENT_ENTITY",
}
_ROLE_CAPABILITIES = {
    "CANDIDATE_MAIN_ENTITY": RoleCapabilities(can_be_owner=True, can_be_main=True),
    # A dependent may own a nested component, but it is not itself an
    # aggregate root/main entity.  This permits C -> B -> A.
    "DEPENDENT_ENTITY": RoleCapabilities(can_be_component=True, can_be_owner=True),
    "RELATIONSHIP_ENTITY": RoleCapabilities(
        can_be_component=True, can_be_owner=True, can_be_main=True),
    "MASTER_DATA_ENTITY": RoleCapabilities(can_be_owner=True, can_be_main=True),
    "REFERENCE_DATA_ENTITY": RoleCapabilities(can_be_owner=True, can_be_main=True),
    "OBSERVATION_EVENT_ENTITY": RoleCapabilities(can_be_owner=True, can_be_main=True),
    "DOCUMENT_CONTENT_ENTITY": RoleCapabilities(can_be_owner=True, can_be_main=True),
    "DERIVED_ANALYTICAL_ENTITY": RoleCapabilities(),
    "SYSTEM_TECHNICAL_ENTITY": RoleCapabilities(),
    "UNCLASSIFIED_ENTITY": RoleCapabilities(),
}


def normalize_entity_role(value: Any) -> str:
    if isinstance(value, Mapping):
        value = (value.get("role") or value.get("entityRole")
                 or value.get("logicalEntityRole") or value.get("type") or "")
    normalized = _key(value)
    return _ROLE_ALIASES.get(normalized, normalized)


def role_capabilities(role: Any) -> RoleCapabilities:
    return _ROLE_CAPABILITIES.get(normalize_entity_role(role), RoleCapabilities())


def can_be_composition_source(role: Any) -> bool:
    return role_capabilities(role).can_be_component


def can_be_composition_target(role: Any) -> bool:
    return role_capabilities(role).can_be_owner


def can_be_main_entity(role: Any) -> bool:
    return role_capabilities(role).can_be_main


def _entity_id(entity: Mapping[str, Any]) -> str:
    return _text(entity.get("entityId") or entity.get("entity_id")
                 or entity.get("logicalEntityId") or entity.get("code")
                 or entity.get("id"))


def _entity_ref(value: Any) -> str:
    if isinstance(value, Mapping):
        value = (value.get("entityId") or value.get("entity_id")
                 or value.get("logicalEntityId") or value.get("code")
                 or value.get("id"))
    return _text(value)


def _relation_endpoint(relation: Mapping[str, Any], source: bool) -> str:
    keys = (("sourceEntity", "source_entity", "source", "fromEntity", "from")
            if source else
            ("targetEntity", "target_entity", "target", "toEntity", "to"))
    for key in keys:
        if key in relation and _entity_ref(relation.get(key)):
            return _entity_ref(relation.get(key))
    return ""


def _relation_type(relation: Mapping[str, Any]) -> str:
    return _key(relation.get("relationType") or relation.get("relation_type")
                or relation.get("type") or relation.get("关系类型"))


def _relation_id(relation: Mapping[str, Any], fallback: str = "") -> str:
    return _text(relation.get("relationId") or relation.get("relation_id")
                 or relation.get("relationCode") or relation.get("code")
                 or relation.get("id") or fallback)


def _iter_entity_records(state: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    """Read logical entities from the canonical state and compatible aliases."""
    containers: list[Any] = [state]
    artifacts = state.get("artifacts")
    if isinstance(artifacts, Mapping):
        containers.extend(artifacts.values())
    seen: set[int] = set()
    while containers:
        container = containers.pop(0)
        if not isinstance(container, Mapping):
            continue
        marker = id(container)
        if marker in seen:
            continue
        seen.add(marker)
        for key in ("entities", "logicalEntities", "logical_entities", "entityDecisions"):
            value = container.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, Mapping):
                        yield item
            elif isinstance(value, Mapping):
                for item in value.values():
                    if isinstance(item, Mapping):
                        yield item
        for key in ("businessObjects", "business_objects", "businessObjectDecisions"):
            value = container.get(key)
            if isinstance(value, list):
                containers.extend(value)
            elif isinstance(value, Mapping):
                containers.extend(value.values())
        nested = container.get("logicalEntities")
        if isinstance(nested, list):
            containers.extend(nested)


def entity_index(state: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for entity in _iter_entity_records(state):
        identifier = _entity_id(entity)
        if identifier:
            result[identifier] = entity
    return result


def _is_explicit_false(value: Any) -> bool:
    return _key(value) in {"N", "NO", "FALSE", "0"}


def is_main_entity(entity: Mapping[str, Any]) -> bool:
    for key in ("isMain", "is_main", "mainEntity", "main_entity", "是否主逻辑实体"):
        if key in entity and _text(entity.get(key)):
            return not _is_explicit_false(entity.get(key))
    return can_be_main_entity(entity.get("role") or entity.get("entityRole")
                              or entity.get("logicalEntityRole") or entity.get("type"))


def is_aggregation_edge(relation: Mapping[str, Any]) -> bool:
    """Return true only for a confirmed, evidenced aggregation relation."""
    status = _status(relation.get("status") or relation.get("decision"))
    if status != CONFIRMED or _relation_type(relation) not in AGGREGATION_RELATION_TYPES:
        return False
    if _relation_type(relation) == COMPOSITION:
        return has_composition_evidence(relation)
    return has_formal_evidence(relation)


@dataclass(frozen=True)
class AggregationComponent:
    entity_ids: tuple[str, ...]
    relation_ids: tuple[str, ...]
    main_entity_ids: tuple[str, ...]
    valid: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "entityIds": list(self.entity_ids),
            "relationIds": list(self.relation_ids),
            "mainEntityIds": list(self.main_entity_ids),
            "valid": self.valid,
        }


@dataclass(frozen=True)
class AggregationAnalysis:
    components: tuple[AggregationComponent, ...]
    issues: tuple[ValidationIssue, ...]


def _issue(code: str, severity: str, message: str, *, artifact_type: str = "",
           artifact_id: str = "", relation: Mapping[str, Any] | None = None,
           details: Mapping[str, Any] | None = None) -> ValidationIssue:
    info = dict(details or {})
    if relation is not None:
        info.setdefault("sourceEntity", _relation_endpoint(relation, True))
        info.setdefault("targetEntity", _relation_endpoint(relation, False))
        info.setdefault("relationType", _relation_type(relation))
    return ValidationIssue(code=code, severity=severity, message=message,
                           artifact_type=artifact_type, artifact_id=artifact_id,
                           details=info)


def _find_composition_cycles(edges: Iterable[tuple[str, Mapping[str, Any]]]) -> list[tuple[set[str], set[str]]]:
    adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
    edge_map: dict[str, tuple[str, str]] = {}
    for relation_id, relation in edges:
        source = _relation_endpoint(relation, True)
        target = _relation_endpoint(relation, False)
        if source and target and source != target:
            adjacency[source].append((target, relation_id))
            edge_map[relation_id] = (source, target)

    colors: dict[str, int] = {}
    path: list[str] = []
    path_index: dict[str, int] = {}
    cycles: dict[frozenset[str], set[str]] = {}

    def visit(node: str) -> None:
        colors[node] = 1
        path_index[node] = len(path)
        path.append(node)
        for child, relation_id in adjacency.get(node, ()):
            if colors.get(child, 0) == 0:
                visit(child)
            elif colors.get(child) == 1:
                cycle_nodes = set(path[path_index[child]:])
                cycle_nodes.add(child)
                relation_ids = cycles.setdefault(frozenset(cycle_nodes), set())
                relation_ids.add(relation_id)
                for edge_id, (edge_source, edge_target) in edge_map.items():
                    if edge_source in cycle_nodes and edge_target in cycle_nodes:
                        relation_ids.add(edge_id)
        path.pop()
        path_index.pop(node, None)
        colors[node] = 2

    for node in adjacency:
        if colors.get(node, 0) == 0:
            visit(node)
    return [(set(nodes), relation_ids) for nodes, relation_ids in cycles.items()]


def _declared_aggregation_relation_ids(state: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    containers: list[Any] = [state]
    while containers:
        value = containers.pop(0)
        if not isinstance(value, Mapping):
            continue
        for key in (
            "aggregationRelationIds", "aggregation_relation_ids",
            "formalAggregationRelationIds", "formal_aggregation_relation_ids",
        ):
            raw = value.get(key)
            if isinstance(raw, list):
                ids.update(_text(item) for item in raw if _text(item))
            elif raw:
                ids.add(_text(raw))
        raw_edges = value.get("aggregationEdges") or value.get("aggregation_edges")
        if isinstance(raw_edges, list):
            for item in raw_edges:
                if isinstance(item, Mapping):
                    relation_id = _relation_id(item)
                    if relation_id:
                        ids.add(relation_id)
        for nested_key in ("artifacts", "businessObjects", "business_objects",
                           "businessObjectDecisions", "aggregationComponents"):
            raw = value.get(nested_key)
            if isinstance(raw, list):
                containers.extend(raw)
            elif isinstance(raw, Mapping):
                containers.extend(raw.values())
    return ids


def analyze_aggregation(state: Mapping[str, Any] | None) -> AggregationAnalysis:
    """Validate COMPOSITION semantics and compute only policy-approved components."""
    if not isinstance(state, Mapping):
        return AggregationAnalysis((), ())
    entities = entity_index(state)
    decisions = relation_decision_index(state)
    issues: list[ValidationIssue] = []
    invalid_relation_ids: set[str] = set()
    formal_composition: list[tuple[str, Mapping[str, Any]]] = []
    valid_composition: list[tuple[str, Mapping[str, Any]]] = []
    aggregation_edges: list[tuple[str, Mapping[str, Any]]] = []
    candidate_composition_sources: set[str] = set()

    for relation_id, relation in decisions.items():
        relation_type = _relation_type(relation)
        status = _status(relation.get("status") or relation.get("decision"))
        source = _relation_endpoint(relation, True)
        target = _relation_endpoint(relation, False)
        if relation_type == COMPOSITION and status != CONFIRMED:
            if source:
                candidate_composition_sources.add(source)
            continue
        if relation_type not in AGGREGATION_RELATION_TYPES or status != CONFIRMED:
            continue
        relation_id = _relation_id(relation, relation_id)
        if relation_type == COMPOSITION and not has_formal_evidence(relation):
            continue
        if relation_type == COMPOSITION and not has_composition_evidence(relation):
            invalid_relation_ids.add(relation_id)
            issues.append(_issue(
                "INVALID_AGGREGATION_EDGE", "ERROR",
                f"COMPOSITION {relation_id} 缺少 ownership/containment 语义证据，普通 FK 不能直接作为聚合边",
                artifact_type="ENTITY_RELATION", artifact_id=relation_id,
                relation=relation,
                details={"reason": "foreign-key or structural evidence is not composition evidence"},
            ))
            continue
        if relation_type == EXTENSION and not has_formal_evidence(relation):
            continue
        aggregation_edges.append((relation_id, relation))
        if relation_type == COMPOSITION:
            formal_composition.append((relation_id, relation))
            if not source or not target or source not in entities or target not in entities:
                invalid_relation_ids.add(relation_id)
                issues.append(_issue(
                    "MISSING_COMPOSITION_OWNER", "ERROR",
                    f"COMPOSITION {relation_id} 引用了不存在的 source 或 owner",
                    artifact_type="ENTITY_RELATION", artifact_id=relation_id,
                    relation=relation, details={"reason": "entity reference missing"},
                ))
                continue
            if source == target:
                invalid_relation_ids.add(relation_id)
                issues.append(_issue(
                    "SELF_COMPOSITION", "ERROR",
                    f"COMPOSITION {relation_id} 不能连接实体自身",
                    artifact_type="ENTITY_RELATION", artifact_id=relation_id,
                    relation=relation,
                ))
                continue
            source_caps = role_capabilities(entities[source].get("role")
                                            or entities[source].get("entityRole")
                                            or entities[source].get("type"))
            target_caps = role_capabilities(entities[target].get("role")
                                            or entities[target].get("entityRole")
                                            or entities[target].get("type"))
            role_valid = True
            if not source_caps.can_be_component:
                role_valid = False
                invalid_relation_ids.add(relation_id)
                code = ("INVALID_COMPOSITION_DIRECTION"
                        if source_caps.can_be_owner and target_caps.can_be_component
                        else "INVALID_COMPOSITION_SOURCE_ROLE")
                issues.append(_issue(
                    code, "ERROR",
                    f"COMPOSITION {relation_id} 的 source 必须是 component/dependent，而不是 owner/main",
                    artifact_type="ENTITY_RELATION", artifact_id=relation_id,
                    relation=relation,
                ))
            if not target_caps.can_be_owner:
                role_valid = False
                invalid_relation_ids.add(relation_id)
                if not (source_caps.can_be_owner and target_caps.can_be_component):
                    issues.append(_issue(
                        "INVALID_COMPOSITION_TARGET_ROLE", "ERROR",
                        f"COMPOSITION {relation_id} 的 target 不具备 owner capability",
                        artifact_type="ENTITY_RELATION", artifact_id=relation_id,
                        relation=relation,
                    ))
            if role_valid:
                valid_composition.append((relation_id, relation))

    owners_by_component: dict[str, set[str]] = defaultdict(set)
    owner_relation_ids: dict[str, set[str]] = defaultdict(set)
    for relation_id, relation in valid_composition:
        source = _relation_endpoint(relation, True)
        target = _relation_endpoint(relation, False)
        owners_by_component[source].add(target)
        owner_relation_ids[source].add(relation_id)
    for component_id, owners in owners_by_component.items():
        if len(owners) > 1:
            relation_ids = owner_relation_ids[component_id]
            invalid_relation_ids.update(relation_ids)
            issues.append(_issue(
                "MULTIPLE_COMPOSITION_OWNERS", "ERROR",
                f"实体 {component_id} 存在多个 COMPOSITION owner，不能自动选择",
                artifact_type="LOGICAL_ENTITY", artifact_id=component_id,
                details={"ownerEntities": sorted(owners), "relationIds": sorted(relation_ids)},
            ))

    for cycle_nodes, relation_ids in _find_composition_cycles(formal_composition):
        invalid_relation_ids.update(relation_ids)
        issues.append(_issue(
            "COMPOSITION_CYCLE", "ERROR",
            "COMPOSITION ownership graph 存在循环，不能形成正式聚合",
            artifact_type="AGGREGATION_COMPONENT",
            artifact_id="COMPONENT:" + ",".join(sorted(cycle_nodes)),
            details={"entityIds": sorted(cycle_nodes), "relationIds": sorted(relation_ids)},
        ))

    for entity_id, entity in entities.items():
        if not can_be_composition_source(entity.get("role") or entity.get("entityRole")
                                          or entity.get("type")):
            continue
        direct = [relation for _, relation in valid_composition
                  if _relation_endpoint(relation, True) == entity_id]
        if direct:
            continue
        if entity_id in candidate_composition_sources:
            issues.append(_issue(
                "UNRESOLVED_COMPOSITION_OWNER", "WARNING",
                f"从属实体 {entity_id} 的 COMPOSITION owner 尚未由正式证据确认",
                artifact_type="LOGICAL_ENTITY", artifact_id=entity_id,
                details={"needsConfirmation": True},
            ))
        else:
            issues.append(_issue(
                "MISSING_COMPOSITION_OWNER", "WARNING",
                f"从属实体 {entity_id} 没有指向 owner 的合法 COMPOSITION",
                artifact_type="LOGICAL_ENTITY", artifact_id=entity_id,
                details={"needsConfirmation": True},
            ))

    declared_ids = _declared_aggregation_relation_ids(state)
    for relation_id in sorted(declared_ids):
        relation = decisions.get(relation_id)
        if relation is not None and _relation_type(relation) in AGGREGATION_RELATION_TYPES \
                and _status(relation.get("status") or relation.get("decision")) != CONFIRMED:
            issues.append(_issue(
                "CANDIDATE_EDGE_USED_FOR_FORMAL_AGGREGATION", "ERROR",
                f"候选或未解析聚合边 {relation_id} 不能用于正式业务对象聚合",
                artifact_type="ENTITY_RELATION", artifact_id=relation_id,
                relation=relation,
            ))

    # Build components from confirmed, role-valid edges.  Edges with ownership
    # conflicts/cycles remain visible in the analysis component but make it
    # invalid; callers that create formal business objects receive only valid
    # components.
    graph_edges: list[tuple[str, Mapping[str, Any]]] = []
    graph_edges.extend(valid_composition)
    graph_edges.extend((relation_id, relation) for relation_id, relation in aggregation_edges
                       if _relation_type(relation) == EXTENSION)
    parent: dict[str, str] = {entity_id: entity_id for entity_id in entities}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for relation_id, relation in graph_edges:
        source = _relation_endpoint(relation, True)
        target = _relation_endpoint(relation, False)
        if source in parent and target in parent:
            union(source, target)
    grouped_entities: dict[str, set[str]] = defaultdict(set)
    for entity_id in entities:
        root = find(entity_id)
        # Connected components include singleton logical entities too.  A
        # singleton main can be a valid standalone Business Object; a
        # singleton dependent becomes a visible missing-main warning rather
        # than being dropped to make coverage look complete.
        grouped_entities[root].add(entity_id)
    grouped_relations: dict[str, set[str]] = defaultdict(set)
    for relation_id, relation in graph_edges:
        source = _relation_endpoint(relation, True)
        target = _relation_endpoint(relation, False)
        if source in parent and target in parent:
            grouped_relations[find(source)].add(relation_id)

    components: list[AggregationComponent] = []
    error_relation_ids = {
        issue.artifact_id for issue in issues
        if issue.severity == "ERROR" and issue.artifact_type == "ENTITY_RELATION"
    }
    for root, component_entities in grouped_entities.items():
        relation_ids = grouped_relations.get(root, set())
        mains = tuple(sorted(entity_id for entity_id in component_entities
                             if is_main_entity(entities[entity_id])))
        component_id = "COMPONENT:" + ",".join(sorted(component_entities))
        if len(mains) == 0:
            issues.append(_issue(
                "MISSING_MAIN_ENTITY", "WARNING",
                f"聚合组件 {component_id} 没有唯一 main logical entity",
                artifact_type="AGGREGATION_COMPONENT", artifact_id=component_id,
                details={"entityIds": sorted(component_entities), "mainCount": 0,
                         "needsConfirmation": True},
            ))
        elif len(mains) > 1:
            issues.append(_issue(
                "MULTIPLE_MAIN_ENTITIES", "ERROR",
                f"聚合组件 {component_id} 包含多个 main logical entity，不能自动合并",
                artifact_type="AGGREGATION_COMPONENT", artifact_id=component_id,
                details={"entityIds": sorted(component_entities),
                         "mainEntityIds": list(mains)},
            ))
        component_error = bool((error_relation_ids | invalid_relation_ids) & relation_ids)
        component_error = component_error or any(
            issue.artifact_id == component_id and issue.severity == "ERROR"
            for issue in issues
        )
        component_valid = len(mains) == 1 and not component_error
        components.append(AggregationComponent(
            entity_ids=tuple(sorted(component_entities)),
            relation_ids=tuple(sorted(relation_ids)),
            main_entity_ids=mains,
            valid=component_valid,
        ))
    return AggregationAnalysis(tuple(components), tuple(issues))


def validate_composition_semantics(state: Mapping[str, Any] | None) -> list[ValidationIssue]:
    return list(analyze_aggregation(state).issues)


def aggregation_components(state: Mapping[str, Any] | None,
                           *, include_invalid: bool = False) -> list[AggregationComponent]:
    analysis = analyze_aggregation(state)
    if include_invalid:
        return list(analysis.components)
    return [component for component in analysis.components if component.valid]


def build_aggregation_components(state: Mapping[str, Any] | None) -> list[AggregationComponent]:
    """Return only components eligible for formal Business Object aggregation."""
    return aggregation_components(state)


def _csv_rows(blob: bytes) -> tuple[list[str], list[dict[str, str]]]:
    text = bytes(blob).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    return list(reader.fieldnames or []), [dict(row) for row in reader]


@dataclass(frozen=True)
class RuleDecision:
    """One R1-R5 decision with its own evidence and provenance."""

    status: str = "UNKNOWN"
    evidence: str = ""
    provenance: tuple[str, ...] = field(default_factory=tuple)
    unknown_reason: str = ""
    negative_evidence: str = ""
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BusinessObjectDecision:
    """Auditable decision record shared by validation and both exporters."""

    candidate_code: str
    candidate_name: str
    english_name: str = ""
    main_entity_id: str = ""
    main_entity_name: str = ""
    member_entity_ids: tuple[str, ...] = field(default_factory=tuple)
    rules: tuple[RuleDecision, RuleDecision, RuleDecision, RuleDecision, RuleDecision] = field(
        default_factory=lambda: (RuleDecision(), RuleDecision(), RuleDecision(),
                                 RuleDecision(), RuleDecision()))
    conflicts: str = ""
    unknowns: str = ""
    confirmation_question: str = ""
    suggested_role: str = ""
    confidence: str = ""
    reported_decision: str = ""
    decision_reason: str = ""
    decision_id: str = ""
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    missing_evidence: str = ""
    previous_status: str = ""
    upgrade_evidence_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def derived_decision(self) -> str:
        return derive_business_object_decision(*(rule.status for rule in self.rules))

    @property
    def decision(self) -> str:
        return self.derived_decision

    def as_csv_row(self) -> list[str]:
        values: list[str] = [
            self.candidate_code, self.candidate_name, self.decision,
        ]
        for rule in self.rules:
            values.extend((rule.status, rule.evidence))
        values.extend((self.confirmation_question, self.confidence))
        return values


def derive_business_object_decision(*statuses: Any) -> str:
    """Derive the final status from R1-R5 only; confidence is never consulted."""
    normalized = [_business_rule_status(value) for value in statuses]
    if any(value == "FAIL" for value in normalized):
        return REJECTED
    if any(value == "UNKNOWN" or value not in BUSINESS_OBJECT_RULE_STATUSES for value in normalized):
        return CANDIDATE
    return CONFIRMED


def _business_rule_status(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("status") or value.get("decision") or value.get("state")
    normalized = _key(value)
    aliases = {
        "P": "PASS", "PASSING": "PASS", "PASSED": "PASS", "通过": "PASS",
        "F": "FAIL", "FAILURE": "FAIL", "FAILED": "FAIL", "不通过": "FAIL",
        "U": "UNKNOWN", "UNRESOLVED": "UNKNOWN", "PENDING": "UNKNOWN", "未知": "UNKNOWN",
    }
    return aliases.get(normalized, normalized or "UNKNOWN")


def _confidence_percent(value: Any) -> str:
    """Normalize numeric modeling confidence without inventing label scores.

    New modeling runs must provide a numeric percentage directly. Legacy
    qualitative labels are preserved when encountered in old state so a
    historical artifact is not silently rewritten.
    """
    if isinstance(value, bool):
        return "100%" if value else "0%"
    text = _text(value).strip()
    normalized = _key(text).replace("％", "%")
    try:
        numeric = float(normalized.rstrip("%"))
    except (TypeError, ValueError):
        return text
    if 0 <= numeric <= 1:
        numeric *= 100
    numeric = max(0.0, min(100.0, numeric))
    return f"{numeric:g}%"


def _first_value(record: Mapping[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in record and record.get(key) not in (None, ""):
            return record.get(key)
    return ""


def _evidence_summary(value: Any) -> str:
    """Serialize evidence as a concise stable human-readable summary."""
    if isinstance(value, Mapping):
        preferred = ("summary", "text", "description", "reason", "claim", "value")
        selected = _first_value(value, preferred)
        if selected not in (None, ""):
            return _text(selected)
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if isinstance(value, (list, tuple, set)):
        parts = [_evidence_summary(item) for item in value]
        return "；".join(part for part in parts if part)
    return _text(value)


def _rule_field(record: Mapping[str, Any], rule: str) -> Any:
    upper = rule.upper()
    aliases = (rule, upper, f"{rule}Decision", f"{upper}Decision",
               f"{rule}Status", f"{upper}Status", f"{rule}_status",
               f"{upper}_STATUS")
    return _first_value(record, aliases)


def _rule_decision(record: Mapping[str, Any], rule: str) -> RuleDecision:
    raw = _rule_field(record, rule)
    nested = raw if isinstance(raw, Mapping) else {}
    status = _business_rule_status(nested or raw)
    evidence = _first_value(nested, ("evidence", "evidences", "proof", "summary", "reason"))
    if evidence in (None, ""):
        evidence = _first_value(record, (
            f"{rule}Evidence", f"{rule.upper()}Evidence", f"{rule}证据",
            f"{rule}_evidence", f"{rule.upper()}_EVIDENCE"))
    provenance = _first_value(nested, ("provenance", "source", "evidenceRef", "evidenceRefs"))
    if provenance in (None, ""):
        provenance = _first_value(record, (
            f"{rule}Provenance", f"{rule.upper()}Provenance", f"{rule}来源"))
    if isinstance(provenance, (list, tuple, set)):
        provenance_values = tuple(sorted({_text(item) for item in provenance if _text(item)}))
    elif provenance:
        provenance_values = (_text(provenance),)
    else:
        provenance_values = ()
    unknown_reason = _first_value(nested, ("unknownReason", "unresolvedReason", "reason"))
    if unknown_reason in (None, ""):
        unknown_reason = _first_value(record, (
            f"{rule}UnknownReason", f"{rule.upper()}UnknownReason", f"{rule}未知原因"))
    negative = _first_value(nested, ("negativeEvidence", "contradiction", "counterEvidence"))
    if negative in (None, ""):
        negative = _first_value(record, (
            f"{rule}NegativeEvidence", f"{rule.upper()}NegativeEvidence", f"{rule}反证"))
    evidence_text = _evidence_summary(evidence)
    if provenance_values:
        evidence_text = (evidence_text + " " if evidence_text else "") + \
                        "[来源:" + "|".join(provenance_values) + "]"
    nested_evidence_ids = evidence_ids(nested) if nested else []
    return RuleDecision(status=status, evidence=evidence_text,
                        provenance=provenance_values,
                        unknown_reason=_evidence_summary(unknown_reason),
                        negative_evidence=_evidence_summary(negative),
                        evidence_ids=tuple(nested_evidence_ids))


def _business_object_candidate_values(state: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Read the canonical candidate collection, without duplicating aliases."""
    containers: list[Mapping[str, Any]] = [state]
    artifacts = state.get("artifacts")
    if isinstance(artifacts, Mapping):
        containers.extend(value for value in artifacts.values() if isinstance(value, Mapping))
    keys = ("businessObjectDecisions", "business_object_decisions",
            "businessObjectCandidates", "business_object_candidates",
            "businessObjects", "business_objects")
    for container in containers:
        for key in keys:
            value = container.get(key)
            if isinstance(value, Mapping):
                value = list(value.values())
            if not isinstance(value, list):
                continue
            records = [item for item in value if isinstance(item, Mapping)]
            # The canonical collection wins.  This prevents a mirrored
            # artifact and its alias from doubling the evaluated count.
            if records:
                return records
    return []


def has_business_object_decisions(state: Mapping[str, Any] | None) -> bool:
    if not isinstance(state, Mapping):
        return False
    records = _business_object_candidate_values(state)
    return bool(records and any(
        any(_rule_field(record, rule) not in (None, "") for rule in BUSINESS_OBJECT_RULES)
        for record in records
    ))


def _candidate_entity_ids(record: Mapping[str, Any]) -> tuple[str, ...]:
    raw = _first_value(record, ("memberEntityIds", "includedEntityIds", "logicalEntityIds",
                                "entityIds", "包含逻辑实体编码", "logicalEntities", "entities"))
    if isinstance(raw, Mapping):
        raw = list(raw.values())
    if not isinstance(raw, (list, tuple, set)):
        raw = [raw] if raw else []
    values = []
    for item in raw:
        value = _entity_ref(item)
        if value and value not in values:
            values.append(value)
    return tuple(sorted(values))


def business_object_decision_records(state: Mapping[str, Any] | None) -> list[BusinessObjectDecision]:
    if not isinstance(state, Mapping) or not has_business_object_decisions(state):
        return []
    raw_records = _business_object_candidate_values(state)
    normalized: list[tuple[str, Mapping[str, Any]]] = []
    for record in raw_records:
        member_ids = _candidate_entity_ids(record)
        code = _text(_first_value(record, ("candidateCode", "candidateId", "businessObjectId",
                                            "business_object_id", "code", "id", "候选业务对象编码")))
        name = _text(_first_value(record, ("candidateName", "businessObjectName", "name",
                                           "business_object_name", "候选业务对象名称")))
        normalized.append((code or f"~{name}|{'|'.join(member_ids)}", record))
    normalized.sort(key=lambda item: item[0])
    result: list[BusinessObjectDecision] = []
    for index, (_, record) in enumerate(normalized, 1):
        member_ids = _candidate_entity_ids(record)
        code = _text(_first_value(record, ("candidateCode", "candidateId", "businessObjectId",
                                            "business_object_id", "code", "id", "候选业务对象编码")))
        if not code:
            code = f"CO{index:04d}"
        main = _first_value(record, ("candidateMainEntity", "candidateMainEntityId",
                                     "mainEntity", "mainEntityId", "candidate_main_entity",
                                     "候选主逻辑实体编码"))
        main_id = _entity_ref(main)
        main_name = ""
        if isinstance(main, Mapping):
            main_name = _text(_first_value(main, ("name", "entityName", "logicalEntityName")))
        main_name = main_name or _text(_first_value(record, ("candidateMainEntityName",
                                                               "mainEntityName", "候选主逻辑实体名称")))
        rules = tuple(_rule_decision(record, rule) for rule in BUSINESS_OBJECT_RULES)
        unknowns = _text(_first_value(record, ("unknowns", "unknownItems", "未知项")))
        if not unknowns:
            unknowns = "；".join(
                f"{rule.upper()}：{decision.unknown_reason}"
                for rule, decision in zip(BUSINESS_OBJECT_RULES, rules)
                if decision.status == "UNKNOWN" and decision.unknown_reason)
        confirmation_question = _text(_first_value(record, (
            "confirmationQuestion", "needsConfirmationQuestion", "确认问题")))
        if not confirmation_question:
            unknown_rules = [rule.upper() for rule, decision in zip(BUSINESS_OBJECT_RULES, rules)
                             if decision.status == "UNKNOWN"]
            if unknown_rules:
                confirmation_question = "请确认" + "、".join(unknown_rules) + "对应的业务对象证据是否成立。"
        raw_reported = _first_value(record, (
            "finalDecision", "decision", "status", "conclusion", "结论", "最终决策"))
        all_evidence_ids = sorted({item for rule in rules for item in rule.evidence_ids})
        decision_id = _text(_first_value(record, (
            "decisionId", "decision_id", "businessObjectDecisionId")))
        if not decision_id:
            decision_id = "BO_DECISION:" + hashlib.sha256(
                code.encode("utf-8")).hexdigest()[:16]
        raw_upgrades = _first_value(record, ("upgradeEvidenceIds", "upgrade_evidence_ids"))
        upgrade_ids = tuple(sorted({_text(item) for item in raw_upgrades if _text(item)})) \
            if isinstance(raw_upgrades, (list, tuple, set)) else ()
        result.append(BusinessObjectDecision(
            candidate_code=code,
            candidate_name=_text(_first_value(record, ("candidateName", "businessObjectName", "name",
                                                       "business_object_name", "候选业务对象名称"))),
            english_name=_text(_first_value(record, ("englishName", "businessObjectEnglishName",
                                                      "business_object_english_name", "业务对象英文名称"))),
            main_entity_id=main_id,
            main_entity_name=main_name,
            member_entity_ids=member_ids,
            rules=rules,
            conflicts=_evidence_summary(_first_value(record, ("conflicts", "conflict", "冲突"))),
            unknowns=unknowns,
            confirmation_question=confirmation_question,
            suggested_role=_text(_first_value(record, ("suggestedRole", "suggestedOwner",
                                                        "建议确认角色"))),
            confidence=_confidence_percent(_first_value(record, ("confidence", "置信度"))),
            reported_decision=_business_rule_status(raw_reported) if raw_reported else "",
            decision_reason=_text(_first_value(record, ("decisionReason", "reason", "决策说明"))),
            decision_id=decision_id,
            evidence_ids=tuple(all_evidence_ids),
            missing_evidence=unknowns,
            previous_status=_text(_first_value(record, ("previousStatus", "previous_status"))),
            upgrade_evidence_ids=upgrade_ids,
        ))
    return result


def validate_business_object_decisions(state: Mapping[str, Any] | None) -> list[ValidationIssue]:
    records = business_object_decision_records(state)
    if not records:
        return []
    issues: list[ValidationIssue] = []
    seen: set[str] = set()
    for record in records:
        if not record.candidate_code or not record.candidate_name:
            issues.append(_issue("BUSINESS_OBJECT_DECISION_MISMATCH", "ERROR",
                                 "业务对象候选必须有稳定编码和名称",
                                 artifact_type="BUSINESS_OBJECT", artifact_id=record.candidate_code))
        if not re.fullmatch(r"(?:100|[0-9]{1,2})(?:\.\d+)?%", record.confidence):
            issues.append(_issue("INVALID_BUSINESS_OBJECT_CONFIDENCE", "ERROR",
                                 f"业务对象 {record.candidate_code} 的置信度必须是 0-100 的百分比数值",
                                 artifact_type="BUSINESS_OBJECT", artifact_id=record.candidate_code))
        if record.candidate_code in seen:
            issues.append(_issue("BUSINESS_OBJECT_DECISION_MISMATCH", "ERROR",
                                 f"业务对象候选编码 {record.candidate_code} 重复",
                                 artifact_type="BUSINESS_OBJECT", artifact_id=record.candidate_code))
        seen.add(record.candidate_code)
        expected = record.derived_decision
        if record.reported_decision and record.reported_decision != expected:
            issues.append(_issue("BUSINESS_OBJECT_DECISION_MISMATCH", "ERROR",
                                 f"业务对象 {record.candidate_code} 的最终决策与 R1-R5 不一致",
                                 artifact_type="BUSINESS_OBJECT", artifact_id=record.candidate_code,
                                 details={"reportedDecision": record.reported_decision,
                                          "derivedDecision": expected}))
        for index, rule in enumerate(record.rules, 1):
            if rule.status not in BUSINESS_OBJECT_RULE_STATUSES:
                issues.append(_issue("BUSINESS_OBJECT_DECISION_MISMATCH", "ERROR",
                                     f"业务对象 {record.candidate_code} 的 R{index} 状态非法",
                                     artifact_type="BUSINESS_OBJECT", artifact_id=record.candidate_code))
            if not rule.evidence:
                issues.append(_issue("MISSING_BUSINESS_OBJECT_EVIDENCE", "ERROR",
                                     f"业务对象 {record.candidate_code} 的 R{index} 缺少证据",
                                     artifact_type="BUSINESS_OBJECT", artifact_id=record.candidate_code,
                                     details={"rule": f"R{index}"}))
            if rule.status == "UNKNOWN" and not rule.unknown_reason:
                issues.append(_issue("MISSING_BUSINESS_OBJECT_UNKNOWN_REASON", "ERROR",
                                     f"业务对象 {record.candidate_code} 的 R{index} 为 UNKNOWN 但没有未知原因",
                                     artifact_type="BUSINESS_OBJECT", artifact_id=record.candidate_code))
            if rule.status == "FAIL" and not (rule.negative_evidence or rule.evidence):
                issues.append(_issue("MISSING_BUSINESS_OBJECT_NEGATIVE_EVIDENCE", "ERROR",
                                     f"业务对象 {record.candidate_code} 的 R{index} 为 FAIL 但没有反证",
                                     artifact_type="BUSINESS_OBJECT", artifact_id=record.candidate_code))
        if expected == CANDIDATE and not record.confirmation_question:
            issues.append(_issue("MISSING_BUSINESS_OBJECT_CONFIRMATION_QUESTION", "WARNING",
                                 f"候选业务对象 {record.candidate_code} 缺少针对 UNKNOWN 规则的确认问题",
                                 artifact_type="BUSINESS_OBJECT", artifact_id=record.candidate_code))
    summary = state.get("businessObjectDecisionSummary") if isinstance(state, Mapping) else None
    if isinstance(summary, Mapping):
        actual = {status: sum(record.decision == status for record in records)
                  for status in (CONFIRMED, CANDIDATE, REJECTED)}
        for status, expected_count in actual.items():
            if status in summary and int(summary.get(status) or 0) != expected_count:
                issues.append(_issue("BUSINESS_OBJECT_DECISION_COUNT_MISMATCH", "ERROR",
                                     "业务对象决策汇总与逐对象记录不一致",
                                     artifact_type="BUSINESS_OBJECT", details={"status": status,
                                                                                 "expected": expected_count,
                                                                                 "reported": summary.get(status)}))
    return issues


def validate_business_object_evidence_isolation(state: Mapping[str, Any] | None) -> list[ValidationIssue]:
    """Reject explicit cross-entity and circular evidence claims."""
    if not isinstance(state, Mapping):
        return []
    issues: list[ValidationIssue] = []
    for record in _business_object_candidate_values(state):
        candidate = _text(_first_value(record, ("candidateCode", "candidateId", "businessObjectId", "code", "id")))
        subjects = set(_candidate_entity_ids(record))
        for rule_name in BUSINESS_OBJECT_RULES:
            raw = _rule_field(record, rule_name)
            evidence_values = raw.get("evidence") if isinstance(raw, Mapping) else None
            if isinstance(evidence_values, Mapping):
                evidence_values = [evidence_values]
            if not isinstance(evidence_values, list):
                continue
            for evidence in evidence_values:
                if not isinstance(evidence, Mapping):
                    continue
                subject = _text(evidence.get("subjectId") or evidence.get("subject_id")
                                or evidence.get("subjectEntity") or evidence.get("subject_entity"))
                if subject and subjects and subject not in subjects and subject != candidate:
                    issues.append(_issue("CROSS_ENTITY_EVIDENCE", "ERROR",
                                         f"业务对象 {candidate} 的 {rule_name.upper()} 使用了实体 {subject} 的证据",
                                         artifact_type="BUSINESS_OBJECT", artifact_id=candidate,
                                         details={"subjectId": subject, "expectedSubjects": sorted(subjects)}))
                evidence_kind = _key(evidence.get("type") or evidence.get("evidenceType") or evidence.get("kind"))
                if evidence.get("derivedClaim") or evidence.get("isDerivedClaim") \
                        or evidence_kind in {"DERIVED_CLAIM", "CLASSIFICATION_CLAIM", "MODEL_CLAIM"}:
                    issues.append(_issue("CIRCULAR_EVIDENCE", "ERROR",
                                         f"业务对象 {candidate} 的 {rule_name.upper()} 使用了派生结论作为事实证据",
                                         artifact_type="BUSINESS_OBJECT", artifact_id=candidate,
                                         details={"evidenceType": evidence_kind}))
                weak_only = evidence_kind in {
                    "TABLE_NAME", "COLUMN_NAME", "FIELD_SEMANTICS", "DATA_PATTERN",
                    "ROW_COUNT", "SAMPLE_DATA", "QUERY_EXECUTION", "MODULE_MEMBERSHIP",
                    "PRIMARY_KEY", "SURROGATE_KEY", "TIMESTAMP_FIELD",
                }
                raw_status = _business_rule_status(raw) if isinstance(raw, Mapping) else ""
                if weak_only and raw_status == "PASS":
                    issues.append(_issue("INSUFFICIENT_R5_EVIDENCE" if rule_name == "r5"
                                         else f"INSUFFICIENT_{rule_name.upper()}_EVIDENCE", "ERROR",
                                         f"{candidate} 的 {rule_name.upper()} 不能仅凭 {evidence_kind} 通过",
                                         artifact_type="BUSINESS_OBJECT", artifact_id=candidate,
                                         details={"evidenceType": evidence_kind}))
    return issues


def write_business_object_decisions_csv(work_dir: str | os.PathLike[str],
                                        state: Mapping[str, Any] | None = None) -> str:
    """Atomically persist all evaluated candidates to mission-work."""
    target_dir = Path(work_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "business_object_decisions.csv"
    records = sorted(business_object_decision_records(state), key=lambda item: item.candidate_code)
    fd, temporary = tempfile.mkstemp(prefix=".business_object_decisions.", suffix=".tmp",
                                      dir=str(target_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(BUSINESS_OBJECT_DECISION_HEADERS)
            writer.writerows(record.as_csv_row() for record in records)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return str(target)


def sync_business_object_decisions(work_dir: str | os.PathLike[str]) -> str:
    state = load_modeling_state(work_dir)
    return write_business_object_decisions_csv(work_dir, state)


def validate_formal_business_object_csv(blob: bytes,
                                        state: Mapping[str, Any] | None) -> list[ValidationIssue]:
    try:
        header, rows = _csv_rows(blob)
    except (TypeError, UnicodeDecodeError, csv.Error):
        return []
    code_column = "业务对象编码"
    if code_column not in header:
        return []
    records = business_object_decision_records(state)
    if not records:
        return [ValidationIssue(
            code="BUSINESS_OBJECT_DECISION_MISMATCH", severity="ERROR",
            message="正式业务对象没有对应的结构化 BusinessObjectDecision",
            artifact_type="BUSINESS_OBJECT", details={"reason": "decision source missing"})]
    index = {record.candidate_code: record for record in records}
    formal_codes = {_text(row.get(code_column)) for row in rows if _text(row.get(code_column))}
    issues = list(validate_business_object_decisions(state))
    for code in sorted(formal_codes):
        record = index.get(code)
        if record is None or record.decision != CONFIRMED:
            issues.append(ValidationIssue(
                code="BUSINESS_OBJECT_DECISION_MISMATCH", severity="ERROR",
                message=f"正式业务对象 {code} 不是经过 R1-R5 确认的 CONFIRMED 决策",
                artifact_type="BUSINESS_OBJECT", artifact_id=code,
                details={"decision": record.decision if record else "MISSING"}))
    for record in records:
        if record.decision == CONFIRMED and record.candidate_code not in formal_codes:
            issues.append(ValidationIssue(
                code="BUSINESS_OBJECT_DECISION_MISSING_FROM_FORMAL_OUTPUT", severity="ERROR",
                message=f"CONFIRMED 业务对象 {record.candidate_code} 未出现在正式业务对象 CSV",
                artifact_type="BUSINESS_OBJECT", artifact_id=record.candidate_code))
    return issues


_RULE_TYPE_ALIASES = {
    "INTEGRITY": BusinessRuleType.INTEGRITY_CONSTRAINT.value,
    "CONSTRAINT": BusinessRuleType.INTEGRITY_CONSTRAINT.value,
    "REFERENTIAL_CONSTRAINT": BusinessRuleType.INTEGRITY_CONSTRAINT.value,
    "UNIQUENESS_CONSTRAINT": BusinessRuleType.INTEGRITY_CONSTRAINT.value,
    "NOT_NULL_CONSTRAINT": BusinessRuleType.INTEGRITY_CONSTRAINT.value,
    "CARDINALITY_CONSTRAINT": BusinessRuleType.INTEGRITY_CONSTRAINT.value,
    "CALCULATION": BusinessRuleType.CALCULATION_RULE.value,
    "STATE_TRANSITION": BusinessRuleType.STATE_TRANSITION_RULE.value,
    "ALERT": BusinessRuleType.ALERT_DETECTION_RULE.value,
    "DETECTION": BusinessRuleType.ALERT_DETECTION_RULE.value,
    "ELIGIBILITY": BusinessRuleType.ELIGIBILITY_RULE.value,
    "DECISION": BusinessRuleType.DECISION_RULE.value,
    "UNCLASSIFIED": BusinessRuleType.UNKNOWN.value,
}


def normalize_business_rule_type(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("ruleType") or value.get("rule_type") or value.get("type")
    normalized = _key(value)
    return _RULE_TYPE_ALIASES.get(normalized, normalized or BusinessRuleType.UNKNOWN.value)


def _rule_value(rule: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in rule and rule.get(key) is not None:
            return rule.get(key)
    return None


def _count_value(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _safe_ratio(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _observed_count(rule: Mapping[str, Any], data: Any, *keys: str) -> int | None:
    value = _rule_value(rule, *keys)
    count = _count_value(value)
    if count is not None:
        return count
    if isinstance(value, (list, tuple, set)):
        return len(value)
    if isinstance(data, Mapping):
        value = _rule_value(data, *keys)
        count = _count_value(value)
        if count is not None:
            return count
        if isinstance(value, (list, tuple, set)):
            return len(value)
    return None


@dataclass(frozen=True)
class RuleValidationResult:
    rule_id: str
    rule_type: str
    validation_status: str
    validator: str
    enforcement: str = RuleEnforcement.UNKNOWN.value
    sample_count: int | None = None
    violation_count: int | None = None
    violation_rate: float | None = None
    hit_count: int | None = None
    hit_rate: float | None = None
    evaluated_count: int | None = None
    match_count: int | None = None
    mismatch_count: int | None = None
    mismatch_rate: float | None = None
    evidence: str = ""
    limitation: str = ""
    existence_status: str = "UNVERIFIED"
    effectiveness_status: str = "UNKNOWN"
    action_status: str = "UNKNOWN"
    rule_origin: str = ""
    tolerance: Any = None
    zero_denominator_count: int | None = None
    null_count: int | None = None
    grain: str = ""
    scope: str = ""
    unit: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ruleId": self.rule_id,
            "ruleType": self.rule_type,
            "validationStatus": self.validation_status,
            "validator": self.validator,
            "enforcement": self.enforcement,
            "sampleCount": self.sample_count,
            "violationCount": self.violation_count,
            "violationRate": self.violation_rate,
            "hitCount": self.hit_count,
            "hitRate": self.hit_rate,
            "evaluatedCount": self.evaluated_count,
            "matchCount": self.match_count,
            "mismatchCount": self.mismatch_count,
            "mismatchRate": self.mismatch_rate,
            "evidence": self.evidence,
            "limitation": self.limitation,
            "existenceStatus": self.existence_status,
            "effectivenessStatus": self.effectiveness_status,
            "actionStatus": self.action_status,
            "ruleOrigin": self.rule_origin,
            "tolerance": self.tolerance,
            "zeroDenominatorCount": self.zero_denominator_count,
            "nullCount": self.null_count,
            "grain": self.grain,
            "scope": self.scope,
            "unit": self.unit,
        }


def _rule_enforcement(rule: Mapping[str, Any]) -> str:
    raw = _key(_rule_value(rule, "enforcement", "enforcementStatus", "enforcement_status"))
    if raw in {item.value for item in RuleEnforcement}:
        return raw
    types = evidence_types(rule)
    # A generic CODE_REFERENCE or EXPLICIT_CONFIG can prove implementation or
    # existence, but not enforcement unless the source explicitly describes a
    # guard/trigger/policy that blocks invalid writes.
    if types & {"DECLARED_CONSTRAINT", "CHECK_CONSTRAINT", "TRIGGER",
                "ENFORCEMENT_CONFIG", "ENFORCEMENT_CODE"} and _provenance_refs(rule):
        return RuleEnforcement.ENFORCED.value
    if types or _rule_value(rule, "observed", "observedPattern") is not None:
        return RuleEnforcement.OBSERVED.value
    if _rule_value(rule, "inference", "inferred") is not None:
        return RuleEnforcement.INFERRED.value
    return RuleEnforcement.UNKNOWN.value


def _rule_id(rule: Mapping[str, Any]) -> str:
    return _text(_rule_value(rule, "ruleId", "rule_id", "ruleCode", "code", "id"))


def _rule_evidence_text(rule: Mapping[str, Any]) -> str:
    value = _rule_value(rule, "evidence", "provenance", "source", "description")
    return _evidence_summary(value)


def _validate_integrity_rule(rule: Mapping[str, Any], data: Any) -> RuleValidationResult:
    sample = _observed_count(rule, data, "sampleCount", "sample_count", "evaluatedCount")
    violations = _observed_count(rule, data, "violationCount", "violations", "invalidCount")
    if violations is None and isinstance(data, (list, tuple)):
        predicate = _rule_value(rule, "violationPredicate", "predicate")
        if callable(predicate):
            violations = sum(bool(predicate(row)) for row in data)
            sample = len(data) if sample is None else sample
    if sample is None or violations is None:
        return RuleValidationResult(_rule_id(rule), BusinessRuleType.INTEGRITY_CONSTRAINT.value,
                                    RuleValidationStatus.INSUFFICIENT_EVIDENCE.value,
                                    "integrity", _rule_enforcement(rule), sample_count=sample,
                                    violation_count=violations, violation_rate=_safe_ratio(violations, sample),
                                    evidence=_rule_evidence_text(rule),
                                    limitation="缺少可复核的样本量或完整性违例计数")
    return RuleValidationResult(_rule_id(rule), BusinessRuleType.INTEGRITY_CONSTRAINT.value,
                                RuleValidationStatus.VALIDATED.value, "integrity",
                                _rule_enforcement(rule), sample_count=sample,
                                violation_count=violations,
                                violation_rate=_safe_ratio(violations, sample),
                                evidence=_rule_evidence_text(rule))


def _validate_alert_rule(rule: Mapping[str, Any], data: Any) -> RuleValidationResult:
    sample = _observed_count(rule, data, "sampleCount", "sample_count", "evaluatedCount")
    hits = _observed_count(rule, data, "hitCount", "matchCount", "matchedRows", "matches",
                           "triggerCount", "hit_count")
    if hits is None and isinstance(data, (list, tuple)):
        predicate = _rule_value(rule, "matchPredicate", "predicate", "condition")
        if callable(predicate):
            hits = sum(bool(predicate(row)) for row in data)
            sample = len(data) if sample is None else sample
    if sample is None and isinstance(data, (list, tuple)):
        sample = len(data)
    if sample is None or hits is None:
        return RuleValidationResult(_rule_id(rule), BusinessRuleType.ALERT_DETECTION_RULE.value,
                                    RuleValidationStatus.INSUFFICIENT_EVIDENCE.value, "alert",
                                    _rule_enforcement(rule), sample_count=sample, hit_count=hits,
                                    hit_rate=_safe_ratio(hits, sample), evidence=_rule_evidence_text(rule),
                                    limitation="缺少可复核的样本量或告警命中计数")
    return RuleValidationResult(_rule_id(rule), BusinessRuleType.ALERT_DETECTION_RULE.value,
                                RuleValidationStatus.VALIDATED.value, "alert",
                                _rule_enforcement(rule), sample_count=sample, hit_count=hits,
                                hit_rate=_safe_ratio(hits, sample), evidence=_rule_evidence_text(rule),
                                limitation="命中率描述触发频率，不表示规则违例率")


def _validate_calculation_rule(rule: Mapping[str, Any], data: Any) -> RuleValidationResult:
    evaluated = _observed_count(rule, data, "evaluatedCount", "sampleCount", "evaluated")
    matches = _observed_count(rule, data, "matchCount", "matches", "matchedCount")
    mismatches = _observed_count(rule, data, "mismatchCount", "mismatches", "invalidCount")
    if matches is None and mismatches is not None and evaluated is not None:
        matches = max(0, evaluated - mismatches)
    if mismatches is None and matches is not None and evaluated is not None:
        mismatches = max(0, evaluated - matches)
    if evaluated is None and isinstance(data, (list, tuple)):
        expected = _rule_value(rule, "expectedValues", "expected")
        actual = _rule_value(rule, "actualValues", "actual")
        if isinstance(expected, (list, tuple)) and isinstance(actual, (list, tuple)):
            evaluated = min(len(expected), len(actual))
            tolerance = float(_rule_value(rule, "tolerance") or 0)
            matches = sum(abs(float(left) - float(right)) <= tolerance
                          for left, right in zip(expected, actual))
            mismatches = evaluated - matches
    if evaluated is None or matches is None or mismatches is None:
        return RuleValidationResult(_rule_id(rule), BusinessRuleType.CALCULATION_RULE.value,
                                    RuleValidationStatus.INSUFFICIENT_EVIDENCE.value, "calculation",
                                    _rule_enforcement(rule), evaluated_count=evaluated,
                                    match_count=matches, mismatch_count=mismatches,
                                    mismatch_rate=_safe_ratio(mismatches, evaluated),
                                    evidence=_rule_evidence_text(rule),
                                    limitation="缺少 expected/actual 或可复核的计算比较结果")
    return RuleValidationResult(_rule_id(rule), BusinessRuleType.CALCULATION_RULE.value,
                                RuleValidationStatus.VALIDATED.value, "calculation",
                                _rule_enforcement(rule), evaluated_count=evaluated,
                                match_count=matches, mismatch_count=mismatches,
                                mismatch_rate=_safe_ratio(mismatches, evaluated),
                                evidence=_rule_evidence_text(rule))


def _validate_transition_rule(rule: Mapping[str, Any], data: Any) -> RuleValidationResult:
    transitions = _rule_value(rule, "transitions", "observedTransitions", "history")
    if not isinstance(transitions, (list, tuple)):
        return RuleValidationResult(_rule_id(rule), BusinessRuleType.STATE_TRANSITION_RULE.value,
                                    RuleValidationStatus.INSUFFICIENT_EVIDENCE.value, "state_transition",
                                    _rule_enforcement(rule), evidence=_rule_evidence_text(rule),
                                    limitation="只有当前状态字段，没有状态历史，无法验证流转")
    allowed = _rule_value(rule, "allowedTransitions", "allowed", "transitionPolicy")
    if not isinstance(allowed, (list, tuple, set)):
        return RuleValidationResult(_rule_id(rule), BusinessRuleType.STATE_TRANSITION_RULE.value,
                                    RuleValidationStatus.UNRESOLVED.value, "state_transition",
                                    _rule_enforcement(rule), sample_count=len(transitions),
                                    evidence=_rule_evidence_text(rule),
                                    limitation="缺少允许/禁止状态流转定义")
    allowed_pairs = {tuple(item) for item in allowed if isinstance(item, (list, tuple)) and len(item) == 2}
    invalid = 0
    for item in transitions:
        pair = (item.get("from"), item.get("to")) if isinstance(item, Mapping) else tuple(item) if isinstance(item, (list, tuple)) else ()
        if pair not in allowed_pairs:
            invalid += 1
    return RuleValidationResult(_rule_id(rule), BusinessRuleType.STATE_TRANSITION_RULE.value,
                                RuleValidationStatus.VALIDATED.value, "state_transition",
                                _rule_enforcement(rule), sample_count=len(transitions),
                                violation_count=invalid, violation_rate=_safe_ratio(invalid, len(transitions)),
                                evidence=_rule_evidence_text(rule))


def _validate_outcome_rule(rule: Mapping[str, Any], data: Any, rule_type: str) -> RuleValidationResult:
    outcomes = _rule_value(rule, "outcomes", "decisions", "results", "observedOutcomes")
    if not isinstance(outcomes, (list, tuple)):
        return RuleValidationResult(_rule_id(rule), rule_type,
                                    RuleValidationStatus.INSUFFICIENT_EVIDENCE.value, "outcome",
                                    _rule_enforcement(rule), evidence=_rule_evidence_text(rule),
                                    limitation="只有 condition，没有 outcome/decision，不能按 condition 命中率验证")
    return RuleValidationResult(_rule_id(rule), rule_type,
                                RuleValidationStatus.SUPPORTED.value, "outcome",
                                _rule_enforcement(rule), sample_count=len(outcomes),
                                evidence=_rule_evidence_text(rule))


def _validate_unknown_rule(rule: Mapping[str, Any], data: Any) -> RuleValidationResult:
    return RuleValidationResult(_rule_id(rule), BusinessRuleType.UNKNOWN.value,
                                RuleValidationStatus.NEEDS_CLASSIFICATION.value, "none",
                                _rule_enforcement(rule), evidence=_rule_evidence_text(rule),
                                limitation="无法可靠分类，禁止默认使用完整性违例验证")


_RULE_VALIDATORS = {
    BusinessRuleType.INTEGRITY_CONSTRAINT.value: _validate_integrity_rule,
    BusinessRuleType.ALERT_DETECTION_RULE.value: _validate_alert_rule,
    BusinessRuleType.CALCULATION_RULE.value: _validate_calculation_rule,
    BusinessRuleType.STATE_TRANSITION_RULE.value: _validate_transition_rule,
}


def validate_business_rule(rule: Mapping[str, Any] | None,
                           data: Any = None) -> RuleValidationResult:
    """Dispatch validation by semantic type; never use alert hits as violations."""
    rule = rule if isinstance(rule, Mapping) else {}
    rule_type = normalize_business_rule_type(rule)
    if rule_type in {BusinessRuleType.ELIGIBILITY_RULE.value, BusinessRuleType.DECISION_RULE.value}:
        return _validate_outcome_rule(rule, data, rule_type)
    validator = _RULE_VALIDATORS.get(rule_type)
    if validator:
        return validator(rule, data)
    return _validate_unknown_rule(rule, data)


def _iter_business_rule_records(state: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    containers: list[Any] = [state]
    artifacts = state.get("artifacts")
    if isinstance(artifacts, Mapping):
        containers.extend(artifacts.values())
    for container in containers:
        if not isinstance(container, Mapping):
            continue
        for key in ("ruleDecisions", "rule_decisions", "businessRules", "business_rules",
                    "rules", "ruleCandidates", "rule_candidates"):
            value = container.get(key)
            if isinstance(value, Mapping):
                value = list(value.values())
            if isinstance(value, list):
                yield from (item for item in value if isinstance(item, Mapping))


def business_rule_validation_issues(state: Mapping[str, Any] | None) -> list[ValidationIssue]:
    if not isinstance(state, Mapping):
        return []
    issues: list[ValidationIssue] = []
    for rule in _iter_business_rule_records(state):
        result = validate_business_rule(rule, rule.get("data"))
        if result.rule_type == BusinessRuleType.UNKNOWN.value:
            issues.append(_issue("UNKNOWN_RULE_TYPE", "WARNING",
                                 f"业务规则 {_rule_id(rule) or '(未命名)'} 无法可靠分类，不能默认按完整性约束验证",
                                 artifact_type="BUSINESS_RULE", artifact_id=_rule_id(rule),
                                 details=result.as_dict()))
        elif result.validation_status in {RuleValidationStatus.INSUFFICIENT_EVIDENCE.value,
                                          RuleValidationStatus.NEEDS_CLASSIFICATION.value}:
            issues.append(_issue("INSUFFICIENT_RULE_EVIDENCE", "WARNING",
                                 f"业务规则 {_rule_id(rule) or '(未命名)'} 缺少适合其类型的验证证据",
                                 artifact_type="BUSINESS_RULE", artifact_id=_rule_id(rule),
                                 details=result.as_dict()))
    return issues


def validate_formal_business_rule_csv(blob: bytes,
                                      state: Mapping[str, Any] | None) -> list[ValidationIssue]:
    """Formal rules must have proven existence, not only a zero-violation profile."""
    try:
        header, rows = _csv_rows(blob)
    except (TypeError, UnicodeDecodeError, csv.Error):
        return []
    code_column = next((item for item in ("规则编码", "rule_code", "ruleId") if item in header), None)
    if not code_column:
        return []
    decisions = {row["rule_decision_id"]: row for row in _rule_audit_rows(state or {})}
    issues: list[ValidationIssue] = []
    formal_ids: set[str] = set()
    for row in rows:
        identifier = _text(row.get(code_column))
        if identifier:
            formal_ids.add(identifier)
        decision = decisions.get(identifier)
        if decision is None:
            issues.append(_issue("UNSUPPORTED_FORMAL_RULE", "ERROR",
                                 f"正式业务规则 {identifier} 没有对应决策记录",
                                 artifact_type="BUSINESS_RULE", artifact_id=identifier))
            continue
        if decision["existence_status"] not in {"DECLARED", "ENFORCED", "IMPLEMENTED"}:
            issues.append(_issue("OBSERVED_ONLY_RULE_IN_FORMAL_OUTPUT", "ERROR",
                                 f"正式业务规则 {identifier} 只有观察/推断证据，不能进入正式目录",
                                 artifact_type="BUSINESS_RULE", artifact_id=identifier,
                                 details={"existenceStatus": decision["existence_status"]}))
    for identifier, decision in decisions.items():
        if decision["existence_status"] in {"DECLARED", "ENFORCED", "IMPLEMENTED"} \
                and identifier not in formal_ids:
            issues.append(_issue("RULE_DECISION_MISSING_FROM_FORMAL_OUTPUT", "ERROR",
                                 f"正式存在的业务规则 {identifier} 未出现在业务规则 CSV",
                                 artifact_type="BUSINESS_RULE", artifact_id=identifier))
    return issues


def validate_formal_indicator_csv(blob: bytes,
                                  state: Mapping[str, Any] | None) -> list[ValidationIssue]:
    try:
        header, rows = _csv_rows(blob)
    except (TypeError, UnicodeDecodeError, csv.Error):
        return []
    code_column = next((item for item in ("指标编码", "指标代码", "indicator_code", "indicatorId")
                        if item in header), None)
    if not code_column:
        return []
    decisions = {row["indicator_decision_id"]: row for row in _indicator_rows(state or {})}
    issues: list[ValidationIssue] = []
    formal_ids: set[str] = set()
    for row in rows:
        identifier = _text(row.get(code_column))
        if identifier:
            formal_ids.add(identifier)
        decision = decisions.get(identifier)
        if decision is None:
            issues.append(_issue("UNSUPPORTED_FORMAL_INDICATOR", "ERROR",
                                 f"正式指标 {identifier} 没有对应指标决策记录",
                                 artifact_type="INDICATOR", artifact_id=identifier))
            continue
        if decision["status"] != CONFIRMED or decision["aggregation_semantics"] == "UNKNOWN":
            issues.append(_issue("UNSUPPORTED_FORMAL_INDICATOR", "ERROR",
                                 f"正式指标 {identifier} 未通过指标决策门禁",
                                 artifact_type="INDICATOR", artifact_id=identifier,
                                 details={"status": decision["status"],
                                          "aggregationSemantics": decision["aggregation_semantics"]}))
    for identifier, decision in decisions.items():
        if decision["status"] == CONFIRMED and decision["aggregation_semantics"] != "UNKNOWN" \
                and identifier not in formal_ids:
            issues.append(_issue("INDICATOR_DECISION_MISSING_FROM_FORMAL_OUTPUT", "ERROR",
                                 f"CONFIRMED 指标 {identifier} 未出现在指标 CSV",
                                 artifact_type="INDICATOR", artifact_id=identifier))
    return issues


def validate_formal_relation_csv(blob: bytes, state: Mapping[str, Any] | None) -> list[ValidationIssue]:
    """Reject formal relation rows without a confirmed, evidenced decision."""
    try:
        header, rows = _csv_rows(blob)
    except (TypeError, UnicodeDecodeError, csv.Error):
        return []  # The structural CSV validator owns parse/encoding errors.
    relation_column = "关系编码"
    if relation_column not in header:
        return []
    decisions = relation_decision_index(state)
    issues: list[ValidationIssue] = []
    for row in rows:
        relation_id = _text(row.get(relation_column))
        if not relation_id:
            continue
        decision = decisions.get(relation_id)
        if decision is None:
            issues.append(ValidationIssue(
                code="UNSUPPORTED_CONFIRMED_RELATION",
                severity="ERROR",
                message=f"正式关系 {relation_id} 没有对应的关系决策和证据，不能进入正式关系 CSV",
                artifact_type="ENTITY_RELATION",
                artifact_id=relation_id,
                evidence_required=EVIDENCE_REQUIRED_FOR_RELATION,
                details={"reason": "formal relation has no relation decision"},
            ))
            continue
        status = _status(decision.get("status") or decision.get("decision"))
        relation_type = _relation_type(decision)
        evidence_ok = has_formal_evidence(decision)
        if relation_type == TRANSFORMATION:
            evidence_ok = has_transformation_evidence(decision)
        if status != CONFIRMED or not evidence_ok:
            issues.append(ValidationIssue(
                code="UNSUPPORTED_CONFIRMED_RELATION",
                severity="ERROR",
                message=f"正式关系 {relation_id} 缺少足够证据，CANDIDATE/UNRESOLVED 不能写入正式关系 CSV",
                artifact_type="ENTITY_RELATION",
                artifact_id=relation_id,
                evidence_required=EVIDENCE_REQUIRED_FOR_RELATION,
                details={"decision": status or UNRESOLVED,
                         "evidenceTypes": sorted(evidence_types(decision))},
            ))
    formal_ids = {_text(row.get(relation_column)) for row in rows if _text(row.get(relation_column))}
    for relation_id, decision in decisions.items():
        if (_status(decision.get("status") or decision.get("decision")) == CONFIRMED
                and relation_id not in formal_ids):
            issues.append(_issue("RELATION_DECISION_MISSING_FROM_FORMAL_OUTPUT", "ERROR",
                                 f"CONFIRMED 关系 {relation_id} 未出现在正式关系 CSV",
                                 artifact_type="ENTITY_RELATION", artifact_id=relation_id))
    return issues


def semantic_validation_issues(state: Mapping[str, Any] | None) -> list[ValidationIssue]:
    """Return read-only semantic issues without inventing a repair action."""
    if not isinstance(state, Mapping):
        return []
    issues: list[ValidationIssue] = []
    # Business-object decisions are validated from the same structured
    # records that feed the audit CSV and formal output.  This is deliberately
    # read-only; it never upgrades a candidate or invents missing evidence.
    issues.extend(validate_business_object_decisions(state))
    issues.extend(validate_business_object_evidence_isolation(state))
    issues.extend(business_rule_validation_issues(state))
    issues.extend(validate_rule_decisions(state))
    issues.extend(validate_indicator_decisions(state))
    issues.extend(validate_relation_decision_integrity(state))
    issues.extend(validate_overloaded_reference_identifiers(state))
    issues.extend(validate_logical_entity_assignments(state))
    issues.extend(validate_uncertainty_preservation(state))
    issues.extend(validate_duplicate_mapping_definitions(state))
    issues.extend(validate_fk_coverage(state))
    decisions = relation_decision_index(state)
    for relation_id, decision in decisions.items():
        status = _status(decision.get("status") or decision.get("decision"))
        relation_evidence_ok = (has_transformation_evidence(decision)
                                if _relation_type(decision) == TRANSFORMATION
                                else has_formal_evidence(decision))
        if status == CONFIRMED and not relation_evidence_ok:
            issues.append(ValidationIssue(
                code="UNSUPPORTED_CONFIRMED_RELATION",
                severity="ERROR",
                message=f"关系决策 {relation_id} 被标记为 CONFIRMED，但没有达到证据门槛",
                artifact_type="ENTITY_RELATION",
                artifact_id=relation_id,
                evidence_required=EVIDENCE_REQUIRED_FOR_RELATION,
                details={"evidenceTypes": sorted(evidence_types(decision))},
            ))

    # Composition direction, role compatibility, ownership and aggregation
    # all use one shared policy.  The validator never repairs an edge.
    issues.extend(validate_composition_semantics(state))

    entities = list(_iter_entity_records(state))
    for entity in entities:
        entity_id = _text(entity.get("entityId") or entity.get("code") or entity.get("id"))
        role = normalize_entity_role(entity.get("role") or entity.get("entityRole")
                                      or entity.get("type"))
        if role == "DERIVED_ANALYTICAL_ENTITY":
            source_relations = [
                decision for decision in decisions.values()
                if _key(decision.get("relationType") or decision.get("type")) == "TRANSFORMATION"
                and _text(decision.get("targetEntity") or decision.get("target")) == entity_id
                and _status(decision.get("status") or decision.get("decision")) == CONFIRMED
                and has_transformation_evidence(decision)
            ]
            if not source_relations:
                issues.append(ValidationIssue(
                    code="MISSING_DERIVATION_LINEAGE",
                    severity="WARNING",
                    message=f"派生实体 {entity_id or '(未命名)'} 尚未确认 TRANSFORMATION 来源；需要补充证据或人工确认",
                    artifact_type="LOGICAL_ENTITY",
                    artifact_id=entity_id,
                    evidence_required=("VIEW_DERIVATION_LINEAGE", "ETL_SQL_LINEAGE", "CODE_REFERENCE", "EXPLICIT_CONFIG"),
                    details={"needsConfirmation": True},
                ))

    business_objects = []
    for key in ("businessObjects", "business_objects", "businessObjectDecisions"):
        value = state.get(key)
        if isinstance(value, list):
            business_objects.extend(item for item in value if isinstance(item, Mapping))
    for business_object in business_objects:
        object_id = _text(
            business_object.get("businessObjectId") or business_object.get("code")
            or business_object.get("id")
        )
        candidates = business_object.get("candidateMainEntities")
        if candidates is None:
            candidates = business_object.get("mainEntities")
        if candidates is None and isinstance(business_object.get("logicalEntities"), list):
            candidates = [
                item for item in business_object["logicalEntities"]
                if isinstance(item, Mapping)
                and str(item.get("isMain") or item.get("主逻辑实体") or "").upper() in {"Y", "TRUE"}
            ]
        if candidates is not None and len(candidates) != 1:
            issues.append(ValidationIssue(
                code="MAIN_LOGICAL_ENTITY_NEEDS_CONFIRMATION",
                severity="WARNING",
                message=f"业务对象 {object_id or '(未命名)'} 的主逻辑实体无法唯一确认，不得为了满足唯一性硬选",
                artifact_type="BUSINESS_OBJECT",
                artifact_id=object_id,
                details={"candidateCount": len(candidates), "needsConfirmation": True},
            ))
    return issues


def load_modeling_state(work_dir: str | os.PathLike[str]) -> dict[str, Any] | None:
    path = Path(work_dir) / "modeling_state.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def validate_formal_relation_file(blob: bytes, work_dir: str | os.PathLike[str]) -> list[ValidationIssue]:
    return validate_formal_relation_csv(blob, load_modeling_state(work_dir))


# ---------------------------------------------------------------------------
# Decision/audit layer
# ---------------------------------------------------------------------------

RELATION_DECISION_HEADERS = (
    "关系决策编码", "源实体编码", "目标实体编码", "关系类型",
    "源属性", "目标属性", "决策状态", "证据类型", "证据族",
    "冲突", "候选来源", "需要确认",
)
RULE_DECISION_HEADERS = (
    "规则决策编码", "规则名称", "规则类型", "规则来源",
    "存在状态", "验证状态", "强制状态", "有效性状态",
    "违例数量", "命中数量", "总数量", "比例", "处置状态",
)
INDICATOR_DECISION_HEADERS = (
    "指标决策编码", "候选名称", "决策状态", "公式状态",
    "聚合语义", "范围", "单位",
)
LOGICAL_ENTITY_DECISION_HEADERS = (
    "实体决策编码", "逻辑实体编码", "实体角色", "业务对象归属状态",
    "业务对象编码", "决策状态",
)

DECISION_AUDIT_HEADERS = {
    "business_object_decisions.csv": BUSINESS_OBJECT_DECISION_HEADERS,
    "relation_decisions.csv": RELATION_DECISION_HEADERS,
    "rule_decisions.csv": RULE_DECISION_HEADERS,
    "indicator_decisions.csv": INDICATOR_DECISION_HEADERS,
    "logical_entity_decisions.csv": LOGICAL_ENTITY_DECISION_HEADERS,
}

DECISION_AUDIT_FIELD_MAPS = {
    "relation_decisions.csv": {
        "relation_decision_id": "关系决策编码", "source_entity": "源实体编码",
        "target_entity": "目标实体编码", "relation_type": "关系类型",
        "source_attribute": "源属性", "target_attribute": "目标属性",
        "status": "决策状态", "evidence_types": "证据类型",
        "evidence_families": "证据族", "conflicts": "冲突",
        "candidate_source": "候选来源", "needs_confirmation": "需要确认",
    },
    "rule_decisions.csv": {
        "rule_decision_id": "规则决策编码", "rule_name": "规则名称",
        "rule_type": "规则类型", "rule_origin": "规则来源",
        "existence_status": "存在状态", "validation_status": "验证状态",
        "enforcement_status": "强制状态", "effectiveness_status": "有效性状态",
        "violation_count": "违例数量", "hit_count": "命中数量",
        "total_count": "总数量", "rate": "比例", "action_status": "处置状态",
    },
    "indicator_decisions.csv": {
        "indicator_decision_id": "指标决策编码", "candidate_name": "候选名称",
        "status": "决策状态", "formula_status": "公式状态",
        "aggregation_semantics": "聚合语义", "scope": "范围", "unit": "单位",
    },
    "logical_entity_decisions.csv": {
        "entity_decision_id": "实体决策编码", "logical_entity": "逻辑实体编码",
        "entity_role": "实体角色", "business_object_assignment_status": "业务对象归属状态",
        "business_object_code": "业务对象编码", "decision": "决策状态",
        # Internal completeness details remain available to validators and
        # modeling_state, but are intentionally not part of the v0.0.1 CSV.
        "missing_evidence": None,
    },
}


def _localized_audit_rows(filename: str, rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    mapping = DECISION_AUDIT_FIELD_MAPS.get(filename, {})
    localized: list[dict[str, Any]] = []
    for row in rows:
        output: dict[str, Any] = {}
        for key, value in row.items():
            if key in {"evidence_ids", "missing_evidence"} \
                    or (filename == "indicator_decisions.csv" and key == "grain"):
                continue
            output_key = mapping.get(key, key)
            if output_key is not None:
                output[output_key] = value
        localized.append(output)
    return localized


def _atomic_text_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _atomic_csv_write(path: Path, headers: Iterable[str], rows: Iterable[Mapping[str, Any]]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(headers), extrasaction="ignore",
                            lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: "" if value is None else value for key, value in row.items()})
    _atomic_text_write(path, buffer.getvalue())


def _unique_mappings(values: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        marker = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if marker not in seen:
            seen.add(marker)
            result.append(value)
    return result


def _records_for_keys(state: Mapping[str, Any], keys: Iterable[str]) -> list[Mapping[str, Any]]:
    containers: list[Any] = [state]
    artifacts = state.get("artifacts")
    if isinstance(artifacts, Mapping):
        containers.extend(value for value in artifacts.values() if isinstance(value, Mapping))
    found: list[Mapping[str, Any]] = []
    for container in containers:
        for key in keys:
            value = container.get(key)
            if isinstance(value, Mapping):
                value = list(value.values())
            if isinstance(value, list):
                found.extend(item for item in value if isinstance(item, Mapping))
    return _unique_mappings(found)


def _rule_existence_status(rule: Mapping[str, Any]) -> str:
    explicit = _key(_rule_value(rule, "existenceStatus", "existence_status", "evidenceStatus",
                                "ruleEvidenceStatus"))
    if explicit in RULE_EXISTENCE_STATUSES:
        return explicit
    types = evidence_types(rule)
    if types & {"DECLARED_CONSTRAINT", "CHECK_CONSTRAINT", "UNIQUE_CONSTRAINT",
                "NOT_NULL_CONSTRAINT", "TRIGGER", "ENFORCEMENT_CONFIG",
                "DATA_CONTRACT", "BUSINESS_DOCUMENT"}:
        return "DECLARED"
    if types & {"VIEW_DERIVATION_LINEAGE", "VIEW_CALCULATION_LOGIC", "ETL_SQL_LINEAGE",
                "CODE_REFERENCE", "EXPLICIT_CONFIG"}:
        return "IMPLEMENTED"
    if types & {"LLM_SEMANTIC_INFERENCE", "BUSINESS_COMMON_SENSE"}:
        return "INFERRED"
    if any(_rule_value(rule, key) is not None for key in
           ("violationCount", "hitCount", "matchCount", "sampleCount", "profile")):
        return "OBSERVED_ONLY"
    return "UNVERIFIED"


def _rule_origin(rule: Mapping[str, Any]) -> str:
    value = _key(_rule_value(rule, "ruleOrigin", "rule_origin", "origin"))
    if value:
        return value
    types = evidence_types(rule)
    return {
        "DECLARED_CONSTRAINT": "DATABASE_CONSTRAINT",
        "CHECK_CONSTRAINT": "DATABASE_CONSTRAINT",
        "UNIQUE_CONSTRAINT": "DATABASE_CONSTRAINT",
        "VIEW_DERIVATION_LINEAGE": "VIEW_IMPLEMENTATION",
        "VIEW_CALCULATION_LOGIC": "VIEW_IMPLEMENTATION",
        "CODE_REFERENCE": "APPLICATION_CODE",
        "EXPLICIT_CONFIG": "CONFIGURATION",
        "BUSINESS_DOCUMENT": "BUSINESS_DOCUMENT",
    }.get(next(iter(sorted(types)), ""), "OBSERVED_PATTERN" if types else "")


def _rule_effectiveness_status(rule: Mapping[str, Any]) -> str:
    value = _key(_rule_value(rule, "effectivenessStatus", "effectiveness_status"))
    return value if value in RULE_EFFECTIVENESS_STATUSES else "UNKNOWN"


def _rule_action_status(rule: Mapping[str, Any]) -> str:
    value = _key(_rule_value(rule, "actionStatus", "action_status"))
    if value in {"CONFIRMED", "KNOWN", "PASS"}:
        return "CONFIRMED"
    if value in {"UNKNOWN", "UNRESOLVED", "PENDING"}:
        return "UNKNOWN"
    action = _rule_value(rule, "action", "outcome", "decision", "result")
    return "CONFIRMED" if action not in (None, "") else "UNKNOWN"


def _rule_audit_rows(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for position, rule in enumerate(_records_for_keys(
            state, ("ruleDecisions", "rule_decisions", "businessRules", "business_rules",
                    "rules", "ruleCandidates", "rule_candidates"))):
        result = validate_business_rule(rule, rule.get("data"))
        identifier = _rule_id(rule) or f"RULE_{position:06d}"
        rate = result.violation_rate
        if rate is None:
            rate = result.hit_rate if result.hit_rate is not None else result.mismatch_rate
        missing = _text(_rule_value(rule, "missingEvidence", "missing_evidence", "limitation"))
        if result.rule_type == BusinessRuleType.ALERT_DETECTION_RULE.value and not missing:
            missing = "命中率不能证明规则有效性；需要效果或处置证据"
        if _rule_action_status(rule) == "UNKNOWN" and not missing and result.rule_type in {
                BusinessRuleType.ALERT_DETECTION_RULE.value,
                BusinessRuleType.ELIGIBILITY_RULE.value,
                BusinessRuleType.DECISION_RULE.value}:
            missing = "缺少明确处置动作证据"
        rows.append({
            "rule_decision_id": _text(_rule_value(rule, "decisionId", "decision_id")) or identifier,
            "rule_name": _text(_rule_value(rule, "ruleName", "name", "rule_code", "ruleCode")),
            "rule_type": result.rule_type,
            "rule_origin": _rule_origin(rule),
            "existence_status": _rule_existence_status(rule),
            "validation_status": result.validation_status,
            "enforcement_status": _rule_enforcement(rule),
            "effectiveness_status": _rule_effectiveness_status(rule),
            "violation_count": result.violation_count,
            "hit_count": result.hit_count,
            "total_count": result.sample_count or result.evaluated_count,
            "rate": rate,
            "action_status": _rule_action_status(rule),
        })
    return sorted(rows, key=lambda item: item["rule_decision_id"])


def _indicator_rows(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = _records_for_keys(state, ("indicatorDecisions", "indicator_decisions",
                                        "indicators", "metrics", "indicatorCandidates"))
    rows: list[dict[str, Any]] = []
    for position, indicator in enumerate(records):
        identifier = _text(_first_value(indicator, ("indicatorDecisionId", "decisionId",
                                                     "indicatorId", "metricId", "code", "id")))
        identifier = identifier or f"INDICATOR_{position:06d}"
        semantics = _key(_first_value(indicator, ("aggregationSemantics", "aggregation_semantics"))) or "UNKNOWN"
        if semantics not in METRIC_AGGREGATION_SEMANTICS:
            semantics = "UNKNOWN"
        formula_status = _key(_first_value(indicator, ("formulaStatus", "formula_status"))) or "UNKNOWN"
        status = _status(_first_value(indicator, ("status", "decision", "metricStatus"))) or UNRESOLVED
        missing = _text(_first_value(indicator, ("missingEvidence", "missing_evidence")))
        if semantics == "UNKNOWN" and not missing:
            missing = "缺少可复核的聚合语义；比例指标不能自动 AVG"
        rows.append({
            "indicator_decision_id": identifier,
            "candidate_name": _text(_first_value(indicator, ("candidateName", "name", "metricName"))),
            "status": status,
            "formula_status": formula_status,
            "aggregation_semantics": semantics,
            "scope": _text(_first_value(indicator, ("scope", "范围"))),
            "unit": _text(_first_value(indicator, ("unit", "单位"))),
        })
    return sorted(rows, key=lambda item: item["indicator_decision_id"])


def _assignment_status(entity: Mapping[str, Any]) -> str:
    raw = _key(_first_value(entity, ("businessObjectAssignmentStatus",
                                     "business_object_assignment_status", "assignmentStatus")))
    if raw in LE_ASSIGNMENT_STATUSES:
        return raw
    code = _text(_first_value(entity, ("businessObjectCode", "business_object_code")))
    return "ASSIGNED" if code else "UNRESOLVED"


def _logical_entity_rows(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for position, entity in enumerate(_unique_mappings(_iter_entity_records(state))):
        identifier = _entity_id(entity) or f"LE_DECISION_{position:06d}"
        status = _assignment_status(entity)
        code = _text(_first_value(entity, ("businessObjectCode", "business_object_code")))
        missing = _text(_first_value(entity, ("missingEvidence", "missing_evidence",
                                               "unassignedReason", "assignmentReason")))
        decision = _status(_first_value(entity, ("decision", "status"))) or status
        rows.append({
            "entity_decision_id": _text(_first_value(entity, ("decisionId", "decision_id"))) or identifier,
            "logical_entity": identifier,
            "entity_role": normalize_entity_role(_first_value(entity, ("role", "entityRole", "type"))),
            "business_object_assignment_status": status,
            "business_object_code": code if status == "ASSIGNED" else "",
            "decision": decision,
            "missing_evidence": missing,
        })
    return sorted(rows, key=lambda item: item["logical_entity"])


def _relation_rows(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for position, relation in enumerate(_iter_relation_decisions(state)):
        identifier = _relation_identity(relation, f"REL_{position:06d}")
        row = {
            "relation_decision_id": identifier,
            "source_entity": _relation_endpoint(relation, True),
            "target_entity": _relation_endpoint(relation, False),
            "relation_type": _relation_type(relation),
            "source_attribute": _text(relation.get("sourceAttribute") or relation.get("source_attribute")),
            "target_attribute": _text(relation.get("targetAttribute") or relation.get("target_attribute")),
            "status": _status(relation.get("status") or relation.get("decision")) or UNRESOLVED,
            "evidence_types": "|".join(sorted(evidence_types(relation))),
            "evidence_families": "|".join(evidence_families(relation)),
            "conflicts": _evidence_summary(relation.get("conflicts") or relation.get("conflict")),
            "candidate_source": _evidence_summary(relation.get("candidateSource") or relation.get("candidate_source")),
            "needs_confirmation": bool(relation.get("needsConfirmation") or relation.get("needs_confirmation")),
        }
        rows.append(row)
    return sorted(rows, key=lambda item: item["relation_decision_id"])


def _pending_rows(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in business_object_decision_records(state):
        if record.decision == CANDIDATE:
            rows.append({"pending_id": record.decision_id, "artifact_type": "BUSINESS_OBJECT",
                         "artifact_id": record.candidate_code, "question": record.confirmation_question,
                         "missing_evidence": record.unknowns})
    for relation in _relation_rows(state):
        if relation["status"] in {CANDIDATE, UNRESOLVED} or relation["needs_confirmation"]:
            rows.append({"pending_id": relation["relation_decision_id"], "artifact_type": "ENTITY_RELATION",
                         "artifact_id": relation["relation_decision_id"],
                         "question": "请补充关系的直接来源、语义或归属证据。",
                         "missing_evidence": relation["missing_evidence"]})
    for rule in _rule_audit_rows(state):
        if rule["action_status"] == "UNKNOWN" or rule["existence_status"] in {"UNVERIFIED", "OBSERVED_ONLY", "INFERRED"}:
            rows.append({"pending_id": rule["rule_decision_id"], "artifact_type": "BUSINESS_RULE",
                         "artifact_id": rule["rule_decision_id"],
                         "question": "请确认规则的正式来源、处置动作或强制执行方式。",
                         "missing_evidence": rule["missing_evidence"]})
    for indicator in _indicator_rows(state):
        if indicator["status"] != CONFIRMED or indicator["aggregation_semantics"] == "UNKNOWN":
            rows.append({"pending_id": indicator["indicator_decision_id"], "artifact_type": "INDICATOR",
                         "artifact_id": indicator["indicator_decision_id"],
                         "question": "请确认指标公式、粒度和聚合语义。",
                         "missing_evidence": indicator["missing_evidence"]})
    for entity in _logical_entity_rows(state):
        if entity["business_object_assignment_status"] == "UNRESOLVED":
            rows.append({"pending_id": entity["entity_decision_id"], "artifact_type": "LOGICAL_ENTITY",
                         "artifact_id": entity["logical_entity"],
                         "question": "请确认该逻辑实体是否属于正式业务对象。",
                         "missing_evidence": entity["missing_evidence"]})
    return sorted(rows, key=lambda item: (item["artifact_type"], item["artifact_id"]))


def write_decision_audits(work_dir: str | os.PathLike[str],
                          state: Mapping[str, Any] | None) -> dict[str, str]:
    """Materialize every semantic decision before any formal export."""
    target_dir = Path(work_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    state = state if isinstance(state, Mapping) else {}
    paths: dict[str, str] = {}
    paths["business_object_decisions.csv"] = write_business_object_decisions_csv(target_dir, state)
    _atomic_csv_write(target_dir / "relation_decisions.csv", RELATION_DECISION_HEADERS,
                      _localized_audit_rows("relation_decisions.csv", _relation_rows(state)))
    _atomic_csv_write(target_dir / "rule_decisions.csv", RULE_DECISION_HEADERS,
                      _localized_audit_rows("rule_decisions.csv", _rule_audit_rows(state)))
    _atomic_csv_write(target_dir / "indicator_decisions.csv", INDICATOR_DECISION_HEADERS,
                      _localized_audit_rows("indicator_decisions.csv", _indicator_rows(state)))
    _atomic_csv_write(target_dir / "logical_entity_decisions.csv", LOGICAL_ENTITY_DECISION_HEADERS,
                      _localized_audit_rows("logical_entity_decisions.csv", _logical_entity_rows(state)))
    # The old pending_confirmations.csv was a duplicate projection of the
    # decision records.  Keep the detailed confirmation data in modeling_state
    # and the per-record decision files, but never expose or require a sixth
    # audit CSV.  Remove a stale file when finalizing an existing workspace.
    try:
        (target_dir / "pending_confirmations.csv").unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass
    for name in DECISION_AUDIT_FILES:
        if name.endswith(".csv"):
            paths[name] = str(target_dir / name)
    if isinstance(state, Mapping):
        persisted_state = dict(state)
        persisted_state["decisionAuditTemplateVersion"] = DECISION_AUDIT_TEMPLATE_VERSION
        _atomic_text_write(target_dir / "modeling_state.json",
                           json.dumps(persisted_state, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    paths["modeling_state.json"] = str(target_dir / "modeling_state.json")
    report = {
        "schemaVersion": "1",
        "decisionAuditTemplateVersion": DECISION_AUDIT_TEMPLATE_VERSION,
        "issues": [issue.as_dict() for issue in semantic_validation_issues(state)],
        "decisionAuditCoverage": decision_audit_coverage(target_dir, state),
    }
    _atomic_text_write(target_dir / "validation_report.json",
                       json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    paths["validation_report.json"] = str(target_dir / "validation_report.json")
    return paths


def _read_csv_file(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def validate_logical_entity_assignments(state: Mapping[str, Any] | None) -> list[ValidationIssue]:
    if not isinstance(state, Mapping):
        return []
    confirmed_codes = {item.candidate_code for item in business_object_decision_records(state)
                       if item.decision == CONFIRMED}
    issues: list[ValidationIssue] = []
    for row in _logical_entity_rows(state):
        status = row["business_object_assignment_status"]
        if status == "ASSIGNED" and row["business_object_code"] not in confirmed_codes:
            issues.append(_issue("INVALID_BUSINESS_OBJECT_ASSIGNMENT", "ERROR",
                                 f"逻辑实体 {row['logical_entity']} 未引用正式 CONFIRMED Business Object",
                                 artifact_type="LOGICAL_ENTITY", artifact_id=row["logical_entity"]))
        if status == "UNASSIGNED" and not row["missing_evidence"]:
            issues.append(_issue("MISSING_UNASSIGNED_REASON", "ERROR",
                                 f"逻辑实体 {row['logical_entity']} 标为 UNASSIGNED 但没有原因",
                                 artifact_type="LOGICAL_ENTITY", artifact_id=row["logical_entity"]))
        if status == "UNRESOLVED" and not row["missing_evidence"]:
            issues.append(_issue("MISSING_ASSIGNMENT_EVIDENCE", "ERROR",
                                 f"逻辑实体 {row['logical_entity']} 归属未解析但没有缺失证据说明",
                                 artifact_type="LOGICAL_ENTITY", artifact_id=row["logical_entity"]))
    return issues


def validate_rule_decisions(state: Mapping[str, Any] | None) -> list[ValidationIssue]:
    if not isinstance(state, Mapping):
        return []
    issues: list[ValidationIssue] = []
    for row in _rule_audit_rows(state):
        if row["rule_type"] == BusinessRuleType.UNKNOWN.value:
            issues.append(_issue("UNKNOWN_RULE_TYPE", "WARNING",
                                 f"业务规则 {row['rule_decision_id']} 无法可靠分类",
                                 artifact_type="BUSINESS_RULE", artifact_id=row["rule_decision_id"]))
        if row["existence_status"] in {"OBSERVED_ONLY", "INFERRED", "UNVERIFIED"}:
            issues.append(_issue("RULE_EXISTENCE_NOT_PROVEN", "WARNING",
                                 f"业务规则 {row['rule_decision_id']} 只有观察/推断证据，不能作为正式规则",
                                 artifact_type="BUSINESS_RULE", artifact_id=row["rule_decision_id"]))
    return issues


def validate_indicator_decisions(state: Mapping[str, Any] | None) -> list[ValidationIssue]:
    if not isinstance(state, Mapping):
        return []
    issues: list[ValidationIssue] = []
    for row in _indicator_rows(state):
        if row["aggregation_semantics"] == "UNKNOWN" and row["status"] == CONFIRMED:
            issues.append(_issue("METRIC_AGGREGATION_SEMANTICS_UNKNOWN", "ERROR",
                                 f"指标 {row['indicator_decision_id']} 未确认聚合语义，不能 CONFIRMED",
                                 artifact_type="INDICATOR", artifact_id=row["indicator_decision_id"]))
    return issues


def validate_relation_decision_integrity(state: Mapping[str, Any] | None) -> list[ValidationIssue]:
    if not isinstance(state, Mapping):
        return []
    issues: list[ValidationIssue] = []
    for relation_id in duplicate_relation_decision_ids(state):
        issues.append(_issue("DUPLICATE_RELATION_DECISION_ID", "ERROR",
                             f"关系决策 ID {relation_id} 重复，不能静默覆盖",
                             artifact_type="ENTITY_RELATION", artifact_id=relation_id))
    for relation in _relation_rows(state):
        if relation["relation_type"] == TRANSFORMATION and relation["status"] == CONFIRMED:
            original = next((item for item in _iter_relation_decisions(state)
                             if _relation_identity(item) == relation["relation_decision_id"]), None)
            if original is not None and not has_transformation_evidence(original):
                issues.append(_issue("TRANSFORMATION_EVIDENCE_GATE", "ERROR",
                                     f"TRANSFORMATION {relation['relation_decision_id']} 缺少直接 derivation/lineage 证据",
                                     artifact_type="ENTITY_RELATION", artifact_id=relation["relation_decision_id"]))
    return issues


def validate_overloaded_reference_identifiers(state: Mapping[str, Any] | None) -> list[ValidationIssue]:
    if not isinstance(state, Mapping):
        return []
    issues: list[ValidationIssue] = []
    for relation in _iter_relation_decisions(state):
        sql = _text(relation.get("joinSql") or relation.get("joinSQL")
                    or relation.get("joinCondition") or relation.get("sql"))
        if " OR " in sql.upper() and _relation_type(relation) in {REFERENCE, TRANSFORMATION}:
            identifier = _relation_identity(relation)
            issues.append(_issue("OVERLOADED_REFERENCE_IDENTIFIER", "WARNING",
                                 f"关系 {identifier} 使用 OR JOIN，引用标识可能承担多个语义",
                                 artifact_type="ENTITY_RELATION", artifact_id=identifier,
                                 details={"joinCondition": sql, "needsDataQualityCheck": True}))
            if sql.upper().count(" OR ") > 1:
                issues.append(_issue("AMBIGUOUS_REFERENCE_MATCH", "WARNING",
                                     f"关系 {identifier} 存在多个 OR JOIN 分支，需要分别统计匹配和双匹配",
                                     artifact_type="ENTITY_RELATION", artifact_id=identifier))
    return issues


def validate_fk_coverage(state: Mapping[str, Any] | None) -> list[ValidationIssue]:
    if not isinstance(state, Mapping):
        return []
    declarations = _records_for_keys(state, ("declaredForeignKeys", "declared_foreign_keys",
                                              "foreignKeys", "foreign_keys", "fkDeclarations"))
    if not declarations:
        return []
    relations = _relation_rows(state)
    mapped_pairs = {(relation["source_entity"], relation["target_entity"])
                    for relation in relations
                    if "FOREIGN_KEY" in relation["evidence_types"].split("|")}
    mapped_ids = {relation["relation_decision_id"] for relation in relations
                  if "FOREIGN_KEY" in relation["evidence_types"].split("|")}
    counts = {"declared": len(declarations), "mapped": 0, "excluded": 0, "unresolved": 0}
    for declaration in declarations:
        source = _text(_first_value(declaration, ("sourceEntity", "sourceTable", "childTable", "source")))
        target = _text(_first_value(declaration, ("targetEntity", "targetTable", "parentTable", "target")))
        disposition = _key(_first_value(declaration, ("disposition", "status", "coverageStatus")))
        if disposition in {"EXCLUDED", "TECHNICAL", "NOT_APPLICABLE"}:
            counts["excluded"] += 1
        elif disposition in {"UNRESOLVED", "PENDING", "NEEDS_CONFIRMATION"}:
            counts["unresolved"] += 1
        elif (_text(_first_value(declaration, ("relationDecisionId", "relation_decision_id"))) in mapped_ids
              or (source, target) in mapped_pairs):
            counts["mapped"] += 1
        else:
            counts.setdefault("missing", 0)
            counts["missing"] += 1
    counts["missing"] = counts.get("missing", 0)
    if counts["mapped"] + counts["excluded"] + counts["unresolved"] + counts["missing"] != counts["declared"]:
        counts["missing"] = counts["declared"] - counts["mapped"] - counts["excluded"] - counts["unresolved"]
    if counts["missing"]:
        return [_issue("FK_COVERAGE_MISSING", "ERROR",
                       "声明 FK 没有进入关系审计、明确排除或待确认集合",
                       artifact_type="FOREIGN_KEY", details=counts)]
    return []


def validate_uncertainty_preservation(state: Mapping[str, Any] | None) -> list[ValidationIssue]:
    if not isinstance(state, Mapping):
        return []
    issues: list[ValidationIssue] = []
    for collection, artifact_type in (("relationDecisions", "ENTITY_RELATION"),
                                      ("businessObjectDecisions", "BUSINESS_OBJECT"),
                                      ("ruleDecisions", "BUSINESS_RULE"),
                                      ("indicatorDecisions", "INDICATOR")):
        value = state.get(collection)
        if not isinstance(value, list):
            continue
        for record in value:
            if not isinstance(record, Mapping):
                continue
            previous = _key(record.get("previousStatus") or record.get("previous_status"))
            current = _status(record.get("status") or record.get("decision") or record.get("metricStatus"))
            upgrades = record.get("upgradeEvidenceIds") or record.get("upgrade_evidence_ids") or []
            if previous in {"UNKNOWN", UNRESOLVED, CANDIDATE} and current == CONFIRMED and not upgrades:
                identifier = _text(record.get("relationId") or record.get("candidateCode")
                                    or record.get("ruleId") or record.get("indicatorId") or record.get("id"))
                issues.append(_issue("UNSUPPORTED_STATUS_UPGRADE", "ERROR",
                                     f"{artifact_type} {identifier} 从不确定状态升级为 CONFIRMED 但没有新证据",
                                     artifact_type=artifact_type, artifact_id=identifier))
    return issues


def validate_duplicate_mapping_definitions(state: Mapping[str, Any] | None) -> list[ValidationIssue]:
    if not isinstance(state, Mapping):
        return []
    definitions = state.get("mappingDefinitions") or state.get("mapping_definitions")
    if not isinstance(definitions, list):
        return []
    seen: set[str] = set()
    duplicates: set[str] = set()
    for definition in definitions:
        if not isinstance(definition, Mapping):
            continue
        key = _text(definition.get("key") or definition.get("businessObjectCode")
                    or definition.get("id") or definition.get("name"))
        if key and key in seen:
            duplicates.add(key)
        seen.add(key)
    return [_issue("DUPLICATE_MAPPING_DEFINITION", "ERROR",
                   f"映射定义 {key} 重复，禁止依赖 dict 后值覆盖前值",
                   artifact_type="MAPPING", artifact_id=key) for key in sorted(duplicates)]


def validate_decision_audits(work_dir: str | os.PathLike[str],
                             state: Mapping[str, Any] | None = None) -> list[ValidationIssue]:
    target_dir = Path(work_dir)
    if state is None:
        state = load_modeling_state(target_dir) or {}
    issues: list[ValidationIssue] = []
    for name in DECISION_AUDIT_FILES:
        if not (target_dir / name).is_file():
            issues.append(_issue("MISSING_DECISION_AUDIT", "ERROR",
                                 f"缺少必须的 mission-work 审计文件 {name}",
                                 artifact_type="DECISION_AUDIT", artifact_id=name))
    expected = {
        "business_object_decisions.csv": len(business_object_decision_records(state)),
        "relation_decisions.csv": len(_relation_rows(state)),
        "rule_decisions.csv": len(_rule_audit_rows(state)),
        "indicator_decisions.csv": len(_indicator_rows(state)),
        "logical_entity_decisions.csv": len(_logical_entity_rows(state)),
    }
    for name, count in expected.items():
        path = target_dir / name
        if not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                header = next(reader, [])
                actual = sum(1 for _ in reader)
        except (OSError, UnicodeError, csv.Error):
            issues.append(_issue("INVALID_DECISION_AUDIT", "ERROR",
                                 f"无法读取决策审计文件 {name}", artifact_type="DECISION_AUDIT", artifact_id=name))
            continue
        expected_header = list(DECISION_AUDIT_HEADERS[name])
        if header != expected_header:
            issues.append(_issue("INVALID_DECISION_AUDIT_SCHEMA", "ERROR",
                                 f"{name} 表头不符合决策审计模板 {DECISION_AUDIT_TEMPLATE_VERSION}",
                                 artifact_type="DECISION_AUDIT", artifact_id=name,
                                 details={"expectedHeader": expected_header, "actualHeader": header}))
        if actual != count:
            issues.append(_issue("DECISION_AUDIT_COVERAGE", "ERROR",
                                 f"{name} 审计覆盖不完整：期望 {count} 行，实际 {actual} 行",
                                 artifact_type="DECISION_AUDIT", artifact_id=name,
                                 details={"expected": count, "actual": actual, "coverage": 0 if count else 100}))
    return issues


def decision_audit_coverage(work_dir: str | os.PathLike[str],
                            state: Mapping[str, Any] | None = None) -> dict[str, Any]:
    target_dir = Path(work_dir)
    state = state if isinstance(state, Mapping) else (load_modeling_state(target_dir) or {})
    expected = {
        "business_object_decisions.csv": len(business_object_decision_records(state)),
        "relation_decisions.csv": len(_relation_rows(state)),
        "rule_decisions.csv": len(_rule_audit_rows(state)),
        "indicator_decisions.csv": len(_indicator_rows(state)),
        "logical_entity_decisions.csv": len(_logical_entity_rows(state)),
    }
    actual: dict[str, int] = {}
    for name in expected:
        try:
            actual[name] = len(_read_csv_file(target_dir / name))
        except (OSError, UnicodeError, csv.Error):
            actual[name] = 0
    return {"templateVersion": DECISION_AUDIT_TEMPLATE_VERSION,
            "expected": expected, "actual": actual,
            "coverage": {name: 100 if expected[name] == actual[name] else 0 for name in expected},
            "complete": expected == actual}


def _coverage_value(coverage: Mapping[str, Any], filename: str) -> float:
    """Return a normalized 0..1 coverage value for one audit artifact."""
    value = (coverage.get("coverage") or {}).get(filename, 0) if isinstance(coverage, Mapping) else 0
    try:
        return 1.0 if float(value) >= 100 else max(0.0, float(value) / 100.0)
    except (TypeError, ValueError):
        return 0.0


def write_validation_report(work_dir: str | os.PathLike[str],
                            *, status: str, issues: Iterable[ValidationIssue] = (),
                            audit_issues: Iterable[ValidationIssue] = (),
                            coverage: Mapping[str, Any] | None = None) -> str:
    """Persist the authoritative semantic-finalize marker for this mission.

    Upload code is allowed to read this marker, but must not recompute any
    semantic decision.  Keep the flat coverage fields for simple consumers and
    the detailed object for audit/debugging compatibility.
    """
    target_dir = Path(work_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    semantic = list(issues)
    audit = list(audit_issues)
    all_issues = semantic + audit
    normalized_status = _key(status) if status else "FAILED"
    coverage = coverage if isinstance(coverage, Mapping) else decision_audit_coverage(target_dir)
    report = {
        "schemaVersion": "2",
        "decisionAuditTemplateVersion": DECISION_AUDIT_TEMPLATE_VERSION,
        "semantic_validation_status": normalized_status,
        "validated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "business_object_decision_coverage": _coverage_value(coverage, "business_object_decisions.csv"),
        "relation_decision_coverage": _coverage_value(coverage, "relation_decisions.csv"),
        "rule_decision_coverage": _coverage_value(coverage, "rule_decisions.csv"),
        "indicator_decision_coverage": _coverage_value(coverage, "indicator_decisions.csv"),
        "logical_entity_decision_coverage": _coverage_value(coverage, "logical_entity_decisions.csv"),
        "errors": [item.as_dict() for item in all_issues if item.severity == "ERROR"],
        "warnings": [item.as_dict() for item in all_issues if item.severity == "WARNING"],
        "issues": [item.as_dict() for item in all_issues],
        "decisionAuditCoverage": dict(coverage),
    }
    return _atomic_text_write(target_dir / "validation_report.json",
                              json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def load_validation_report(work_dir: str | os.PathLike[str]) -> dict[str, Any] | None:
    """Read only the persisted semantic-finalize marker."""
    try:
        value = json.loads((Path(work_dir) / "validation_report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def semantic_validation_status(work_dir: str | os.PathLike[str]) -> str:
    report = load_validation_report(work_dir) or {}
    return _key(report.get("semantic_validation_status"))


_FORMAL_ARTIFACT_REQUIRED_HEADERS = {
    "business_objects.csv": {"业务对象编码", "业务对象名称", "业务对象定义"},
    "logical_entities.csv": {"业务对象编码", "逻辑实体编码", "逻辑实体名称", "逻辑实体定义"},
    "business_attributes.csv": {"逻辑实体编码", "业务属性编码", "业务属性名称", "是否页面显示"},
    "entity_relations.csv": {"关系编码", "源逻辑实体编码", "目标逻辑实体编码", "关系分类"},
    "business_rules.csv": {"规则编码", "规则名称", "规则描述", "触发条件", "判断或结果", "处置动作"},
    "rules.csv": {"规则编码", "规则名称", "规则描述", "触发条件", "判断或结果", "处置动作"},
    "terms.csv": {"术语编码", "术语名称", "术语定义"},
    "business_terms.csv": {"术语编码", "术语名称", "术语定义"},
    "indicators.csv": {"指标编码", "指标名称", "指标定义", "计算公式", "聚合类型"},
    "indicator.csv": {"指标编码", "指标名称", "指标定义", "计算公式", "聚合类型"},
    "metrics.csv": {"指标编码", "指标名称", "指标定义", "计算公式", "聚合类型"},
}


def _formal_artifact_schema_issues(name: str, blob: bytes) -> list[ValidationIssue]:
    required = _FORMAL_ARTIFACT_REQUIRED_HEADERS.get(name)
    if not required:
        return []
    try:
        header, _ = _csv_rows(blob)
    except (TypeError, UnicodeDecodeError, csv.Error):
        return [_issue("FORMAL_OUTPUT_INVALID_SCHEMA", "ERROR",
                       f"正式输出 {name} 不是可读取的 UTF-8 CSV",
                       artifact_type="OUTPUT", artifact_id=name)]
    missing = sorted(required - set(header))
    if missing:
        return [_issue("FORMAL_OUTPUT_INVALID_SCHEMA", "ERROR",
                       f"正式输出 {name} 缺少必要列",
                       artifact_type="OUTPUT", artifact_id=name,
                       details={"missingHeaders": missing})]
    return []


def _formal_output_issues(output_dir: Path, work_dir: Path,
                          state: Mapping[str, Any],
                          required_outputs: Iterable[str] | None,
                          validate_artifact_schema: bool = False) -> list[ValidationIssue]:
    """Run formal-output consistency only during semantic finalization."""
    requested_names = {os.path.basename(str(item)).lower() for item in (required_outputs or ())}
    names = requested_names.copy()
    if not names:
        names = {item.name.lower() for item in output_dir.glob("*.csv")}
    issues: list[ValidationIssue] = []
    for name in sorted(names):
        path = output_dir / name
        if not path.is_file():
            if requested_names:
                issues.append(_issue("REQUESTED_ARTIFACT_MISSING", "ERROR",
                                     f"请求的正式产物 {name} 未生成",
                                     artifact_type="OUTPUT", artifact_id=name,
                                     details={"artifact": name,
                                              "message": "Requested artifact was not produced."}))
            continue
        try:
            blob = path.read_bytes()
        except OSError:
            issues.append(_issue("FORMAL_OUTPUT_UNREADABLE", "ERROR",
                                 f"正式输出 {name} 无法读取", artifact_type="OUTPUT", artifact_id=name))
            continue
        if not blob.strip():
            issues.append(_issue("FORMAL_OUTPUT_EMPTY", "ERROR",
                                 f"正式输出 {name} 为空", artifact_type="OUTPUT", artifact_id=name))
            continue
        if validate_artifact_schema:
            issues.extend(_formal_artifact_schema_issues(name, blob))
        if name == "business_objects.csv":
            issues.extend(validate_formal_business_object_csv(blob, state))
        elif name in {"entity_relations.csv", "entity_relationships.csv"}:
            issues.extend(validate_formal_relation_csv(blob, state))
        elif name in {"business_rules.csv", "rules.csv"}:
            issues.extend(validate_formal_business_rule_csv(blob, state))
        elif name in {"metrics.csv", "indicator.csv", "atomic_indicators.csv", "composite_indicators.csv"}:
            issues.extend(validate_formal_indicator_csv(blob, state))
    return issues


def finalize_semantic_model(work_dir: str | os.PathLike[str],
                            state: Mapping[str, Any] | None = None,
                            *, output_dir: str | os.PathLike[str] | None = None,
                            required_outputs: Iterable[str] | None = None,
                            validate_artifact_schema: bool = False) -> dict[str, Any]:
    """Materialize and validate decisions exactly once at modeling finalize.

    A prior validation marker makes missing audit files a hard failure instead
    of allowing a later upload to silently recreate them.  The function is
    intentionally the only place that combines semantic validation with
    formal-output consistency; upload callers must only read its marker.
    """
    target_dir = Path(work_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    state = state if isinstance(state, Mapping) else (load_modeling_state(target_dir) or {})
    marker_exists = (target_dir / "validation_report.json").is_file()
    missing_before = [name for name in DECISION_AUDIT_FILES
                      if not (target_dir / name).is_file()]
    if marker_exists and missing_before:
        audit_issues = [_issue("MISSING_DECISION_AUDIT", "ERROR",
                                f"缺少必须的 mission-work 审计文件 {name}",
                                artifact_type="DECISION_AUDIT", artifact_id=name)
                        for name in missing_before]
        coverage = decision_audit_coverage(target_dir, state)
        path = write_validation_report(target_dir, status="FAILED",
                                       audit_issues=audit_issues, coverage=coverage)
        return {"status": "FAILED", "report": path, "issues": audit_issues,
                "auditIssues": audit_issues, "coverage": coverage}

    # First finalize is the only allowed materialization point.  The writer
    # emits the complete decision ledger, not just formal/confirmed results.
    write_decision_audits(target_dir, state)
    audit_issues = validate_decision_audits(target_dir, state)
    semantic_issues = semantic_validation_issues(state)
    if output_dir is not None:
        semantic_issues.extend(_formal_output_issues(Path(output_dir), target_dir, state,
                                                      required_outputs, validate_artifact_schema))
    coverage = decision_audit_coverage(target_dir, state)
    if not coverage.get("complete"):
        audit_issues.append(_issue("DECISION_AUDIT_COVERAGE", "ERROR",
                                   "决策审计未达到 100% 覆盖", artifact_type="DECISION_AUDIT",
                                   details=dict(coverage)))
    status = "FAILED" if any(item.severity == "ERROR"
                              for item in [*semantic_issues, *audit_issues]) else "PASSED"
    report_path = write_validation_report(target_dir, status=status,
                                          issues=semantic_issues,
                                          audit_issues=audit_issues,
                                          coverage=coverage)
    all_issues = semantic_issues + audit_issues
    return {"status": status, "report": report_path, "issues": all_issues,
            "semanticIssues": semantic_issues, "auditIssues": audit_issues,
            "coverage": coverage}
