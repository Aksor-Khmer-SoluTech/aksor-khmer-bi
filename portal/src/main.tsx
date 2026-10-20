import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import RecentErrorsDialog from "./components/RecentErrorsDialog";
import Toaster from "./components/Toaster";
import { failureInfo, reportError } from "./notify";
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

// The net under every async handler that doesn't catch its own failure (a Delete button whose request answered
// 500, a background reload): say what went wrong on screen instead of only in the console and network tab.
window.addEventListener("unhandledrejection", (event) => {
  reportError(event.reason);
});
// A script error nobody caught is kept for Account menu -> Recent errors (not toasted: the browser's own benign
// ones, like a ResizeObserver loop, would be noise).
window.addEventListener("error", (event) => {
  if (!event.error || /ResizeObserver/.test(event.message)) return;
  failureInfo(event.error);
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
    <Toaster />
    <RecentErrorsDialog />
  </StrictMode>
);
