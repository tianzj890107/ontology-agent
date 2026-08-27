import test from "node:test";
import assert from "node:assert/strict";
import { ONTOLOGY_LAYOUT_OPTIONS, ontologyLayoutOption } from "../src/ontologyLayoutOptions.js";

test("布局选项固定为关系聚类可视化和语义环形可视化", () => {
  assert.deepEqual(ONTOLOGY_LAYOUT_OPTIONS.map((option) => option.value), ["network", "radial"]);
  assert.deepEqual(ONTOLOGY_LAYOUT_OPTIONS.map((option) => option.label), ["关系聚类可视化", "语义环形可视化"]);
  assert.deepEqual(ONTOLOGY_LAYOUT_OPTIONS.map((option) => option.hint), [
    "ForceAtlas2 是一种先进的力导向图布局",
    "按照业务对象、逻辑实体、业务属性等语义层级，由内向外分层排列节点",
  ]);
});

test("ontologyLayoutOption 按 value 返回选项，未知值返回空", () => {
  assert.equal(ontologyLayoutOption("network").label, "关系聚类可视化");
  assert.equal(ontologyLayoutOption("radial").label, "语义环形可视化");
  assert.equal(ontologyLayoutOption("unknown"), null);
});
