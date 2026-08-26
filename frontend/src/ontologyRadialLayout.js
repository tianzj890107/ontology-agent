import { ONTOLOGY_LAYER_DEFINITIONS } from "./ontologyGraphModel.js";

export { ONTOLOGY_LAYER_DEFINITIONS } from "./ontologyGraphModel.js";

const TAU = Math.PI * 2;

export const nodeWidth = (node) => Array.isArray(node?.symbolSize) ? Number(node.symbolSize[0]) || 92 : Number(node?.symbolSize) || 92;
export const nodeHeight = (node) => Array.isArray(node?.symbolSize) ? Number(node.symbolSize[1]) || 38 : Number(node?.symbolSize) || 38;

export function computeTrackCapacity(radius, angularSpan = TAU, width = 92, gap = 10, aspectScale = 1) {
  if (radius <= 0) return 1;
  // Ramanujan ellipse circumference: wider viewports naturally provide more slots.
  const a = radius * aspectScale;
  const b = radius;
  const h = ((a - b) ** 2) / Math.max(1, (a + b) ** 2);
  const circumference = Math.PI * (a + b) * (1 + 3 * h / (10 + Math.sqrt(4 - 3 * h)));
  return Math.max(1, Math.floor(circumference * angularSpan / TAU / Math.max(1, width + gap)));
}

export function computeTrackCount(count, radius, angularSpan = TAU, width = 92, gap = 10) {
  return Math.max(1, Math.ceil(Math.max(0, count) / computeTrackCapacity(radius, angularSpan, width, gap)));
}

export function computeRingRadius(previousRadius, previousHeight, currentHeight, gap = 8) {
  return previousRadius + previousHeight / 2 + currentHeight / 2 + gap;
}

export function computeNodeAngle(start, end, index, count) {
  return start + (end - start) * ((index + 0.5) / Math.max(1, count));
}

export function polarToCartesian(centerX, centerY, radius, angle, aspectScale = 1) {
  return { x: centerX + radius * aspectScale * Math.cos(angle), y: centerY + radius * Math.sin(angle) };
}

export function computeSectorAngles(groups, gap = 0.035, startAngle = -Math.PI / 2) {
  if (!groups.length) return [];
  const safeGap = Math.min(gap, TAU / groups.length / 3);
  const usable = TAU - safeGap * groups.length;
  const weighted = groups.map((group) => ({ ...group, weight: Math.max(1, Number(group.weight) || Math.sqrt(Math.max(1, group.count || 1))) }));
  const total = weighted.reduce((sum, group) => sum + group.weight, 0);
  let cursor = startAngle;
  return weighted.map((group) => {
    const span = usable * group.weight / total;
    const sector = { ...group, start: cursor, end: cursor + span, span };
    cursor += span + safeGap;
    return sector;
  });
}

export function boxesOverlap(a, b, horizontalGap = 0, verticalGap = horizontalGap) {
  return Math.abs(a.x - b.x) < (nodeWidth(a) + nodeWidth(b)) / 2 + horizontalGap
    && Math.abs(a.y - b.y) < (nodeHeight(a) + nodeHeight(b)) / 2 + verticalGap;
}

export function hasNodeOverlap(nodes, horizontalGap = 0, verticalGap = horizontalGap) {
  for (let a = 0; a < nodes.length; a += 1) {
    for (let b = a + 1; b < nodes.length; b += 1) if (boxesOverlap(nodes[a], nodes[b], horizontalGap, verticalGap)) return true;
  }
  return false;
}

const angleDistance = (a, b) => { const distance = Math.abs(a - b) % TAU; return Math.min(distance, TAU - distance); };

function angleCandidates(preferred, radius, width, gap, aspectScale) {
  const capacity = computeTrackCapacity(radius, TAU, Math.max(24, width / 3), gap, aspectScale);
  const samples = Math.min(360, Math.max(60, capacity));
  const step = TAU / samples;
  const angles = [preferred];
  for (let offset = 1; angles.length < samples; offset += 1) angles.push(preferred + offset * step, preferred - offset * step);
  return angles.slice(0, samples);
}

