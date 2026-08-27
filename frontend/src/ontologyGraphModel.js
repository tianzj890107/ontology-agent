import Graph from "graphology";

export const ONTOLOGY_LAYER_DEFINITIONS = [
  { key: "businessObject", label: "业务对象", color: "#2563eb", baseRadius: 88, sigmaSize: 15 },
  { key: "logicalEntity", label: "逻辑实体", color: "#0f766e", baseRadius: 188, sigmaSize: 10 },
  { key: "businessAttribute", label: "业务属性", color: "#64748b", baseRadius: 300, sigmaSize: 4 },
  { key: "entityRelation", label: "实体关系", color: "#0891b2", baseRadius: 356, sigmaSize: 6 },
  { key: "metric", label: "指标", color: "#7c3aed", baseRadius: 412, sigmaSize: 7 },
  { key: "businessRule", label: "业务规则", color: "#c2410c", baseRadius: 524, sigmaSize: 7 },
  { key: "action", label: "动作", color: "#0e7490", baseRadius: 636, sigmaSize: 7 },
];

const LAYER_BY_KEY = new Map(ONTOLOGY_LAYER_DEFINITIONS.map((layer) => [layer.key, layer]));

function ontologyNodeStyle(name, color) {
  const length = Array.from(String(name || "")).length;
  return {
    symbol: "circle",
    symbolSize: [Math.max(92, Math.min(220, length * 14 + 32)), 38],
    itemStyle: { color, borderColor: "#fff", borderWidth: 1.5 },
  };
}

function ontologyReferences(value) {
  return String(value || "").split(/[，,、;；|]/).map((item) => item.trim()).filter(Boolean);
}

