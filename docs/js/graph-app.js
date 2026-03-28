import { setupThemeToggle } from "./browser-runtime.js";
import { loadSiteData } from "./site-render.js";

const TYPE_ORDER = ["Species", "Variant", "Move", "Ability", "Item", "Type", "Ruleset"];
const EDGE_KINDS = [
  { id: "belongsToSpecies", label: "species links", checked: true },
  { id: "hasType", label: "typing", checked: true },
  { id: "hasAbility", label: "abilities", checked: true },
  { id: "hasMoveType", label: "move typing", checked: true },
  { id: "learnsMove", label: "learnsets", checked: false },
  { id: "availableIn", label: "rulesets", checked: false },
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

async function loadGraphIndex() {
  const response = await fetch("./graph-index.json", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load graph-index.json: ${response.status}`);
  }
  return response.json();
}

function buildAdjacency(edges) {
  const neighbors = new Map();
  edges.forEach((edge) => {
    if (!neighbors.has(edge.source)) neighbors.set(edge.source, new Set());
    if (!neighbors.has(edge.target)) neighbors.set(edge.target, new Set());
    neighbors.get(edge.source).add(edge.target);
    neighbors.get(edge.target).add(edge.source);
  });
  return neighbors;
}

function buildLayout(nodes, width, height) {
  const types = TYPE_ORDER.filter((type) => nodes.some((node) => node.type === type));
  const clusterCenters = new Map();
  const radiusX = Math.max(width * 0.34, 260);
  const radiusY = Math.max(height * 0.26, 190);
  types.forEach((type, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(types.length, 1) - Math.PI / 2;
    clusterCenters.set(type, {
      x: width / 2 + Math.cos(angle) * radiusX,
      y: height / 2 + Math.sin(angle) * radiusY,
    });
  });

  const positions = new Map();
  types.forEach((type) => {
    const center = clusterCenters.get(type) || { x: width / 2, y: height / 2 };
    const group = nodes
      .filter((node) => node.type === type)
      .sort((a, b) => String(a.label).localeCompare(String(b.label)));
    let ring = 0;
    let indexInRing = 0;
    let capacity = 1;
    group.forEach((node) => {
      if (indexInRing >= capacity) {
        ring += 1;
        indexInRing = 0;
      }
      const ringRadius = ring * 22;
      capacity = ring === 0 ? 1 : Math.max(10, Math.floor((Math.PI * 2 * ringRadius) / 18));
      const angle = ring === 0 ? 0 : (Math.PI * 2 * indexInRing) / capacity;
      positions.set(node.id, {
        x: center.x + Math.cos(angle) * ringRadius,
        y: center.y + Math.sin(angle) * ringRadius,
      });
      indexInRing += 1;
    });
  });
  return positions;
}

function nodeRadius(node) {
  const base = node.type === "Ruleset" ? 5.5 : node.type === "Species" ? 5 : 3.4;
  return Math.min(11, base + Math.log2((Number(node.degree) || 0) + 1) * 0.9);
}

function matchesRuleset(node, ruleset) {
  if (!ruleset) return true;
  if (node.type === "Ruleset") return node.id === ruleset;
  return Array.isArray(node.contexts) && node.contexts.includes(ruleset);
}

function projectGraph(rawGraph, state) {
  const enabledTypes = new Set(
    TYPE_ORDER.filter((type) => document.getElementById(`graph-type-${slugify(type)}`)?.checked),
  );
  const enabledEdgeKinds = new Set(
    EDGE_KINDS.filter((kind) => document.getElementById(`graph-edge-${slugify(kind.id)}`)?.checked).map(
      (kind) => kind.id,
    ),
  );
  const ruleset = state.selectedRuleset;
  const nodeMap = new Map();
  rawGraph.nodes.forEach((node) => {
    if (!enabledTypes.has(node.type)) return;
    if (!matchesRuleset(node, ruleset)) return;
    nodeMap.set(node.id, node);
  });

  const edges = rawGraph.edges.filter((edge) => {
    if (!enabledEdgeKinds.has(edge.kind)) return false;
    if (!nodeMap.has(edge.source) || !nodeMap.has(edge.target)) return false;
    return true;
  });

  const connectedNodeIds = new Set(edges.flatMap((edge) => [edge.source, edge.target]));
  const nodes = [...nodeMap.values()].filter((node) => {
    if (node.type === "Ruleset" && state.selectedRuleset && node.id === state.selectedRuleset) return true;
    return connectedNodeIds.has(node.id) || enabledEdgeKinds.size === 0;
  });
  return {
    nodes,
    edges,
    adjacency: buildAdjacency(edges),
  };
}

function updateStats(projected) {
  const nodeCount = document.querySelector("[data-graph-node-count]");
  const edgeCount = document.querySelector("[data-graph-edge-count]");
  if (nodeCount) nodeCount.textContent = String(projected.nodes.length);
  if (edgeCount) edgeCount.textContent = String(projected.edges.length);
}

function renderSearchResults(state, nodes) {
  const target = document.getElementById("graph-results");
  const badge = document.getElementById("graph-results-badge");
  if (!target || !badge) return;
  const query = normalize(state.searchText);
  if (!query) {
    badge.textContent = "0 results";
    target.innerHTML = `
      <div class="qe-placeholder">
        <span class="qe-placeholder-icon">◌</span>
        <p>Search results will appear here.</p>
      </div>
    `;
    return;
  }
  const matches = nodes
    .filter((node) => {
      const haystack = normalize(`${node.label} ${node.id} ${node.identifiers.join(" ")}`);
      return haystack.includes(query);
    })
    .slice(0, 14);
  badge.textContent = `${matches.length} results`;
  if (!matches.length) {
    target.innerHTML = `
      <div class="qe-placeholder">
        <span class="qe-placeholder-icon">∅</span>
        <p>No nodes matched "${escapeHtml(state.searchText)}".</p>
      </div>
    `;
    return;
  }
  target.innerHTML = matches
    .map(
      (node) => `
        <button class="graph-result-card" type="button" data-graph-node="${escapeHtml(node.id)}">
          <strong>${escapeHtml(node.label)}</strong>
          <span>${escapeHtml(node.type)} · degree ${escapeHtml(node.degree)}</span>
        </button>
      `,
    )
    .join("");
}

function renderDetail(state, projected) {
  const target = document.getElementById("graph-detail");
  const badge = document.getElementById("graph-selection-badge");
  const focusBadge = document.getElementById("graph-focus-badge");
  if (!target || !badge || !focusBadge) return;
  const node = projected.nodes.find((entry) => entry.id === state.selectedNodeId);
  if (!node) {
    badge.textContent = "No selection";
    focusBadge.textContent = state.selectedRuleset ? "Ruleset filtered" : "Whole graph";
    target.innerHTML = `
      <div class="qe-placeholder">
        <span class="qe-placeholder-icon">◎</span>
        <p>Pick a node or search for an entity to inspect its graph neighborhood.</p>
      </div>
    `;
    return;
  }
  const neighbors = [...(projected.adjacency.get(node.id) || new Set())]
    .map((id) => projected.nodes.find((entry) => entry.id === id))
    .filter(Boolean)
    .sort((a, b) => String(a.label).localeCompare(String(b.label)))
    .slice(0, 12);
  badge.textContent = node.type;
  focusBadge.textContent = node.label;
  target.innerHTML = `
    <article class="graph-detail-card">
      <div class="graph-detail-head">
        <div>
          <p class="panel-kicker">Selected Node</p>
          <h3>${escapeHtml(node.label)}</h3>
          <p class="pokedex-summary">${escapeHtml(node.id)}</p>
        </div>
        <span class="graph-type-pill graph-type-${slugify(node.type)}">${escapeHtml(node.type)}</span>
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
        node.identifiers.length
          ? `<section class="pokedex-section"><p class="panel-kicker">Identifiers</p><div class="pokedex-chip-row">${node.identifiers
              .slice(0, 8)
              .map((value) => `<span class="info-chip">${escapeHtml(value)}</span>`)
              .join("")}</div></section>`
          : ""
      }
      ${
        node.contexts.length
          ? `<section class="pokedex-section"><p class="panel-kicker">Ruleset Contexts</p><div class="pokedex-chip-row">${node.contexts
              .slice(0, 10)
              .map((value) => `<span class="info-chip">${escapeHtml(value.replace(/^pkm:/, ""))}</span>`)
              .join("")}</div></section>`
          : ""
      }
      <section class="pokedex-section">
        <p class="panel-kicker">Neighborhood Preview</p>
        <div class="graph-neighbor-list">
          ${
            neighbors.length
              ? neighbors
                  .map(
                    (entry) => `
                      <button class="graph-neighbor-card" type="button" data-graph-node="${escapeHtml(entry.id)}">
                        <strong>${escapeHtml(entry.label)}</strong>
                        <span>${escapeHtml(entry.type)}</span>
                      </button>
                    `,
                  )
                  .join("")
              : `<p class="pokedex-summary">No visible neighbors under the current filters.</p>`
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
      `<option value="">All published rulesets</option>`,
      ...rulesets.map((node) => `<option value="${escapeHtml(node.id)}">${escapeHtml(node.label)}</option>`),
    ].join("");
  }
}

