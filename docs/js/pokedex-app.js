import { createWorkerRpc, setupMobileNav, setupThemeToggle } from "./browser-runtime.js";
import { getCanonicalMechanicsLabel, mechanicsSourceCandidates } from "./docs-sources.js";
import { loadSiteData } from "./site-render.js";

const PKM_PREFIX = "https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#";
const POKEAPI_DEFAULT_RULESET_IRI = "<https://laurajoyhutchins.github.io/pokemontology/id/ruleset/pokeapi-default>";
const askWorker = createWorkerRpc("pokedex");

const CATALOG_QUERY = `
PREFIX pkm: <${PKM_PREFIX}>

SELECT ?species ?speciesName ?identifier
       (GROUP_CONCAT(DISTINCT CONCAT(STR(?slot), ":", ?typeName); separator="|") AS ?typePairs)
WHERE {
  ?species a pkm:Species ;
           pkm:hasName ?speciesName ;
           pkm:hasIdentifier ?identifier .
  OPTIONAL {
    ?typing a pkm:TypingAssignment ;
            pkm:aboutPokemon ?species ;
            pkm:aboutType ?type ;
            pkm:hasContext ${POKEAPI_DEFAULT_RULESET_IRI} ;
            pkm:hasTypeSlot ?slot .
    ?type pkm:hasName ?typeName .
  }
}
GROUP BY ?species ?speciesName ?identifier
`;

const TYPE_QUERY = `
PREFIX pkm: <${PKM_PREFIX}>

SELECT ?typeName ?slot
WHERE {
  VALUES ?pokemon { __POKEMON__ }
  ?typing a pkm:TypingAssignment ;
          pkm:aboutPokemon ?pokemon ;
          pkm:aboutType ?type ;
          pkm:hasContext ${POKEAPI_DEFAULT_RULESET_IRI} ;
          pkm:hasTypeSlot ?slot .
  ?type pkm:hasName ?typeName .
}
ORDER BY ?slot
`;

const MOVES_QUERY = `
PREFIX pkm: <${PKM_PREFIX}>

SELECT DISTINCT ?moveName
WHERE {
  VALUES ?pokemon { __POKEMON__ }
  ?record a pkm:MoveLearnRecord ;
          pkm:aboutPokemon ?pokemon ;
          pkm:learnableMove ?move ;
          pkm:isLearnableInRuleset true .
  ?move pkm:hasName ?moveName .
}
ORDER BY ?moveName
LIMIT 36
`;

const RULESET_QUERY = `
PREFIX pkm: <${PKM_PREFIX}>

SELECT ?rulesetName (COUNT(DISTINCT ?move) AS ?moveCount)
WHERE {
  VALUES ?pokemon { __POKEMON__ }
  ?record a pkm:MoveLearnRecord ;
          pkm:aboutPokemon ?pokemon ;
          pkm:hasContext ?ruleset ;
          pkm:learnableMove ?move ;
          pkm:isLearnableInRuleset true .
  ?ruleset pkm:hasName ?rulesetName .
}
GROUP BY ?rulesetName
ORDER BY DESC(?moveCount) ?rulesetName
LIMIT 8
`;

const ABILITY_QUERY = `
PREFIX pkm: <${PKM_PREFIX}>

SELECT ?abilityName ?hidden
WHERE {
  VALUES ?pokemon { __POKEMON__ }
  ?assignment a pkm:AbilityAssignment ;
              pkm:aboutPokemon ?pokemon ;
              pkm:aboutAbility ?ability .
  ?ability pkm:hasName ?abilityName .
  OPTIONAL { ?assignment pkm:isHiddenAbility ?hidden . }
}
ORDER BY ?abilityName
`;

const STATS_QUERY = `
PREFIX pkm: <${PKM_PREFIX}>

SELECT ?statName ?value
WHERE {
  VALUES ?pokemon { __POKEMON__ }
  ?assignment a pkm:StatAssignment ;
              pkm:aboutPokemon ?pokemon ;
              pkm:aboutStat ?stat ;
              pkm:hasValue ?value .
  ?stat pkm:hasName ?statName .
}
`;

