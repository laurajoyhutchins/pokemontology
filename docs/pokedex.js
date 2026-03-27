import { createPokedexApp } from "./js/pokedex-app.js";

createPokedexApp().catch((error) => {
  console.error("Pokedex page failed to boot:", error);
});
