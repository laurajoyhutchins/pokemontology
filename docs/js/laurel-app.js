import { createState } from "./state.js";
import { createWorkerRpc, readStorage, setupThemeToggle, writeStorage } from "./browser-runtime.js";
import {
  buildSelectedSources,
  renderQueryArtifactLinks,
  renderQuerySourceControls,
} from "./docs-sources.js";
import {
  configureQueryPresentation,
  exportLastResultsToCsv,
  renderGeneratedQuery,
  renderGrounding,
  renderQueryResults,
  toggleResultActions,
  renderValidation,
  setResultsContent,
} from "./query-execution.js";
import { defaultQuestion, formatPrefixBlock, loadSchemaPack } from "./schema-pack.js";
import {
  loadSiteData,
  renderArtifacts,
  renderError,
  renderExamples,
  renderModules,
  renderPipelines,
  renderStats,
} from "./site-render.js";

const POWER_MODE_STORAGE_KEY = "pokemontology-power-mode";
const askWorker = createWorkerRpc("req");

export async function createLaurelApp() {
  const state = createState();
  setupThemeToggle();
  setupPowerToggle();
  setupNavHighlight();
  bindStaticActions(state);

  try {
    state.siteData = await loadSiteData();
    state.schemaPack = await loadSchemaPack();
    configureQueryPresentation(state.schemaPack);
    renderQuerySourceControls(state.siteData);
    renderQueryArtifactLinks(state.siteData);
    renderArtifacts(state.siteData.artifacts || []);
    renderModules(state.siteData.modules || [], state.siteData.site?.repository_url || "");
    renderPipelines(state.siteData.pipelines || []);
    renderExamples(state.siteData.examples || [], state.siteData.site?.repository_url || "");
    renderStats(state.siteData);
    populateExampleSelect(state.siteData.query_examples || []);
    hydrateDefaultValues(state);
    if (document.getElementById("nl-question")) {
      initWorkers(state);
      initQueryRuntime(state);
      setStatus("[data-status-model]", supportsWebGpu() ? "WebGPU ready" : "CPU fallback");
      bindInteractiveActions(state);
    }
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

function resetLaurelPanels({ preserveQuestion = true } = {}) {
  const queryStatus = document.getElementById("qe-status");
  renderGrounding([]);
  renderGeneratedQuery("");
  renderValidation(null);
  setResultsContent(`
    <div class="qe-placeholder">
      <span class="qe-placeholder-icon">▶</span>
      <p>Professor Laurel will summarize the translated query results here.</p>
    </div>
  `);
  toggleResultActions(false);
  if (queryStatus) queryStatus.textContent = "";
  setInlineStatus(preserveQuestion ? "Ready for a new query." : "");
  setStatus("[data-status-grounding]", "Pending");
  setStatus("[data-status-validator]", "Standby");
}

function invalidateLaurelRun(state, { preserveQuestion = true } = {}) {
  const runBtn = document.getElementById("laurel-run-btn");
  state.activeRunId += 1;
  state.lastGrounding = [];
  state.currentQuestion = preserveQuestion
    ? document.getElementById("nl-question")?.value.trim() || ""
    : "";
  if (runBtn) runBtn.disabled = false;
  resetLaurelPanels({ preserveQuestion });
}

function stableStringify(value) {
  return JSON.stringify(value, Object.keys(value).sort());
}

function matchesKey(matches) {
  return JSON.stringify(
    (matches || []).map((match) => ({
      label: match.label,
      kind: match.kind,
      iri: match.iri,
      score: Number(match.score || 0).toFixed(4),
    })),
  );
}

function applyPowerMode(mode) {
  const body = document.body;
  const toggle = document.querySelector("[data-power-toggle]");
  const label = document.querySelector("[data-power-label]");
  body.dataset.powerMode = mode;
  if (toggle) toggle.setAttribute("aria-pressed", String(mode === "on"));
  if (label) label.textContent = `Technical: ${mode === "on" ? "On" : "Off"}`;
}

function resolvedInitialPowerMode() {
  return readStorage(POWER_MODE_STORAGE_KEY) === "on" ? "on" : "off";
}

function setupPowerToggle() {
  applyPowerMode(resolvedInitialPowerMode());
  const toggle = document.querySelector("[data-power-toggle]");
  if (!toggle) return;
  toggle.addEventListener("click", () => {
    const next = document.body.dataset.powerMode === "on" ? "off" : "on";
    writeStorage(POWER_MODE_STORAGE_KEY, next);
    applyPowerMode(next);
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
  const seededQuestion = defaultQuestion(state.schemaPack);
  state.defaultQuestionText = seededQuestion;
  state.defaultQuestionPending = true;
  if (question) question.value = seededQuestion;
  if (editor) editor.value = formatPrefixBlock(state.schemaPack);
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

  document.getElementById("clear-results-btn")?.addEventListener("click", () => {
    setResultsContent(`
      <div class="qe-placeholder">
        <span class="qe-placeholder-icon">▶</span>
        <p>Professor Laurel will summarize the translated query results here.</p>
      </div>
    `);
    toggleResultActions(false);
  });

  document.getElementById("copy-sparql-btn")?.addEventListener("click", async () => {
    const preview = document.getElementById("generated-query-preview");
    if (!preview?.textContent) return;
    if (preview.textContent === "No SPARQL generated yet.") return;
    await navigator.clipboard.writeText(preview.textContent);
  });

  document.getElementById("sample-question-btn")?.addEventListener("click", () => {
    const question = document.getElementById("nl-question");
    if (!question) return;
    question.value = state.defaultQuestionText || defaultQuestion(state.schemaPack);
    state.defaultQuestionPending = true;
    invalidateLaurelRun(state);
    question.focus();
  });
}

function bindInteractiveActions(state) {
  const question = document.getElementById("nl-question");
  const runButton = document.getElementById("run-btn");
  const exampleSelect = document.getElementById("example-select");
  const editor = document.getElementById("sparql-editor");

  document.getElementById("laurel-run-btn")?.addEventListener("click", async () => {
    await runLaurelPipeline(state);
  });

  question?.addEventListener("beforeinput", (event) => {
    if (!state.defaultQuestionPending) return;
    if (question.value !== state.defaultQuestionText) {
      state.defaultQuestionPending = false;
      return;
    }
    if (!event.inputType || event.inputType.startsWith("history")) return;
    question.value = "";
    question.selectionStart = 0;
    question.selectionEnd = 0;
    state.defaultQuestionPending = false;
  });

  question?.addEventListener("input", () => {
    const nextQuestion = question.value.trim();
    if (nextQuestion === state.currentQuestion) return;
    invalidateLaurelRun(state);
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
    await executeEditorQuery(state);
  });
}

function initWorkers(state) {
  state.retrievalWorker = new Worker("./workers/retrieval-worker.js", { type: "module" });
  state.llmWorker = new Worker("./workers/llm-worker.js", { type: "module" });
  state.queryWorker = new Worker("./workers/query-worker.js", { type: "module" });
}

function sourcesKey(sources) {
  return JSON.stringify([...sources].sort());
}

function ensureQueryGraphReady(state, sources, { background = false } = {}) {
  const key = sourcesKey(sources);
  if (!sources.length || state.warmedSourcesKey === key) {
    return Promise.resolve();
  }
  if (state.queryWarmupPromise?.key === key) {
    return state.queryWarmupPromise.promise;
  }

  const promise = askWorker(
    state.queryWorker,
    { action: "warmup", sources },
    {
      timeoutMs: 120000,
      onProgress: (progress) => {
        if (progress.message) setInlineStatus(progress.message);
      },
    },
  )
    .then(() => {
      state.warmedSourcesKey = key;
    })
    .finally(() => {
      if (state.queryWarmupPromise?.key === key) {
        state.queryWarmupPromise = null;
      }
    });

  state.queryWarmupPromise = { key, promise };
  if (background) {
    promise.catch((error) => {
      const runLabel = document.getElementById("run-btn-label");
      if (runLabel) runLabel.textContent = "Run SPARQL";
      setInlineStatus(`Background graph warmup failed: ${error.message}`);
    });
  }
  return promise;
}

function initQueryRuntime(state) {
  const runButton = document.getElementById("run-btn");
  const runLabel = document.getElementById("run-btn-label");
  if (runButton) runButton.disabled = false;
  if (runLabel) runLabel.textContent = "Run SPARQL";
  const sources = buildSelectedSources(state.siteData);
  if (sources.length) {
    setInlineStatus("Preparing local query graph in the background…");
    ensureQueryGraphReady(state, sources, { background: true }).then(() => {
      if (state.warmedSourcesKey === sourcesKey(sources)) {
        setInlineStatus("Ready for a new query.");
      }
    });
  } else {
    setInlineStatus("Ready for a new query.");
  }
}

async function runLaurelPipeline(state) {
  const runBtn = document.getElementById("laurel-run-btn");
  if (runBtn) runBtn.disabled = true;
  const runId = state.activeRunId + 1;
  state.activeRunId = runId;
  try {
    const question = document.getElementById("nl-question")?.value.trim() || "";
    const editor = document.getElementById("sparql-editor");
    if (!question) return;
    state.currentQuestion = question;
    resetLaurelPanels();
    const sources = buildSelectedSources(state.siteData);
    const schemaVersion = stableStringify({
      inference: state.schemaPack?.inference || {},
      retrieval: state.schemaPack?.retrieval || {},
      validation: state.schemaPack?.validation || {},
    });

    setInlineStatus("Grounding question…");
    setStatus("[data-status-grounding]", "Searching");
    const retrievalKey = `${question}::${schemaVersion}`;
    let retrieval = state.retrievalCache.get(retrievalKey);
    if (!retrieval) {
      retrieval = await askWorker(state.retrievalWorker, {
        question,
        schemaPack: state.schemaPack,
        topK: 4,
      });
      state.retrievalCache.set(retrievalKey, retrieval);
    }
    if (state.activeRunId !== runId) return;
    state.lastGrounding = retrieval.matches || [];
    renderGrounding(state.lastGrounding);
    setStatus("[data-status-grounding]", `${state.lastGrounding.length} notes`);

    setInlineStatus("Generating local translation…");
    const generationKey = `${question}::${matchesKey(state.lastGrounding)}::${schemaVersion}`;
    let generation = state.generationCache.get(generationKey);
    if (!generation) {
      generation = await askWorker(
        state.llmWorker,
        {
          question,
          matches: state.lastGrounding,
          schemaPack: state.schemaPack,
          webgpuAvailable: supportsWebGpu(),
        },
        {
          onProgress: (progress) => {
            if (progress.message) setInlineStatus(progress.message);
            if (progress.backend) setStatus("[data-status-model]", progress.backend);
          },
        },
      );
      state.generationCache.set(generationKey, generation);
    }
    if (state.activeRunId !== runId) return;
    setStatus("[data-status-model]", generation.backend);
    setResultsContent(
      '<div class="laurel-answer"><p class="laurel-answer-kicker">Inference Engine</p><p>Translation complete. Executing generated SPARQL.</p></div>',
    );
    renderGeneratedQuery(generation.sparql);
    if (editor) editor.value = generation.sparql;

    setInlineStatus("Validating query AST…");
    const validationKey = `${generation.sparql}::${schemaVersion}`;
    let validation = state.validationCache.get(validationKey);
    if (!validation) {
      validation = await askWorker(state.queryWorker, {
        action: "validate",
        sparql: generation.sparql,
        schemaPack: state.schemaPack,
      });
      state.validationCache.set(validationKey, validation);
    }
    if (!validation.ok && generation.fallbackSparql && generation.fallbackSparql !== generation.sparql) {
      setInlineStatus("Primary translation failed validation. Trying Laurel fallback…");
      renderGeneratedQuery(generation.fallbackSparql);
      if (editor) editor.value = generation.fallbackSparql;
      const fallbackValidationKey = `${generation.fallbackSparql}::${schemaVersion}`;
      let fallbackValidation = state.validationCache.get(fallbackValidationKey);
      if (!fallbackValidation) {
        fallbackValidation = await askWorker(state.queryWorker, {
          action: "validate",
          sparql: generation.fallbackSparql,
          schemaPack: state.schemaPack,
        });
        state.validationCache.set(fallbackValidationKey, fallbackValidation);
      }
      if (state.activeRunId !== runId) return;
      if (fallbackValidation.ok) {
        validation = {
          ...fallbackValidation,
          messages: [
            "Primary browser-local translation failed validation; Laurel fell back to a bundled safe query.",
            ...fallbackValidation.messages,
          ],
        };
      }
    }
    if (state.activeRunId !== runId) return;
    renderValidation(validation);
    setStatus("[data-status-validator]", validation.ok ? "Validated" : "Needs repair");
    if (!validation.ok) {
      setInlineStatus("Validation failed.");
      return;
    }

    setInlineStatus("Running SPARQL…");
    await executeEditorQuery(state, sources, runId);
  } finally {
    if (runBtn && state.activeRunId === runId) runBtn.disabled = false;
  }
}

async function executeEditorQuery(state, sources = buildSources(), runId = state.activeRunId) {
  const editor = document.getElementById("sparql-editor");
  const status = document.getElementById("qe-status");
  const question = document.getElementById("nl-question")?.value.trim() || "";
  if (!editor) return;
  if (!editor.value.trim()) return;
  if (!sources.length) {
    setResultsContent('<div class="qe-error">Select at least one source.</div>');
    return;
  }

  setResultsContent('<div class="qe-loading"><span class="qe-spinner"></span> Querying…</div>');
  const started = performance.now();
  try {
    await ensureQueryGraphReady(state, sources);
    const executionKey = `${editor.value}::${JSON.stringify(sources)}`;
    let result = state.executionCache.get(executionKey);
    if (!result) {
      result = (
        await askWorker(
          state.queryWorker,
          {
            action: "execute",
            sparql: editor.value,
            sources,
          },
          {
            timeoutMs: 120000,
            onProgress: (progress) => {
              if (progress.message) setInlineStatus(progress.message);
            },
          },
        )
      ).result;
      state.executionCache.set(executionKey, result);
    }
    if (state.activeRunId !== runId) return;
    renderQueryResults(result, question);
    if (status) status.textContent = `${Math.round(performance.now() - started)}ms`;
    setInlineStatus("Field query complete.");
  } catch (error) {
    if (state.activeRunId !== runId) return;
    setResultsContent(`<div class="qe-error"><strong>Error:</strong> ${error.message}</div>`);
    if (status) status.textContent = "";
    setInlineStatus("Execution failed.");
  }
}
