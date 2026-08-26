import test from "node:test";
import assert from "node:assert/strict";
import {
  computeFitScale,
  computeNodeAngle,
  computeRingRadius,
  computeSectorAngles,
  computeTrackCapacity,
  computeTrackCount,
  hasNodeOverlap,
  layoutOntologyRadial,
  nodeHeight,
  nodeWidth,
  ONTOLOGY_LAYER_DEFINITIONS,
  polarToCartesian,
  scaledTypography,
} from "../src/ontologyRadialLayout.js";

const makeNode = (layer, id, width = 92, height = 38) => ({ id, layer, nodeType: layer, name: id, symbolSize: [width, height] });
const relation = (source, target) => ({ source, target });

test("五个语义层按固定配置顺序声明", () => {
  assert.deepEqual(ONTOLOGY_LAYER_DEFINITIONS.map((layer) => layer.key), ["businessObject", "logicalEntity", "businessAttribute", "metric", "businessRule"]);
});

test("节点尺寸、轨道容量、轨道数和半径计算", () => {
  assert.equal(nodeWidth({ symbolSize: [120, 40] }), 120);
  assert.equal(nodeHeight({ symbolSize: [120, 40] }), 40);
  assert.equal(computeTrackCapacity(300, Math.PI * 2, 92, 18), Math.floor(300 * Math.PI * 2 / 110));
  assert.ok(computeTrackCount(80, 150, Math.PI * 2, 92, 18) > 1);
  assert.equal(computeRingRadius(100, 38, 50, 18), 162);
});

test("外圈半径更大时容量自然增加", () => {
  assert.ok(computeTrackCapacity(500, Math.PI * 2, 92, 18) > computeTrackCapacity(200, Math.PI * 2, 92, 18));
});

test("角度与极坐标转换正确", () => {
  assert.equal(computeNodeAngle(0, 1, 0, 1), 0.5);
  const point = polarToCartesian(100, 100, 50, 0);
  assert.deepEqual(point, { x: 150, y: 100 });
});

test("选择层级只保留可见节点及两端都可见的真实连线", () => {
  const graph = { nodes: [makeNode("businessObject", "bo"), makeNode("logicalEntity", "le"), makeNode("businessAttribute", "ba")], links: [relation("bo", "le"), relation("le", "ba")] };
  const layout = layoutOntologyRadial(graph, { selectedLayers: ["businessObject", "logicalEntity"] });
  assert.deepEqual(new Set(layout.nodes.map((node) => node.layer)), new Set(["businessObject", "logicalEntity"]));
  assert.deepEqual(layout.links, [relation("bo", "le")]);
});

test("业务对象内圈会自动扩圈且不重叠", () => {
  const nodes = Array.from({ length: 6 }, (_, index) => makeNode("businessObject", `bo${index}`, 220));
  const layout = layoutOntologyRadial({ nodes, links: [] }, { selectedLayers: ["businessObject"], minGap: 18 });
  assert.ok(layout.tracks.filter((track) => track.layer === "businessObject").length >= 1);
  assert.equal(hasNodeOverlap(layout.nodes, 17.99), false);
});

test("数据多的扇区更宽但密度也更高", () => {
  const sectors = computeSectorAngles([{ id: "small", count: 4, weight: 2 }, { id: "large", count: 100, weight: 10 }]);
  assert.ok(sectors[1].span > sectors[0].span);
  assert.ok(sectors[1].span / sectors[0].span < 100 / 4);
});

