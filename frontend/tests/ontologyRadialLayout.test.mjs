import test from "node:test";
import assert from "node:assert/strict";
import {
  computeSectorWeights,
  computeSectorAngles,
  computeNodeAngle,
  computeTrackCapacity,
  computeTrackCount,
  computeRingRadius,
  polarToCartesian,
  layoutOntologyRadial,
  normalizeOntologyData,
  nodeWidth,
} from "../src/ontologyRadialLayout.js";

const TAU = Math.PI * 2;
const obj = (id, code, entities = []) => ({
  id, code, name: code, nodeType: "businessObject", symbolSize: [92, 38], children: entities,
});
const ent = (id, code, attributes = []) => ({
  id, code, name: code, nodeType: "entity", symbolSize: [92, 38], children: attributes,
});
const attr = (id, code) => ({ id, code, name: code, nodeType: "attribute", symbolSize: [92, 38] });

test("computeSectorWeights 按后代节点数量分配扇区权重", () => {
  const entitiesByObject = new Map([
    ["o1", [ent("e1", "E1"), ent("e2", "E2", [attr("a1", "A1"), attr("a2", "A2")])]],
    ["o2", [ent("e3", "E3")]],
  ]);
  const attributesByEntity = new Map([
    ["e1", []],
    ["e2", [attr("a1", "A1"), attr("a2", "A2")]],
    ["e3", []],
  ]);
  const weights = computeSectorWeights([{ id: "o1" }, { id: "o2" }], entitiesByObject, attributesByEntity);
  // o1: 1 + (1+2) = 4；o2: 1 + 0 = 1
  assert.deepEqual(weights, [4, 1]);
});

test("computeSectorAngles 权重占比对应角度占比且预留扇区间隙", () => {
  const sectors = computeSectorAngles([3, 1], 0.1);
  assert.equal(sectors.length, 2);
  // 首个扇区起点到末个扇区终点 = 整圆减去末段间隙（0.1）
  const totalSpan = sectors[1].end - sectors[0].start;
  assert.ok(Math.abs(totalSpan - (TAU - 0.1)) < 1e-9);
  const first = sectors[0].end - sectors[0].start;
  const second = sectors[1].end - sectors[1].start;
  assert.ok(Math.abs(first / second - 3) < 1e-9);
  assert.ok(sectors[0].start < sectors[0].end && sectors[0].end < sectors[1].start);
});

test("computeNodeAngle 均匀分布且单节点取中心", () => {
  assert.equal(computeNodeAngle(0, 1, 0, 1), 0.5);
  assert.ok(Math.abs(computeNodeAngle(0, 1, 0, 2) - 0.25) < 1e-9);
  assert.ok(Math.abs(computeNodeAngle(0, 1, 1, 2) - 0.75) < 1e-9);
});

test("computeTrackCapacity 保证最小安全间距", () => {
  const radius = 300;
  const span = 1.0;
  const maxWidth = 92;
  const minGap = 18;
  const capacity = computeTrackCapacity(radius, span, maxWidth, minGap);
  const arc = radius * span;
  assert.equal(capacity, Math.floor(arc / (maxWidth + minGap)));
});

test("computeTrackCount 节点过多时自动增加多条轨道", () => {
  const firstRadius = 150;
  const span = 0.8;
  const maxWidth = 92;
  const minGap = 18;
  const one = computeTrackCount(3, firstRadius, span, maxWidth, minGap);
  const many = computeTrackCount(80, firstRadius, span, maxWidth, minGap);
  assert.ok(many >= one);
  assert.ok(many > 1);
});

test("computeRingRadius 依赖前后层最大节点尺寸与安全间距", () => {
  const r1 = computeRingRadius(100, 92, 92, 18, 0);
  assert.equal(r1, 100 + 46 + 18 + 46);
  const r2 = computeRingRadius(100, 92, 120, 18, 0);
  assert.ok(r2 > r1);
  const r3 = computeRingRadius(100, 92, 92, 18, 2);
  assert.equal(r3, r1 + 2 * (92 + 18));
});

test("polarToCartesian 极坐标转笛卡尔", () => {
  const p = polarToCartesian(400, 300, 100, 0);
  assert.ok(Math.abs(p.x - 500) < 1e-9 && Math.abs(p.y - 300) < 1e-9);
  const q = polarToCartesian(400, 300, 100, Math.PI / 2);
  assert.ok(Math.abs(q.x - 400) < 1e-9 && Math.abs(q.y - 400) < 1e-9);
});

test("normalizeOntologyData 展平对象/实体/属性并保留归属", () => {
  const data = [
    obj("o1", "O1", [ent("e1", "E1", [attr("a1", "A1")])]),
    ent("e2", "E2"),
  ];
  const { objects, entities, attributes } = normalizeOntologyData(data);
  assert.equal(objects.length, 1);
  assert.equal(entities.length, 2);
  assert.equal(attributes.length, 1);
  assert.equal(entities[0].objectId, "o1");
  assert.equal(entities[1].objectId, null);
  assert.equal(attributes[0].entityId, "e1");
});

