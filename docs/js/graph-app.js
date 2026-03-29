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
const MIN_ZOOM = 0.3;
const MAX_ZOOM = 2.8;
const ZOOM_STEP_IN = 1.12;
const ZOOM_STEP_OUT = 0.88;
const DEFAULT_NODE_LIMIT = 240;
const DEFAULT_SEARCH = "Pikachu";
const URL_STATE_VERSION = "1";
const GRAPH_PADDING = 36;
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

function readCheckedIds(prefix, ids) {
  return new Set(ids.filter((id) => document.getElementById(`${prefix}${slugify(id)}`)?.checked));
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

function nodeRadius(node) {
  const base = node.type === "Ruleset" ? 7 : node.type === "Species" ? 6 : 4.5;
  return Math.min(13, base + Math.log2((Number(node.degree) || 0) + 1) * 0.85);
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
  const nodes = [...limitedIds]
    .map((id) => state.nodesById.get(id))
    .filter(Boolean)
    .sort((a, b) => String(a.label).localeCompare(String(b.label)));
  const edges = state.rawGraph.edges.filter(
    (edge) => limitedIds.has(edge.source) && limitedIds.has(edge.target) && passesEdgeFilters(edge, state),
  );
  const adjacency = new Map();
  edges.forEach((edge) => {
    if (!adjacency.has(edge.source)) adjacency.set(edge.source, new Set());
    if (!adjacency.has(edge.target)) adjacency.set(edge.target, new Set());
    adjacency.get(edge.source).add(edge.target);
    adjacency.get(edge.target).add(edge.source);
  });
  return {
    anchorId,
    nodes,
    edges,
    adjacency,
    queryMatches,
  };
}

function buildLayout(nodes, anchorId, width, height) {
  const positions = new Map();
  if (!nodes.length) return positions;
  const types = TYPE_ORDER.filter((type) => nodes.some((node) => node.type === type));
  const orbitX = Math.max(width * 0.34, 250);
  const orbitY = Math.max(height * 0.28, 180);
  const centers = new Map();
  types.forEach((type, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(types.length, 1) - Math.PI / 2;
    centers.set(type, {
      x: width / 2 + Math.cos(angle) * orbitX,
      y: height / 2 + Math.sin(angle) * orbitY,
    });
  });

  const anchor = nodes.find((node) => node.id === anchorId);
  if (anchor) {
    positions.set(anchor.id, { x: width / 2, y: height / 2 });
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

function homePanOffsetX() {
  const sidebar = document.querySelector(".graph-sidebar");
  if (!(sidebar instanceof HTMLElement) || sidebar.hidden) return 0;
  return -Math.round(sidebar.getBoundingClientRect().width * 0.62);
}

function resetViewport(state) {
  state.panX = homePanOffsetX();
  state.panY = 0;
  state.zoom = 1;
}

function fitNodeIds(state, nodeIds) {
  if (!state.lastLayout || !state.lastRect || !nodeIds.size) return;
  const points = [...nodeIds]
    .map((id) => {
      const point = state.lastLayout.get(id);
      const node = state.nodesById.get(id);
      if (!point || !node) return null;
      const radius = nodeRadius(node) + GRAPH_PADDING;
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
  const body = document.getElementById("graph-controls-body");
  const toggle = document.getElementById("graph-controls-toggle");
  const reopen = document.getElementById("graph-controls-reopen");
  controls?.classList.toggle("is-collapsed", collapsed);
  if (controls) controls.hidden = false;
  if (body) body.hidden = collapsed;
  if (toggle) {
    toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    toggle.textContent = collapsed ? "Expand" : "Collapse";
  }
  if (reopen) {
    reopen.hidden = true;
    reopen.setAttribute("aria-expanded", collapsed ? "false" : "true");
  }
}

function autoCollapseControls(state) {
  if (!state.controlsCollapsed) {
    setControlsCollapsed(state, true);
  }
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
  };
  return JSON.stringify(payload);
}

function snapshotState(state) {
  return JSON.parse(serializeState(state));
}

function applyCheckboxSet(prefix, values) {
  values.forEach((value) => {
    const input = document.getElementById(`${prefix}${slugify(value)}`);
    if (input instanceof HTMLInputElement) input.checked = true;
  });
}

function replaceCheckboxSet(prefix, allValues, selectedValues) {
  allValues.forEach((value) => {
    const input = document.getElementById(`${prefix}${slugify(value)}`);
    if (input instanceof HTMLInputElement) {
      input.checked = selectedValues.has(value);
    }
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

  const searchInput = document.getElementById("graph-search");
  if (searchInput instanceof HTMLInputElement) searchInput.value = state.searchText;
  const hopDepth = document.getElementById("graph-hop-depth");
  if (hopDepth instanceof HTMLSelectElement) hopDepth.value = String(state.hopDepth);
  const ruleset = document.getElementById("graph-ruleset");
  if (ruleset instanceof HTMLSelectElement) ruleset.value = state.selectedRuleset;
  replaceCheckboxSet("graph-type-", TYPE_ORDER, parseListParam(snapshot.types || encodeSet(new Set(TYPE_ORDER))));
  replaceCheckboxSet(
    "graph-edge-",
    EDGE_KINDS.map((kind) => kind.id),
    parseListParam(snapshot.edges || encodeSet(new Set(EDGE_KINDS.map((kind) => kind.id)))),
  );
  syncNodeLimitControls(state);
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
    if (state.manualVisibleIds.size) {
      focusBadge.textContent = anchor
        ? `${anchor.label} · custom scene`
        : `Custom scene · ${projected.nodes.length} nodes`;
    } else {
      focusBadge.textContent = anchor ? `${anchor.label} · ${projected.nodes.length} node query` : "Top-degree overview";
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
  if (state.manualVisibleIds.size) {
    target.textContent = `Custom scene with ${projected.nodes.length} visible nodes. Shareable URL and history are active.`;
    return;
  }
  if (!query) {
    target.textContent = Number.isFinite(state.nodeLimit)
      ? `No query text. Showing top-degree overview limited to ${state.nodeLimit} nodes.`
      : "No query text. Showing the full top-degree overview.";
    return;
  }
  const topMatch = projected.queryMatches[0];
  if (!topMatch) {
    target.textContent = `No visible match for "${query}" under the current filters.`;
    return;
  }
  const exact = normalize(topMatch.label) === normalize(query) || normalize(topMatch.id) === normalize(query);
  target.textContent = exact
    ? `Exact match: ${topMatch.label}. Rendering a ${state.hopDepth}-hop neighborhood.`
    : `${projected.queryMatches.length} matches for "${query}". Focused on ${topMatch.label}.`;
}

function syncNodeLimitControls(state) {
  const input = document.getElementById("graph-node-limit");
  const maxButton = document.getElementById("graph-node-limit-max");
  if (input instanceof HTMLInputElement) {
    input.value = Number.isFinite(state.nodeLimit) ? String(state.nodeLimit) : "MAX";
  }
  if (maxButton instanceof HTMLButtonElement) {
    maxButton.hidden = !state.nodeLimitEditing;
  }
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
  if (Number.isFinite(state.nodeLimit)) {
    state.lastFiniteNodeLimit = state.nodeLimit;
  }
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
  const pinned = state.pinnedNodeIds.has(node.id);
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
      </div>
      ${
        breakdown.length
          ? `<section class="pokedex-section"><p class="panel-kicker">Incident Edges</p><div class="graph-breakdown-list">${breakdown
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
        <p class="panel-kicker">Neighbors</p>
        <div class="graph-neighbor-list graph-results">
          ${
            neighbors.length
              ? neighbors
                  .map(
                    (entry) => `
                      <button class="graph-neighbor-card" type="button" data-graph-node="${escapeHtml(entry.id)}">
                        <strong>${escapeHtml(entry.label)}</strong>
                        <span>${escapeHtml(entry.type)} · degree ${escapeHtml(entry.degree)}</span>
                      </button>
                    `,
                  )
                  .join("")
              : `<p class="pokedex-summary">No visible neighbors under the current query.</p>`
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

function applyQueryValue(state, value) {
  state.searchText = value;
  const searchInput = document.getElementById("graph-search");
  if (searchInput instanceof HTMLInputElement) {
    searchInput.value = value;
  }
  const match = findMatches(
    state.rawGraph.nodes.filter((node) => passesNodeFilters(node, state)),
    state.searchText,
  )[0];
  clearSceneState(state);
  state.activePerspective = "";
  setNodeSelection(state, match?.id || "");
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
    const projected = buildProjectedGraph(state);
    renderStats(projected);
    renderFocus(projected, state);
    renderQueryStatus(projected, state);
    renderDetail(projected, state);
    updateZoomReadout(state);
    drawGraph(canvas, projected, state);
    state.lastProjected = projected;
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
    const typesMatch = perspective.enabledTypes.every((type) => state.enabledTypes.has(type)) && state.enabledTypes.size === perspective.enabledTypes.length;
    const edgesMatch =
      perspective.enabledEdgeKinds.every((kind) => state.enabledEdgeKinds.has(kind)) &&
      state.enabledEdgeKinds.size === perspective.enabledEdgeKinds.length;
    if (!typesMatch || !edgesMatch) state.activePerspective = "";
  }
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

  const positions = buildLayout(projected.nodes, projected.anchorId, rect.width, rect.height);
  state.lastLayout = positions;
  state.lastRect = { width: rect.width, height: rect.height };
  const selectedNeighbors = projected.adjacency.get(state.selectedNodeId) || new Set();
  const toScreen = (point) => ({
    x: (point.x - rect.width / 2) * state.zoom + rect.width / 2 + state.panX,
    y: (point.y - rect.height / 2) * state.zoom + rect.height / 2 + state.panY,
  });

  context.save();
  context.fillStyle = "rgba(47, 85, 71, 0.035)";
  for (let x = 0; x < rect.width; x += 28) context.fillRect(x, 0, 1, rect.height);
  for (let y = 0; y < rect.height; y += 28) context.fillRect(0, y, rect.width, 1);
  context.restore();

  projected.edges.forEach((edge) => {
    const source = positions.get(edge.source);
    const target = positions.get(edge.target);
    if (!source || !target) return;
    const a = toScreen(source);
    const b = toScreen(target);
    const active =
      state.selectedNodeId &&
      (edge.source === state.selectedNodeId ||
        edge.target === state.selectedNodeId ||
        (selectedNeighbors.has(edge.source) && selectedNeighbors.has(edge.target)));
    context.beginPath();
    context.moveTo(a.x, a.y);
    context.lineTo(b.x, b.y);
    context.strokeStyle = active
      ? "rgba(185, 131, 42, 0.82)"
      : EDGE_KINDS.find((kind) => kind.id === edge.kind)?.color || "rgba(47, 85, 71, 0.14)";
    context.lineWidth = active ? 2 : 1;
    context.stroke();
  });

  projected.nodes.forEach((node) => {
    const point = positions.get(node.id);
    if (!point) return;
    const screen = toScreen(point);
    const radius = Math.max(2.2, nodeRadius(node) * state.zoom);
    const active =
      node.id === state.selectedNodeId ||
      selectedNeighbors.has(node.id) ||
      node.id === projected.anchorId ||
      state.pinnedNodeIds.has(node.id);
    context.beginPath();
    context.arc(screen.x, screen.y, radius, 0, Math.PI * 2);
    context.fillStyle = TYPE_COLORS[node.type] || "#54795c";
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
      context.fillStyle = "#17322b";
      context.font = '700 12px "IBM Plex Mono", monospace';
      context.fillText(String(labelNode.label || ""), screen.x + 12, screen.y - 12);
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
        radius: Math.max(10, nodeRadius(node) * state.zoom + 4),
      };
    })
    .filter(Boolean);
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
      if (dist && lastPinchDist) {
        state.zoom = clampZoom(state.zoom * (dist / lastPinchDist));
      }
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
  document.getElementById("graph-controls-reopen")?.addEventListener("click", () => {
    setControlsCollapsed(state, false);
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
    rerender();
  });
  document.getElementById("graph-reset-view")?.addEventListener("click", () => {
    clearSceneState(state);
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
    const ids = state.selectedNodeId ? new Set([state.selectedNodeId, ...(state.lastProjected?.adjacency.get(state.selectedNodeId) || [])]) : new Set();
    if (ids.size) fitNodeIds(state, ids);
    rerender();
  });
  document.getElementById("graph-fit-graph")?.addEventListener("click", () => {
    const ids = new Set((state.lastProjected?.nodes || []).map((node) => node.id));
    fitNodeIds(state, ids);
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
      }
      rerender();
    });
  });
  document.getElementById("graph-hop-depth")?.addEventListener("change", (event) => {
    state.hopDepth = Number(event.target.value || 2);
    rerender();
  });
  document.getElementById("graph-node-limit")?.addEventListener("focus", () => {
    activateNodeLimitEditor(state);
  });
  document.getElementById("graph-node-limit")?.addEventListener("click", () => {
    activateNodeLimitEditor(state);
  });
  document.getElementById("graph-node-limit")?.addEventListener("change", (event) => {
    commitNodeLimitValue(state, event.target.value);
    rerender();
  });
  document.getElementById("graph-node-limit-max")?.addEventListener("pointerdown", () => {
    state.nodeLimitMaxPending = true;
  });
  document.getElementById("graph-node-limit-max")?.addEventListener("click", () => {
    commitNodeLimitValue(state, "MAX");
    const input = document.getElementById("graph-node-limit");
    if (input instanceof HTMLInputElement) input.blur();
    rerender();
  });
  document.getElementById("graph-node-limit")?.addEventListener("blur", (event) => {
    if (state.nodeLimitMaxPending) {
      state.nodeLimitMaxPending = false;
      return;
    }
    commitNodeLimitValue(state, event.target.value);
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
    rerender();
  });
  TYPE_ORDER.forEach((type) => {
    document.getElementById(`graph-type-${slugify(type)}`)?.addEventListener("change", () => {
      updateFilterDerivedState(state);
      rerender();
    });
  });
  EDGE_KINDS.forEach((kind) => {
    document.getElementById(`graph-edge-${slugify(kind.id)}`)?.addEventListener("change", () => {
      updateFilterDerivedState(state);
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
    if (event.key === "]") {
      document.getElementById("graph-history-forward")?.click();
    }
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
    lastProjected: null,
    manualVisibleIds: urlState.manualVisibleIds,
    hiddenNodeIds: urlState.hiddenNodeIds,
    pinnedNodeIds: urlState.pinnedNodeIds,
    activePerspective: urlState.activePerspective,
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
  if (!(canvas instanceof HTMLCanvasElement)) {
    throw new Error("Graph canvas missing.");
  }
  replaceCheckboxSet("graph-type-", TYPE_ORDER, urlState.enabledTypes.size ? urlState.enabledTypes : new Set(TYPE_ORDER));
  replaceCheckboxSet(
    "graph-edge-",
    EDGE_KINDS.map((kind) => kind.id),
    urlState.enabledEdgeKinds.size ? urlState.enabledEdgeKinds : new Set(EDGE_KINDS.filter((kind) => kind.checked).map((kind) => kind.id)),
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
    resetViewport(state);
    rerender();
  });

  window.addEventListener("resize", () => rerender({ skipRecord: true }));
  rerender();
}
