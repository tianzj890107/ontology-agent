export const ONTOLOGY_LAYOUT_OPTIONS = Object.freeze([
  {
    value: "network",
    label: "关系聚类可视化",
    hint: "ForceAtlas2 是一种先进的力导向图布局",
  },
  {
    value: "radial",
    label: "语义环形可视化",
    hint: "按照业务对象、逻辑实体、业务属性等语义层级，由内向外分层排列节点",
  },
]);

export function ontologyLayoutOption(value) {
  return ONTOLOGY_LAYOUT_OPTIONS.find((option) => option.value === value) || null;
}