test("nodeWidth 返回名称长度决定的宽度，缺失时使用兜底", () => {
  assert.equal(nodeWidth({ symbolSize: [120, 38] }), 120);
  assert.equal(nodeWidth({}), 92);
  assert.equal(nodeWidth({}, 64), 64);
});

test("业务属性默认隐藏：showAttributes=false 时不生成属性节点", () => {
  const data = [obj("o1", "O1", [ent("e1", "E1", [attr("a1", "A1")])])];
  const hidden = layoutOntologyRadial(data, { width: 800, height: 600 });
  const shown = layoutOntologyRadial(data, { width: 800, height: 600, showAttributes: true });
  assert.ok(hidden.nodes.every((node) => node.nodeType !== "attribute"));
  assert.ok(shown.nodes.some((node) => node.nodeType === "attribute"));
});

test("没有业务对象时逻辑实体位于最内层", () => {
  const data = [ent("e1", "E1"), ent("e2", "E2")];
  const layout = layoutOntologyRadial(data, { width: 800, height: 600 });
  assert.ok(layout.nodes.every((node) => node.nodeType === "entity"));
  const minRadius = Math.min(...layout.nodes.map((node) => Math.hypot(node.x - layout.centerX, node.y - layout.centerY)));
  const firstRadius = 92 / 2 + 18;
  assert.ok(Math.abs(minRadius - firstRadius) < 1e-6);
});

test("只生成真实 links：对象->实体 与 实体->属性", () => {
  const data = [
    obj("o1", "O1", [ent("e1", "E1", [attr("a1", "A1"), attr("a2", "A2")]), ent("e2", "E2")]),
    ent("e3", "E3"), // 无归属实体：不生成对象连线
  ];
  const layout = layoutOntologyRadial(data, { width: 800, height: 600, showAttributes: true });
  const ids = new Set(layout.nodes.map((node) => node.id));
  assert.ok(layout.links.every((link) => ids.has(link.source) && ids.has(link.target)));
  assert.equal(layout.links.length, 2 + 2); // o1->e1, o1->e2, e1->a1, e1->a2
  const o1e3 = layout.links.find((link) => link.source === "o1" && link.target === "e3");
  assert.equal(o1e3, undefined);
});

test("属性层支持多轨道且节点不重叠（角度间距 >= 安全间距）", () => {
  const manyAttrs = Array.from({ length: 40 }, (_, i) => attr(`a${i}`, `A${i}`));
  const data = [obj("o1", "O1", [ent("e1", "E1", manyAttrs)])];
  const layout = layoutOntologyRadial(data, { width: 1200, height: 900, showAttributes: true });
  const attrNodes = layout.nodes.filter((node) => node.nodeType === "attribute");
  assert.equal(attrNodes.length, 40);
  const radii = new Set(attrNodes.map((node) => Math.hypot(node.x - layout.centerX, node.y - layout.centerY)));
  assert.ok(radii.size >= 2, "属性应分布在多条轨道");
  // 同轨道相邻节点角度差对应弧长 >= 节点宽度 + 间距
  const grouped = new Map();
  attrNodes.forEach((node) => {
    const r = Math.hypot(node.x - layout.centerX, node.y - layout.centerY);
    const angle = Math.atan2(node.y - layout.centerY, node.x - layout.centerX);
    if (!grouped.has(r)) grouped.set(r, []);
    grouped.get(r).push(angle);
  });
  grouped.forEach((angles, r) => {
    angles.sort((a, b) => a - b);
    for (let i = 1; i < angles.length; i += 1) {
      const arc = r * (angles[i] - angles[i - 1]);
      assert.ok(arc >= 92 - 1e-6, `同轨道弧长 ${arc} 小于节点宽度`);
    }
  });
});

test("首尾节点不会被画布边界裁切（含悬浮放大余量）", () => {
  const manyAttrs = Array.from({ length: 30 }, (_, i) => attr(`a${i}`, `A${i}`));
  const data = [obj("o1", "O1", [ent("e1", "E1", manyAttrs)])];
  const layout = layoutOntologyRadial(data, { width: 800, height: 600, showAttributes: true });
  layout.nodes.forEach((node) => {
    const half = 92 / 2;
    assert.ok(node.x - half >= 0, `节点 ${node.id} 左边界越界`);
    assert.ok(node.y - half >= 0, `节点 ${node.id} 上边界越界`);
    assert.ok(node.x + half <= layout.canvasWidth, `节点 ${node.id} 右边界越界`);
    assert.ok(node.y + half <= layout.canvasHeight, `节点 ${node.id} 下边界越界`);
  });
});

test("画布在需要时扩大，允许滚动缩放平移", () => {
  const manyAttrs = Array.from({ length: 60 }, (_, i) => attr(`a${i}`, `A${i}`));
  const data = [obj("o1", "O1", [ent("e1", "E1", manyAttrs)])];
  const layout = layoutOntologyRadial(data, { width: 800, height: 600, showAttributes: true });
  assert.ok(layout.canvasWidth >= 800 && layout.canvasHeight >= 600);
  assert.ok(layout.canvasWidth > 800 || layout.canvasHeight > 600);
});
