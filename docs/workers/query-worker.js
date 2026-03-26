import { validateQueryAst } from "../js/query-validation.js";

self.onmessage = async (event) => {
  const { sparql, schemaPack } = event.data;
  const validation = await validateQueryAst(sparql, schemaPack);
  self.postMessage(validation);
};
