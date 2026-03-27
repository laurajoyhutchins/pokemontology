const DEFAULT_ARTIFACTS = {
  ontology: { label: "ontology.ttl", path: "ontology.ttl" },
  shapes: { label: "shapes.ttl", path: "shapes.ttl" },
  mechanicsSlices: [
    "mechanics-base.ttl",
    "mechanics-learnsets-current.ttl",
    "mechanics-learnsets-modern.ttl",
    "mechanics-learnsets-legacy.ttl",
  ],
  debug: { label: "pokeapi-demo.ttl (debug)", path: "pokeapi-demo.ttl" },
};

function artifactByPreferredPath(siteData, preferredPaths, fallback) {
  const artifacts = siteData?.artifacts || [];
  for (const path of preferredPaths) {
    const match = artifacts.find((artifact) => artifact.path === path);
    if (match) return match;
  }
  return fallback;
}

export function getQuerySourceDefinitions(siteData) {
  if (Array.isArray(siteData?.query_sources) && siteData.query_sources.length) {
    return siteData.query_sources.map((source) => ({
      id: source.id,
      label: source.label,
      checked: Boolean(source.checked),
      role: source.role || "data",
      paths: Array.isArray(source.paths) ? source.paths : source.path ? [source.path] : [],
    }));
  }

  return [
    {
      id: "src-ontology",
      label: DEFAULT_ARTIFACTS.ontology.path,
      checked: true,
      role: "ontology",
      paths: [DEFAULT_ARTIFACTS.ontology.path],
    },
    {
      id: "src-mechanics",
      label: "mechanics slices",
      checked: true,
      role: "mechanics",
      paths: DEFAULT_ARTIFACTS.mechanicsSlices,
    },
    {
      id: "src-pokeapi-demo",
      label: DEFAULT_ARTIFACTS.debug.label,
      checked: false,
      role: "debug",
      paths: [DEFAULT_ARTIFACTS.debug.path],
    },
    {
      id: "src-shapes",
      label: DEFAULT_ARTIFACTS.shapes.path,
      checked: false,
      role: "shapes",
      paths: [DEFAULT_ARTIFACTS.shapes.path],
    },
  ];
}

function artifactPathsFromSources(siteData) {
  const sourcePaths = getQuerySourceDefinitions(siteData).flatMap((source) => source.paths || []);
  return [...new Set(sourcePaths)];
}

export function getCanonicalMechanicsLabel(siteData) {
  const mechanics = getQuerySourceDefinitions(siteData).find((source) => source.role === "mechanics");
  return mechanics?.label || "mechanics slices";
}

export function renderQuerySourceControls(siteData) {
  const target = document.querySelector("[data-query-sources]");
  if (!target) return;
  target.innerHTML = getQuerySourceDefinitions(siteData)
    .map(
      (source) => `
        <label class="source-toggle">
          <input type="checkbox" id="${source.id}" ${source.checked ? "checked" : ""}>
          <span>${source.label}</span>
        </label>`,
    )
    .join("");
}

export function renderQueryArtifactLinks(siteData) {
  const target = document.querySelector("[data-query-artifacts]");
  if (!target) return;
  target.innerHTML = artifactPathsFromSources(siteData)
    .map((path) => `<a class="button button-secondary" href="./${path}">${path}</a>`)
    .join("")
    .concat(
      siteData?.site?.repository_url
        ? `<a class="button button-secondary" href="${siteData.site.repository_url}" data-repository-url>Source</a>`
        : "",
    );
}

export function buildSelectedSources(siteData, { documentRef = document, baseUrl = window.location.href } = {}) {
  return getQuerySourceDefinitions(siteData)
    .filter((source) => documentRef.getElementById(source.id)?.checked)
    .flatMap((source) => source.paths.map((path) => new URL(`./${path}`, baseUrl).href));
}

export function mechanicsSourceCandidates(siteData, { baseUrl } = {}) {
  const rootBase = baseUrl || window.location.href;
  const sourceDefs = getQuerySourceDefinitions(siteData);
  const canonical = sourceDefs
    .filter((source) => source.checked && source.role !== "debug" && source.role !== "shapes")
    .flatMap((source) => source.paths)
    .map((path) => new URL(`./${path}`, rootBase).href);
  const fallback = [
    new URL(`./${DEFAULT_ARTIFACTS.ontology.path}`, rootBase).href,
    new URL("./pokeapi.ttl", rootBase).href,
  ];
  return canonical.length ? [canonical, fallback] : [fallback];
}