test("业务对象及其逻辑实体保持同一方向并在各轨道轮转分布", () => {
  const nodes = [];
  const links = [];
  for (const bo of ["bo-a", "bo-b"]) {
    nodes.push({ ...makeNode("businessObject", bo), sectorId: bo });
    for (let index = 0; index < 12; index += 1) {
      const id = `${bo}-le-${index}`;
      nodes.push({ ...makeNode("logicalEntity", id, 150), sectorId: bo, parentId: bo });
      links.push(relation(bo, id));
    }
  }
  const layout = layoutOntologyRadial({ nodes, links }, { selectedLayers: ["businessObject", "logicalEntity"] });
  for (const bo of ["bo-a", "bo-b"]) {
    const businessObject = layout.nodes.find((node) => node.id === bo);
    const entities = layout.nodes.filter((node) => node.layer === "logicalEntity" && node.sectorId === bo);
    assert.equal(Math.min(...entities.map((node) => node.trackIndex)), 0);
    assert.ok(entities.every((node) => Math.cos(node.angle - businessObject.angle) > 0));
  }
  assert.equal(hasNodeOverlap(layout.nodes, 17.99), false);
});

test("多个逻辑实体的属性共享全局属性轨道", () => {
  const nodes = [makeNode("businessObject", "bo"), ...Array.from({ length: 3 }, (_, index) => makeNode("logicalEntity", `le${index}`, 120))];
  const links = Array.from({ length: 3 }, (_, index) => relation("bo", `le${index}`));
  for (let entity = 0; entity < 3; entity += 1) {
    for (let index = 0; index < 40; index += 1) {
      const id = `ba${entity}-${index}`;
      nodes.push(makeNode("businessAttribute", id, 120));
      links.push(relation(`le${entity}`, id));
    }
  }
  const layout = layoutOntologyRadial({ nodes, links }, { selectedLayers: ["businessObject", "logicalEntity", "businessAttribute"], minGap: 18 });
  const attributeTracks = layout.tracks.filter((track) => track.layer === "businessAttribute");
  assert.ok(attributeTracks.length > 1);
  assert.ok(attributeTracks.slice(1).some((track, index) => track.capacity > attributeTracks[index].capacity));
  assert.equal(hasNodeOverlap(layout.nodes, 17.99), false);
  const actualMaxTrack = Math.max(...layout.nodes.filter((node) => node.layer === "businessAttribute").map((node) => node.trackIndex));
  assert.equal(actualMaxTrack + 1, attributeTracks.length);
});

test("边界由实际放置结果生成并包含两个不可见锚点", () => {
  const nodes = Array.from({ length: 50 }, (_, index) => makeNode("businessAttribute", `ba${index}`, 140));
  const layout = layoutOntologyRadial({ nodes, links: [] }, { selectedLayers: ["businessAttribute"], padding: 32, hoverScale: 1.12 });
  assert.equal(layout.boundaryAnchors.length, 2);
  assert.equal(layout.boundaryAnchors[0].x, 0);
  assert.equal(layout.boundaryAnchors[0].y, 0);
  assert.equal(layout.boundaryAnchors[1].x, layout.naturalWidth);
  assert.equal(layout.boundaryAnchors[1].y, layout.naturalHeight);
  layout.nodes.forEach((node) => {
    assert.ok(node.x - nodeWidth(node) * 1.12 / 2 >= 0);
    assert.ok(node.y - nodeHeight(node) * 1.12 / 2 >= 0);
    assert.ok(node.x + nodeWidth(node) * 1.12 / 2 <= layout.naturalWidth);
    assert.ok(node.y + nodeHeight(node) * 1.12 / 2 <= layout.naturalHeight);
  });
});

test("fit 将完整自然布局等比放入 viewport", () => {
  assert.equal(computeFitScale(1000, 500, 500, 500, 0), 0.5);
  assert.equal(computeFitScale(400, 800, 800, 400, 0), 0.5);
});

test("文字随缩放缩小并在放大时封顶", () => {
  const base = scaledTypography(13, 0.5, 1);
  assert.equal(scaledTypography(13, 0.5, 0.5), base * 0.5);
  assert.equal(scaledTypography(13, 0.5, 5), 13 * 0.5 * 1.8);
});

test("没有可见节点时不生成布局", () => {
  assert.equal(layoutOntologyRadial({ nodes: [makeNode("metric", "m1")], links: [] }, { selectedLayers: ["logicalEntity"] }), null);
});
