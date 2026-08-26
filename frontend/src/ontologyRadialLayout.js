// 本体可视化径向分层多轨道布局（47313/47314 共用）。
//
// 布局语义：
//   - 第一层：业务对象（最内层）
//   - 第二层：逻辑实体
//   - 第三层：业务属性（默认隐藏）
//   - 业务对象占据独立扇区，扇区角度与其后代节点数量成正比；
//   - 每个语义层是一个环形区域，节点过多时在该区域内自动增加多条相邻轨道；
//   - 只生成真实数据关系连线，不创建虚拟根节点。
//
// 所有几何计算都是纯函数，便于单元测试。

const TAU = Math.PI * 2;

// 从 buildOntologyTree 生成的 roots 数组中规范化出扁平层级数据。
// data 中的 root 可以是 businessObject（children 为 entity）或 entity（无业务对象归属）。
export function normalizeOntologyData(data) {
  const objects = [];
  const entities = [];
  const attributes = [];
  (data || []).forEach((root) => {
    if (!root) return;
    if (root.nodeType === "businessObject") {
      objects.push(root);
      (root.children || []).forEach((child) => {
        if (child && child.nodeType === "entity") entities.push({ ...child, objectId: root.id });
      });
    } else if (root.nodeType === "entity") {
      entities.push({ ...root, objectId: null });
    }
  });
  entities.forEach((entity) => {
    (entity.children || []).forEach((child) => {
      if (child && child.nodeType === "attribute") attributes.push({ ...child, entityId: entity.id });
    });
  });
  return { objects, entities, attributes };
}

// 节点宽度：名称越长宽度越大；symbolSize[0] 由调用方按名称长度计算。
export function nodeWidth(node, fallback = 92) {
  const size = node && node.symbolSize;
  if (Array.isArray(size) && typeof size[0] === "number" && size[0] > 0) return size[0];
  return fallback;
}

// 1) 业务对象扇区权重：与后代节点数量（逻辑实体 + 业务属性）成正比。
export function computeSectorWeights(objects, entitiesByObject, attributesByEntity) {
  return objects.map((object) => {
    const entities = entitiesByObject.get(object.id) || [];
    const weight = entities.reduce(
      (sum, entity) => sum + 1 + (attributesByEntity.get(entity.id) || []).length,
      0,
    );
    return weight > 0 ? weight : 1;
  });
}

// 按权重把整圆（预留扇区间隙）切分为连续扇区。
export function computeSectorAngles(weights, sectorGap = 0.05, startAngle = -Math.PI / 2) {
  const count = weights.length;
  const totalWeight = weights.reduce((sum, value) => sum + value, 0) || count;
  const usable = TAU - sectorGap * count;
  const sectors = [];
  let angle = startAngle;
  weights.forEach((weight) => {
    const span = usable * (weight / totalWeight);
    sectors.push({ start: angle, end: angle + span });
    angle += span + sectorGap;
  });
  return sectors;
}

// 5) 节点角度：在 [spanStart, spanEnd) 内均匀分布。
export function computeNodeAngle(spanStart, spanEnd, index, total) {
  if (total <= 1) return (spanStart + spanEnd) / 2;
  return spanStart + ((index + 0.5) / total) * (spanEnd - spanStart);
}

// 2) 单条轨道在给定半径与扇区角度内最多可容纳的节点数。
// 安全间距由 minGap 保证：每个节点占用 (maxNodeWidth + minGap)。
export function computeTrackCapacity(radius, spanAngle, maxNodeWidth, minGap) {
  const arcLength = radius * Math.max(0, spanAngle);
  const slot = maxNodeWidth + minGap;
  if (slot <= 0 || arcLength <= 0) return 0;
  return Math.floor(arcLength / slot);
}

// 3) 需要的轨道数：从最内轨道开始贪心填充，容量随半径增大而增大。
export function computeTrackCount(count, firstRadius, spanAngle, maxNodeWidth, minGap) {
  let remaining = Math.max(0, count);
  let tracks = 0;
  let radius = firstRadius;
  while (remaining > 0) {
    tracks += 1;
    const capacity = computeTrackCapacity(radius, spanAngle, maxNodeWidth, minGap);
    if (capacity > 0) remaining -= capacity;
    else remaining -= 1; // 退化扇区也必须前进，避免死循环
    radius += maxNodeWidth + minGap;
  }
  return tracks;
}

// 4) 轨道半径：前一轨道最大节点尺寸 + 安全间距 + 当前轨道最大节点尺寸。
// trackIndex 为同层内的轨道序号（0 起）。
export function computeRingRadius(prevRadius, prevMaxWidth, currentMaxWidth, minGap, trackIndex = 0) {
  const base = prevRadius + prevMaxWidth / 2 + minGap + currentMaxWidth / 2;
  return base + trackIndex * (currentMaxWidth + minGap);
}

