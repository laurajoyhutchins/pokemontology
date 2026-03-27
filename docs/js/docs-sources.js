const DEFAULT_ARTIFACTS = {
  ontology: {
    label: "ontology.ttl",
    path: "ontology.ttl",
  },
  shapes: {
    label: "shapes.ttl",
    path: "shapes.ttl",
  },
  mechanics: {
    label: "mechanics.ttl",
    preferred_paths: ["mechanics.ttl", "pokeapi.ttl"],
  },
  debug: {
    label: "pokeapi-demo.ttl (debug)",
    path: "pokeapi-demo.ttl",
  },
};

function artifactByPreferredPath(siteData, preferredPaths, fallback) {
  const artifacts = siteData?.artifacts || [];
  for (const path of preferredPaths) {
    const match = artifacts.find((artifact) => artifact.path === path);
    if (match) return match;
  }
  return fallback;
}

export function getOntologyArtifact(siteData) {
  return artifactByPreferredPath(siteData, ["ontology.ttl"], DEFAULT_ARTIFACTS.ontology);
}

export function getShapesArtifact(siteData) {
  return artifactByPreferredPath(siteData, ["shapes.ttl"], DEFAULT_ARTIFACTS.shapes);
}

export function getCanonicalMechanicsArtifact(siteData) {
  return artifactByPreferredPath(
    siteData,
    DEFAULT_ARTIFACTS.mechanics.preferred_paths,
    { ...DEFAULT_ARTIFACTS.mechanics, path: DEFAULT_ARTIFACTS.mechanics.preferred_paths[0] },
  );
}

export function getDebugMechanicsArtifact() {
  return DEFAULT_ARTIFACTS.debug;
}

export function getQuerySourceDefinitions(siteData) {
  return [
    {
      id: "src-ontology",
      path: getOntologyArtifact(siteData).path,
      label: getOntologyArtifact(siteData).path,
      checked: true,
    },
    {
      id: "src-mechanics",
      path: getCanonicalMechanicsArtifact(siteData).path,
      label: getCanonicalMechanicsArtifact(siteData).path,
      checked: true,
    },
    {
      id: "src-pokeapi-demo",
      path: getDebugMechanicsArtifact().path,
      label: getDebugMechanicsArtifact().label,
      checked: false,
    },
    {
      id: "src-shapes",
      path: getShapesArtifact(siteData).path,
      label: getShapesArtifact(siteData).path,
      checked: false,
    },
  ];
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
  const artifacts = [
    getOntologyArtifact(siteData),
    getCanonicalMechanicsArtifact(siteData),
    getDebugMechanicsArtifact(),
    getShapesArtifact(siteData),
  ];
  target.innerHTML = artifacts
    .map(
      (artifact) => `<a class="button button-secondary" href="./${artifact.path}">${artifact.path}</a>`,
    )
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
    .map((source) => new URL(`./${source.path}`, baseUrl).href);
}

export function mechanicsSourceCandidates(siteData, { baseUrl } = {}) {
  const rootBase = baseUrl || window.location.href;
  const ontology = new URL(`./${getOntologyArtifact(siteData).path}`, rootBase).href;
  const canonical = getCanonicalMechanicsArtifact(siteData).path;
  const candidates = [[ontology, new URL(`./${canonical}`, rootBase).href]];
  if (canonical !== "pokeapi.ttl") {
    candidates.push([ontology, new URL("./pokeapi.ttl", rootBase).href]);
  }
  return candidates;
}
