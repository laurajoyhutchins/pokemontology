import { setupThemeToggle } from "./browser-runtime.js";
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

function selectedNodeTypes() {
  return new Set(
    TYPE_ORDER.filter((type) => document.getElementById(`graph-type-${slugify(type)}`)?.checked),
  );
}

function selectedEdgeKinds() {
  return new Set(
    EDGE_KINDS.filter((kind) => document.getElementById(`graph-edge-${slugify(kind.id)}`)?.checked).map(
      (kind) => kind.id,
    ),
  );
}

function matchesRuleset(node, ruleset) {
  if (!ruleset) return true;
  if (node.type === "Ruleset") return node.id === ruleset;
  return Array.isArray(node.contexts) && node.contexts.includes(ruleset);
}

function passesNodeFilters(node, state) {
  return state.enabledTypes.has(node.type) && matchesRuleset(node, state.selectedRuleset);
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

function bfsNeighborhood(anchorId, state) {
  const included = new Set();
  const queue = [{ id: anchorId, depth: 0 }];
  while (queue.length && included.size < state.nodeLimit) {
    const current = queue.shift();
    if (included.has(current.id)) continue;
    const node = state.nodesById.get(current.id);
    if (!node || !passesNodeFilters(node, state)) continue;
    included.add(current.id);
    if (current.depth >= state.hopDepth) continue;

    const candidates = (state.adjacency.get(current.id) || [])
      .filter((edge) => passesEdgeFilters(edge, state))
      .map((edge) => (edge.source === current.id ? edge.target : edge.source))
      .map((id) => state.nodesById.get(id))
      .filter((node) => node && passesNodeFilters(node, state))
      .sort((a, b) => (Number(b.degree) || 0) - (Number(a.degree) || 0));

    for (const node of candidates) {
      if (included.has(node.id)) continue;
      if (queue.some((entry) => entry.id === node.id)) continue;
      queue.push({ id: node.id, depth: current.depth + 1 });
      if (queue.length + included.size >= state.nodeLimit) break;
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
  const queryMatches = findMatches(state.rawGraph.nodes.filter((node) => passesNodeFilters(node, state)), state.searchText);
  const anchorId = state.selectedNodeId || queryMatches[0]?.id || "";
  const visibleIds = anchorId ? bfsNeighborhood(anchorId, state) : overviewNodes(state);
  const nodes = [...visibleIds]
    .map((id) => state.nodesById.get(id))
    .filter(Boolean)
    .sort((a, b) => String(a.label).localeCompare(String(b.label)));
  const edges = state.rawGraph.edges.filter(
    (edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target) && passesEdgeFilters(edge, state),
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
    const active = node.id === state.selectedNodeId || selectedNeighbors.has(node.id) || node.id === projected.anchorId;
    context.beginPath();
    context.arc(screen.x, screen.y, radius, 0, Math.PI * 2);
    context.fillStyle = TYPE_COLORS[node.type] || "#54795c";
    context.globalAlpha = active || !state.selectedNodeId ? 0.96 : 0.46;
    context.fill();
    context.globalAlpha = 1;
    context.lineWidth = active ? 2.6 : 1.1;
    context.strokeStyle = active ? "#17322b" : "rgba(23, 50, 43, 0.4)";
    context.stroke();
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

function renderStats(projected) {
  const nodeCount = document.querySelector("[data-graph-node-count]");
  const edgeCount = document.querySelector("[data-graph-edge-count]");
  if (nodeCount) nodeCount.textContent = String(projected.nodes.length);
  if (edgeCount) edgeCount.textContent = String(projected.edges.length);
}

function renderFocus(projected) {
  const focusBadge = document.getElementById("graph-focus-badge");
  const hoverReadout = document.getElementById("graph-hover-readout");
  if (focusBadge) {
    const anchor = projected.nodes.find((node) => node.id === projected.anchorId);
    focusBadge.textContent = anchor ? `${anchor.label} · ${projected.nodes.length} node query` : "Top-degree overview";
  }
  if (hoverReadout && !hoverReadout.dataset.locked) {
    hoverReadout.textContent = projected.anchorId ? "Click nodes to repivot the local graph" : "Search or click a node to query locally";
  }
}

function renderQueryStatus(projected, state) {
  const target = document.getElementById("graph-query-status");
  if (!target) return;
  const query = state.searchText.trim();
  if (!query) {
    target.textContent = `No query text. Showing top-degree overview limited to ${state.nodeLimit} nodes.`;
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
  badge.textContent = node.type;
  target.innerHTML = `
    <article class="graph-detail-card">
      <div class="graph-detail-head">
        <div>
          <h3>${escapeHtml(node.label)}</h3>
          <p class="pokedex-summary">${escapeHtml(node.id)}</p>
        </div>
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

function applyQueryValue(state, value, rerender) {
  state.searchText = value;
  const searchInput = document.getElementById("graph-search");
  if (searchInput instanceof HTMLInputElement) {
    searchInput.value = value;
  }
  const match = findMatches(
    state.rawGraph.nodes.filter((node) => passesNodeFilters(node, state)),
    state.searchText,
  )[0];
  state.selectedNodeId = match?.id || "";
  resetViewport(state);
  rerender();
}

function updateHoverReadout(state, text, locked = false) {
  const target = document.getElementById("graph-hover-readout");
  if (!target) return;
  target.dataset.locked = locked ? "true" : "";
  target.textContent = text;
}

function clampZoom(value) {
  return Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, value));
}

function updateZoomReadout(state) {
  const target = document.getElementById("graph-zoom-level");
  if (!target) return;
  target.textContent = `${Math.round(state.zoom * 100)}%`;
}

function homePanOffsetX() {
  const sidebar = document.querySelector(".graph-sidebar");
  if (!(sidebar instanceof HTMLElement) || sidebar.hidden) return 0;
  return -Math.round(sidebar.getBoundingClientRect().width / 2);
}

function resetViewport(state) {
  state.panX = homePanOffsetX();
  state.panY = 0;
  state.zoom = 1;
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

function setupCanvasInteractions(canvas, state, rerender) {
  let dragging = false;
  let lastX = 0;
  let lastY = 0;

  canvas.addEventListener("pointerdown", (event) => {
    autoCollapseControls(state);
    dragging = true;
    lastX = event.clientX;
    lastY = event.clientY;
    canvas.setPointerCapture(event.pointerId);
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
    } else if (!dragging) {
      updateHoverReadout(state, state.selectedNodeId ? "Click nodes to repivot the local graph" : "Search or click a node to query locally");
    }

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
    state.hoverNodeId = "";
    updateHoverReadout(state, state.selectedNodeId ? "Click nodes to repivot the local graph" : "Search or click a node to query locally");
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
    if (!button) return;
    state.selectedNodeId = button.getAttribute("data-graph-node") || "";
    state.panX = 0;
    state.panY = 0;
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
    applyQueryValue(state, event.target.value, rerender);
  });
  document.getElementById("graph-clear-query")?.addEventListener("click", () => {
    applyQueryValue(state, "", rerender);
  });
  document.getElementById("graph-reset-query")?.addEventListener("click", () => {
    applyQueryValue(state, "Pikachu", rerender);
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
  document.querySelectorAll("[data-graph-preset]").forEach((button) => {
    button.addEventListener("click", () => {
      applyQueryValue(state, button.getAttribute("data-graph-preset") || "", rerender);
    });
  });
  document.getElementById("graph-hop-depth")?.addEventListener("change", (event) => {
    state.hopDepth = Number(event.target.value || 2);
    rerender();
  });
  document.getElementById("graph-node-limit")?.addEventListener("change", (event) => {
    state.nodeLimit = Number(event.target.value || 240);
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
  window.addEventListener("keydown", (event) => {
    if (event.key === "/") {
      event.preventDefault();
      document.getElementById("graph-search")?.focus();
    }
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

  const { nodesById, adjacency } = buildIndexes(rawGraph);
  const state = {
    rawGraph,
    nodesById,
    adjacency,
    selectedRuleset: "",
    searchText: "Pikachu",
    selectedNodeId: "",
    hoverNodeId: "",
    hopDepth: 2,
    nodeLimit: 240,
    panX: 0,
    panY: 0,
    zoom: 1,
    controlsCollapsed: false,
    hitMap: [],
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
  const searchInput = document.getElementById("graph-search");
  if (searchInput instanceof HTMLInputElement) {
    searchInput.value = state.searchText;
  }
  resetViewport(state);

  const rerender = () => {
    const projected = buildProjectedGraph(state);
    renderStats(projected);
    renderFocus(projected);
    renderQueryStatus(projected, state);
    renderDetail(projected, state);
    updateZoomReadout(state);
    drawGraph(canvas, projected, state);
  };

  setupCanvasInteractions(canvas, state, rerender);
  bindSelectionHandlers(state, rerender);
  wireControls(state, rerender);
  setControlsCollapsed(state, false);

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
    state.panX = 0;
    state.panY = 0;
    rerender();
  });

  window.addEventListener("resize", rerender);
  rerender();
}
