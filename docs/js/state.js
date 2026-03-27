export function createState() {
  return {
    siteData: null,
    schemaPack: null,
    retrievalWorker: null,
    llmWorker: null,
    queryWorker: null,
    generatedQuery: "",
    lastGrounding: [],
    modelStatus: "Checking…",
    groundingStatus: "Pending",
    validatorStatus: "Standby",
    retrievalCache: new Map(),
    generationCache: new Map(),
    validationCache: new Map(),
    executionCache: new Map(),
    queryWarmupPromise: null,
    warmedSourcesKey: "",
    currentQuestion: "",
    activeRunId: 0,
  };
}
