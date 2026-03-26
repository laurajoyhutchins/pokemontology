export async function loadSiteData() {
  const response = await fetch("./site-data.json", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load site-data.json: ${response.status}`);
  }
  return response.json();
}

export function renderArtifacts(artifacts) {
  const target = document.querySelector("[data-artifacts]");
  if (!target) return;
  target.innerHTML = artifacts
    .map(
      (a) => `
        <article class="artifact-card fade-up delay-1">
          <h3>${a.label}</h3>
          <p>${a.description}</p>
          <div class="artifact-meta">
            <div><strong>IRI</strong> <code>${a.iri}</code></div>
            <div><a href="./${a.path}">Open ${a.path}</a></div>
          </div>
        </article>`,
    )
    .join("");
}

export function renderModules(modules, repositoryUrl) {
  const target = document.querySelector("[data-modules]");
  const count = document.querySelector("[data-module-count]");
  if (!target) return;
  if (count) count.textContent = String(modules.length);
  target.innerHTML = modules
    .map(
      (m, i) => `
        <article class="module-card fade-up delay-${(i % 3) + 1}">
          <h3>${m.name.replace(/^[0-9]+-/, "").replace(/-/g, " ")}</h3>
          <code>${m.source_path}</code>
          ${repositoryUrl ? `<div style="margin-top:0.5rem"><a class="example-link" href="${repositoryUrl}/blob/main/${m.source_path}" target="_blank" rel="noopener">View source →</a></div>` : ""}
        </article>`,
    )
    .join("");
}

export function renderPipelines(pipelines) {
  const target = document.querySelector("[data-pipelines]");
  if (!target) return;
  target.innerHTML = pipelines
    .map(
      (p, i) => `
        <article class="pipeline-card fade-up delay-${(i % 3) + 1}">
          <h3>${p.name}</h3>
          <p>${p.summary}</p>
          <pre><code>${p.command}</code></pre>
        </article>`,
    )
    .join("");
}

export function renderExamples(examples, repositoryUrl) {
  const target = document.querySelector("[data-examples]");
  if (!target) return;
  target.innerHTML = examples
    .map(
      (e, i) => `
        <article class="example-card fade-up delay-${(i % 3) + 1}">
          <span class="example-kind">${e.kind}</span>
          <h3>${e.name}</h3>
          <p>${e.summary}</p>
          <div class="example-path"><code>${e.path}</code></div>
          ${repositoryUrl ? `<a class="example-link" href="${repositoryUrl}/blob/main/${e.path}" target="_blank" rel="noopener">View on GitHub →</a>` : ""}
        </article>`,
    )
    .join("");
}

export function renderStats(data) {
  const repoLink = document.querySelector("[data-repository-url]");
  const pagesBase = document.querySelector("[data-pages-base-url]");
  if (repoLink) repoLink.href = data.site.repository_url;
  if (pagesBase) pagesBase.textContent = data.site.pages_base_url;
}

export function renderError(error) {
  const fallback = document.querySelector("[data-site-error]");
  if (!fallback) return;
  fallback.hidden = false;
  fallback.textContent = `Site metadata unavailable: ${error.message}`;
}
