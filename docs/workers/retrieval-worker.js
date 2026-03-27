self.onmessage = (event) => {
  const { question, schemaPack, topK = 4, requestId } = event.data;
  const items = schemaPack?.items || [];
  const retrievalConfig = schemaPack?.retrieval || {};
  const minScore = minimumScore(question || "", retrievalConfig.minimum_scores || []);
  const effectiveTopK = retrievalConfig.top_k || topK;
  const sparseIndex = schemaPack?.sparse_index || {};
  const itemNorms = schemaPack?.item_norms || [];
  const queryCounts = tokenCounts(question || "");
  const queryNorm = Math.sqrt(
    [...queryCounts.values()].reduce((sum, value) => sum + (value * value), 0),
  );
  const rawScores = new Map();

  if (queryNorm) {
    queryCounts.forEach((queryWeight, token) => {
      const postings = sparseIndex[token] || [];
      postings.forEach(([itemIndex, itemWeight]) => {
        rawScores.set(
          itemIndex,
          (rawScores.get(itemIndex) || 0) + (queryWeight * itemWeight),
        );
      });
    });
  }

  const matches = [...rawScores.entries()]
    .map(([itemIndex, dot]) => {
      const itemNorm = itemNorms[itemIndex] || 0;
      const score = itemNorm && queryNorm ? dot / (queryNorm * itemNorm) : 0;
      return {
        ...items[itemIndex],
        score,
      };
    })
    .filter((item) => item.score >= minScore)
    .sort((a, b) => b.score - a.score)
    .slice(0, effectiveTopK);

  self.postMessage({ requestId, matches });
};

function tokenize(text) {
  return String(text)
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
}

function tokenCounts(text) {
  const tokens = tokenize(text);
  const counts = new Map();
  tokens.forEach((token) => counts.set(token, (counts.get(token) || 0) + 1));
  return counts;
}

function minimumScore(question, scoreRules) {
  const tokenCount = tokenize(question).length;
  for (const rule of scoreRules) {
    if (rule.max_tokens === null || tokenCount <= rule.max_tokens) {
      return rule.score;
    }
  }
  return 0.16;
}
