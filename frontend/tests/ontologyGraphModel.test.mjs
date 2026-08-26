import test from "node:test";
import assert from "node:assert/strict";
import { buildGraphologyGraph, buildOntologyGraph, filterOntologyGraph } from "../src/ontologyGraphModel.js";

function fixtureRecords() {
  return new Map([
    ["businessObject", [{ "业务对象编码": "BO1", "业务对象名称": "订单" }]],
    ["logicalEntity", [{ "逻辑实体编码": "LE1", "逻辑实体名称": "订单明细", "业务对象编码": "BO1" }]],
    ["businessAttribute", [{ "业务属性编码": "BA1", "业务属性名称": "金额", "逻辑实体编码": "LE1" }]],
    ["metric", [{ "指标编码": "M1", "指标名称": "订单金额", "来源业务属性": "BA1" }]],
    ["businessRule", [{ "规则编码": "R1", "规则名称": "金额必须非负", "规则描述": "订单金额不能为负数" }]],
  ]);
}

test("统一模型生成五类节点并保留来源和原始行", () => {
  const model = buildOntologyGraph(fixtureRecords());
  assert.deepEqual(new Set(model.nodes.map((node) => node.nodeType)), new Set(["businessObject", "logicalEntity", "businessAttribute", "metric", "businessRule"]));
  const entity = model.nodes.find((node) => node.code === "LE1");
  assert.equal(entity.label, "订单明细");
  assert.equal(entity.source, "logical_entities.csv");
  assert.equal(entity.originalData["业务对象编码"], "BO1");
});

test("只从正式字段生成 BO→LE、LE→属性和指标来源边", () => {
  const model = buildOntologyGraph(fixtureRecords());
  assert.ok(model.links.some((edge) => edge.source === "businessObject:BO1" && edge.target === "logicalEntity:LE1"));
  assert.ok(model.links.some((edge) => edge.source === "logicalEntity:LE1" && edge.target === "businessAttribute:BA1"));
  assert.ok(model.links.some((edge) => edge.source === "businessAttribute:BA1" && edge.target === "metric:M1"));
});

test("无正式来源字段的规则仅生成孤立节点，不按文本猜边", () => {
  const model = buildOntologyGraph(fixtureRecords());
  const rule = model.nodes.find((node) => node.nodeType === "businessRule");
  assert.ok(rule);
  assert.equal(model.links.some((edge) => edge.source === rule.id || edge.target === rule.id), false);
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