// 6) 极坐标转笛卡尔坐标。
export function polarToCartesian(centerX, centerY, radius, angle) {
  return { x: centerX + radius * Math.cos(angle), y: centerY + radius * Math.sin(angle) };
}

// 7) 生成最终 ECharts nodes / links。
export function layoutOntologyRadial(data, options = {}) {
  const {
    width = 800,
    height = 600,
    showAttributes = false,
    minGap = 18,
    sectorGap = 0.05,
    padding = 56,
    hoverScale = 1.12,
  } = options;
  const { objects, entities, attributes } = normalizeOntologyData(data);
  if (!entities.length) return null;

  const visibleAttributes = showAttributes ? attributes : [];
  const maxObjectWidth = objects.length ? Math.max(...objects.map((node) => nodeWidth(node))) : 0;
  const maxEntityWidth = Math.max(...entities.map((node) => nodeWidth(node)));
  const maxAttributeWidth = visibleAttributes.length
    ? Math.max(...visibleAttributes.map((node) => nodeWidth(node)))
    : 0;

  // 实体按业务对象分组；无归属实体归入 unassigned 组（真实数据中无对象连线）。
  const entitiesByObject = new Map();
  const unassigned = [];
  entities.forEach((entity) => {
    if (entity.objectId && objects.some((object) => object.id === entity.objectId)) {
      if (!entitiesByObject.has(entity.objectId)) entitiesByObject.set(entity.objectId, []);
      entitiesByObject.get(entity.objectId).push(entity);
    } else {
      unassigned.push(entity);
    }
  });
  const attributesByEntity = new Map();
  visibleAttributes.forEach((attribute) => {
    if (!attributesByEntity.has(attribute.entityId)) attributesByEntity.set(attribute.entityId, []);
    attributesByEntity.get(attribute.entityId).push(attribute);
  });

  // 分组（业务对象 + 无归属组），扇区权重 = 后代数量（实体 + 属性）。
  const groups = [];
  objects.forEach((object) => {
    groups.push({ object, items: entitiesByObject.get(object.id) || [] });
  });
  if (unassigned.length) {
    groups.push({ object: null, items: unassigned });
  }
  const groupWeights = groups.map((group) => {
    const weight = group.items.reduce(
      (sum, entity) => sum + 1 + (attributesByEntity.get(entity.id) || []).length,
      0,
    );
    return weight > 0 ? weight : 1;
  });
  const sectors = computeSectorAngles(groupWeights, sectorGap);

  // 轨道半径：
  //  - 无业务对象时，实体作为最内层；
  //  - 业务对象环 -> 实体环（按扇区需要多条轨道）-> 属性环（多条轨道）。
  const objectRadius = objects.length
    ? computeRingRadius(0, 0, maxObjectWidth, minGap, 0)
    : 0;
  const entityFirstRadius = objects.length
    ? computeRingRadius(objectRadius, maxObjectWidth, maxEntityWidth, minGap, 0)
    : computeRingRadius(0, 0, maxEntityWidth, minGap, 0);
  const entityRingRadius = (track) => entityFirstRadius + track * (maxEntityWidth + minGap);

  // 每个扇区需要几条实体轨道；全局取最大值。
  let entityTrackCount = 1;
  groups.forEach((group, index) => {
    const sector = sectors[index];
    if (!sector || !group.items.length) return;
    const span = sector.end - sector.start;
    entityTrackCount = Math.max(
      entityTrackCount,
      computeTrackCount(group.items.length, entityFirstRadius, span, maxEntityWidth, minGap),
    );
  });

  const attributeFirstRadius = entityTrackCount
    ? computeRingRadius(entityRingRadius(entityTrackCount - 1), maxEntityWidth, maxAttributeWidth, minGap, 0)
    : 0;
  const attributeRingRadius = (track) => attributeFirstRadius + track * (maxAttributeWidth + minGap);

  // 属性层轨道数：按每个实体的属性子区间计算，全局取最大值。
  let attributeTrackCount = 0;
  entities.forEach((entity) => {
    const attrs = attributesByEntity.get(entity.id) || [];
    if (!attrs.length) return;
    const groupIndex = groups.findIndex((group) => (group.items || []).some((item) => item.id === entity.id));
    const sector = sectors[Math.max(0, groupIndex)];
    const span = Math.max(0, (sector ? sector.end - sector.start : TAU) * 0.9);
    attributeTrackCount = Math.max(
      attributeTrackCount,
      computeTrackCount(attrs.length, attributeFirstRadius, span, maxAttributeWidth, minGap),
    );
  });

  // 画布尺寸：外圈预留节点半径与悬浮放大空间，不允许裁切。
  const outerRadius = attributeTrackCount > 0
    ? attributeRingRadius(attributeTrackCount - 1)
    : entityRingRadius(entityTrackCount - 1);
  const maxOuterHalfWidth = attributeTrackCount > 0 ? maxAttributeWidth / 2 : maxEntityWidth / 2;
  const requiredRadius = outerRadius + maxOuterHalfWidth * hoverScale + padding;
  const canvasWidth = Math.max(width, requiredRadius * 2);
  const canvasHeight = Math.max(height, requiredRadius * 2);
  const centerX = canvasWidth / 2;
  const centerY = canvasHeight / 2;

  const nodes = [];
  const links = [];
  const entityAngularSpans = new Map();
  const addNode = (node, radius, angle) => {
    const { x, y } = polarToCartesian(centerX, centerY, radius, angle);
    nodes.push({ ...node, children: undefined, x, y, angle });
  };

  // 业务对象节点：位于各自扇区中心。
  groups.forEach((group, index) => {
    if (!group.object) return;
    const sector = sectors[index];
    addNode(group.object, objectRadius, (sector.start + sector.end) / 2);
  });

  // 实体节点：在所属扇区内，按属性数量分配子区间（有属性时）或均匀分布（无属性时）。
  groups.forEach((group, index) => {
    if (!group.items.length) return;
    const sector = sectors[index];
    const span = sector.end - sector.start;
    const items = group.items;
    const attrCounts = items.map((entity) => (attributesByEntity.get(entity.id) || []).length);
    const attrTotal = attrCounts.reduce((sum, value) => sum + value, 0);
    const withSubSpans = visibleAttributes.length > 0 && attrTotal > 0;
    const subSpans = [];
    if (withSubSpans) {
      let angle = sector.start;
      items.forEach((entity, itemIndex) => {
        const weight = attrCounts[itemIndex] + 1;
        const sub = span * (weight / (attrTotal + items.length));
        subSpans.push({ start: angle, end: angle + sub });
        angle += sub;
      });
    }
    // 贪心分配到多条实体轨道，保持顺序。
    let remaining = items.map((item, itemIndex) => ({ item, itemIndex }));
    let track = 0;
    while (remaining.length) {
      const radius = entityRingRadius(track);
      const capacity = computeTrackCapacity(radius, span, maxEntityWidth, minGap);
      const take = capacity > 0 ? Math.min(capacity, remaining.length) : 1;
      const batch = remaining.slice(0, take);
      remaining = remaining.slice(take);
      batch.forEach(({ item, itemIndex }) => {
        const angularSpan = withSubSpans ? subSpans[itemIndex] : sector;
        const center = withSubSpans
          ? (subSpans[itemIndex].start + subSpans[itemIndex].end) / 2
          : computeNodeAngle(sector.start, sector.end, itemIndex, items.length);
        entityAngularSpans.set(item.id, angularSpan);
        addNode(item, radius, center);
        if (group.object) links.push({ source: group.object.id, target: item.id });
        else item.lineStyle = { opacity: 0 };
      });
      track += 1;
    }
  });

  // 属性节点：位于所属实体的角度附近（实体子区间内），在多条属性轨道上展开。
  if (visibleAttributes.length) {
    entities.forEach((entity) => {
      const attrs = attributesByEntity.get(entity.id) || [];
      if (!attrs.length) return;
      const angularSpan = entityAngularSpans.get(entity.id)
        || { start: -Math.PI, end: Math.PI };
      const span = Math.max(0.0001, angularSpan.end - angularSpan.start);
      let remaining = [...attrs];
      let track = 0;
      while (remaining.length) {
        const radius = attributeRingRadius(track);
        const capacity = computeTrackCapacity(radius, span, maxAttributeWidth, minGap);
        const take = capacity > 0 ? Math.min(capacity, remaining.length) : 1;
        const batch = remaining.slice(0, take);
        remaining = remaining.slice(take);
        batch.forEach((attribute, slot) => {
          const angle = computeNodeAngle(angularSpan.start, angularSpan.end, slot, take);
          addNode(attribute, radius, angle);
          links.push({ source: entity.id, target: attribute.id });
        });
        track += 1;
      }
    });
  }

  return { nodes, links, canvasWidth, canvasHeight, centerX, centerY, rings: { objectRadius, entityRingRadius, attributeRingRadius, entityTrackCount, attributeTrackCount } };
}