function rawBounds(nodes) {
  if (!nodes.length) return { minX: 0, maxX: 0, minY: 0, maxY: 0, width: 0, height: 0 };
  const minX = Math.min(...nodes.map((node) => node.x - nodeWidth(node) / 2));
  const maxX = Math.max(...nodes.map((node) => node.x + nodeWidth(node) / 2));
  const minY = Math.min(...nodes.map((node) => node.y - nodeHeight(node) / 2));
  const maxY = Math.max(...nodes.map((node) => node.y + nodeHeight(node) / 2));
  return { minX, maxX, minY, maxY, width: maxX - minX, height: maxY - minY };
}

function placementScore(candidate, preferred, placed, targetAspect) {
  const bounds = rawBounds(placed);
  const next = rawBounds([...placed, candidate]);
  const growth = next.width * next.height - bounds.width * bounds.height;
  const aspectPenalty = Math.abs(next.width / Math.max(1, next.height) - targetAspect);
  return angleDistance(candidate.angle, preferred) * 800 + growth / 100 + aspectPenalty * 20;
}

function findPlacement(node, track, preferred, placed, options) {
  let best = null;
  for (const angle of angleCandidates(preferred, track.radius, nodeWidth(node), options.horizontalGap, options.aspectScale)) {
    const candidate = { ...node, ...polarToCartesian(0, 0, track.radius, angle, options.aspectScale), angle, trackIndex: track.trackIndex };
    if (placed.some((other) => boxesOverlap(candidate, other, options.horizontalGap, options.verticalGap))) continue;
    const score = placementScore(candidate, preferred, placed, options.targetAspect);
    if (!best || score < best.score) best = { node: candidate, score };
  }
  return best?.node || null;
}

function layerMinimumRadius(previousLayer, height, radialGap) {
  if (!previousLayer.length) return 0;
  return Math.max(...previousLayer.map((node) => node.normalizedRadius + nodeHeight(node) / 2)) + radialGap + height / 2;
}

function preferredAngles(nodes, placedById) {
  const groups = new Map();
  nodes.forEach((node) => { const key = node.parentId || node.sectorId || node.id; if (!groups.has(key)) groups.set(key, []); groups.get(key).push(node); });
  const result = new Map();
  [...groups].forEach(([key, members], groupIndex) => {
    const center = placedById.get(key)?.angle ?? (-Math.PI / 2 + TAU * groupIndex / Math.max(1, groups.size));
    const spread = Math.min(Math.PI, Math.max(0.2, members.length * 0.04));
    members.forEach((node, index) => result.set(node.id, center + spread * ((index + 0.5) / members.length - 0.5)));
  });
  return result;
}