function termValue(binding, key) {
  return binding?.[key]?.value || "";
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function parseDexNumber(identifier) {
  const match = String(identifier).match(/:(\d+)$/);
  return match ? Number(match[1]) : Number.MAX_SAFE_INTEGER;
}

function parseTypePairs(raw) {
  return String(raw || "")
    .split("|")
    .map((entry) => {
      const [slot, name] = entry.split(":");
      return {
        slot: Number(slot || 99),
        name: name || "",
      };
    })
    .filter((entry) => entry.name)
    .sort((a, b) => a.slot - b.slot);
}

function slugify(value) {
  return String(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

function toCatalogEntry(binding) {
  const speciesName = termValue(binding, "speciesName");
  const identifier = termValue(binding, "identifier");
  return {
    speciesIri: termValue(binding, "species"),
    speciesName,
    identifier,
    dexNumber: parseDexNumber(identifier),
    typePairs: parseTypePairs(termValue(binding, "typePairs")),
    slug: slugify(speciesName),
  };
}

function toPlainRows(result) {
  return (result?.bindings || []).map((binding) =>
    Object.fromEntries(Object.entries(binding).map(([key, term]) => [key, term?.value || ""])),
  );
}

function typeBadgeHtml(typeName) {
  const slug = slugify(typeName);
  return `<span class="type-chip type-${slug}">${escapeHtml(typeName)}</span>`;
}

function renderCatalog(entries, selectedSlug) {
  const target = document.getElementById("pokedex-results");
  if (!target) return;
  if (!entries.length) {
    target.innerHTML = `
      <div class="qe-placeholder">
        <span class="qe-placeholder-icon">∅</span>
        <p>No Pokemon matched this search.</p>
      </div>
    `;
    return;
  }

  target.innerHTML = entries
    .map((entry) => `
      <button
        class="pokedex-card ${entry.slug === selectedSlug ? "is-selected" : ""}"
        type="button"
        data-pokemon-slug="${escapeHtml(entry.slug)}"
      >
        <div class="pokedex-card-head">
          <span class="pokedex-dex">#${entry.dexNumber}</span>
          <span class="pokedex-variant-tag">Field Entry</span>
        </div>
        <div class="pokedex-card-copy">
          <h3>${escapeHtml(entry.speciesName)}</h3>
          <p>${escapeHtml(entry.identifier)}</p>
        </div>
        <div class="pokedex-type-row">
          ${entry.typePairs.map((type) => typeBadgeHtml(type.name)).join("")}
        </div>
      </button>
    `)
    .join("");
}

function renderDetailLoading(entry) {
  const target = document.getElementById("pokedex-detail");
  const badge = document.getElementById("pokedex-entry-badge");
  if (badge) badge.textContent = entry ? `#${entry.dexNumber}` : "Loading";
  if (!target) return;
  target.innerHTML = `
    <div class="qe-placeholder">
      <span class="qe-placeholder-icon">◔</span>
      <p>Loading ${escapeHtml(entry?.speciesName || "entry")} details…</p>
    </div>
  `;
}

function renderDetailPlaceholder(message = "Choose a result to inspect its ontology-backed details.") {
  const target = document.getElementById("pokedex-detail");
  const badge = document.getElementById("pokedex-entry-badge");
  if (badge) badge.textContent = "No selection";
  if (!target) return;
  target.innerHTML = `
    <div class="qe-placeholder">
      <span class="qe-placeholder-icon">◎</span>
      <p>${escapeHtml(message)}</p>
    </div>
  `;
}

function renderDetail(entry, detail) {
  const target = document.getElementById("pokedex-detail");
  const badge = document.getElementById("pokedex-entry-badge");
  if (!target) return;
  if (badge) badge.textContent = `#${entry.dexNumber}`;

  const typeRows = detail.types.length ? detail.types : entry.typePairs.map((type) => ({ typeName: type.name }));

  const stats = detail.stats.length
    ? `
      <section class="pokedex-section">
        <p class="panel-kicker">Base Stats</p>
        <div class="pokedex-stat-list">
          ${detail.stats.map((row) => `
            <div class="pokedex-stat-row">
              <span>${escapeHtml(row.statName)}</span>
              <strong>${escapeHtml(row.value)}</strong>
            </div>
          `).join("")}
        </div>
      </section>
    `
    : "";

  const abilities = detail.abilities.length
    ? `
      <section class="pokedex-section">
        <p class="panel-kicker">Abilities</p>
        <div class="pokedex-chip-row">
          ${detail.abilities.map((row) => `
            <span class="info-chip">${escapeHtml(row.abilityName)}${row.hidden === "true" ? " (Hidden)" : ""}</span>
          `).join("")}
        </div>
      </section>
    `
    : "";

  target.innerHTML = `
    <article class="pokedex-entry">
      <div class="pokedex-entry-head">
        <div>
          <p class="panel-kicker">Species Record</p>
          <h3>${escapeHtml(entry.speciesName)}</h3>
          <p class="pokedex-subhead">${escapeHtml(entry.identifier)}</p>
        </div>
        <div class="pokedex-entry-meta">
          <span class="pokedex-record-id">Dex ${escapeHtml(entry.dexNumber)}</span>
        </div>
      </div>

      <section class="pokedex-section pokedex-section-hero">
        <div class="pokedex-chip-row">
          ${typeRows.map((row) => typeBadgeHtml(row.typeName)).join("")}
        </div>
        <div class="pokedex-summary-grid">
          <div class="pokedex-summary-card">
            <span>Types</span>
            <strong>${escapeHtml(typeRows.length)}</strong>
          </div>
          <div class="pokedex-summary-card">
            <span>Moves</span>
            <strong>${escapeHtml(detail.moves.length)}</strong>
          </div>
          <div class="pokedex-summary-card">
            <span>Rulesets</span>
            <strong>${escapeHtml(detail.rulesets.length)}</strong>
          </div>
          <div class="pokedex-summary-card">
            <span>Abilities</span>
            <strong>${escapeHtml(detail.abilities.length)}</strong>
          </div>
        </div>
      </section>

      <section class="pokedex-section">
        <p class="panel-kicker">Move Preview</p>
        <p class="pokedex-summary">
          Showing ${detail.moves.length} distinct learnable move names from the ontology-backed dataset.
        </p>
        <div class="pokedex-chip-row">
          ${detail.moves.map((row) => `<span class="info-chip">${escapeHtml(row.moveName)}</span>`).join("")}
        </div>
      </section>

      <section class="pokedex-section">
        <p class="panel-kicker">Ruleset Coverage</p>
        <div class="pokedex-ruleset-list">
          ${detail.rulesets.map((row) => `
            <div class="pokedex-ruleset-row">
              <span>${escapeHtml(row.rulesetName)}</span>
              <strong>${escapeHtml(row.moveCount)} moves</strong>
            </div>
          `).join("")}
        </div>
      </section>

      ${abilities}
      ${stats}
    </article>
  `;
}

function renderError(message) {
  const results = document.getElementById("pokedex-results");
  const detail = document.getElementById("pokedex-detail");
  const status = document.querySelector("[data-pokedex-status]");
  const badge = document.querySelector("[data-pokedex-catalog-badge]");
  if (status) status.textContent = "Error";
  if (badge) badge.textContent = "Query failed";
  const html = `
    <div class="qe-empty">
      <p>${escapeHtml(message)}</p>
    </div>
  `;
  if (results) results.innerHTML = html;
  if (detail) detail.innerHTML = html;
}

function buildPokemonQuery(template, pokemonIri) {
  return template.replace("__POKEMON__", `<${pokemonIri}>`);
}

async function fetchCatalog(worker, appState) {
  const status = document.querySelector("[data-pokedex-status]");
  const badge = document.querySelector("[data-pokedex-catalog-badge]");
  const onProgress = (event) => {
    if (status) status.textContent = event.message || "Loading";
    if (badge) badge.textContent = event.stage === "ready" ? "Graph ready" : "Preparing graph";
  };

  let response = null;
  let lastError = null;
  for (const candidateSources of mechanicsSourceCandidates(appState.siteData)) {
    try {
      await askWorker(
        worker,
        { action: "warmup", sources: candidateSources },
        { onProgress, timeoutMs: 120000 },
      );
      response = await askWorker(
        worker,
        { action: "execute", sparql: CATALOG_QUERY, sources: candidateSources },
        { timeoutMs: 120000 },
      );
      appState.sources = candidateSources;
      break;
    } catch (error) {
      lastError = error;
    }
  }

  if (!response || !appState.sources?.length) {
    throw lastError ?? new Error("No mechanics dataset could be loaded.");
  }

  appState.catalog = response.result.bindings.map(toCatalogEntry).sort((a, b) => {
    if (a.dexNumber !== b.dexNumber) return a.dexNumber - b.dexNumber;
    return a.speciesName.localeCompare(b.speciesName);
  });

  if (status) status.textContent = "Graph ready";
  if (badge) badge.textContent = "Live SPARQL";
}

function filteredCatalog(catalog, search) {
  const needle = search.trim().toLowerCase();
  if (!needle) return catalog;
  return catalog.filter((entry) =>
    entry.speciesName.toLowerCase().includes(needle) ||
    String(entry.dexNumber).includes(needle),
  );
}

function updateCounts(entries, catalogLength) {
  const total = document.querySelector("[data-pokedex-count]");
  const visible = document.querySelector("[data-pokedex-visible]");
  if (total) total.textContent = String(catalogLength);
  if (visible) visible.textContent = String(entries.length);
}

async function loadDetail(worker, entry) {
  const sourceList = entry.sources || null;
  if (!sourceList?.length) {
    throw new Error("No active mechanics sources are available.");
  }
  const [types, moves, rulesets, abilities, stats] = await Promise.all([
    askWorker(worker, { action: "execute", sparql: buildPokemonQuery(TYPE_QUERY, entry.speciesIri), sources: sourceList }, { timeoutMs: 20000 }),
    askWorker(worker, { action: "execute", sparql: buildPokemonQuery(MOVES_QUERY, entry.speciesIri), sources: sourceList }, { timeoutMs: 20000 }),
    askWorker(worker, { action: "execute", sparql: buildPokemonQuery(RULESET_QUERY, entry.speciesIri), sources: sourceList }, { timeoutMs: 20000 }),
    askWorker(worker, { action: "execute", sparql: buildPokemonQuery(ABILITY_QUERY, entry.speciesIri), sources: sourceList }, { timeoutMs: 20000 }),
    askWorker(worker, { action: "execute", sparql: buildPokemonQuery(STATS_QUERY, entry.speciesIri), sources: sourceList }, { timeoutMs: 20000 }),
  ]);

  return {
    types: toPlainRows(types.result),
    moves: toPlainRows(moves.result),
    rulesets: toPlainRows(rulesets.result),
    abilities: toPlainRows(abilities.result),
    stats: toPlainRows(stats.result).sort((a, b) => a.statName.localeCompare(b.statName)),
  };
}

function bindCatalogInteractions(appState) {
  const search = document.getElementById("pokedex-search");
  const results = document.getElementById("pokedex-results");

  search?.addEventListener("input", () => {
    appState.search = search.value;
    const nextEntries = filteredCatalog(appState.catalog, appState.search);
    updateCounts(nextEntries, appState.catalog.length);
    if (!nextEntries.some((entry) => entry.slug === appState.selectedSlug)) {
      appState.selectedSlug = nextEntries[0]?.slug || "";
      if (appState.selectedSlug) {
        void selectEntry(appState, appState.selectedSlug);
      } else {
        renderCatalog([], "");
        renderDetailPlaceholder("No Pokemon matched this search.");
      }
      return;
    }
    renderCatalog(nextEntries, appState.selectedSlug);
  });

  results?.addEventListener("click", (event) => {
    const button = event.target instanceof Element ? event.target.closest("[data-pokemon-slug]") : null;
    const slug = button?.getAttribute("data-pokemon-slug");
    if (!slug) return;
    void selectEntry(appState, slug);
  });
}

async function selectEntry(appState, slug) {
  const entry = appState.catalog.find((item) => item.slug === slug);
  if (!entry) return;
  appState.selectedSlug = slug;
  renderCatalog(filteredCatalog(appState.catalog, appState.search), appState.selectedSlug);
  renderDetailLoading(entry);
  const detail = await loadDetail(appState.worker, { ...entry, sources: appState.sources });
  if (appState.selectedSlug !== slug) return;
  renderDetail(entry, detail);
}

export async function createPokedexApp() {
  if (!document.getElementById("pokedex-results")) return;

  setupThemeToggle();
  setupMobileNav();
  const appState = {
    catalog: [],
    search: "",
    selectedSlug: "",
    siteData: null,
    sources: [],
    worker: new Worker("./workers/query-worker.js", { type: "module" }),
  };

  try {
    const siteData = await loadSiteData();
    appState.siteData = siteData;
    const repoLink = document.querySelector("[data-repository-url]");
    if (repoLink) repoLink.href = siteData.site?.repository_url || repoLink.href;
    const mechanicsNotice = document.querySelector("[data-pokedex-mechanics-artifact]");
    if (mechanicsNotice) mechanicsNotice.textContent = getCanonicalMechanicsLabel(siteData);

    bindCatalogInteractions(appState);
    await fetchCatalog(appState.worker, appState);
    const initialEntries = filteredCatalog(appState.catalog, appState.search);
    appState.selectedSlug = initialEntries[0]?.slug || "";
    updateCounts(initialEntries, appState.catalog.length);
    renderCatalog(initialEntries, appState.selectedSlug);
    if (appState.selectedSlug) {
      await selectEntry(appState, appState.selectedSlug);
    }
  } catch (error) {
    renderError(error.message || String(error));
    throw error;
  }
}
