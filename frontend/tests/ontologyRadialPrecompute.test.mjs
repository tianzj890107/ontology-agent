import test from "node:test";
import assert from "node:assert/strict";
import {
  createRadialLayoutCache,
  layoutIsForViewport,
  normalizeViewport,
  ontologyDataFingerprint,
  prepareRadialLayout,
  RADIAL_LAYOUT_VERSION,
  radialCacheKey,
  radialGraphOption,
  readViewport,
} from "../src/ontologyRadialPrecompute.js";

const makeNode = (layer, id, width = 92, height = 38) => ({ id, layer, nodeType: layer, name: id, symbolSize: [width, height] });
const relation = (source, target) => ({ source, target });

function sampleGraph() {
  return {
    nodes: [
      makeNode("businessObject", "bo1", 150),
      makeNode("logicalEntity", "le1", 130),
      makeNode("businessAttribute", "ba1", 110),
    ],
    links: [relation("bo1", "le1"), relation("le1", "ba1")],
    availability: {},
  };
}

test("数据指纹稳定且随节点或连线变化", () => {
  const first = ontologyDataFingerprint(sampleGraph());
  assert.equal(ontologyDataFingerprint(sampleGraph()), first);
  const extra = sampleGraph();
  extra.nodes.push(makeNode("metric", "m1"));
  assert.notEqual(ontologyDataFingerprint(extra), first);
  const relink = sampleGraph();
  relink.links[0].target = "le2";
  assert.notEqual(ontologyDataFingerprint(relink), first);
});

test("缓存键包含数据、层级、viewport 与布局版本", () => {
  const key = radialCacheKey({ fingerprint: "fp1", layerKey: "businessObject|logicalEntity", width: 1200, height: 700 });
  assert.equal(key, `radial:fp1:businessObject|logicalEntity:1200x700:${RADIAL_LAYOUT_VERSION}`);
  assert.notEqual(key, radialCacheKey({ fingerprint: "fp2", layerKey: "businessObject|logicalEntity", width: 1200, height: 700 }));
  assert.notEqual(key, radialCacheKey({ fingerprint: "fp1", layerKey: "businessObject", width: 1200, height: 700 }));
  assert.notEqual(key, radialCacheKey({ fingerprint: "fp1", layerKey: "businessObject|logicalEntity", width: 1000, height: 700 }));
  assert.notEqual(key, radialCacheKey({ fingerprint: "fp1", layerKey: "businessObject|logicalEntity", width: 1200, height: 700, version: "v2" }));
});

test("draftLayers 未确认不影响缓存键（layerKey 由 appliedLayers 决定）", () => {
  const applied = ["businessObject", "logicalEntity"];
  const base = radialCacheKey({ fingerprint: "fp", layerKey: applied.join("|"), width: 1200, height: 700 });
  assert.equal(radialCacheKey({ fingerprint: "fp", layerKey: ["businessObject", "logicalEntity", "businessAttribute"].filter((key) => applied.includes(key)).join("|"), width: 1200, height: 700 }), base);
});

test("viewport 归一化并四舍五入为整数", () => {
  assert.deepEqual(normalizeViewport(1201.4, 699.6), { width: 1201, height: 700 });
  assert.deepEqual(normalizeViewport(0, 0), { width: 320, height: 520 });
  assert.deepEqual(normalizeViewport(200, 300), { width: 320, height: 520 });
});

test("readViewport 从元素读取尺寸", () => {
  assert.deepEqual(readViewport(null), { width: 320, height: 520 });
  assert.deepEqual(readViewport({ clientWidth: 1440, clientHeight: 800 }), { width: 1440, height: 800 });
});

