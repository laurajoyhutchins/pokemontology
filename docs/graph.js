import { createGraphApp } from "./js/graph-app.js";

createGraphApp().catch((error) => {
  console.error("Knowledge graph page failed to boot:", error);
});
