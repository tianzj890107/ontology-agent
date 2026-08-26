import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildGraphologyGraph, buildOntologyGraph } from "../src/ontologyGraphModel.js";
import { FORCE_ATLAS_CONFIG, forceAtlasIterations, graphBounds, layoutOntologyForceAtlas, semanticSeed } from "../src/ontologyForceLayout.js";

function model(businessObjects = 2, entitiesPerObject = 3, attributesPerEntity = 8, isolated = 2) {
  const nodes = [];
  const links = [];
  for (let objectIndex = 0; objectIndex < businessObjects; objectIndex += 1) {
    const bo = `businessObject:BO${objectIndex}`;
    nodes.push({ id: bo, code: `BO${objectIndex}`, name: `业务对象${objectIndex}`, label: `业务对象${objectIndex}`, layer: "businessObject", nodeType: "businessObject", sectorId: bo });
    for (let entityIndex = 0; entityIndex < entitiesPerObject; entityIndex += 1) {
      const le = `logicalEntity:LE${objectIndex}-${entityIndex}`;
      nodes.push({ id: le, name: `逻辑实体${entityIndex}`, label: `逻辑实体${entityIndex}`, layer: "logicalEntity", nodeType: "logicalEntity", parentId: bo, sectorId: bo });
      links.push({ id: `${bo}->${le}`, source: bo, target: le, weight: 2.2 });
      for (let attributeIndex = 0; attributeIndex < attributesPerEntity; attributeIndex += 1) {
        const ba = `businessAttribute:BA${objectIndex}-${entityIndex}-${attributeIndex}`;
        nodes.push({ id: ba, name: `属性${attributeIndex}`, label: `属性${attributeIndex}`, layer: "businessAttribute", nodeType: "businessAttribute", parentId: le, sectorId: bo });
        links.push({ id: `${le}->${ba}`, source: le, target: ba, weight: 1.35 });
      }
    }
  }
  for (let index = 0; index < isolated; index += 1) nodes.push({ id: `businessRule:R${index}`, name: `规则${index}`, label: `规则${index}`, layer: "businessRule", nodeType: "businessRule" });
  return { nodes, links, availability: {} };
}

function assertFiniteLayout(graph) {
  graph.forEachNode((node, attributes) => {
    assert.ok(Number.isFinite(attributes.x), `${node} x must be finite`);
    assert.ok(Number.isFinite(attributes.y), `${node} y must be finite`);
  });
}

function csvRecords(path) {
  const source = readFileSync(path, "utf8").replace(/^\uFEFF/, "");
  const rows = []; let row = []; let cell = ""; let quoted = false;
  for (let index = 0; index < source.length; index += 1) {
    const char = source[index];
    if (char === '"') {
      if (quoted && source[index + 1] === '"') { cell += '"'; index += 1; }
      else quoted = !quoted;
    } else if (char === "," && !quoted) { row.push(cell); cell = ""; }
    else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && source[index + 1] === "\n") index += 1;
      row.push(cell); cell = "";
      if (row.some(Boolean)) rows.push(row);
      row = [];
    } else cell += char;
  }
  if (cell || row.length) { row.push(cell); if (row.some(Boolean)) rows.push(row); }
  const headers = rows[0] || [];
  return rows.slice(1).map((values) => Object.fromEntries(headers.map((header, index) => [header.trim(), String(values[index] || "").trim()])));
}

test("ForceAtlas2 参数集中配置且按规模限制迭代", () => {
  for (const key of ["scalingRatio", "gravity", "strongGravityMode", "barnesHutOptimize", "slowDown", "edgeWeightInfluence"]) assert.ok(key in FORCE_ATLAS_CONFIG);
  assert.ok(forceAtlasIterations(50) > forceAtlasIterations(900));
});

test("semantic seed 不把节点全部放在原点", () => {
  const graph = buildGraphologyGraph(model(), ["businessObject", "logicalEntity", "businessAttribute", "businessRule"]);
  semanticSeed(graph);
  assert.ok(new Set(graph.mapNodes((node, attributes) => `${attributes.x.toFixed(3)},${attributes.y.toFixed(3)}`)).size > 4);
});

test("同一输入稳定完成且所有坐标有限", () => {
  const first = buildGraphologyGraph(model(), ["businessObject", "logicalEntity", "businessAttribute", "businessRule"]);
  const second = buildGraphologyGraph(model(), ["businessObject", "logicalEntity", "businessAttribute", "businessRule"]);
  layoutOntologyForceAtlas(first, { iterations: 30 });
  layoutOntologyForceAtlas(second, { iterations: 30 });
  assertFiniteLayout(first);
  assert.deepEqual(first.mapNodes((node, attributes) => [attributes.x, attributes.y]), second.mapNodes((node, attributes) => [attributes.x, attributes.y]));
});

test("孤立规则被紧凑放置，不把边界扩大到极端范围", () => {
  const graph = buildGraphologyGraph(model(2, 2, 5, 12), ["businessObject", "logicalEntity", "businessAttribute", "businessRule"]);
  layoutOntologyForceAtlas(graph, { iterations: 35 });
  const bounds = graphBounds(graph);
  assertFiniteLayout(graph);
  assert.ok(bounds.width <= 100.000001);
  assert.ok(bounds.height <= 100.000001);
});

test("多个业务对象形成有限的非同点布局", () => {
  const graph = buildGraphologyGraph(model(6, 4, 8, 0), ["businessObject", "logicalEntity", "businessAttribute"]);
  layoutOntologyForceAtlas(graph, { iterations: 45 });
  const points = graph.filterNodes((node, attributes) => attributes.nodeType === "businessObject").map((node) => `${graph.getNodeAttribute(node, "x").toFixed(2)},${graph.getNodeAttribute(node, "y").toFixed(2)}`);
  assert.equal(new Set(points).size, 6);
  assertFiniteLayout(graph);
});

test("300+ 属性图可在有限迭代内完成", { timeout: 10000 }, () => {
  const graph = buildGraphologyGraph(model(4, 4, 20, 4), ["businessObject", "logicalEntity", "businessAttribute", "businessRule"]);
  assert.ok(graph.order > 300);
  layoutOntologyForceAtlas(graph, { iterations: 24, overlapIterations: 3 });
  assertFiniteLayout(graph);
});

test("仓库真实五层输出可构图和完成布局", { timeout: 15000 }, () => {
  const records = new Map([
    ["businessObject", csvRecords("output/business_objects.csv")],
    ["logicalEntity", csvRecords("output/logical_entities.csv")],
    ["businessAttribute", csvRecords("output/business_attributes.csv")],
    ["metric", csvRecords("output/indicators.csv")],
    ["businessRule", csvRecords("output/business_rules.csv")],
  ]);
  const ontology = buildOntologyGraph(records);
  const graph = buildGraphologyGraph(ontology, ["businessObject", "logicalEntity", "businessAttribute", "metric", "businessRule"]);
  assert.equal(ontology.nodes.filter((node) => node.nodeType === "businessObject").length, 8);
  assert.ok(ontology.nodes.filter((node) => node.nodeType === "businessAttribute").length > 800);
  assert.ok(graph.order > 900);
  layoutOntologyForceAtlas(graph, { iterations: 18, overlapIterations: 2 });
  assertFiniteLayout(graph);
  const bounds = graphBounds(graph);
  assert.ok(bounds.width <= 100.000001 && bounds.height <= 100.000001);
});
