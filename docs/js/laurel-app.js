import { createState } from "./state.js";
import {
  DEFAULT_PREFIXES,
  buildSources,
  executeQuery,
  exportLastResultsToCsv,
  loadComunicaEngine,
  renderGeneratedQuery,
  renderGrounding,
  renderFindingsSummary,
  renderQueryResults,
  renderValidation,
  setResultsContent,
} from "./query-execution.js";
import { defaultQuestion, loadSchemaPack } from "./schema-pack.js";
import {
  loadSiteData,
  renderArtifacts,
  renderError,
  renderExamples,
  renderModules,
  renderPipelines,
  renderStats,
} from "./site-render.js";

const THEME_STORAGE_KEY = "pokemontology-theme";

export async function createLaurelApp() {
  const state = createState();
  setupThemeToggle();
  setupNavHighlight();
  bindStaticActions(state);

  try {
    state.siteData = await loadSiteData();
    state.schemaPack = await loadSchemaPack();
    renderArtifacts(state.siteData.artifacts || []);
    renderModules(state.siteData.modules || [], state.siteData.site?.repository_url || "");
    renderPipelines(state.siteData.pipelines || []);
    renderExamples(state.siteData.examples || [], state.siteData.site?.repository_url || "");
    renderStats(state.siteData);
    populateExampleSelect(state.siteData.query_examples || []);
    hydrateDefaultValues(state);
    initWorkers(state);
    await initQueryEngine();
    setStatus("[data-status-model]", supportsWebGpu() ? "WebGPU ready" : "CPU fallback");
    bindInteractiveActions(state);
  } catch (error) {
    renderError(error);
    throw error;
  }
}

function supportsWebGpu() {
  return Boolean(navigator.gpu);
}

function setStatus(selector, value) {
  const target = document.querySelector(selector);
  if (target) target.textContent = value;
}

function setInlineStatus(message) {
  const target = document.getElementById("laurel-status");
  if (target) target.textContent = message;
}

function applyTheme(theme) {
  const root = document.documentElement;
  const toggle = document.querySelector("[data-theme-toggle]");
  const label = document.querySelector("[data-theme-label]");
  root.dataset.theme = theme;
  if (toggle) toggle.setAttribute("aria-pressed", String(theme === "dark"));
  if (label) label.textContent = theme === "dark" ? "Light" : "Dark";
}

function resolvedInitialTheme() {
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function setupThemeToggle() {
  applyTheme(resolvedInitialTheme());
  const toggle = document.querySelector("[data-theme-toggle]");
  if (!toggle) return;
  toggle.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    window.localStorage.setItem(THEME_STORAGE_KEY, next);
    applyTheme(next);
  });
}

function setupNavHighlight() {
  const sections = [...document.querySelectorAll("main section[id]")];
  const navLinks = [...document.querySelectorAll(".nav-links a[href^='#']")];
  if (!sections.length || !navLinks.length) return;
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const id = entry.target.id;
        navLinks.forEach((link) => {
          link.classList.toggle("nav-active", link.getAttribute("href") === `#${id}`);
        });
      });
    },
    { rootMargin: "-20% 0px -65% 0px", threshold: 0 },
  );
  sections.forEach((section) => observer.observe(section));
}

function populateExampleSelect(examples) {
  const select = document.getElementById("example-select");
  if (!select) return;
  select.innerHTML = '<option value="">— pick a query —</option>';
  const groups = [...new Set(examples.map((example) => example.group).filter(Boolean))];
  groups.forEach((group) => {
    const optgroup = document.createElement("optgroup");
    optgroup.label = group;
    examples
      .filter((example) => example.group === group)
      .forEach((example) => {
        const option = document.createElement("option");
        option.value = example.label;
        option.textContent = example.label;
        optgroup.appendChild(option);
      });
    select.appendChild(optgroup);
  });
}

function hydrateDefaultValues(state) {
  const question = document.getElementById("nl-question");
  const editor = document.getElementById("sparql-editor");
  if (question) question.value = defaultQuestion(state.schemaPack);
  if (editor) editor.value = DEFAULT_PREFIXES;
}

function bindStaticActions(state) {
  document.getElementById("toggle-advanced-btn")?.addEventListener("click", () => {
    const details = document.getElementById("advanced-console");
    const button = document.getElementById("toggle-advanced-btn");
    if (!details || !button) return;
    details.open = !details.open;
    button.setAttribute("aria-expanded", String(details.open));
  });

  document.getElementById("export-csv-btn")?.addEventListener("click", () => {
    exportLastResultsToCsv();
  });

  document.getElementById("sample-question-btn")?.addEventListener("click", () => {
    const question = document.getElementById("nl-question");
    if (!question) return;
    question.value = defaultQuestion(state.schemaPack);
    question.focus();
  });
}