export function buildOntologyGraph(records) {
  const rows = (layer) => records.get(layer) || [];
  const nodes = [];
  const links = [];
  const indexes = { businessObject: new Map(), logicalEntity: new Map(), businessAttribute: new Map() };
  const addIndex = (layer, node, ...values) => values.filter(Boolean).forEach((value) => indexes[layer].set(String(value).trim(), node));
  const addNode = (layer, code, name, row, index, source) => {
    const definition = LAYER_BY_KEY.get(layer);
    const label = name || code || `${layer}${index + 1}`;
    const node = {
      id: `${layer}:${code || index}`,
      code: code || "",
      name: label,
      label,
      layer,
      nodeType: layer,
      source,
      originalData: row,
      ...ontologyNodeStyle(label, definition.color),
    };
    nodes.push(node);
    return node;
  };
  const addLink = (source, target, relationType, weight) => {
    links.push({ id: `${relationType}:${source}->${target}`, source, target, relationType, weight });
  };

  rows("businessObject").forEach((row, index) => {
    const code = row["业务对象编码"];
    if (!code) return;
    const node = addNode("businessObject", code, row["业务对象名称"] || code, row, index, "business_objects.csv");
    node.sectorId = node.id;
    addIndex("businessObject", node, code, row["业务对象名称"]);
  });
  rows("logicalEntity").forEach((row, index) => {
    const code = row["逻辑实体编码"];
    if (!code) return;
    const node = addNode("logicalEntity", code, row["逻辑实体名称"] || code, row, index, "logical_entities.csv");
    addIndex("logicalEntity", node, code, row["逻辑实体名称"]);
    const parent = indexes.businessObject.get(row["业务对象编码"]) || indexes.businessObject.get(row["业务对象名称"]);
    node.parentId = parent?.id || null;
    node.sectorId = parent?.sectorId || "ontology:unassigned";
    if (parent) addLink(parent.id, node.id, "businessObjectLogicalEntity", 2.2);
  });
  rows("businessAttribute").forEach((row, index) => {
    const code = row["业务属性编码"];
    if (!code) return;
    const node = addNode("businessAttribute", code, row["业务属性名称"] || code, row, index, "business_attributes.csv");
    addIndex("businessAttribute", node, code, row["业务属性名称"]);
    const parent = indexes.logicalEntity.get(row["逻辑实体编码"]) || indexes.logicalEntity.get(row["逻辑实体名称"]);
    node.parentId = parent?.id || null;
    node.sectorId = parent?.sectorId || "ontology:unassigned";
    if (parent) addLink(parent.id, node.id, "logicalEntityBusinessAttribute", 1.35);
  });
  rows("entityRelation").forEach((row, index) => {
    const code = row["关系编码"] || `relation-${index + 1}`;
    const name = row["关系中文名称"] || row["关系英文名称"] || code;
    const node = addNode("entityRelation", code, name, row, index, "entity_relations.csv");
    const source = indexes.logicalEntity.get(row["源逻辑实体编码"]) || indexes.logicalEntity.get(row["源逻辑实体名称"]);
    const target = indexes.logicalEntity.get(row["目标逻辑实体编码"]) || indexes.logicalEntity.get(row["目标逻辑实体名称"]);
    node.parentId = source?.id || target?.id || null;
    node.sectorId = source?.sectorId || target?.sectorId || "ontology:relations";
    if (source) addLink(source.id, node.id, "entityRelationSource", 1.6);
    if (target) addLink(node.id, target.id, "entityRelationTarget", 1.6);
  });
  rows("metric").forEach((row, index) => {
    const code = row["指标编码"] || `metric-${index + 1}`;
    const node = addNode("metric", code, row["指标名称"] || code, row, index, "metric-compatible.csv");
    const sources = ["来源业务属性", "来源逻辑实体", "来源业务对象"];
    const linked = new Set();
    sources.forEach((field) => ontologyReferences(row[field]).forEach((reference) => {
      const parent = indexes.businessAttribute.get(reference)
        || indexes.logicalEntity.get(reference)
        || indexes.businessObject.get(reference);
      if (parent && !linked.has(parent.id)) {
        addLink(parent.id, node.id, "metricSource", 1.5);
        linked.add(parent.id);
      }
    }));
    const primaryParent = nodes.find((candidate) => linked.has(candidate.id));
    node.parentId = primaryParent?.id || null;
    node.sectorId = primaryParent?.sectorId || "ontology:metrics";
  });
  rows("businessRule").forEach((row, index) => {
    const code = row["规则编码"] || `rule-${index + 1}`;
    const node = addNode("businessRule", code, row["规则名称"] || code, row, index, "business_rules.csv");
    const searchable = Object.values(row).map((value) => String(value || "")).join("\n");
    const linked = new Set();
    const linkExactMentions = (indexMap) => indexMap.forEach((parent, reference) => {
      if (!reference || !searchable.includes(reference) || linked.has(parent.id)) return;
      addLink(parent.id, node.id, "ruleScope", 1.35);
      linked.add(parent.id);
    });
    linkExactMentions(indexes.businessObject);
    linkExactMentions(indexes.logicalEntity);
    const primaryParent = nodes.find((candidate) => linked.has(candidate.id));
    node.parentId = primaryParent?.id || null;
    node.sectorId = primaryParent?.sectorId || "ontology:rules";
  });
  rows("action").forEach((row, index) => {
    const code = row["动作编码"] || `action-${index + 1}`;
    const node = addNode("action", code, row["动作名称"] || code, row, index, "actions.csv");
    const parent = indexes.businessObject.get(row["业务对象编码"]);
    node.parentId = parent?.id || null;
    node.sectorId = parent?.sectorId || "ontology:actions";
    if (parent) addLink(parent.id, node.id, "businessObjectAction", 1.5);
  });
  const availability = Object.fromEntries(ONTOLOGY_LAYER_DEFINITIONS.map((layer) => [layer.key, nodes.some((node) => node.layer === layer.key)]));
  return { nodes, links, availability };
}

export function filterOntologyGraph(model, selectedLayers) {
  const selected = new Set(selectedLayers || ONTOLOGY_LAYER_DEFINITIONS.map((layer) => layer.key));
  const nodes = (model?.nodes || []).filter((node) => selected.has(node.layer));
  const ids = new Set(nodes.map((node) => node.id));
  const links = (model?.links || []).filter((edge) => ids.has(edge.source) && ids.has(edge.target));
  return { nodes, links, availability: model?.availability || {} };
}

export function buildGraphologyGraph(model, selectedLayers) {
  const filtered = filterOntologyGraph(model, selectedLayers);
  const graph = new Graph({ type: "undirected", multi: false, allowSelfLoops: false });
  filtered.nodes.forEach((node) => {
    const definition = LAYER_BY_KEY.get(node.layer);
    graph.addNode(node.id, {
      ...node,
      label: node.label || node.name || node.code || node.id,
      color: definition?.color || "#64748b",
      size: definition?.sigmaSize || 5,
      x: 0,
      y: 0,
    });
  });
  filtered.links.forEach((edge, index) => {
    if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) return;
    const key = edge.id || `ontology-edge:${index}:${edge.source}->${edge.target}`;
    if (graph.hasEdge(key)) return;
    graph.addUndirectedEdgeWithKey(key, edge.source, edge.target, {
      ...edge,
      size: Math.max(0.7, Math.min(2.4, Number(edge.weight) || 1)),
      color: "#cbd5e1",
    });
  });
  return graph;
}
