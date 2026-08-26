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
  layoutQualityMetrics,
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
  assert.equal(hasNodeOverlap(layout.nodes, 9.99, 5.99), false);
});

test("数据多的扇区更宽但密度也更高", () => {
  const sectors = computeSectorAngles([{ id: "small", count: 4, weight: 2 }, { id: "large", count: 100, weight: 10 }]);
  assert.ok(sectors[1].span > sectors[0].span);
  assert.ok(sectors[1].span / sectors[0].span < 100 / 4);
});

test("父节点角度作为软偏好且后代可跨区填充空位", () => {
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
    assert.ok(entities.some((node) => Math.cos(node.angle - businessObject.angle) > 0));
  }
  assert.equal(hasNodeOverlap(layout.nodes, 9.99, 5.99), false);
});

test("大量宽业务对象形成中心多轨区域而不是扩大单一空心圆", () => {
  const nodes = Array.from({ length: 20 }, (_, index) => ({ ...makeNode("businessObject", `bo${index}`, 180), sectorId: `bo${index}` }));
  const layout = layoutOntologyRadial({ nodes, links: [] }, { selectedLayers: ["businessObject"], viewportWidth: 1200, viewportHeight: 700 });
  const tracks = layout.tracks.filter((track) => track.layer === "businessObject");
  assert.equal(tracks[0].radius, 0);
  assert.ok(tracks.length > 2);
  assert.ok(tracks.length < nodes.length);
  assert.ok(layout.quality.outerRadius < 300);
  assert.equal(hasNodeOverlap(layout.nodes, 9.99, 5.99), false);
});

test("少量两层节点保持高密度自然边界", () => {
  const nodes = [
    { ...makeNode("businessObject", "bo-a", 150), sectorId: "bo-a" },
    { ...makeNode("businessObject", "bo-b", 150), sectorId: "bo-b" },
    ...Array.from({ length: 5 }, (_, index) => ({ ...makeNode("logicalEntity", `le-${index}`, 140), parentId: index % 2 ? "bo-b" : "bo-a", sectorId: index % 2 ? "bo-b" : "bo-a" })),
  ];
  const layout = layoutOntologyRadial({ nodes, links: [] }, { selectedLayers: ["businessObject", "logicalEntity"], viewportWidth: 1200, viewportHeight: 700 });
  assert.ok(layout.quality.density > 0.35);
  assert.ok(layout.naturalWidth < 600);
  assert.ok(layout.naturalHeight < 350);
});

test("宽画布生成横向轨道并减少未使用的横向空间", () => {
  const nodes = Array.from({ length: 40 }, (_, index) => makeNode("logicalEntity", `le${index}`, 130));
  const wide = layoutOntologyRadial({ nodes, links: [] }, { selectedLayers: ["logicalEntity"], viewportWidth: 1400, viewportHeight: 700 });
  const square = layoutOntologyRadial({ nodes, links: [] }, { selectedLayers: ["logicalEntity"], viewportWidth: 700, viewportHeight: 700 });
  assert.ok(wide.aspectScale > square.aspectScale);
  assert.ok(wide.naturalWidth / wide.naturalHeight > square.naturalWidth / square.naturalHeight);
  assert.equal(hasNodeOverlap(wide.nodes, 9.99, 5.99), false);
});

test("大量属性自动增加共享轨道且外轨容量递增", () => {
  const nodes = [];
  const links = [];
  for (let index = 0; index < 6; index += 1) nodes.push({ ...makeNode("businessObject", `bo${index}`, 150), sectorId: `bo${index}` });
  for (let index = 0; index < 24; index += 1) {
    const parent = `bo${index % 6}`;
    nodes.push({ ...makeNode("logicalEntity", `le${index}`, 140), parentId: parent, sectorId: parent });
    links.push(relation(parent, `le${index}`));
  }
  for (let index = 0; index < 320; index += 1) {
    const parent = `le${index % 24}`;
    nodes.push({ ...makeNode("businessAttribute", `ba${index}`, 120), parentId: parent, sectorId: `bo${index % 6}` });
    links.push(relation(parent, `ba${index}`));
  }
  const layout = layoutOntologyRadial({ nodes, links }, { viewportWidth: 1400, viewportHeight: 760 });
  const attributes = layout.tracks.filter((track) => track.layer === "businessAttribute");
  assert.ok(attributes.length > 1);
  assert.ok(attributes.at(-1).capacity > attributes[0].capacity);
  assert.equal(hasNodeOverlap(layout.nodes, 9.99, 5.99), false);
  const scale = computeFitScale(layout.naturalWidth, layout.naturalHeight, 1400, 760);
  assert.ok(layout.naturalWidth * scale <= 1400);
  assert.ok(layout.naturalHeight * scale <= 760);
});

test("没有实际节点的语义层不占半径", () => {
  const nodes = Array.from({ length: 12 }, (_, index) => makeNode("logicalEntity", `le${index}`, 130));
  const onlyEntity = layoutOntologyRadial({ nodes, links: [] }, { selectedLayers: ["logicalEntity"], viewportWidth: 1000, viewportHeight: 600 });
  const withEmptyLayers = layoutOntologyRadial({ nodes, links: [] }, { selectedLayers: ["businessObject", "logicalEntity", "businessAttribute", "metric", "businessRule"], viewportWidth: 1000, viewportHeight: 600 });
  assert.equal(withEmptyLayers.naturalWidth, onlyEntity.naturalWidth);
  assert.equal(withEmptyLayers.naturalHeight, onlyEntity.naturalHeight);
  assert.deepEqual(withEmptyLayers.tracks, onlyEntity.tracks);
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
  assert.equal(computeFitScale(200, 100, 800, 400, 0), 4);
});

test("质量指标量化边界、密度、外半径和最近邻", () => {
  const metrics = layoutQualityMetrics([makeNode("logicalEntity", "a"), { ...makeNode("logicalEntity", "b"), x: 120, y: 0 }].map((node) => ({ x: 0, y: 0, ...node })));
  assert.ok(metrics.nodeArea > 0);
  assert.ok(metrics.boundingArea > 0);
  assert.ok(metrics.density > 0);
  assert.ok(metrics.averageNearestNeighborDistance > 0);
});

test("文字随缩放缩小并在放大时封顶", () => {
  const base = scaledTypography(13, 0.5, 1);
  assert.equal(scaledTypography(13, 0.5, 0.5), base * 0.5);
  assert.equal(scaledTypography(13, 0.5, 5), 13 * 0.5 * 1.8);
});

test("没有可见节点时不生成布局", () => {
  assert.equal(layoutOntologyRadial({ nodes: [makeNode("metric", "m1")], links: [] }, { selectedLayers: ["logicalEntity"] }), null);
});
