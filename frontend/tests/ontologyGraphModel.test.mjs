import test from "node:test";
import assert from "node:assert/strict";
import { buildGraphologyGraph, buildOntologyGraph, filterOntologyGraph } from "../src/ontologyGraphModel.js";

function fixtureRecords() {
  return new Map([
    ["businessObject", [{ "业务对象编码": "BO1", "业务对象名称": "订单" }]],
    ["logicalEntity", [{ "逻辑实体编码": "LE1", "逻辑实体名称": "订单明细", "业务对象编码": "BO1" }]],
    ["businessAttribute", [{ "业务属性编码": "BA1", "业务属性名称": "金额", "逻辑实体编码": "LE1" }]],
    ["entityRelation", [{ "关系编码": "REL1", "关系中文名称": "包含", "源逻辑实体编码": "LE1", "目标逻辑实体名称": "订单明细" }]],
    ["metric", [{ "指标编码": "M1", "指标名称": "订单金额", "来源业务属性": "BA1" }]],
    ["businessRule", [{ "规则编码": "R1", "规则名称": "订单金额必须非负", "规则描述": "订单明细金额不能为负数" }]],
    ["action", [{ "动作编码": "ACT1", "动作名称": "创建订单", "业务对象编码": "BO1" }]],
  ]);
}

test("统一模型生成七类节点并保留来源和原始行", () => {
  const model = buildOntologyGraph(fixtureRecords());
  assert.deepEqual(new Set(model.nodes.map((node) => node.nodeType)), new Set(["businessObject", "logicalEntity", "businessAttribute", "entityRelation", "metric", "businessRule", "action"]));
  const entity = model.nodes.find((node) => node.code === "LE1");
  assert.equal(entity.label, "订单明细");
  assert.equal(entity.source, "logical_entities.csv");
  assert.equal(entity.originalData["业务对象编码"], "BO1");
});

test("关系、指标、规则和动作都挂载到真实本体节点", () => {
  const model = buildOntologyGraph(fixtureRecords());
  assert.ok(model.links.some((edge) => edge.source === "businessObject:BO1" && edge.target === "logicalEntity:LE1"));
  assert.ok(model.links.some((edge) => edge.source === "logicalEntity:LE1" && edge.target === "businessAttribute:BA1"));
  assert.ok(model.links.some((edge) => edge.source === "businessAttribute:BA1" && edge.target === "metric:M1"));
  assert.ok(model.links.some((edge) => edge.source === "logicalEntity:LE1" && edge.target === "entityRelation:REL1"));
  assert.ok(model.links.some((edge) => edge.source === "businessObject:BO1" && edge.target === "businessRule:R1"));
  assert.ok(model.links.some((edge) => edge.source === "businessObject:BO1" && edge.target === "action:ACT1"));
});

test("规则只按结构化文本中的精确资产名称挂载", () => {
  const model = buildOntologyGraph(fixtureRecords());
  const rule = model.nodes.find((node) => node.nodeType === "businessRule");
  assert.ok(rule);
  assert.equal(model.links.some((edge) => edge.target === rule.id && edge.relationType === "ruleScope"), true);
});

test("图层过滤只保留两端可见的原边，不跨隐藏层造边", () => {
  const model = buildOntologyGraph(fixtureRecords());
  const filtered = filterOntologyGraph(model, ["businessObject", "businessAttribute"]);
  assert.deepEqual(new Set(filtered.nodes.map((node) => node.nodeType)), new Set(["businessObject", "businessAttribute"]));
  assert.equal(filtered.links.length, 0);
});

test("Graphology 图保留节点语义、边权重和过滤结果", () => {
  const model = buildOntologyGraph(fixtureRecords());
  const graph = buildGraphologyGraph(model, ["businessObject", "logicalEntity", "businessAttribute"]);
  assert.equal(graph.order, 3);
  assert.equal(graph.size, 2);
  assert.equal(graph.getNodeAttribute("businessObject:BO1", "nodeType"), "businessObject");
  assert.ok(graph.edges().every((edge) => Number(graph.getEdgeAttribute(edge, "weight")) > 0));
});