test("prepareRadialLayout 生成完整缓存载荷", () => {
  const prepared = prepareRadialLayout(sampleGraph(), ["businessObject", "logicalEntity", "businessAttribute"], { width: 1200, height: 700 });
  assert.ok(prepared);
  assert.equal(prepared.viewportWidth, 1200);
  assert.equal(prepared.viewportHeight, 700);
  assert.equal(prepared.layerKey, "businessObject|logicalEntity|businessAttribute");
  assert.ok(prepared.fitScale > 0);
  assert.equal(prepared.renderData.data.length, prepared.layout.nodes.length + prepared.layout.boundaryAnchors.length);
  assert.ok(prepared.layout.naturalWidth >= prepared.layout.nodes.length);
  // 同一输入重复准备结果稳定。
  const again = prepareRadialLayout(sampleGraph(), ["businessObject", "logicalEntity", "businessAttribute"], { width: 1200, height: 700 });
  assert.deepEqual(prepared.layout.nodes, again.layout.nodes);
  assert.equal(prepared.fitScale, again.fitScale);
});

test("没有可见节点时准备结果为 null", () => {
  assert.equal(prepareRadialLayout({ nodes: [makeNode("metric", "m1")], links: [] }, ["logicalEntity"], { width: 1200, height: 700 }), null);
});

test("radialGraphOption 使用 ECharts graph layout none", () => {
  const prepared = prepareRadialLayout(sampleGraph(), ["businessObject", "logicalEntity", "businessAttribute"], { width: 1200, height: 700 });
  const option = radialGraphOption(prepared);
  assert.equal(option.series[0].type, "graph");
  assert.equal(option.series[0].layout, "none");
  assert.equal(option.series[0].data.length, prepared.renderData.data.length);
  assert.equal(option.series[0].links, prepared.renderData.links);
  assert.equal(option.series[0].roam, true);
  assert.equal(option.series[0].animationDuration, 0);
});

test("layoutIsForViewport 拒绝错误 viewport 的缓存", () => {
  const prepared = prepareRadialLayout(sampleGraph(), ["businessObject", "logicalEntity", "businessAttribute"], { width: 1200, height: 700 });
  assert.equal(layoutIsForViewport(prepared, { width: 1200, height: 700 }), true);
  assert.equal(layoutIsForViewport(prepared, { width: 1000, height: 700 }), false);
  assert.equal(layoutIsForViewport(null, { width: 1200, height: 700 }), false);
});

test("缓存控制器：命中、写入、删除与限制规模", () => {
  const cache = createRadialLayoutCache({ maxEntries: 2 });
  const preparedA = prepareRadialLayout(sampleGraph(), ["businessObject"], { width: 800, height: 600 });
  const preparedB = prepareRadialLayout(sampleGraph(), ["logicalEntity"], { width: 800, height: 600 });
  const preparedC = prepareRadialLayout(sampleGraph(), ["businessAttribute"], { width: 800, height: 600 });
  cache.set("a", preparedA);
  cache.set("b", preparedB);
  assert.equal(cache.size(), 2);
  assert.equal(cache.get("a"), preparedA);
  cache.set("c", preparedC);
  assert.equal(cache.size(), 2);
  assert.equal(cache.has("a"), false);
  assert.equal(cache.get("c"), preparedC);
  cache.delete("b");
  assert.equal(cache.has("b"), false);
  cache.clear();
  assert.equal(cache.size(), 0);
});

test("缓存控制器：in-flight Promise 复用", async () => {
  const cache = createRadialLayoutCache({ maxEntries: 4 });
  let resolveFirst;
  const first = new Promise((resolve) => { resolveFirst = resolve; });
  cache.putInFlight("k", first);
  assert.equal(cache.getInFlight("k"), first);
  assert.equal(cache.inflightSize(), 1);
  resolveFirst("done");
  await first;
  cache.clearInFlight("k");
  assert.equal(cache.inflightSize(), 0);
  assert.equal(cache.getInFlight("k"), null);
});

test("缓存控制器：相同键重复 set 不超限且保留最新", () => {
  const cache = createRadialLayoutCache({ maxEntries: 1 });
  const a = { value: 1 };
  const b = { value: 2 };
  cache.set("k", a);
  cache.set("k", b);
  assert.equal(cache.size(), 1);
  assert.equal(cache.get("k"), b);
});
