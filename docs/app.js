async function loadSiteData() {
  const response = await fetch("./site-data.json", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load site-data.json: ${response.status}`);
  }
  return response.json();
}

function renderArtifacts(artifacts) {
  const target = document.querySelector("[data-artifacts]");
  if (!target) return;
  target.innerHTML = artifacts
    .map(
      (artifact) => `
        <article class="artifact-card fade-up delay-1">
          <h3>${artifact.label}</h3>
          <p>${artifact.description}</p>
          <div class="artifact-meta">
            <div><strong>IRI</strong> <code>${artifact.iri}</code></div>
            <div><a href="./${artifact.path}">Open ${artifact.path}</a></div>
          </div>
        </article>
      `,
    )
    .join("");
}

function renderModules(modules) {
  const target = document.querySelector("[data-modules]");
  const count = document.querySelector("[data-module-count]");
  if (!target || !count) return;
  count.textContent = String(modules.length);
  target.innerHTML = modules
    .map(
      (module, index) => `
        <article class="module-card fade-up delay-${(index % 3) + 1}">
          <h3>${module.name.replace(/^[0-9]+-/, "").replace(/-/g, " ")}</h3>
          <p>Source module in the authoring graph.</p>
          <code>${module.source_path}</code>
        </article>
      `,
    )
    .join("");
}

function renderPipelines(pipelines) {
  const target = document.querySelector("[data-pipelines]");
  if (!target) return;
  target.innerHTML = pipelines
    .map(
      (pipeline, index) => `
        <article class="pipeline-card fade-up delay-${(index % 3) + 1}">
          <h3>${pipeline.name}</h3>
          <p>${pipeline.summary}</p>
          <pre><code>${pipeline.command}</code></pre>
        </article>
      `,
    )
    .join("");
}

function renderStats(data) {
  const artifactCount = document.querySelector("[data-artifact-count]");
  const pipelineCount = document.querySelector("[data-pipeline-count]");
  const repoLink = document.querySelector("[data-repository-url]");
  const pagesBase = document.querySelector("[data-pages-base-url]");

  if (artifactCount) artifactCount.textContent = String(data.artifacts.length);
  if (pipelineCount) pipelineCount.textContent = String(data.pipelines.length);
  if (repoLink) repoLink.href = data.site.repository_url;
  if (pagesBase) pagesBase.textContent = data.site.pages_base_url;
}

function renderError(error) {
  const fallback = document.querySelector("[data-site-error]");
  if (!fallback) return;
  fallback.hidden = false;
  fallback.textContent = `Site metadata unavailable: ${error.message}`;
}

async function main() {
  try {
    const data = await loadSiteData();
    renderArtifacts(data.artifacts);
    renderModules(data.modules);
    renderPipelines(data.pipelines);
    renderStats(data);
  } catch (error) {
    renderError(error);
  }
}

main();