function bindInteractiveActions(state) {
  const question = document.getElementById("nl-question");
  const runButton = document.getElementById("run-btn");
  const exampleSelect = document.getElementById("example-select");
  const editor = document.getElementById("sparql-editor");

  document.getElementById("ask-btn")?.addEventListener("click", async () => {
    await runLaurelPipeline(state);
  });

  question?.addEventListener("keydown", async (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      await runLaurelPipeline(state);
    }
  });

  editor?.addEventListener("keydown", (event) => {
    if (event.key === "Tab") {
      event.preventDefault();
      const start = editor.selectionStart;
      const end = editor.selectionEnd;
      editor.value = editor.value.slice(0, start) + "  " + editor.value.slice(end);
      editor.selectionStart = editor.selectionEnd = start + 2;
    }
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      if (!runButton?.disabled) runButton.click();
    }
  });

  exampleSelect?.addEventListener("change", (event) => {
    const value = event.target.value;
    const example = (state.siteData?.query_examples || []).find((item) => item.label === value);
    if (!example || !editor) return;
    editor.value = example.query;
    renderGeneratedQuery(example.query);
  });

  document.getElementById("copy-query-btn")?.addEventListener("click", async () => {
    if (!editor?.value) return;
    await navigator.clipboard.writeText(editor.value);
  });

  document.getElementById("clear-query-btn")?.addEventListener("click", () => {
    if (editor) editor.value = "";
    renderGeneratedQuery("");
    renderValidation(null);
  });

  runButton?.addEventListener("click", async () => {
    await executeEditorQuery();
  });
}

function initWorkers(state) {
  state.retrievalWorker = new Worker("./workers/retrieval-worker.js", { type: "module" });
  state.llmWorker = new Worker("./workers/llm-worker.js", { type: "module" });
  state.queryWorker = new Worker("./workers/query-worker.js", { type: "module" });
}

async function initQueryEngine() {
  const runButton = document.getElementById("run-btn");
  const runLabel = document.getElementById("run-btn-label");
  try {
    await loadComunicaEngine();
    if (runButton) runButton.disabled = false;
    if (runLabel) runLabel.textContent = "Run SPARQL";
  } catch (error) {
    if (runLabel) runLabel.textContent = "Engine failed";
    setResultsContent(`<div class="qe-error">${error.message}</div>`);
  }
}

async function askWorker(worker, payload) {
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      reject(new Error("Worker response timed out."));
    }, 10000);
    worker.onmessage = (event) => {
      window.clearTimeout(timeout);
      resolve(event.data);
    };
    worker.onerror = (event) => {
      window.clearTimeout(timeout);
      reject(event.error || new Error("Worker failed."));
    };
    worker.postMessage(payload);
  });
}

async function runLaurelPipeline(state) {
  const question = document.getElementById("nl-question")?.value.trim() || "";
  const editor = document.getElementById("sparql-editor");
  if (!question) return;

  setInlineStatus("Grounding question…");
  setStatus("[data-status-grounding]", "Searching");
  const retrieval = await askWorker(state.retrievalWorker, {
    question,
    schemaPack: state.schemaPack,
    topK: 4,
  });
  state.lastGrounding = retrieval.matches || [];
  renderGrounding(state.lastGrounding);
  setStatus("[data-status-grounding]", `${state.lastGrounding.length} notes`);

  setInlineStatus("Generating local translation…");
  const generation = await askWorker(state.llmWorker, {
    question,
    matches: state.lastGrounding,
    schemaPack: state.schemaPack,
    webgpuAvailable: supportsWebGpu(),
  });
  setStatus("[data-status-model]", generation.backend);
  renderFindingsSummary(generation.summary);
  renderGeneratedQuery(generation.sparql);
  if (editor) editor.value = generation.sparql;

  setInlineStatus("Validating query AST…");
  const validation = await askWorker(state.queryWorker, {
    sparql: generation.sparql,
    schemaPack: state.schemaPack,
  });
  renderValidation(validation);
  setStatus("[data-status-validator]", validation.ok ? "Validated" : "Needs repair");
  if (!validation.ok) {
    setInlineStatus("Validation failed.");
    return;
  }

  setInlineStatus("Running SPARQL…");
  await executeEditorQuery();
}

async function executeEditorQuery() {
  const editor = document.getElementById("sparql-editor");
  const status = document.getElementById("qe-status");
  const sources = buildSources();
  if (!editor) return;
  if (!editor.value.trim()) return;
  if (!sources.length) {
    setResultsContent('<div class="qe-error">Select at least one source.</div>');
    return;
  }

  setResultsContent('<div class="qe-loading"><span class="qe-spinner"></span> Querying…</div>');
  const started = performance.now();
  try {
    const result = await executeQuery(editor.value, sources);
    renderQueryResults(result);
    if (status) status.textContent = `${Math.round(performance.now() - started)}ms`;
    setInlineStatus("Field query complete.");
  } catch (error) {
    setResultsContent(`<div class="qe-error"><strong>Error:</strong> ${error.message}</div>`);
    if (status) status.textContent = "";
    setInlineStatus("Execution failed.");
  }
}