function setupCanvasInteractions(canvas, state, rerender) {
  let dragging = false;
  let lastX = 0;
  let lastY = 0;

  canvas.addEventListener("pointerdown", (event) => {
    dragging = true;
    lastX = event.clientX;
    lastY = event.clientY;
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    state.panX += event.clientX - lastX;
    state.panY += event.clientY - lastY;
    lastX = event.clientX;
    lastY = event.clientY;
    rerender();
  });
  canvas.addEventListener("pointerup", (event) => {
    dragging = false;
    canvas.releasePointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointerleave", () => {
    dragging = false;
  });
  canvas.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      const next = state.zoom * (event.deltaY < 0 ? 1.08 : 0.92);
      state.zoom = Math.max(0.35, Math.min(2.6, next));
      rerender();
    },
    { passive: false },
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

  const positions = buildLayout(projected.nodes, rect.width, rect.height);
  const selectedNodeId = state.selectedNodeId;
  const selectedNeighbors = projected.adjacency.get(selectedNodeId) || new Set();

  const toScreen = (point) => ({
    x: (point.x - rect.width / 2) * state.zoom + rect.width / 2 + state.panX,
    y: (point.y - rect.height / 2) * state.zoom + rect.height / 2 + state.panY,
  });

  projected.edges.forEach((edge) => {
    const source = positions.get(edge.source);
    const target = positions.get(edge.target);
    if (!source || !target) return;
    const a = toScreen(source);
    const b = toScreen(target);
    const emphasized =
      selectedNodeId &&
      (edge.source === selectedNodeId ||
        edge.target === selectedNodeId ||
        (selectedNeighbors.has(edge.source) && selectedNeighbors.has(edge.target)));
    context.beginPath();
    context.moveTo(a.x, a.y);
    context.lineTo(b.x, b.y);
    context.strokeStyle = emphasized ? "rgba(185, 131, 42, 0.8)" : "rgba(47, 85, 71, 0.12)";
    context.lineWidth = emphasized ? 1.8 : 1;
    context.stroke();
  });

  projected.nodes.forEach((node) => {
    const point = positions.get(node.id);
    if (!point) return;
    const screen = toScreen(point);
    const radius = nodeRadius(node) * state.zoom;
    const active = node.id === selectedNodeId || selectedNeighbors.has(node.id);
    context.beginPath();
    context.arc(screen.x, screen.y, radius, 0, Math.PI * 2);
    context.fillStyle = TYPE_COLORS[node.type] || "#54795c";
    context.globalAlpha = active || !selectedNodeId ? 0.94 : 0.38;
    context.fill();
    context.globalAlpha = 1;
    context.lineWidth = active ? 2.5 : 1.2;
    context.strokeStyle = active ? "#17322b" : "rgba(23, 50, 43, 0.45)";
    context.stroke();
  });

  if (selectedNodeId && positions.has(selectedNodeId)) {
    const node = projected.nodes.find((entry) => entry.id === selectedNodeId);
    const point = toScreen(positions.get(selectedNodeId));
    context.fillStyle = "#17322b";
    context.font = '700 12px "IBM Plex Mono", monospace';
    context.fillText(String(node?.label || ""), point.x + 12, point.y - 12);
  }

  state.hitMap = projected.nodes.map((node) => {
    const point = positions.get(node.id);
    if (!point) return null;
    const screen = toScreen(point);
    return {
      id: node.id,
      x: screen.x,
      y: screen.y,
      radius: nodeRadius(node) * state.zoom + 3,
    };
  }).filter(Boolean);
}

