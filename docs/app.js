import { createLaurelApp } from "./js/laurel-app.js";

createLaurelApp().catch((error) => {
  console.error("Professor Laurel failed to boot:", error);
});
