const THEME_STORAGE_KEY = "pokemontology-theme";

export function readStorage(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStorage(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Storage can be unavailable in privacy-restricted contexts.
  }
}

export function resolvedInitialTheme() {
  const stored = readStorage(THEME_STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(theme) {
  const root = document.documentElement;
  const toggle = document.querySelector("[data-theme-toggle]");
  const label = document.querySelector("[data-theme-label]");
  root.dataset.theme = theme;
  if (toggle) toggle.setAttribute("aria-pressed", String(theme === "dark"));
  if (toggle) toggle.setAttribute("aria-label", `Current theme: ${theme}`);
  if (label) label.textContent = theme === "dark" ? "Dark" : "Light";
}

export function setupThemeToggle() {
  applyTheme(resolvedInitialTheme());
  const toggle = document.querySelector("[data-theme-toggle]");
  if (!toggle) return;
  toggle.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    writeStorage(THEME_STORAGE_KEY, next);
    applyTheme(next);
  });
}

export function setupMobileNav() {
  const toggle = document.querySelector("[data-nav-toggle]");
  const header = document.querySelector(".site-header");
  if (!toggle || !header) return;
  toggle.addEventListener("click", () => {
    const isOpen = header.classList.toggle("nav-open");
    toggle.setAttribute("aria-expanded", String(isOpen));
    toggle.setAttribute("aria-label", isOpen ? "Close navigation" : "Open navigation");
  });
  document.querySelectorAll(".nav-links a").forEach((link) => {
    link.addEventListener("click", () => {
      header.classList.remove("nav-open");
      toggle.setAttribute("aria-expanded", "false");
      toggle.setAttribute("aria-label", "Open navigation");
    });
  });
}

export function createWorkerRpc(requestPrefix = "req") {
  let nextWorkerRequestId = 0;

  return async function askWorker(worker, payload, { onProgress, timeoutMs = 10000 } = {}) {
    if (!worker.__pendingRequests) {
      worker.__pendingRequests = new Map();
      worker.onmessage = (event) => {
        const requestId = event.data?.requestId;
        if (!requestId) return;
        const pending = worker.__pendingRequests.get(requestId);
        if (!pending) return;
        if (event.data?.type === "progress") {
          pending.onProgress?.(event.data);
          return;
        }
        if (event.data?.error) {
          window.clearTimeout(pending.timeout);
          worker.__pendingRequests.delete(requestId);
          pending.reject(new Error(event.data.error));
          return;
        }
        window.clearTimeout(pending.timeout);
        worker.__pendingRequests.delete(requestId);
        pending.resolve(event.data);
      };
      worker.onerror = (event) => {
        const error = event.error || new Error("Worker failed.");
        worker.__pendingRequests.forEach((pending) => {
          window.clearTimeout(pending.timeout);
          pending.reject(error);
        });
        worker.__pendingRequests.clear();
      };
    }

    const requestId = `${requestPrefix}-${++nextWorkerRequestId}`;
    return new Promise((resolve, reject) => {
      const timeout = window.setTimeout(() => {
        worker.__pendingRequests.delete(requestId);
        reject(new Error("Worker response timed out."));
      }, timeoutMs);
      worker.__pendingRequests.set(requestId, {
        resolve,
        reject,
        onProgress,
        timeout,
      });
      worker.postMessage({
        ...payload,
        requestId,
      });
    });
  };
}