function bindSelectionHandlers(state, rerender) {
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-graph-node]");
    if (!button) return;
    state.selectedNodeId = button.getAttribute("data-graph-node") || "";
    rerender();
  });
}

export async function createGraphApp() {
  setupThemeToggle();
  const [siteData, rawGraph] = await Promise.all([loadSiteData(), loadGraphIndex()]);
  const status = document.querySelector("[data-graph-status]");
  const repoLink = document.querySelector("[data-repository-url]");
  if (repoLink) repoLink.href = siteData?.site?.repository_url || repoLink.href;
  if (status) status.textContent = "Ready";

  renderFilterControls(rawGraph);

  const state = {
    rawGraph,
    selectedRuleset: "",
    searchText: "",
    selectedNodeId: "",
    panX: 0,
    panY: 0,
    zoom: 1,
    hitMap: [],
  };
  const canvas = document.getElementById("graph-canvas");
  if (!(canvas instanceof HTMLCanvasElement)) {
    throw new Error("Graph canvas missing.");
  }

  const rerender = () => {
    const projected = projectGraph(state.rawGraph, state);
    updateStats(projected);
    renderDetail(state, projected);
    renderSearchResults(state, projected.nodes);
    drawGraph(canvas, projected, state);
  };

  setupCanvasInteractions(canvas, state, rerender);
  bindSelectionHandlers(state, rerender);

  canvas.addEventListener("click", (event) => {
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
    rerender();
  });

  document.getElementById("graph-search")?.addEventListener("input", (event) => {
    state.searchText = event.target.value;
    const query = normalize(state.searchText);
    if (query) {
      const match = state.rawGraph.nodes.find((node) =>
        normalize(`${node.label} ${node.id} ${node.identifiers.join(" ")}`).includes(query),
      );
      if (match) state.selectedNodeId = match.id;
    }
    rerender();
  });

  document.getElementById("graph-ruleset")?.addEventListener("change", (event) => {
    state.selectedRuleset = event.target.value;
    rerender();
  });

  TYPE_ORDER.forEach((type) => {
    document.getElementById(`graph-type-${slugify(type)}`)?.addEventListener("change", rerender);
  });
  EDGE_KINDS.forEach((kind) => {
    document.getElementById(`graph-edge-${slugify(kind.id)}`)?.addEventListener("change", rerender);
  });

  window.addEventListener("resize", rerender);
  rerender();
}