export function packSemanticLayer(layerNodes, context = {}) {
  const layer = context.layer || layerNodes[0]?.layer;
  const options = {
    horizontalGap: context.horizontalGap ?? 10,
    verticalGap: context.verticalGap ?? 6,
    radialGap: context.radialGap ?? 8,
    aspectScale: context.aspectScale ?? 1,
    targetAspect: context.targetAspect ?? 1,
  };
  const queue = [...layerNodes];
  const nodes = [];
  const tracks = [];
  const collisions = [...(context.placed || [])];
  if (!queue.length) return { nodes, tracks };
  if (layer === "businessObject") {
    const center = { ...queue.shift(), x: 0, y: 0, angle: -Math.PI / 2, normalizedRadius: 0, trackIndex: 0 };
    nodes.push(center); collisions.push(center);
    tracks.push({ layer, trackIndex: 0, radius: 0, minRadius: 0, maxHeight: nodeHeight(center), capacity: 1, count: 1 });
  }
  if (!queue.length) return { nodes, tracks };
  const maxHeight = Math.max(...layerNodes.map(nodeHeight));
  const firstRadius = layer === "businessObject"
    ? computeRingRadius(0, nodeHeight(nodes[0]), maxHeight, options.radialGap)
    : layerMinimumRadius(context.previousLayerNodes || [], maxHeight, options.radialGap);
  const byId = new Map([...(context.placedById || new Map()), ...nodes.map((node) => [node.id, node])]);
  const preferences = layer === "businessObject"
    ? new Map(queue.map((node, index) => [node.id, -Math.PI / 2 + TAU * (index + 1) / layerNodes.length]))
    : preferredAngles(queue, byId);
  for (const node of queue) {
    const preferred = preferences.get(node.id) ?? -Math.PI / 2;
    let selected = null;
    for (const track of tracks.filter((item) => item.radius > 0)) {
      selected = findPlacement(node, track, preferred, collisions, options);
      if (selected) break;
    }
    if (!selected) {
      const prior = tracks.at(-1);
      let radius = Math.max(firstRadius, computeRingRadius(prior?.radius || 0, prior?.maxHeight || 0, nodeHeight(node), options.radialGap));
      let track;
      for (let attempt = 0; attempt < 400 && !selected; attempt += 1) {
        track = { layer, trackIndex: tracks.length, radius, minRadius: firstRadius, maxHeight: nodeHeight(node), count: 0 };
        selected = findPlacement(node, track, preferred, collisions, options);
        if (!selected) radius += Math.max(2, nodeHeight(node) / 5);
      }
      track.radius = radius;
      tracks.push(track);
    }
    selected.normalizedRadius = tracks[selected.trackIndex].radius;
    const track = tracks[selected.trackIndex];
    track.count += 1;
    track.maxHeight = Math.max(track.maxHeight, nodeHeight(selected));
    track.capacity = computeTrackCapacity(track.radius, TAU, Math.max(...layerNodes.map(nodeWidth)), options.horizontalGap, options.aspectScale);
    nodes.push(selected); collisions.push(selected);
  }
  return { nodes, tracks };
}

function canMove(nodes, allNodes, radius, options) {
  const ids = new Set(nodes.map((node) => node.id));
  const stationary = allNodes.filter((node) => !ids.has(node.id));
  const moved = nodes.map((node) => ({ ...node, ...polarToCartesian(0, 0, radius, node.angle, options.aspectScale), normalizedRadius: radius }));
  return !hasNodeOverlap(moved, options.horizontalGap, options.verticalGap)
    && !moved.some((node) => stationary.some((other) => boxesOverlap(node, other, options.horizontalGap, options.verticalGap)));
}

export function compactTrackRadii(nodes, tracks, options = {}) {
  const settings = { horizontalGap: options.horizontalGap ?? 10, verticalGap: options.verticalGap ?? 6, radialGap: options.radialGap ?? 8, aspectScale: options.aspectScale ?? 1 };
  const result = nodes.map((node) => ({ ...node }));
  const resultTracks = tracks.map((track) => ({ ...track }));
  for (const definition of ONTOLOGY_LAYER_DEFINITIONS) {
    const layerTracks = resultTracks.filter((track) => track.layer === definition.key && track.radius > 0).sort((a, b) => a.radius - b.radius);
    layerTracks.forEach((track, index) => {
      const members = result.filter((node) => node.layer === definition.key && node.trackIndex === track.trackIndex);
      const prior = layerTracks[index - 1];
      const lower = prior ? computeRingRadius(prior.radius, prior.maxHeight, track.maxHeight, settings.radialGap) : track.minRadius;
      for (const step of [4, 1, 0.25]) {
        while (track.radius - step >= lower && canMove(members, result, track.radius - step, settings)) {
          track.radius -= step;
          members.forEach((node) => Object.assign(node, polarToCartesian(0, 0, track.radius, node.angle, settings.aspectScale), { normalizedRadius: track.radius }));
        }
      }
    });
  }
  return { nodes: result, tracks: resultTracks };
}

export function calculateNaturalBounds(nodes, options = {}) {
  const padding = options.padding ?? 12;
  const hoverScale = options.hoverScale ?? 1.12;
  const minX = Math.min(...nodes.map((node) => node.x - nodeWidth(node) * hoverScale / 2));
  const maxX = Math.max(...nodes.map((node) => node.x + nodeWidth(node) * hoverScale / 2));
  const minY = Math.min(...nodes.map((node) => node.y - nodeHeight(node) * hoverScale / 2));
  const maxY = Math.max(...nodes.map((node) => node.y + nodeHeight(node) * hoverScale / 2));
  return { minX, maxX, minY, maxY, width: maxX - minX + padding * 2, height: maxY - minY + padding * 2, padding };
}

