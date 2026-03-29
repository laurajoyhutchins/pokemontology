import { setupMobileNav, setupThemeToggle } from "./browser-runtime.js";
import { loadSiteData } from "./site-render.js";

const TYPE_ORDER = ["Species", "Variant", "Move", "Ability", "Item", "Type", "Ruleset"];
const EDGE_KINDS = [
  { id: "belongsToSpecies", label: "species", checked: true, color: "rgba(214, 109, 77, 0.44)" },
  { id: "hasType", label: "typing", checked: true, color: "rgba(216, 92, 140, 0.42)" },
  { id: "hasAbility", label: "ability", checked: true, color: "rgba(108, 165, 111, 0.40)" },
  { id: "hasMoveType", label: "move type", checked: true, color: "rgba(90, 136, 200, 0.42)" },
  { id: "learnsMove", label: "learnset", checked: false, color: "rgba(232, 184, 80, 0.20)" },
  { id: "availableIn", label: "context edges", checked: false, color: "rgba(108, 143, 128, 0.22)" },
];
const TYPE_COLORS = {
  Species: "#d66d4d",
  Variant: "#e8b850",
  Move: "#5a88c8",
  Ability: "#6ca56f",
  Item: "#b680d0",
  Type: "#d85c8c",
  Ruleset: "#6c8f80",
};
const LAYOUT_OPTIONS = ["orbit", "radial", "hierarchical", "force-lite"];
const SIZE_OPTIONS = ["degree", "contexts", "uniform"];
const COLOR_OPTIONS = ["type", "contexts"];
const DENSITY_OPTIONS = ["smart", "full", "focused"];
const MIN_ZOOM = 0.3;
const MAX_ZOOM = 2.8;
const ZOOM_STEP_IN = 1.12;
const ZOOM_STEP_OUT = 0.88;
const DEFAULT_NODE_LIMIT = 240;
const DEFAULT_SEARCH = "Pikachu";
const DEFAULT_LAYOUT_MODE = "orbit";
const DEFAULT_SIZE_MODE = "degree";
const DEFAULT_COLOR_MODE = "type";
const DEFAULT_EDGE_DENSITY = "smart";
const URL_STATE_VERSION = "2";
const GRAPH_PADDING = 36;
const CONTEXT_COLOR_STOPS = ["#d9d381", "#e8b850", "#d66d4d", "#5a88c8"];
const PERSPECTIVES = {
  typing: {
    label: "Typing",
    enabledTypes: ["Species", "Variant", "Type", "Ruleset"],
    enabledEdgeKinds: ["belongsToSpecies", "hasType", "availableIn"],
  },
  abilities: {
    label: "Abilities",
    enabledTypes: ["Species", "Variant", "Ability", "Ruleset"],
    enabledEdgeKinds: ["belongsToSpecies", "hasAbility", "availableIn"],
  },
  moves: {
    label: "Moves",
    enabledTypes: ["Species", "Variant", "Move", "Type", "Ruleset"],
    enabledEdgeKinds: ["belongsToSpecies", "hasMoveType", "availableIn"],
  },
  rulesets: {
    label: "Rulesets",
    enabledTypes: ["Species", "Variant", "Move", "Ability", "Type", "Ruleset"],
    enabledEdgeKinds: ["belongsToSpecies", "hasType", "hasAbility", "hasMoveType", "availableIn"],
  },
  learnsets: {
    label: "Learnsets",
    enabledTypes: ["Species", "Variant", "Move", "Ruleset"],
    enabledEdgeKinds: ["belongsToSpecies", "learnsMove", "availableIn"],
  },
};

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function slugify(value) {
  return String(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

function normalize(value) {
  return String(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function clampZoom(value) {
  return Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, value));
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function readCheckedIds(prefix, ids) {
  return new Set(ids.filter((id) => document.getElementById(`${prefix}${slugify(id)}`)?.checked));
}

function parseListParam(value) {
  return new Set(
    String(value || "")
      .split(",")
      .map((entry) => entry.trim())
      .filter(Boolean),
  );
}

function encodeSet(set) {
  return [...set].sort().join(",");
}

function parseBooleanParam(value) {
  return value === "1" || value === "true";
}

function parseChoice(value, options, fallback) {
  return options.includes(value) ? value : fallback;
}

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function hexToRgb(hex) {
  const normalized = hex.replace("#", "");
  const size = normalized.length === 3 ? 1 : 2;
  const values = normalized.length === 3
    ? normalized.split("").map((part) => Number.parseInt(part.repeat(2), 16))
    : [0, 1, 2].map((index) => Number.parseInt(normalized.slice(index * size, index * size + size), 16));
  return { r: values[0], g: values[1], b: values[2] };
}

function interpolateColor(start, end, t) {
  const a = hexToRgb(start);
  const b = hexToRgb(end);
  return `rgb(${Math.round(lerp(a.r, b.r, t))}, ${Math.round(lerp(a.g, b.g, t))}, ${Math.round(lerp(a.b, b.b, t))})`;
}

function gradientColor(stops, ratio) {
  if (ratio <= 0) return stops[0];
  if (ratio >= 1) return stops[stops.length - 1];
  const scaled = ratio * (stops.length - 1);
  const index = Math.floor(scaled);
  const t = scaled - index;
  return interpolateColor(stops[index], stops[index + 1], t);
}

function selectedNodeTypes() {
  return readCheckedIds("graph-type-", TYPE_ORDER);
}

function selectedEdgeKinds() {
  return readCheckedIds(
    "graph-edge-",
    EDGE_KINDS.map((kind) => kind.id),
  );
}

async function loadGraphIndex() {
  const response = await fetch("./graph-index.json", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load graph-index.json: ${response.status}`);
  }
  return response.json();
}

function buildIndexes(rawGraph) {
  const nodesById = new Map(rawGraph.nodes.map((node) => [node.id, node]));
  const adjacency = new Map();
  rawGraph.edges.forEach((edge) => {
    if (!adjacency.has(edge.source)) adjacency.set(edge.source, []);
    if (!adjacency.has(edge.target)) adjacency.set(edge.target, []);
    adjacency.get(edge.source).push(edge);
    adjacency.get(edge.target).push(edge);
  });
  return { nodesById, adjacency };
}

function matchesRuleset(node, ruleset) {
  if (!ruleset) return true;
  if (node.type === "Ruleset") return node.id === ruleset;
  return Array.isArray(node.contexts) && node.contexts.includes(ruleset);
}

function passesNodeFilters(node, state) {
  return (
    state.enabledTypes.has(node.type) &&
    matchesRuleset(node, state.selectedRuleset) &&
    !state.hiddenNodeIds.has(node.id)
  );
}

function passesEdgeFilters(edge, state) {
  return state.enabledEdgeKinds.has(edge.kind);
}

function findMatches(nodes, query) {
  const norm = normalize(query);
  if (!norm) return [];
  return nodes
    .map((node) => {
      const label = normalize(node.label);
      const curie = normalize(node.id);
      const identifiers = normalize((node.identifiers || []).join(" "));
      let score = 0;
      if (label === norm || curie === norm) score += 1000;
      if (label.startsWith(norm)) score += 200;
      if (curie.startsWith(norm)) score += 120;
      if (identifiers.includes(norm)) score += 60;
      if (`${label} ${curie} ${identifiers}`.includes(norm)) score += 20;
      score += Math.min(40, Number(node.degree) || 0);
      return { node, score };
    })
    .filter((entry) => entry.score > 0)
    .sort((a, b) => b.score - a.score || String(a.node.label).localeCompare(String(b.node.label)))
    .map((entry) => entry.node);
}

function bfsNeighborhood(anchorId, state, depthOverride = state.hopDepth, limitOverride = state.nodeLimit) {
  const included = new Set();
  const queue = [{ id: anchorId, depth: 0 }];
  while (queue.length && included.size < limitOverride) {
    const current = queue.shift();
    if (included.has(current.id)) continue;
    const node = state.nodesById.get(current.id);
    if (!node || !passesNodeFilters(node, state)) continue;
    included.add(current.id);
    if (current.depth >= depthOverride) continue;

    const candidates = (state.adjacency.get(current.id) || [])
      .filter((edge) => passesEdgeFilters(edge, state))
      .map((edge) => (edge.source === current.id ? edge.target : edge.source))
      .map((id) => state.nodesById.get(id))
      .filter((neighbor) => neighbor && passesNodeFilters(neighbor, state))
      .sort((a, b) => (Number(b.degree) || 0) - (Number(a.degree) || 0));

    for (const node of candidates) {
      if (included.has(node.id)) continue;
      if (queue.some((entry) => entry.id === node.id)) continue;
      queue.push({ id: node.id, depth: current.depth + 1 });
      if (queue.length + included.size >= limitOverride) break;
    }
  }
  return included;
}

function overviewNodes(state) {
  return new Set(
    state.rawGraph.nodes
      .filter((node) => passesNodeFilters(node, state))
      .sort((a, b) => (Number(b.degree) || 0) - (Number(a.degree) || 0))
      .slice(0, state.nodeLimit)
      .map((node) => node.id),
  );
}

function filterEdgesByDensity(edges, state, focusIds) {
  if (state.edgeDensityMode === "full") return edges;
  return edges.filter((edge) => {
    if (edge.kind !== "learnsMove") return true;
    const touchesFocus = focusIds.has(edge.source) || focusIds.has(edge.target);
    if (touchesFocus) return true;
    if (state.edgeDensityMode === "focused") return false;
    return (Number(edge.context_count) || 0) >= 2;
  });
}

function buildAdjacency(edges) {
  const adjacency = new Map();
  edges.forEach((edge) => {
    if (!adjacency.has(edge.source)) adjacency.set(edge.source, new Set());
    if (!adjacency.has(edge.target)) adjacency.set(edge.target, new Set());
    adjacency.get(edge.source).add(edge.target);
    adjacency.get(edge.target).add(edge.source);
  });
  return adjacency;
}

function removeIsolatedNodes(nodes, edges, state, anchorId) {
  if (!state.hideIsolated) return { nodes, edges };
  const adjacency = buildAdjacency(edges);
  const retainedIds = new Set(
    nodes
      .filter(
        (node) =>
          adjacency.has(node.id) ||
          node.id === state.selectedNodeId ||
          node.id === anchorId ||
          state.pinnedNodeIds.has(node.id),
      )
      .map((node) => node.id),
  );
  return {
    nodes: nodes.filter((node) => retainedIds.has(node.id)),
    edges: edges.filter((edge) => retainedIds.has(edge.source) && retainedIds.has(edge.target)),
  };
}

function filterToSelectedNeighborhood(nodes, edges, state, anchorId) {
  if (!state.selectedNeighborhoodOnly || !state.selectedNodeId) return { nodes, edges };
  const adjacency = buildAdjacency(edges);
  const retainedIds = new Set([
    state.selectedNodeId,
    ...(adjacency.get(state.selectedNodeId) || []),
    anchorId,
    ...state.pinnedNodeIds,
  ].filter(Boolean));
  return {
    nodes: nodes.filter((node) => retainedIds.has(node.id)),
    edges: edges.filter((edge) => retainedIds.has(edge.source) && retainedIds.has(edge.target)),
  };
}

function buildProjectedGraph(state) {
  const filteredNodes = state.rawGraph.nodes.filter((node) => passesNodeFilters(node, state));
  const queryMatches = findMatches(filteredNodes, state.searchText);
  const anchorId = state.selectedNodeId || queryMatches[0]?.id || "";
  let visibleIds;
  if (state.manualVisibleIds.size) {
    visibleIds = new Set(
      [...state.manualVisibleIds, ...state.pinnedNodeIds].filter((id) => {
        const node = state.nodesById.get(id);
        return node && passesNodeFilters(node, state);
      }),
    );
  } else {
    visibleIds = anchorId ? bfsNeighborhood(anchorId, state) : overviewNodes(state);
    state.pinnedNodeIds.forEach((id) => {
      const node = state.nodesById.get(id);
      if (node && passesNodeFilters(node, state)) visibleIds.add(id);
    });
  }

  const limitedIds =
    Number.isFinite(state.nodeLimit) && visibleIds.size > state.nodeLimit
      ? new Set(
          [...visibleIds]
            .map((id) => state.nodesById.get(id))
            .filter(Boolean)
            .sort((a, b) => (Number(b.degree) || 0) - (Number(a.degree) || 0))
            .slice(0, state.nodeLimit)
            .map((node) => node.id),
        )
      : visibleIds;

  let nodes = [...limitedIds]
    .map((id) => state.nodesById.get(id))
    .filter(Boolean)
    .sort((a, b) => String(a.label).localeCompare(String(b.label)));

  const focusIds = new Set([anchorId, state.selectedNodeId, ...state.pinnedNodeIds].filter(Boolean));
  let edges = state.rawGraph.edges.filter(
    (edge) => limitedIds.has(edge.source) && limitedIds.has(edge.target) && passesEdgeFilters(edge, state),
  );
  edges = filterEdgesByDensity(edges, state, focusIds);

  const isolatedResult = removeIsolatedNodes(nodes, edges, state, anchorId);
  nodes = isolatedResult.nodes;
  edges = isolatedResult.edges;
  const selectionResult = filterToSelectedNeighborhood(nodes, edges, state, anchorId);
  nodes = selectionResult.nodes;
  edges = selectionResult.edges;

  const adjacency = buildAdjacency(edges);

  return {
    anchorId,
    nodes,
    edges,
    adjacency,
    queryMatches,
  };
}

function averageNeighborPosition(nodeId, adjacency, positions) {
  const neighbors = [...(adjacency.get(nodeId) || [])]
    .map((id) => positions.get(id))
    .filter(Boolean);
  if (!neighbors.length) return null;
  return {
    x: neighbors.reduce((sum, point) => sum + point.x, 0) / neighbors.length,
    y: neighbors.reduce((sum, point) => sum + point.y, 0) / neighbors.length,
  };
}

function graphChromeMetrics() {
  const header = document.querySelector(".site-header .topbar");
  const siteShell = document.querySelector(".site-header .site-shell");
  const sidebar = document.querySelector(".graph-sidebar");
  const headerBottom = header instanceof HTMLElement ? header.getBoundingClientRect().bottom : 0;
  const shellRect = siteShell instanceof HTMLElement ? siteShell.getBoundingClientRect() : null;
  const sidebarRect =
    sidebar instanceof HTMLElement && !sidebar.hidden ? sidebar.getBoundingClientRect() : null;
  return {
    headerBottom,
    shellLeft: shellRect ? shellRect.left : GRAPH_PADDING,
    shellWidth: shellRect ? shellRect.width : 0,
    sidebarLeft: sidebarRect ? sidebarRect.left : window.innerWidth - GRAPH_PADDING,
    sidebarWidth: sidebarRect ? sidebarRect.width : 0,
  };
}

function syncGraphViewportVars() {
  const root = document.documentElement;
  const { headerBottom, shellLeft, shellWidth, sidebarLeft } = graphChromeMetrics();
  const shellIsFluid = shellWidth > 0 && shellWidth < 1239;
  root.style.setProperty("--graph-frame-top", `${Math.round(headerBottom + GRAPH_PADDING * 0.5)}px`);
  root.style.setProperty("--graph-frame-right", `${Math.max(GRAPH_PADDING, Math.round(window.innerWidth - sidebarLeft + GRAPH_PADDING * 0.5))}px`);
  root.style.setProperty("--graph-frame-bottom", `${GRAPH_PADDING}px`);
  root.style.setProperty(
    "--graph-frame-left",
    `${shellIsFluid ? Math.max(16, Math.round(shellLeft)) : GRAPH_PADDING}px`,
  );
}

function graphLayoutFrame(width, height) {
  const { headerBottom, sidebarWidth } = graphChromeMetrics();
  const top = clamp(headerBottom + GRAPH_PADDING * 0.8, GRAPH_PADDING, height * 0.38);
  const rightInset = Math.max(GRAPH_PADDING, sidebarWidth + GRAPH_PADDING * 1.5);
  const leftInset = GRAPH_PADDING;
  const bottom = Math.max(top + 120, height - GRAPH_PADDING);
  return {
    left: leftInset,
    right: width - rightInset,
    top,
    bottom,
    width: Math.max(120, width - leftInset - rightInset),
    height: Math.max(120, bottom - top),
    centerX: leftInset + Math.max(120, width - leftInset - rightInset) / 2,
    centerY: top + Math.max(120, bottom - top) / 2,
  };
}

function typeCenter(type, width, height, nodes) {
  const frame = graphLayoutFrame(width, height);
  const types = TYPE_ORDER.filter((entry) => nodes.some((node) => node.type === entry));
  const index = Math.max(0, types.indexOf(type));
  const orbitX = Math.max(frame.width * 0.34, 250);
  const orbitY = Math.max(frame.height * 0.28, 160);
  const angle = (Math.PI * 2 * index) / Math.max(types.length, 1) - Math.PI / 2;
  return {
    x: frame.centerX + Math.cos(angle) * orbitX,
    y: frame.centerY + Math.sin(angle) * orbitY,
  };
}

function preservePositions(targets, previous, adjacency, nodes, width, height, mix = 0.28) {
  const positions = new Map();
  const nodeSet = new Set(nodes.map((node) => node.id));
  nodes.forEach((node) => {
    const target = targets.get(node.id) || { x: width / 2, y: height / 2 };
    const prev = previous?.get(node.id);
    if (prev) {
      positions.set(node.id, {
        x: lerp(prev.x, target.x, mix),
        y: lerp(prev.y, target.y, mix),
      });
      return;
    }
    const neighborAverage = averageNeighborPosition(node.id, adjacency, previous || new Map());
    if (neighborAverage) {
      positions.set(node.id, {
        x: lerp(neighborAverage.x, target.x, 0.45),
        y: lerp(neighborAverage.y, target.y, 0.45),
      });
      return;
    }
    positions.set(node.id, target);
  });
  return new Map(
    [...positions.entries()].filter(([id]) => nodeSet.has(id)),
  );
}

function buildOrbitTargets(nodes, anchorId, width, height) {
  const positions = new Map();
  if (!nodes.length) return positions;
  const frame = graphLayoutFrame(width, height);
  const types = TYPE_ORDER.filter((type) => nodes.some((node) => node.type === type));
  const orbitX = Math.max(frame.width * 0.34, 250);
  const orbitY = Math.max(frame.height * 0.28, 160);
  const centers = new Map();
  types.forEach((type, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(types.length, 1) - Math.PI / 2;
    centers.set(type, {
      x: frame.centerX + Math.cos(angle) * orbitX,
      y: frame.centerY + Math.sin(angle) * orbitY,
    });
  });

  if (anchorId && nodes.some((node) => node.id === anchorId)) {
    positions.set(anchorId, { x: frame.centerX, y: frame.centerY });
  }

  types.forEach((type) => {
    const group = nodes
      .filter((node) => node.type === type && node.id !== anchorId)
      .sort((a, b) => (Number(b.degree) || 0) - (Number(a.degree) || 0));
    const center = centers.get(type) || { x: width / 2, y: height / 2 };
    let ring = 0;
    let indexInRing = 0;
    let ringCapacity = 1;
    group.forEach((node) => {
      if (indexInRing >= ringCapacity) {
        ring += 1;
        indexInRing = 0;
      }
      const radius = 42 + ring * 28 + (anchorId ? 26 : 0);
      ringCapacity = Math.max(8, Math.floor((Math.PI * 2 * radius) / 28));
      const angle = (Math.PI * 2 * indexInRing) / ringCapacity + ring * 0.17;
      positions.set(node.id, {
        x: center.x + Math.cos(angle) * radius,
        y: center.y + Math.sin(angle) * radius,
      });
      indexInRing += 1;
    });
  });
  return positions;
}

function computeDistances(anchorId, adjacency) {
  const distances = new Map();
  if (!anchorId) return distances;
  const queue = [anchorId];
  distances.set(anchorId, 0);
  while (queue.length) {
    const current = queue.shift();
    const depth = distances.get(current) || 0;
    for (const neighbor of adjacency.get(current) || []) {
      if (distances.has(neighbor)) continue;
      distances.set(neighbor, depth + 1);
      queue.push(neighbor);
    }
  }
  return distances;
}

function buildRadialTargets(nodes, adjacency, anchorId, width, height) {
  if (!anchorId || !nodes.some((node) => node.id === anchorId)) {
    return buildOrbitTargets(nodes, anchorId, width, height);
  }
  const frame = graphLayoutFrame(width, height);
  const positions = new Map([[anchorId, { x: frame.centerX, y: frame.centerY }]]);
  const distances = computeDistances(anchorId, adjacency);
  const grouped = new Map();
  nodes.forEach((node) => {
    if (node.id === anchorId) return;
    const depth = distances.get(node.id) ?? 99;
    if (!grouped.has(depth)) grouped.set(depth, []);
    grouped.get(depth).push(node);
  });
  [...grouped.entries()]
    .sort((a, b) => a[0] - b[0])
    .forEach(([depth, group], depthIndex) => {
      const ringRadius = 92 + depthIndex * 86;
      const sorted = group.sort((a, b) => {
        const typeIndex = TYPE_ORDER.indexOf(a.type) - TYPE_ORDER.indexOf(b.type);
        if (typeIndex) return typeIndex;
        return String(a.label).localeCompare(String(b.label));
      });
      sorted.forEach((node, index) => {
        const angle = (Math.PI * 2 * index) / Math.max(sorted.length, 1) - Math.PI / 2;
        positions.set(node.id, {
          x: frame.centerX + Math.cos(angle) * ringRadius,
          y: frame.centerY + Math.sin(angle) * ringRadius,
        });
      });
    });
  return positions;
}

function buildHierarchicalTargets(nodes, anchorId, width, height) {
  const positions = new Map();
  const frame = graphLayoutFrame(width, height);
  const types = TYPE_ORDER.filter((type) => nodes.some((node) => node.type === type));
  const columnWidth = frame.width / Math.max(types.length, 1);
  types.forEach((type, typeIndex) => {
    const columnNodes = nodes
      .filter((node) => node.type === type)
      .sort((a, b) => (a.id === anchorId ? -1 : b.id === anchorId ? 1 : String(a.label).localeCompare(String(b.label))));
    columnNodes.forEach((node, rowIndex) => {
      positions.set(node.id, {
        x: frame.left + columnWidth * typeIndex + columnWidth / 2,
        y: frame.top + (frame.height / (columnNodes.length + 1)) * (rowIndex + 1),
      });
    });
  });
  return positions;
}

function initializeForceSeeds(nodes, targets, adjacency, previous, width, height) {
  const positions = new Map();
  nodes.forEach((node) => {
    const prev = previous?.get(node.id);
    if (prev) {
      positions.set(node.id, { x: prev.x, y: prev.y });
      return;
    }
    const neighborAverage = averageNeighborPosition(node.id, adjacency, positions) || averageNeighborPosition(node.id, adjacency, previous || new Map());
    const fallback = targets.get(node.id) || typeCenter(node.type, width, height, nodes);
    const seed = neighborAverage
      ? {
          x: lerp(neighborAverage.x, fallback.x, 0.42),
          y: lerp(neighborAverage.y, fallback.y, 0.42),
        }
      : fallback;
    positions.set(node.id, seed);
  });
  return positions;
}

function buildForceLiteTargets(nodes, adjacency, anchorId, width, height, previous) {
  const targets = buildRadialTargets(nodes, adjacency, anchorId, width, height);
  const positions = initializeForceSeeds(nodes, targets, adjacency, previous, width, height);
  const velocities = new Map(nodes.map((node) => [node.id, { x: 0, y: 0 }]));

  for (let step = 0; step < 42; step += 1) {
    nodes.forEach((node) => {
      const point = positions.get(node.id);
      const velocity = velocities.get(node.id);
      let forceX = 0;
      let forceY = 0;

      nodes.forEach((other) => {
        if (other.id === node.id) return;
        const otherPoint = positions.get(other.id);
        const dx = point.x - otherPoint.x;
        const dy = point.y - otherPoint.y;
        const distanceSq = Math.max(36, dx * dx + dy * dy);
        const repulsion = 2800 / distanceSq;
        forceX += (dx / Math.sqrt(distanceSq)) * repulsion;
        forceY += (dy / Math.sqrt(distanceSq)) * repulsion;
      });

      (adjacency.get(node.id) || new Set()).forEach((neighborId) => {
        const otherPoint = positions.get(neighborId);
        if (!otherPoint) return;
        forceX += (otherPoint.x - point.x) * 0.016;
        forceY += (otherPoint.y - point.y) * 0.016;
      });

      const target = targets.get(node.id) || { x: width / 2, y: height / 2 };
      forceX += (target.x - point.x) * 0.022;
      forceY += (target.y - point.y) * 0.022;

      velocity.x = (velocity.x + forceX) * 0.72;
      velocity.y = (velocity.y + forceY) * 0.72;
      point.x = clamp(point.x + velocity.x, GRAPH_PADDING, width - GRAPH_PADDING);
      point.y = clamp(point.y + velocity.y, GRAPH_PADDING, height - GRAPH_PADDING);
    });
  }

  return positions;
}

function resolveLayout(projected, state, width, height) {
  const previous = state.layoutCache.get(state.layoutMode) || new Map();
  let positions;
  if (state.layoutMode === "radial") {
    const targets = buildRadialTargets(projected.nodes, projected.adjacency, projected.anchorId, width, height);
    positions = preservePositions(targets, previous, projected.adjacency, projected.nodes, width, height, 0.24);
  } else if (state.layoutMode === "hierarchical") {
    const targets = buildHierarchicalTargets(projected.nodes, projected.anchorId, width, height);
    positions = preservePositions(targets, previous, projected.adjacency, projected.nodes, width, height, 0.3);
  } else if (state.layoutMode === "force-lite") {
    positions = buildForceLiteTargets(projected.nodes, projected.adjacency, projected.anchorId, width, height, previous);
  } else {
    const targets = buildOrbitTargets(projected.nodes, projected.anchorId, width, height);
    positions = preservePositions(targets, previous, projected.adjacency, projected.nodes, width, height, 0.22);
  }
  state.layoutCache.set(state.layoutMode, new Map(positions));
  return positions;
}

function buildLayout(projected, state, width, height) {
  return resolveLayout(projected, state, width, height);
}

function homePanOffsetX() {
  return 0;
}

function resetViewport(state) {
  state.panX = homePanOffsetX();
  state.panY = 0;
  state.zoom = 1;
}

function baseNodeRadius(node) {
  const base = node.type === "Ruleset" ? 7 : node.type === "Species" ? 6 : 4.5;
  return Math.min(13, base + Math.log2((Number(node.degree) || 0) + 1) * 0.85);
}

function nodeRadius(node, state) {
  if (state.sizeMode === "uniform") return 6;
  if (state.sizeMode === "contexts") {
    return Math.min(13, 4.6 + Math.log2((node.contexts?.length || 0) + 1) * 1.3);
  }
  return baseNodeRadius(node);
}

function nodeColor(node, state) {
  if (state.colorMode === "contexts") {
    const maxContexts = Math.max(1, ...state.lastProjected.nodes.map((entry) => entry.contexts?.length || 0));
    const ratio = (node.contexts?.length || 0) / maxContexts;
    return gradientColor(CONTEXT_COLOR_STOPS, ratio);
  }
  return TYPE_COLORS[node.type] || "#54795c";
}

function fitNodeIds(state, nodeIds) {
  if (!state.lastLayout || !state.lastRect || !nodeIds.size) return;
  const points = [...nodeIds]
    .map((id) => {
      const point = state.lastLayout.get(id);
      const node = state.nodesById.get(id);
      if (!point || !node) return null;
      const radius = nodeRadius(node, state) + GRAPH_PADDING;
      return {
        left: point.x - radius,
        right: point.x + radius,
        top: point.y - radius,
        bottom: point.y + radius,
      };
    })
    .filter(Boolean);
  if (!points.length) return;
  const bounds = points.reduce(
    (acc, point) => ({
      left: Math.min(acc.left, point.left),
      right: Math.max(acc.right, point.right),
      top: Math.min(acc.top, point.top),
      bottom: Math.max(acc.bottom, point.bottom),
    }),
    { left: Infinity, right: -Infinity, top: Infinity, bottom: -Infinity },
  );
  const width = Math.max(1, bounds.right - bounds.left);
  const height = Math.max(1, bounds.bottom - bounds.top);
  const availableWidth = Math.max(80, state.lastRect.width - GRAPH_PADDING * 2);
  const availableHeight = Math.max(80, state.lastRect.height - GRAPH_PADDING * 2);
  state.zoom = clampZoom(Math.min(availableWidth / width, availableHeight / height, 1.6));
  const centerX = (bounds.left + bounds.right) / 2;
  const centerY = (bounds.top + bounds.bottom) / 2;
  state.panX = -((centerX - state.lastRect.width / 2) * state.zoom);
  state.panY = -((centerY - state.lastRect.height / 2) * state.zoom);
}

function setControlsCollapsed(state, collapsed) {
  state.controlsCollapsed = collapsed;
  const controls = document.getElementById("graph-controls");
  const toggle = document.getElementById("graph-controls-toggle");
  const reopen = document.getElementById("graph-controls-reopen");
  controls?.classList.toggle("is-collapsed", collapsed);
  if (controls) controls.hidden = false;
  if (toggle) {
    toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    toggle.textContent = "Collapse";
  }
  if (reopen) reopen.hidden = true;
}

function autoCollapseControls(state) {
  if (!state.controlsCollapsed) setControlsCollapsed(state, true);
}

function serializeState(state) {
  const payload = {
    v: URL_STATE_VERSION,
    q: state.searchText.trim() || "",
    sel: state.selectedNodeId || "",
    ruleset: state.selectedRuleset || "",
    depth: String(state.hopDepth),
    limit: Number.isFinite(state.nodeLimit) ? String(state.nodeLimit) : "MAX",
    types: encodeSet(state.enabledTypes),
    edges: encodeSet(state.enabledEdgeKinds),
    visible: encodeSet(state.manualVisibleIds),
    hidden: encodeSet(state.hiddenNodeIds),
    pinned: encodeSet(state.pinnedNodeIds),
    perspective: state.activePerspective || "",
    layout: state.layoutMode,
    size: state.sizeMode,
    color: state.colorMode,
    density: state.edgeDensityMode,
    isolates: state.hideIsolated ? "1" : "",
    neighborhood: state.selectedNeighborhoodOnly ? "1" : "",
  };
  return JSON.stringify(payload);
}

function snapshotState(state) {
  return JSON.parse(serializeState(state));
}

function replaceCheckboxSet(prefix, allValues, selectedValues) {
  allValues.forEach((value) => {
    const input = document.getElementById(`${prefix}${slugify(value)}`);
    if (input instanceof HTMLInputElement) input.checked = selectedValues.has(value);
  });
}

function decodeUrlState() {
  const params = new URLSearchParams(window.location.search);
  return {
    searchText: params.get("q") || DEFAULT_SEARCH,
    selectedNodeId: params.get("sel") || "",
    selectedRuleset: params.get("ruleset") || "",
    hopDepth: Math.max(1, Math.min(4, Number.parseInt(params.get("depth") || "2", 10) || 2)),
    nodeLimit: parseNodeLimitValue(params.get("limit") || DEFAULT_NODE_LIMIT),
    enabledTypes: parseListParam(params.get("types")),
    enabledEdgeKinds: parseListParam(params.get("edges")),
    manualVisibleIds: parseListParam(params.get("visible")),
    hiddenNodeIds: parseListParam(params.get("hidden")),
    pinnedNodeIds: parseListParam(params.get("pinned")),
    activePerspective: params.get("perspective") || "",
    layoutMode: parseChoice(params.get("layout") || DEFAULT_LAYOUT_MODE, LAYOUT_OPTIONS, DEFAULT_LAYOUT_MODE),
    sizeMode: parseChoice(params.get("size") || DEFAULT_SIZE_MODE, SIZE_OPTIONS, DEFAULT_SIZE_MODE),
    colorMode: parseChoice(params.get("color") || DEFAULT_COLOR_MODE, COLOR_OPTIONS, DEFAULT_COLOR_MODE),
    edgeDensityMode: parseChoice(
      params.get("density") || DEFAULT_EDGE_DENSITY,
      DENSITY_OPTIONS,
      DEFAULT_EDGE_DENSITY,
    ),
    hideIsolated: parseBooleanParam(params.get("isolates") || ""),
    selectedNeighborhoodOnly: parseBooleanParam(params.get("neighborhood") || ""),
  };
}

function writeUrlState(state) {
  const params = new URLSearchParams();
  params.set("q", state.searchText.trim() || DEFAULT_SEARCH);
  if (state.selectedNodeId) params.set("sel", state.selectedNodeId);
  if (state.selectedRuleset) params.set("ruleset", state.selectedRuleset);
  params.set("depth", String(state.hopDepth));
  params.set("limit", Number.isFinite(state.nodeLimit) ? String(state.nodeLimit) : "MAX");
  if (state.enabledTypes.size !== TYPE_ORDER.length) params.set("types", encodeSet(state.enabledTypes));
  if (state.enabledEdgeKinds.size !== EDGE_KINDS.length) params.set("edges", encodeSet(state.enabledEdgeKinds));
  if (state.manualVisibleIds.size) params.set("visible", encodeSet(state.manualVisibleIds));
  if (state.hiddenNodeIds.size) params.set("hidden", encodeSet(state.hiddenNodeIds));
  if (state.pinnedNodeIds.size) params.set("pinned", encodeSet(state.pinnedNodeIds));
  if (state.activePerspective) params.set("perspective", state.activePerspective);
  if (state.layoutMode !== DEFAULT_LAYOUT_MODE) params.set("layout", state.layoutMode);
  if (state.sizeMode !== DEFAULT_SIZE_MODE) params.set("size", state.sizeMode);
  if (state.colorMode !== DEFAULT_COLOR_MODE) params.set("color", state.colorMode);
  if (state.edgeDensityMode !== DEFAULT_EDGE_DENSITY) params.set("density", state.edgeDensityMode);
  if (state.hideIsolated) params.set("isolates", "1");
  if (state.selectedNeighborhoodOnly) params.set("neighborhood", "1");
  const next = params.toString();
  const url = next ? `${window.location.pathname}?${next}` : window.location.pathname;
  window.history.replaceState(null, "", url);
}

function pushHistoryState(state) {
  const snapshot = snapshotState(state);
  const serialized = JSON.stringify(snapshot);
  const current = state.history[state.historyIndex];
  if (current && JSON.stringify(current) === serialized) return;
  state.history = state.history.slice(0, state.historyIndex + 1);
  state.history.push(snapshot);
  state.historyIndex = state.history.length - 1;
}

function applySnapshotToUi(state, snapshot) {
  state.searchText = snapshot.q || DEFAULT_SEARCH;
  state.selectedNodeId = snapshot.sel || "";
  state.selectedRuleset = snapshot.ruleset || "";
  state.hopDepth = Math.max(1, Math.min(4, Number.parseInt(snapshot.depth || "2", 10) || 2));
  state.nodeLimit = parseNodeLimitValue(snapshot.limit || DEFAULT_NODE_LIMIT);
  if (Number.isFinite(state.nodeLimit)) state.lastFiniteNodeLimit = state.nodeLimit;
  state.manualVisibleIds = parseListParam(snapshot.visible);
  state.hiddenNodeIds = parseListParam(snapshot.hidden);
  state.pinnedNodeIds = parseListParam(snapshot.pinned);
  state.activePerspective = snapshot.perspective || "";
  state.layoutMode = parseChoice(snapshot.layout || DEFAULT_LAYOUT_MODE, LAYOUT_OPTIONS, DEFAULT_LAYOUT_MODE);
  state.sizeMode = parseChoice(snapshot.size || DEFAULT_SIZE_MODE, SIZE_OPTIONS, DEFAULT_SIZE_MODE);
  state.colorMode = parseChoice(snapshot.color || DEFAULT_COLOR_MODE, COLOR_OPTIONS, DEFAULT_COLOR_MODE);
  state.edgeDensityMode = parseChoice(snapshot.density || DEFAULT_EDGE_DENSITY, DENSITY_OPTIONS, DEFAULT_EDGE_DENSITY);
  state.hideIsolated = parseBooleanParam(snapshot.isolates || "");
  state.selectedNeighborhoodOnly = parseBooleanParam(snapshot.neighborhood || "");
  state.layoutCache = new Map();
  syncUiFromState(state);
  replaceCheckboxSet("graph-type-", TYPE_ORDER, parseListParam(snapshot.types || encodeSet(new Set(TYPE_ORDER))));
  replaceCheckboxSet(
    "graph-edge-",
    EDGE_KINDS.map((kind) => kind.id),
    parseListParam(snapshot.edges || encodeSet(new Set(EDGE_KINDS.map((kind) => kind.id)))),
  );
}

function syncPerspectiveButtons(state) {
  document.querySelectorAll("[data-graph-perspective]").forEach((button) => {
    const active = button.getAttribute("data-graph-perspective") === state.activePerspective;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function syncHistoryControls(state) {
  const back = document.getElementById("graph-history-back");
  const forward = document.getElementById("graph-history-forward");
  const badge = document.getElementById("graph-history-badge");
  if (back instanceof HTMLButtonElement) back.disabled = state.historyIndex <= 0;
  if (forward instanceof HTMLButtonElement) forward.disabled = state.historyIndex >= state.history.length - 1;
  if (badge) {
    badge.textContent = `History ${Math.max(1, state.historyIndex + 1)} / ${Math.max(1, state.history.length)}`;
  }
}

function renderStats(projected) {
  const nodeCount = document.querySelector("[data-graph-node-count]");
  const edgeCount = document.querySelector("[data-graph-edge-count]");
  if (nodeCount) nodeCount.textContent = String(projected.nodes.length);
  if (edgeCount) edgeCount.textContent = String(projected.edges.length);
}

function renderFocus(projected, state) {
  const focusBadge = document.getElementById("graph-focus-badge");
  const hoverReadout = document.getElementById("graph-hover-readout");
  if (focusBadge) {
    const anchor = projected.nodes.find((node) => node.id === projected.anchorId);
    const layoutLabel = state.layoutMode === "force-lite" ? "Force" : state.layoutMode[0].toUpperCase() + state.layoutMode.slice(1);
    if (state.manualVisibleIds.size) {
      focusBadge.textContent = anchor
        ? `${anchor.label} · ${layoutLabel} scene`
        : `Custom scene · ${layoutLabel}`;
    } else {
      focusBadge.textContent = anchor ? `${anchor.label} · ${layoutLabel} query` : `Top-degree overview · ${layoutLabel}`;
    }
  }
  if (hoverReadout && !hoverReadout.dataset.locked) {
    hoverReadout.textContent = projected.anchorId ? "Click nodes to repivot the local graph" : "Search or click a node to query locally";
  }
}

function renderQueryStatus(projected, state) {
  const target = document.getElementById("graph-query-status");
  if (!target) return;
  const query = state.searchText.trim();
  const isolateLabel = state.hideIsolated ? " Hidden isolates enabled." : "";
  const neighborhoodLabel =
    state.selectedNeighborhoodOnly && state.selectedNodeId
      ? " Selected-neighborhood mode active."
      : state.selectedNeighborhoodOnly
        ? " Selection-only mode is waiting for a node."
        : "";
  if (state.manualVisibleIds.size) {
    target.textContent = `Custom scene with ${projected.nodes.length} visible nodes. ${state.edgeDensityMode} edge density active.${isolateLabel}${neighborhoodLabel}`;
    return;
  }
  if (!query) {
    target.textContent = Number.isFinite(state.nodeLimit)
      ? `No query text. Showing top-degree overview limited to ${state.nodeLimit} nodes.${isolateLabel}${neighborhoodLabel}`
      : `No query text. Showing the full top-degree overview.${isolateLabel}${neighborhoodLabel}`;
    return;
  }
  const topMatch = projected.queryMatches[0];
  if (!topMatch) {
    target.textContent = `No visible match for "${query}" under the current filters.`;
    return;
  }
  const exact = normalize(topMatch.label) === normalize(query) || normalize(topMatch.id) === normalize(query);
  target.textContent = exact
    ? `Exact match: ${topMatch.label}. Rendering a ${state.hopDepth}-hop neighborhood with ${state.layoutMode} layout.${isolateLabel}${neighborhoodLabel}`
    : `${projected.queryMatches.length} matches for "${query}". Focused on ${topMatch.label}.${isolateLabel}${neighborhoodLabel}`;
}

function syncNodeLimitControls(state) {
  const input = document.getElementById("graph-node-limit");
  const maxButton = document.getElementById("graph-node-limit-max");
  if (input instanceof HTMLInputElement) input.value = Number.isFinite(state.nodeLimit) ? String(state.nodeLimit) : "MAX";
  if (maxButton instanceof HTMLButtonElement) maxButton.hidden = !state.nodeLimitEditing;
}

function parseNodeLimitValue(value) {
  const normalized = String(value || "").trim().toUpperCase();
  if (normalized === "MAX") return Infinity;
  const next = Number.parseInt(normalized, 10);
  return Number.isFinite(next) && next > 0 ? next : DEFAULT_NODE_LIMIT;
}

function activateNodeLimitEditor(state) {
  state.nodeLimitEditing = true;
  syncNodeLimitControls(state);
}

function commitNodeLimitValue(state, value) {
  state.nodeLimit = parseNodeLimitValue(value);
  if (Number.isFinite(state.nodeLimit)) state.lastFiniteNodeLimit = state.nodeLimit;
  state.nodeLimitEditing = false;
  state.nodeLimitMaxPending = false;
  syncNodeLimitControls(state);
}

function edgeKindBreakdown(nodeId, projected) {
  const counts = new Map();
  projected.edges.forEach((edge) => {
    if (edge.source !== nodeId && edge.target !== nodeId) return;
    counts.set(edge.kind, (counts.get(edge.kind) || 0) + 1);
  });
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}

function incidentEdges(nodeId, projected) {
  return projected.edges.filter((edge) => edge.source === nodeId || edge.target === nodeId);
}

function summarizeNodeContexts(node, state) {
  const contexts = Array.isArray(node.contexts) ? node.contexts : [];
  return contexts
    .map((id) => state.nodesById.get(id))
    .filter(Boolean)
    .sort((a, b) => String(a.label).localeCompare(String(b.label)))
    .slice(0, 10);
}

function neighborGroupsByType(nodeId, projected) {
  const groups = new Map();
  [...(projected.adjacency.get(nodeId) || new Set())]
    .map((id) => projected.nodes.find((entry) => entry.id === id))
    .filter(Boolean)
    .sort((a, b) => (Number(b.degree) || 0) - (Number(a.degree) || 0))
    .forEach((neighbor) => {
      if (!groups.has(neighbor.type)) groups.set(neighbor.type, []);
      groups.get(neighbor.type).push(neighbor);
    });
  return TYPE_ORDER.filter((type) => groups.has(type)).map((type) => ({
    type,
    neighbors: groups.get(type),
  }));
}

function degreeBucketLabel(value) {
  const degree = Number(value) || 0;
  if (degree <= 1) return "0-1";
  if (degree <= 4) return "2-4";
  if (degree <= 9) return "5-9";
  return "10+";
}

function degreeBucketSortKey(label) {
  return ["0-1", "2-4", "5-9", "10+"].indexOf(label);
}

function collectFacetCounts(projected) {
  const typeCounts = new Map();
  projected.nodes.forEach((node) => typeCounts.set(node.type, (typeCounts.get(node.type) || 0) + 1));

  const edgeCounts = new Map();
  projected.edges.forEach((edge) => edgeCounts.set(edge.kind, (edgeCounts.get(edge.kind) || 0) + 1));

  const rulesetCounts = new Map();
  projected.nodes.forEach((node) => {
    if (node.type === "Ruleset") rulesetCounts.set(node.id, (rulesetCounts.get(node.id) || 0) + 1);
    (node.contexts || []).forEach((contextId) => {
      rulesetCounts.set(contextId, (rulesetCounts.get(contextId) || 0) + 1);
    });
  });

  const degreeCounts = new Map();
  projected.nodes.forEach((node) => {
    const bucket = degreeBucketLabel(node.degree);
    degreeCounts.set(bucket, (degreeCounts.get(bucket) || 0) + 1);
  });

  return {
    typeCounts,
    edgeCounts,
    rulesetCounts,
    degreeCounts,
  };
}

function renderFacetButtons(entries, kind, state, options = {}) {
  const limit = options.limit || 6;
  const emptyLabel = options.emptyLabel || "None";
  const activeSet = options.activeSet || null;
  const selectedValue = options.selectedValue || "";
  const getLabel = options.getLabel || ((entry) => entry.label);
  const items = entries.slice(0, limit);
  if (!items.length) return `<span class="graph-facet-empty">${escapeHtml(emptyLabel)}</span>`;
  return items
    .map((entry) => {
      const active =
        kind === "ruleset"
          ? selectedValue === entry.id
          : activeSet instanceof Set && activeSet.has(entry.id);
      return `<button class="graph-facet-chip ${active ? "is-active" : ""}" type="button" data-graph-facet="${escapeHtml(kind)}" data-graph-facet-value="${escapeHtml(entry.id)}"><span>${escapeHtml(getLabel(entry))}</span><strong>${escapeHtml(entry.count)}</strong></button>`;
    })
    .join("");
}

function renderFacets(projected, state) {
  const target = document.getElementById("graph-facets");
  if (!target) return;
  const counts = collectFacetCounts(projected);
  const typeEntries = TYPE_ORDER.map((type) => ({ id: type, label: type, count: counts.typeCounts.get(type) || 0 }))
    .filter((entry) => entry.count > 0);
  const edgeEntries = EDGE_KINDS.map((kind) => ({ id: kind.id, label: kind.label, count: counts.edgeCounts.get(kind.id) || 0 }))
    .filter((entry) => entry.count > 0)
    .sort((a, b) => b.count - a.count);
  const rulesetEntries = [...counts.rulesetCounts.entries()]
    .map(([id, count]) => ({ id, count, label: state.nodesById.get(id)?.label || id }))
    .sort((a, b) => b.count - a.count || String(a.label).localeCompare(String(b.label)))
    .slice(0, 6);
  const degreeEntries = [...counts.degreeCounts.entries()]
    .map(([label, count]) => ({ id: label, label, count }))
    .sort((a, b) => degreeBucketSortKey(a.label) - degreeBucketSortKey(b.label));

  target.innerHTML = `
    <section class="graph-facet-group">
      <span class="graph-facet-label">Types</span>
      <div class="graph-facet-row">
        ${renderFacetButtons(typeEntries, "type", state, { activeSet: state.enabledTypes, emptyLabel: "No visible types" })}
      </div>
    </section>
    <section class="graph-facet-group">
      <span class="graph-facet-label">Edges</span>
      <div class="graph-facet-row">
        ${renderFacetButtons(edgeEntries, "edge", state, { activeSet: state.enabledEdgeKinds, emptyLabel: "No visible edges" })}
      </div>
    </section>
    <section class="graph-facet-group">
      <span class="graph-facet-label">Rulesets</span>
      <div class="graph-facet-row">
        ${renderFacetButtons(rulesetEntries, "ruleset", state, { selectedValue: state.selectedRuleset, emptyLabel: "No visible rulesets" })}
      </div>
    </section>
    <section class="graph-facet-group">
      <span class="graph-facet-label">Degree</span>
      <div class="graph-facet-row graph-facet-row-static">
        ${degreeEntries.length
          ? degreeEntries.map((entry) => `<span class="graph-facet-chip graph-facet-chip-static"><span>${escapeHtml(entry.label)}</span><strong>${escapeHtml(entry.count)}</strong></span>`).join("")
          : `<span class="graph-facet-empty">No visible nodes</span>`}
      </div>
    </section>
  `;
}

function renderDetail(projected, state) {
  const target = document.getElementById("graph-detail");
  const badge = document.getElementById("graph-selection-badge");
  if (!target || !badge) return;
  const node = projected.nodes.find((entry) => entry.id === state.selectedNodeId);
  if (!node) {
    const matches = projected.queryMatches.slice(0, 18);
    if (state.searchText.trim()) {
      badge.textContent = `${matches.length} matches`;
      target.innerHTML = matches.length
        ? `
          <section class="graph-inspector-section">
            <p class="panel-kicker">Matches</p>
            <div class="graph-results">
              ${matches
                .map(
                  (entry) => `
                    <button class="graph-result-card" type="button" data-graph-node="${escapeHtml(entry.id)}">
                      <strong>${escapeHtml(entry.label)}</strong>
                      <span>${escapeHtml(entry.type)} · degree ${escapeHtml(entry.degree)}</span>
                    </button>
                  `,
                )
                .join("")}
            </div>
          </section>
        `
        : `
          <div class="qe-placeholder">
            <span class="qe-placeholder-icon">∅</span>
            <p>No visible nodes matched "${escapeHtml(state.searchText)}".</p>
          </div>
        `;
      return;
    }
    badge.textContent = "No selection";
    target.innerHTML = `
      <div class="qe-placeholder">
        <span class="qe-placeholder-icon">◎</span>
        <p>Select a node or search to inspect its local graph.</p>
      </div>
    `;
    return;
  }
  const neighbors = [...(projected.adjacency.get(node.id) || new Set())]
    .map((id) => projected.nodes.find((entry) => entry.id === id))
    .filter(Boolean)
    .sort((a, b) => (Number(b.degree) || 0) - (Number(a.degree) || 0))
    .slice(0, 18);
  const breakdown = edgeKindBreakdown(node.id, projected);
  const incident = incidentEdges(node.id, projected);
  const groupedNeighbors = neighborGroupsByType(node.id, projected);
  const contexts = summarizeNodeContexts(node, state);
  const pinned = state.pinnedNodeIds.has(node.id);
  const neighborhoodOnly = state.selectedNeighborhoodOnly && state.selectedNodeId === node.id;
  badge.textContent = node.type;
  target.innerHTML = `
    <article class="graph-detail-card">
      <div class="graph-detail-head">
        <div>
          <h3>${escapeHtml(node.label)}</h3>
          <p class="pokedex-summary">${escapeHtml(node.id)}</p>
        </div>
        <span class="graph-type-pill graph-type-${slugify(node.type)}">${escapeHtml(node.type)}</span>
      </div>
      <div class="graph-action-grid">
        <button class="qe-action-btn" type="button" data-graph-action="focus">Focus</button>
        <button class="qe-action-btn" type="button" data-graph-action="expand-1">Expand 1 hop</button>
        <button class="qe-action-btn" type="button" data-graph-action="expand-2">Expand 2 hops</button>
        <button class="qe-action-btn" type="button" data-graph-action="hide">Hide</button>
        <button class="qe-action-btn ${pinned ? "is-active" : ""}" type="button" data-graph-action="pin">${pinned ? "Unpin" : "Pin"}</button>
        <button class="qe-action-btn ${neighborhoodOnly ? "is-active" : ""}" type="button" data-graph-action="toggle-neighborhood">${neighborhoodOnly ? "Show full scene" : "Show neighborhood"}</button>
      </div>
      <div class="graph-detail-grid">
        <div class="graph-detail-metric">
          <span>Degree</span>
          <strong>${escapeHtml(node.degree)}</strong>
        </div>
        <div class="graph-detail-metric">
          <span>Contexts</span>
          <strong>${escapeHtml(node.contexts.length)}</strong>
        </div>
        <div class="graph-detail-metric">
          <span>Layout</span>
          <strong>${escapeHtml(state.layoutMode)}</strong>
        </div>
        <div class="graph-detail-metric">
          <span>Color Mode</span>
          <strong>${escapeHtml(state.colorMode)}</strong>
        </div>
      </div>
      <section class="pokedex-section">
        <p class="panel-kicker">Node Summary</p>
        <div class="graph-summary-stack">
          <p class="pokedex-summary">Visible in ${escapeHtml(incident.length)} incident edges and ${escapeHtml(groupedNeighbors.length)} neighbor groups under the current scene.</p>
          ${
            contexts.length
              ? `<div class="graph-context-badges">${contexts
                  .map((entry) => `<button class="info-chip graph-context-chip ${state.selectedRuleset === entry.id ? "is-active" : ""}" type="button" data-graph-facet="ruleset" data-graph-facet-value="${escapeHtml(entry.id)}">${escapeHtml(entry.label)}</button>`)
                  .join("")}</div>`
              : `<p class="pokedex-summary">No visible ruleset contexts on this node.</p>`
          }
        </div>
      </section>
      ${
        breakdown.length
          ? `<section class="pokedex-section"><p class="panel-kicker">Top Predicates</p><div class="graph-breakdown-list">${breakdown
              .map(([kind, count]) => `<div class="graph-breakdown-row"><span>${escapeHtml(kind)}</span><strong>${escapeHtml(count)}</strong></div>`)
              .join("")}</div></section>`
          : ""
      }
      ${
        node.identifiers.length
          ? `<section class="pokedex-section"><p class="panel-kicker">Identifiers</p><div class="pokedex-chip-row">${node.identifiers
              .slice(0, 6)
              .map((value) => `<span class="info-chip">${escapeHtml(value)}</span>`)
              .join("")}</div></section>`
          : ""
      }
      <section class="pokedex-section">
        <p class="panel-kicker">Neighbors By Type</p>
        <div class="graph-neighbor-groups">
          ${
            groupedNeighbors.length
              ? groupedNeighbors
                  .map(
                    (group) => `
                      <section class="graph-neighbor-group">
                        <div class="graph-neighbor-group-head">
                          <span class="graph-type-pill graph-type-${slugify(group.type)}">${escapeHtml(group.type)}</span>
                          <strong>${escapeHtml(group.neighbors.length)}</strong>
                        </div>
                        <div class="graph-neighbor-list graph-results">
                          ${group.neighbors
                            .slice(0, 4)
                            .map(
                              (entry) => `
                                <button class="graph-neighbor-card" type="button" data-graph-node="${escapeHtml(entry.id)}">
                                  <strong>${escapeHtml(entry.label)}</strong>
                                  <span>${escapeHtml(entry.type)} · degree ${escapeHtml(entry.degree)}</span>
                                </button>
                              `,
                            )
                            .join("")}
                        </div>
                      </section>
                    `,
                  )
                  .join("")
              : `<p class="pokedex-summary">No visible neighbors under the current query.</p>`
          }
        </div>
      </section>
      <section class="pokedex-section">
        <p class="panel-kicker">Immediate Pivots</p>
        <div class="graph-neighbor-list graph-results">
          ${
            neighbors.length
              ? neighbors
                  .slice(0, 8)
                  .map(
                    (entry) => `
                      <button class="graph-neighbor-card" type="button" data-graph-node="${escapeHtml(entry.id)}">
                        <strong>${escapeHtml(entry.label)}</strong>
                        <span>${escapeHtml(entry.type)} · degree ${escapeHtml(entry.degree)}</span>
                      </button>
                    `,
                  )
                  .join("")
              : `<p class="pokedex-summary">No visible pivot candidates under the current query.</p>`
          }
        </div>
      </section>
    </article>
  `;
}

function renderFilterControls(rawGraph) {
  const nodeTarget = document.getElementById("graph-node-filters");
  const edgeTarget = document.getElementById("graph-edge-filters");
  const rulesetSelect = document.getElementById("graph-ruleset");

  if (nodeTarget) {
    nodeTarget.innerHTML = TYPE_ORDER.filter((type) => rawGraph.nodes.some((node) => node.type === type))
      .map(
        (type) => `
          <label class="source-toggle graph-toggle">
            <input type="checkbox" id="graph-type-${slugify(type)}" checked>
            <span>${escapeHtml(type)}</span>
          </label>
        `,
      )
      .join("");
  }
  if (edgeTarget) {
    edgeTarget.innerHTML = EDGE_KINDS.map(
      (kind) => `
        <label class="source-toggle graph-toggle">
          <input type="checkbox" id="graph-edge-${slugify(kind.id)}" ${kind.checked ? "checked" : ""}>
          <span>${escapeHtml(kind.label)}</span>
        </label>
      `,
    ).join("");
  }
  if (rulesetSelect) {
    const rulesets = rawGraph.nodes
      .filter((node) => node.type === "Ruleset")
      .sort((a, b) => String(a.label).localeCompare(String(b.label)));
    rulesetSelect.innerHTML = [
      `<option value="">All rulesets</option>`,
      ...rulesets.map((node) => `<option value="${escapeHtml(node.id)}">${escapeHtml(node.label)}</option>`),
    ].join("");
  }
}

function clearSceneState(state) {
  state.manualVisibleIds = new Set();
  state.hiddenNodeIds = new Set();
  state.pinnedNodeIds = new Set();
}

function setNodeSelection(state, nodeId) {
  state.selectedNodeId = nodeId || "";
}

function resetLayoutCache(state) {
  state.layoutCache = new Map();
}

function applyQueryValue(state, value) {
  state.searchText = value;
  const searchInput = document.getElementById("graph-search");
  if (searchInput instanceof HTMLInputElement) searchInput.value = value;
  const match = findMatches(
    state.rawGraph.nodes.filter((node) => passesNodeFilters(node, state)),
    state.searchText,
  )[0];
  clearSceneState(state);
  state.activePerspective = "";
  setNodeSelection(state, match?.id || "");
  resetLayoutCache(state);
  resetViewport(state);
}

function updateHoverReadout(state, text, locked = false) {
  const target = document.getElementById("graph-hover-readout");
  if (!target) return;
  target.dataset.locked = locked ? "true" : "";
  target.textContent = text;
}

function updateZoomReadout(state) {
  const target = document.getElementById("graph-zoom-level");
  if (!(target instanceof HTMLInputElement)) return;
  target.value = `${Math.round(state.zoom * 100)}%`;
}

function parseZoomValue(value) {
  const normalized = String(value || "").replace(/%/g, "").trim();
  const next = Number.parseFloat(normalized);
  if (!Number.isFinite(next) || next <= 0) return 1;
  return clampZoom(next / 100);
}

function syncUiFromState(state) {
  const searchInput = document.getElementById("graph-search");
  if (searchInput instanceof HTMLInputElement) searchInput.value = state.searchText;
  const hopDepth = document.getElementById("graph-hop-depth");
  if (hopDepth instanceof HTMLSelectElement) hopDepth.value = String(state.hopDepth);
  const ruleset = document.getElementById("graph-ruleset");
  if (ruleset instanceof HTMLSelectElement) ruleset.value = state.selectedRuleset;
  const layout = document.getElementById("graph-layout-mode");
  if (layout instanceof HTMLSelectElement) layout.value = state.layoutMode;
  const size = document.getElementById("graph-size-mode");
  if (size instanceof HTMLSelectElement) size.value = state.sizeMode;
  const color = document.getElementById("graph-color-mode");
  if (color instanceof HTMLSelectElement) color.value = state.colorMode;
  const density = document.getElementById("graph-edge-density");
  if (density instanceof HTMLSelectElement) density.value = state.edgeDensityMode;
  const hideIsolated = document.getElementById("graph-hide-isolated");
  if (hideIsolated instanceof HTMLInputElement) hideIsolated.checked = state.hideIsolated;
  const selectedNeighborhoodOnly = document.getElementById("graph-selected-neighborhood-only");
  if (selectedNeighborhoodOnly instanceof HTMLInputElement) {
    selectedNeighborhoodOnly.checked = state.selectedNeighborhoodOnly;
  }
  syncNodeLimitControls(state);
  syncPerspectiveButtons(state);
}

function recordRenderState(state) {
  pushHistoryState(state);
  writeUrlState(state);
  syncHistoryControls(state);
  syncPerspectiveButtons(state);
}

function rerenderFactory(state, canvas) {
  return (options = {}) => {
    syncGraphViewportVars();
    const projected = buildProjectedGraph(state);
    state.lastProjected = projected;
    renderStats(projected);
    renderFocus(projected, state);
    renderQueryStatus(projected, state);
    renderFacets(projected, state);
    renderDetail(projected, state);
    updateZoomReadout(state);
    drawGraph(canvas, projected, state);
    syncUiFromState(state);
    if (!options.skipRecord) recordRenderState(state);
    if (window.innerWidth <= 640 && state.selectedNodeId) {
      document.querySelector(".graph-workbench")?.classList.remove("sidebar-dismissed");
    }
  };
}

function ensureSceneBase(state) {
  if (!state.manualVisibleIds.size && state.lastProjected) {
    state.manualVisibleIds = new Set(state.lastProjected.nodes.map((node) => node.id));
  }
}

function expandFromNode(state, nodeId, depth) {
  const node = state.nodesById.get(nodeId);
  if (!node || !passesNodeFilters(node, state)) return;
  ensureSceneBase(state);
  bfsNeighborhood(nodeId, state, depth, Infinity).forEach((id) => {
    const candidate = state.nodesById.get(id);
    if (candidate && passesNodeFilters(candidate, state)) state.manualVisibleIds.add(id);
  });
  state.hiddenNodeIds.delete(nodeId);
  setNodeSelection(state, nodeId);
}

function hideNode(state, nodeId) {
  state.hiddenNodeIds.add(nodeId);
  state.manualVisibleIds.delete(nodeId);
  state.pinnedNodeIds.delete(nodeId);
  if (state.selectedNodeId === nodeId) state.selectedNodeId = "";
}

function togglePinNode(state, nodeId) {
  const node = state.nodesById.get(nodeId);
  if (!node || !passesNodeFilters(node, state)) return;
  if (state.pinnedNodeIds.has(nodeId)) {
    state.pinnedNodeIds.delete(nodeId);
  } else {
    ensureSceneBase(state);
    state.manualVisibleIds.add(nodeId);
    state.pinnedNodeIds.add(nodeId);
    state.hiddenNodeIds.delete(nodeId);
  }
}

function focusNode(state, nodeId) {
  const node = state.nodesById.get(nodeId);
  if (!node || !passesNodeFilters(node, state)) return;
  state.selectedNodeId = nodeId;
  state.searchText = node.label || node.id;
  clearSceneState(state);
  resetLayoutCache(state);
  resetViewport(state);
}

function applyPerspective(state, perspectiveId) {
  const perspective = PERSPECTIVES[perspectiveId];
  if (!perspective) return;
  state.activePerspective = perspectiveId;
  replaceCheckboxSet("graph-type-", TYPE_ORDER, new Set(perspective.enabledTypes));
  replaceCheckboxSet(
    "graph-edge-",
    EDGE_KINDS.map((kind) => kind.id),
    new Set(perspective.enabledEdgeKinds),
  );
  clearSceneState(state);
  resetLayoutCache(state);
  resetViewport(state);
}

function applySnapshot(state, snapshot, rerender) {
  applySnapshotToUi(state, snapshot);
  resetViewport(state);
  rerender({ skipRecord: true });
  syncHistoryControls(state);
  writeUrlState(state);
}

function updateFilterDerivedState(state) {
  if (state.activePerspective) {
    const perspective = PERSPECTIVES[state.activePerspective];
    const typesMatch =
      perspective.enabledTypes.every((type) => state.enabledTypes.has(type)) &&
      state.enabledTypes.size === perspective.enabledTypes.length;
    const edgesMatch =
      perspective.enabledEdgeKinds.every((kind) => state.enabledEdgeKinds.has(kind)) &&
      state.enabledEdgeKinds.size === perspective.enabledEdgeKinds.length;
    if (!typesMatch || !edgesMatch) state.activePerspective = "";
  }
}

function edgeStyle(edge, active, state) {
  const baseColor = EDGE_KINDS.find((kind) => kind.id === edge.kind)?.color || "rgba(47, 85, 71, 0.14)";
  if (active) {
    return { strokeStyle: "rgba(185, 131, 42, 0.82)", lineWidth: 2.2 };
  }
  if (state.edgeDensityMode === "focused" && edge.kind === "learnsMove") {
    return { strokeStyle: "rgba(232, 184, 80, 0.10)", lineWidth: 0.8 };
  }
  if (state.edgeDensityMode === "smart" && edge.kind === "learnsMove") {
    return { strokeStyle: "rgba(232, 184, 80, 0.16)", lineWidth: 0.9 };
  }
  return { strokeStyle: baseColor, lineWidth: edge.kind === "learnsMove" ? 0.95 : 1.1 };
}

function nodeFitsFrame(screen, radius, frame, inset = 6) {
  return (
    screen.x - radius >= frame.left + inset &&
    screen.x + radius <= frame.right - inset &&
    screen.y - radius >= frame.top + inset &&
    screen.y + radius <= frame.bottom - inset
  );
}

function drawGraph(canvas, projected, state) {
  const context = canvas.getContext("2d");
  if (!context) return;
  const rect = canvas.getBoundingClientRect();
  const scale = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * scale));
  canvas.height = Math.max(1, Math.floor(rect.height * scale));
  context.setTransform(scale, 0, 0, scale, 0, 0);
  context.clearRect(0, 0, rect.width, rect.height);

  const positions = buildLayout(projected, state, rect.width, rect.height);
  const frame = graphLayoutFrame(rect.width, rect.height);
  state.lastLayout = positions;
  state.lastRect = { width: rect.width, height: rect.height };
  const selectedNeighbors = projected.adjacency.get(state.selectedNodeId) || new Set();
  const toScreen = (point) => ({
    x: (point.x - rect.width / 2) * state.zoom + rect.width / 2 + state.panX,
    y: (point.y - rect.height / 2) * state.zoom + rect.height / 2 + state.panY,
  });
  const visibleNodeIds = new Set(
    projected.nodes
      .map((node) => {
        const point = positions.get(node.id);
        if (!point) return null;
        const screen = toScreen(point);
        const radius = Math.max(2.2, nodeRadius(node, state) * state.zoom);
        return nodeFitsFrame(screen, radius, frame) ? node.id : null;
      })
      .filter(Boolean),
  );

  context.save();
  context.fillStyle = "rgba(47, 85, 71, 0.035)";
  for (let x = 0; x < rect.width; x += 28) context.fillRect(x, 0, 1, rect.height);
  for (let y = 0; y < rect.height; y += 28) context.fillRect(0, y, rect.width, 1);
  context.restore();

  projected.edges.forEach((edge) => {
    const source = positions.get(edge.source);
    const target = positions.get(edge.target);
    if (!source || !target) return;
    if (!visibleNodeIds.has(edge.source) || !visibleNodeIds.has(edge.target)) return;
    const a = toScreen(source);
    const b = toScreen(target);
    const active =
      state.selectedNodeId &&
      (edge.source === state.selectedNodeId ||
        edge.target === state.selectedNodeId ||
        (selectedNeighbors.has(edge.source) && selectedNeighbors.has(edge.target)));
    const style = edgeStyle(edge, active, state);
    context.beginPath();
    context.moveTo(a.x, a.y);
    context.lineTo(b.x, b.y);
    context.strokeStyle = style.strokeStyle;
    context.lineWidth = style.lineWidth;
    context.stroke();
  });

  projected.nodes.forEach((node) => {
    const point = positions.get(node.id);
    if (!point) return;
    const screen = toScreen(point);
    const radius = Math.max(2.2, nodeRadius(node, state) * state.zoom);
    if (!visibleNodeIds.has(node.id)) return;
    const active =
      node.id === state.selectedNodeId ||
      selectedNeighbors.has(node.id) ||
      node.id === projected.anchorId ||
      state.pinnedNodeIds.has(node.id);
    context.beginPath();
    context.arc(screen.x, screen.y, radius, 0, Math.PI * 2);
    context.fillStyle = nodeColor(node, state);
    context.globalAlpha = active || !state.selectedNodeId ? 0.96 : 0.46;
    context.fill();
    context.globalAlpha = 1;
    context.lineWidth = active ? 2.6 : 1.1;
    context.strokeStyle = active ? "#17322b" : "rgba(23, 50, 43, 0.4)";
    context.stroke();
    if (state.pinnedNodeIds.has(node.id)) {
      context.beginPath();
      context.arc(screen.x, screen.y, radius + 4, 0, Math.PI * 2);
      context.strokeStyle = "rgba(185, 131, 42, 0.9)";
      context.lineWidth = 1.2;
      context.stroke();
    }
  });

  const labelNode = projected.nodes.find((node) => node.id === (state.hoverNodeId || state.selectedNodeId || projected.anchorId));
  if (labelNode) {
    const point = positions.get(labelNode.id);
    if (point) {
      const screen = toScreen(point);
      if (visibleNodeIds.has(labelNode.id)) {
        context.fillStyle = "#17322b";
        context.font = '700 12px "IBM Plex Mono", monospace';
        context.fillText(String(labelNode.label || ""), screen.x + 12, screen.y - 12);
      }
    }
  }

  state.hitMap = projected.nodes
    .map((node) => {
      const point = positions.get(node.id);
      if (!point) return null;
      const screen = toScreen(point);
      return {
        id: node.id,
        x: screen.x,
        y: screen.y,
        radius: Math.max(10, nodeRadius(node, state) * state.zoom + 4),
      };
    })
    .filter((entry) => entry && visibleNodeIds.has(entry.id));
}

function setupCanvasInteractions(canvas, state, rerender) {
  const activePointers = new Map();
  let lastPinchDist = null;

  function getPinchDist() {
    const pts = [...activePointers.values()];
    if (pts.length < 2) return null;
    return Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
  }

  canvas.addEventListener("pointerdown", (event) => {
    autoCollapseControls(state);
    activePointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    canvas.setPointerCapture(event.pointerId);
    if (activePointers.size === 2) lastPinchDist = getPinchDist();
  });
  canvas.addEventListener("pointermove", (event) => {
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const hit = [...state.hitMap]
      .reverse()
      .find((entry) => {
        const dx = x - entry.x;
        const dy = y - entry.y;
        return dx * dx + dy * dy <= entry.radius * entry.radius;
      });
    state.hoverNodeId = hit?.id || "";
    if (hit) {
      const node = state.nodesById.get(hit.id);
      updateHoverReadout(state, `${node?.label || hit.id} · ${node?.type || ""}`);
    } else if (activePointers.size === 0) {
      updateHoverReadout(state, state.selectedNodeId ? "Click nodes to repivot the local graph" : "Search or click a node to query locally");
    }

    if (!activePointers.has(event.pointerId)) return;
    const prev = activePointers.get(event.pointerId);
    const dx = event.clientX - prev.x;
    const dy = event.clientY - prev.y;
    activePointers.set(event.pointerId, { x: event.clientX, y: event.clientY });

    if (activePointers.size >= 2) {
      const dist = getPinchDist();
      if (dist && lastPinchDist) state.zoom = clampZoom(state.zoom * (dist / lastPinchDist));
      lastPinchDist = dist;
      rerender();
    } else {
      state.panX += dx;
      state.panY += dy;
      rerender();
    }
  });
  canvas.addEventListener("pointerup", (event) => {
    activePointers.delete(event.pointerId);
    canvas.releasePointerCapture(event.pointerId);
    if (activePointers.size < 2) lastPinchDist = null;
  });
  canvas.addEventListener("pointerleave", (event) => {
    activePointers.delete(event.pointerId);
    if (activePointers.size === 0) {
      state.hoverNodeId = "";
      updateHoverReadout(state, state.selectedNodeId ? "Click nodes to repivot the local graph" : "Search or click a node to query locally");
    }
  });
  canvas.addEventListener("pointercancel", (event) => {
    activePointers.delete(event.pointerId);
    lastPinchDist = null;
  });
  canvas.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      autoCollapseControls(state);
      const next = state.zoom * (event.deltaY < 0 ? 1.08 : 0.92);
      state.zoom = clampZoom(next);
      rerender();
    },
    { passive: false },
  );
  canvas.addEventListener("dblclick", () => {
    autoCollapseControls(state);
    resetViewport(state);
    rerender();
  });
}

function bindSelectionHandlers(state, rerender) {
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-graph-node]");
    if (button) {
      state.selectedNodeId = button.getAttribute("data-graph-node") || "";
      resetLayoutCache(state);
      resetViewport(state);
      rerender();
      return;
    }
    const action = event.target.closest("[data-graph-action]");
    if (!action || !state.selectedNodeId) return;
    const nodeId = state.selectedNodeId;
    switch (action.getAttribute("data-graph-action")) {
      case "focus":
        focusNode(state, nodeId);
        break;
      case "expand-1":
        expandFromNode(state, nodeId, 1);
        break;
      case "expand-2":
        expandFromNode(state, nodeId, 2);
        break;
      case "hide":
        hideNode(state, nodeId);
        break;
      case "pin":
        togglePinNode(state, nodeId);
        break;
      case "toggle-neighborhood":
        state.selectedNeighborhoodOnly = !state.selectedNeighborhoodOnly;
        break;
      default:
        return;
    }
    resetViewport(state);
    rerender();
  });
}

function wireControls(state, rerender) {
  document.getElementById("graph-controls-toggle")?.addEventListener("click", () => {
    setControlsCollapsed(state, !state.controlsCollapsed);
  });
  document.getElementById("graph-search")?.addEventListener("focus", () => {
    if (state.controlsCollapsed) setControlsCollapsed(state, false);
  });
  document.getElementById("graph-search")?.addEventListener("input", (event) => {
    applyQueryValue(state, event.target.value);
    rerender();
  });
  document.getElementById("graph-clear-query")?.addEventListener("click", () => {
    applyQueryValue(state, "");
    rerender();
  });
  document.getElementById("graph-reset-query")?.addEventListener("click", () => {
    applyQueryValue(state, DEFAULT_SEARCH);
    replaceCheckboxSet("graph-type-", TYPE_ORDER, new Set(TYPE_ORDER));
    replaceCheckboxSet(
      "graph-edge-",
      EDGE_KINDS.map((kind) => kind.id),
      new Set(EDGE_KINDS.filter((kind) => kind.checked).map((kind) => kind.id)),
    );
    state.selectedRuleset = "";
    state.layoutMode = DEFAULT_LAYOUT_MODE;
    state.sizeMode = DEFAULT_SIZE_MODE;
    state.colorMode = DEFAULT_COLOR_MODE;
    state.edgeDensityMode = DEFAULT_EDGE_DENSITY;
    state.hideIsolated = false;
    state.selectedNeighborhoodOnly = false;
    resetLayoutCache(state);
    rerender();
  });
  document.getElementById("graph-reset-view")?.addEventListener("click", () => {
    clearSceneState(state);
    resetLayoutCache(state);
    resetViewport(state);
    rerender();
  });
  document.getElementById("graph-history-back")?.addEventListener("click", () => {
    if (state.historyIndex <= 0) return;
    state.historyIndex -= 1;
    applySnapshot(state, state.history[state.historyIndex], rerender);
  });
  document.getElementById("graph-history-forward")?.addEventListener("click", () => {
    if (state.historyIndex >= state.history.length - 1) return;
    state.historyIndex += 1;
    applySnapshot(state, state.history[state.historyIndex], rerender);
  });
  document.getElementById("graph-fit-selection")?.addEventListener("click", () => {
    const ids = state.selectedNodeId
      ? new Set([state.selectedNodeId, ...(state.lastProjected?.adjacency.get(state.selectedNodeId) || [])])
      : new Set();
    if (ids.size) fitNodeIds(state, ids);
    rerender();
  });
  document.getElementById("graph-fit-graph")?.addEventListener("click", () => {
    fitNodeIds(state, new Set((state.lastProjected?.nodes || []).map((node) => node.id)));
    rerender();
  });
  document.getElementById("graph-layout-mode")?.addEventListener("change", (event) => {
    state.layoutMode = parseChoice(event.target.value, LAYOUT_OPTIONS, DEFAULT_LAYOUT_MODE);
    resetLayoutCache(state);
    rerender();
  });
  document.getElementById("graph-size-mode")?.addEventListener("change", (event) => {
    state.sizeMode = parseChoice(event.target.value, SIZE_OPTIONS, DEFAULT_SIZE_MODE);
    rerender();
  });
  document.getElementById("graph-color-mode")?.addEventListener("change", (event) => {
    state.colorMode = parseChoice(event.target.value, COLOR_OPTIONS, DEFAULT_COLOR_MODE);
    rerender();
  });
  document.getElementById("graph-edge-density")?.addEventListener("change", (event) => {
    state.edgeDensityMode = parseChoice(event.target.value, DENSITY_OPTIONS, DEFAULT_EDGE_DENSITY);
    resetLayoutCache(state);
    rerender();
  });
  document.getElementById("graph-hide-isolated")?.addEventListener("change", (event) => {
    state.hideIsolated = Boolean(event.target.checked);
    resetLayoutCache(state);
    rerender();
  });
  document.getElementById("graph-selected-neighborhood-only")?.addEventListener("change", (event) => {
    state.selectedNeighborhoodOnly = Boolean(event.target.checked);
    resetLayoutCache(state);
    rerender();
  });
  document.getElementById("graph-zoom-out")?.addEventListener("click", () => {
    state.zoom = clampZoom(state.zoom * ZOOM_STEP_OUT);
    rerender();
  });
  document.getElementById("graph-zoom-in")?.addEventListener("click", () => {
    state.zoom = clampZoom(state.zoom * ZOOM_STEP_IN);
    rerender();
  });
  document.getElementById("graph-zoom-reset")?.addEventListener("click", () => {
    resetViewport(state);
    rerender();
  });
  document.getElementById("graph-zoom-level")?.addEventListener("change", (event) => {
    state.zoom = parseZoomValue(event.target.value);
    rerender();
  });
  document.getElementById("graph-zoom-level")?.addEventListener("blur", (event) => {
    state.zoom = parseZoomValue(event.target.value);
    rerender();
  });
  document.getElementById("graph-zoom-level")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      event.target.blur();
      return;
    }
    if (event.key === "Escape") {
      updateZoomReadout(state);
      event.target.blur();
    }
  });
  document.querySelectorAll("[data-graph-preset]").forEach((button) => {
    button.addEventListener("click", () => {
      applyQueryValue(state, button.getAttribute("data-graph-preset") || "");
      rerender();
    });
  });
  document.querySelectorAll("[data-graph-perspective]").forEach((button) => {
    button.addEventListener("click", () => {
      const perspectiveId = button.getAttribute("data-graph-perspective") || "";
      state.activePerspective = state.activePerspective === perspectiveId ? "" : perspectiveId;
      if (state.activePerspective) {
        applyPerspective(state, state.activePerspective);
      } else {
        replaceCheckboxSet("graph-type-", TYPE_ORDER, new Set(TYPE_ORDER));
        replaceCheckboxSet(
          "graph-edge-",
          EDGE_KINDS.map((kind) => kind.id),
          new Set(EDGE_KINDS.filter((kind) => kind.checked).map((kind) => kind.id)),
        );
        resetLayoutCache(state);
      }
      rerender();
    });
  });
  document.getElementById("graph-hop-depth")?.addEventListener("change", (event) => {
    state.hopDepth = Number(event.target.value || 2);
    resetLayoutCache(state);
    rerender();
  });
  document.getElementById("graph-node-limit")?.addEventListener("focus", () => activateNodeLimitEditor(state));
  document.getElementById("graph-node-limit")?.addEventListener("click", () => activateNodeLimitEditor(state));
  document.getElementById("graph-node-limit")?.addEventListener("change", (event) => {
    commitNodeLimitValue(state, event.target.value);
    resetLayoutCache(state);
    rerender();
  });
  document.getElementById("graph-node-limit-max")?.addEventListener("pointerdown", () => {
    state.nodeLimitMaxPending = true;
  });
  document.getElementById("graph-node-limit-max")?.addEventListener("click", () => {
    commitNodeLimitValue(state, "MAX");
    const input = document.getElementById("graph-node-limit");
    if (input instanceof HTMLInputElement) input.blur();
    resetLayoutCache(state);
    rerender();
  });
  document.getElementById("graph-node-limit")?.addEventListener("blur", (event) => {
    if (state.nodeLimitMaxPending) {
      state.nodeLimitMaxPending = false;
      return;
    }
    commitNodeLimitValue(state, event.target.value);
    resetLayoutCache(state);
    rerender();
  });
  document.getElementById("graph-node-limit")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      event.target.blur();
      return;
    }
    if (event.key === "Escape") {
      state.nodeLimitEditing = false;
      state.nodeLimitMaxPending = false;
      syncNodeLimitControls(state);
      rerender();
    }
  });
  document.getElementById("graph-ruleset")?.addEventListener("change", (event) => {
    state.selectedRuleset = event.target.value;
    resetLayoutCache(state);
    rerender();
  });
  TYPE_ORDER.forEach((type) => {
    document.getElementById(`graph-type-${slugify(type)}`)?.addEventListener("change", () => {
      updateFilterDerivedState(state);
      resetLayoutCache(state);
      rerender();
    });
  });
  EDGE_KINDS.forEach((kind) => {
    document.getElementById(`graph-edge-${slugify(kind.id)}`)?.addEventListener("change", () => {
      updateFilterDerivedState(state);
      resetLayoutCache(state);
      rerender();
    });
  });
  window.addEventListener("keydown", (event) => {
    if (event.key === "/") {
      event.preventDefault();
      document.getElementById("graph-search")?.focus();
      return;
    }
    if (event.key === "[") {
      document.getElementById("graph-history-back")?.click();
      return;
    }
    if (event.key === "]") document.getElementById("graph-history-forward")?.click();
  });
  document.addEventListener("click", (event) => {
    const facet = event.target.closest("[data-graph-facet]");
    if (!facet) return;
    const kind = facet.getAttribute("data-graph-facet");
    const value = facet.getAttribute("data-graph-facet-value") || "";
    if (!kind || !value) return;
    if (kind === "type") {
      const next = state.enabledTypes.size === 1 && state.enabledTypes.has(value) ? new Set(TYPE_ORDER) : new Set([value]);
      replaceCheckboxSet("graph-type-", TYPE_ORDER, next);
      updateFilterDerivedState(state);
    } else if (kind === "edge") {
      const allEdges = EDGE_KINDS.map((entry) => entry.id);
      const next = state.enabledEdgeKinds.size === 1 && state.enabledEdgeKinds.has(value) ? new Set(allEdges) : new Set([value]);
      replaceCheckboxSet("graph-edge-", allEdges, next);
      updateFilterDerivedState(state);
    } else if (kind === "ruleset") {
      state.selectedRuleset = state.selectedRuleset === value ? "" : value;
    } else {
      return;
    }
    resetLayoutCache(state);
    rerender();
  });
}

export async function createGraphApp() {
  setupThemeToggle();
  setupMobileNav();
  const [siteData, rawGraph] = await Promise.all([loadSiteData(), loadGraphIndex()]);
  const status = document.querySelector("[data-graph-status]");
  const repoLink = document.querySelector("[data-repository-url]");
  if (repoLink) repoLink.href = siteData?.site?.repository_url || repoLink.href;
  if (status) status.textContent = "Ready";

  renderFilterControls(rawGraph);

  const { nodesById, adjacency } = buildIndexes(rawGraph);
  const urlState = decodeUrlState();
  const state = {
    rawGraph,
    nodesById,
    adjacency,
    selectedRuleset: urlState.selectedRuleset,
    searchText: urlState.searchText,
    selectedNodeId: urlState.selectedNodeId,
    hoverNodeId: "",
    hopDepth: urlState.hopDepth,
    nodeLimit: urlState.nodeLimit,
    lastFiniteNodeLimit: Number.isFinite(urlState.nodeLimit) ? urlState.nodeLimit : DEFAULT_NODE_LIMIT,
    nodeLimitEditing: false,
    nodeLimitMaxPending: false,
    panX: 0,
    panY: 0,
    zoom: 1,
    controlsCollapsed: false,
    hitMap: [],
    lastLayout: null,
    lastRect: null,
    lastProjected: { nodes: [] },
    manualVisibleIds: urlState.manualVisibleIds,
    hiddenNodeIds: urlState.hiddenNodeIds,
    pinnedNodeIds: urlState.pinnedNodeIds,
    activePerspective: urlState.activePerspective,
    layoutMode: urlState.layoutMode,
    sizeMode: urlState.sizeMode,
    colorMode: urlState.colorMode,
    edgeDensityMode: urlState.edgeDensityMode,
    hideIsolated: urlState.hideIsolated,
    selectedNeighborhoodOnly: urlState.selectedNeighborhoodOnly,
    layoutCache: new Map(),
    history: [],
    historyIndex: -1,
    get enabledTypes() {
      return selectedNodeTypes();
    },
    get enabledEdgeKinds() {
      return selectedEdgeKinds();
    },
  };

  const canvas = document.getElementById("graph-canvas");
  if (!(canvas instanceof HTMLCanvasElement)) throw new Error("Graph canvas missing.");

  replaceCheckboxSet("graph-type-", TYPE_ORDER, urlState.enabledTypes.size ? urlState.enabledTypes : new Set(TYPE_ORDER));
  replaceCheckboxSet(
    "graph-edge-",
    EDGE_KINDS.map((kind) => kind.id),
    urlState.enabledEdgeKinds.size
      ? urlState.enabledEdgeKinds
      : new Set(EDGE_KINDS.filter((kind) => kind.checked).map((kind) => kind.id)),
  );
  syncUiFromState(state);
  resetViewport(state);

  const rerender = rerenderFactory(state, canvas);

  setupCanvasInteractions(canvas, state, rerender);
  bindSelectionHandlers(state, rerender);
  wireControls(state, rerender);
  setControlsCollapsed(state, window.innerWidth <= 640);

  document.getElementById("graph-sidebar-close")?.addEventListener("click", () => {
    document.querySelector(".graph-workbench")?.classList.add("sidebar-dismissed");
  });

  canvas.addEventListener("click", (event) => {
    autoCollapseControls(state);
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const hit = [...state.hitMap]
      .reverse()
      .find((entry) => {
        const dx = x - entry.x;
        const dy = y - entry.y;
        return dx * dx + dy * dy <= entry.radius * entry.radius;
      });
    if (!hit) return;
    state.selectedNodeId = hit.id;
    resetLayoutCache(state);
    resetViewport(state);
    rerender();
  });

  window.addEventListener("resize", () => {
    resetLayoutCache(state);
    rerender({ skipRecord: true });
  });
  rerender();
}
