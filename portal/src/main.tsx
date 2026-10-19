import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles/index.css";
import { keepTooltipsOnScreen } from "./tooltips";

keepTooltipsOnScreen();

// A tab left open across an upgrade still runs the old build, whose page chunks the new image no longer has: opening
// another page then fails to fetch its chunk. Reload once to pick up the new build (the guard stops a reload loop
// if the chunk is missing for another reason).
window.addEventListener("vite:preloadError", (event) => {
  const key = "portal_chunk_reload";
  try {
    if (sessionStorage.getItem(key) === location.pathname + location.hash) return;
    sessionStorage.setItem(key, location.pathname + location.hash);
  } catch {
    return;
  }
  event.preventDefault();
  location.reload();
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