export function layoutQualityMetrics(nodes) {
  if (!nodes.length) return { nodeArea: 0, boundingArea: 0, density: 0, outerRadius: 0, averageNearestNeighborDistance: 0 };
  const bounds = rawBounds(nodes);
  const nodeArea = nodes.reduce((sum, node) => sum + nodeWidth(node) * nodeHeight(node), 0);
  const nearest = nodes.map((node, index) => Math.min(...nodes.filter((_, other) => other !== index).map((other) => Math.hypot(node.x - other.x, node.y - other.y))));
  return { nodeArea, boundingArea: bounds.width * bounds.height, density: nodeArea / Math.max(1, bounds.width * bounds.height), outerRadius: Math.max(...nodes.map((node) => node.normalizedRadius + nodeHeight(node) / 2)), averageNearestNeighborDistance: nodes.length > 1 ? nearest.reduce((sum, value) => sum + value, 0) / nodes.length : 0 };
}

export function layoutOntologyRadial(graph, options = {}) {
  const selected = new Set(options.selectedLayers || ONTOLOGY_LAYER_DEFINITIONS.map((layer) => layer.key));
  const sourceNodes = (graph?.nodes || []).filter((node) => selected.has(node.layer));
  if (!sourceNodes.length) return null;
  const visibleIds = new Set(sourceNodes.map((node) => node.id));
  const links = (graph?.links || []).filter((link) => visibleIds.has(link.source) && visibleIds.has(link.target));
  const targetAspect = Math.max(0.75, Math.min(2.4, Number(options.viewportWidth) / Math.max(1, Number(options.viewportHeight)) || 1));
  const aspectScale = Math.max(1, Math.min(1.8, targetAspect));
  const settings = { horizontalGap: options.horizontalGap ?? options.minGap ?? 10, verticalGap: options.verticalGap ?? options.minGap ?? 6, radialGap: options.radialGap ?? 8, aspectScale, targetAspect };
  const placed = []; const tracks = []; const placedById = new Map(); let previousLayerNodes = [];
  for (const definition of ONTOLOGY_LAYER_DEFINITIONS) {
    if (!selected.has(definition.key)) continue;
    const layerNodes = sourceNodes.filter((node) => node.layer === definition.key);
    if (!layerNodes.length) continue;
    const packed = packSemanticLayer(layerNodes, { ...settings, layer: definition.key, placed, placedById, previousLayerNodes });
    packed.nodes.forEach((node) => { placed.push(node); placedById.set(node.id, node); });
    tracks.push(...packed.tracks); previousLayerNodes = packed.nodes;
  }
  const compacted = compactTrackRadii(placed, tracks, settings);
  const bounds = calculateNaturalBounds(compacted.nodes, options);
  const nodes = compacted.nodes.map((node) => ({ ...node, x: node.x - bounds.minX + bounds.padding, y: node.y - bounds.minY + bounds.padding }));
  const boundaryAnchors = [{ id: "ontology:boundary:start", x: 0, y: 0, layoutAnchor: true, symbolSize: 0 }, { id: "ontology:boundary:end", x: bounds.width, y: bounds.height, layoutAnchor: true, symbolSize: 0 }];
  return { nodes, links, tracks: compacted.tracks, boundaryAnchors, naturalWidth: bounds.width, naturalHeight: bounds.height, aspectScale, quality: layoutQualityMetrics(compacted.nodes) };
}

export function computeFitScale(naturalWidth, naturalHeight, viewportWidth, viewportHeight, padding = 8) {
  return Math.min(Math.max(1, viewportWidth - padding * 2) / Math.max(1, naturalWidth), Math.max(1, viewportHeight - padding * 2) / Math.max(1, naturalHeight));
}

export function scaledTypography(baseSize, fitScale, roamZoom, maxZoom = 1.8) {
  return baseSize * fitScale * Math.min(Math.max(0.1, roamZoom), maxZoom);
}
