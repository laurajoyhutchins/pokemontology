self.onmessage = (event) => {
  const { question, schemaPack, topK = 4 } = event.data;
  const vocabulary = schemaPack?.vocabulary || [];
  const vectors = schemaPack?.vectors || [];
  const items = schemaPack?.items || [];
  const queryVector = vectorize(question || "", vocabulary);
  const minScore = minimumScore(question || "");

  const matches = items
    .map((item, index) => ({
      ...item,
      score: cosine(queryVector, vectors[index] || []),
    }))
    .sort((a, b) => b.score - a.score)
    .slice(0, topK)
    .filter((item) => item.score >= minScore);

  self.postMessage({ matches });
};

function tokenize(text) {
  return String(text)
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
}

function vectorize(text, vocabulary) {
  const tokens = tokenize(text);
  const counts = new Map();
  tokens.forEach((token) => counts.set(token, (counts.get(token) || 0) + 1));
  return vocabulary.map((token) => counts.get(token) || 0);
}

function cosine(left, right) {
  let dot = 0;
  let leftNorm = 0;
  let rightNorm = 0;
  const length = Math.max(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    const l = left[index] || 0;
    const r = right[index] || 0;
    dot += l * r;
    leftNorm += l * l;
    rightNorm += r * r;
  }
  if (!leftNorm || !rightNorm) return 0;
  return dot / (Math.sqrt(leftNorm) * Math.sqrt(rightNorm));
}

function minimumScore(question) {
  const tokenCount = tokenize(question).length;
  if (tokenCount <= 2) return 0.34;
  if (tokenCount <= 5) return 0.24;
  return 0.16;
}
