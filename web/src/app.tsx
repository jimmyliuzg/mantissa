import { useEffect, useState } from "preact/hooks";
import { TopBar } from "./components/top-bar";
import { Landing } from "./pages/landing";
import { Viewer } from "./pages/viewer";
import { Wizard } from "./pages/wizard";

/**
 * Tiny client-side router. v1 has three routes:
 *   - landing:  /             (no hash, or empty hash)
 *   - viewer:   /#/review     (hash-routed so static hosts without
 *                              SPA fallback still work)
 *   - wizard:   /#/wizard
 *
 * Hash routing was chosen deliberately so the site can deploy to any
 * static host without configuring a rewrite to index.html.
 */
function getRoute(): "landing" | "viewer" | "wizard" {
  const hash = window.location.hash.replace(/^#\/?/, "");
  if (hash.startsWith("review")) return "viewer";
  if (hash.startsWith("wizard")) return "wizard";
  return "landing";
}

export function App() {
  const [route, setRoute] = useState(getRoute());

  useEffect(() => {
    const onHash = () => setRoute(getRoute());
    const skip = document.querySelector<HTMLAnchorElement>(".skip-link");
    const focusMain = (event: Event) => {
      event.preventDefault();
      document.getElementById("main-content")?.focus();
    };
    skip?.addEventListener("click", focusMain);
    window.addEventListener("hashchange", onHash);
    return () => {
      window.removeEventListener("hashchange", onHash);
      skip?.removeEventListener("click", focusMain);
    };
  }, []);

  return (
    <div class="app">
      <TopBar />
      <main id="main-content" tabIndex={-1}>
        {route === "landing" && (
          <Landing
            onOpenViewer={() => navigate("#/review")}
            onOpenWizard={() => navigate("#/wizard")}
          />
        )}
        {route === "viewer" && <Viewer />}
        {route === "wizard" && <Wizard />}
      </main>
      <footer>
        <span>Mantissa · Plan Viewer</span>
        <span class="muted">Calculated on your device. Shared links include plan data.</span>
      </footer>
    </div>
  );
}

function navigate(path: string) {
  // Hash navigation: setting hash triggers the hashchange event.
  window.location.hash = path.replace(/^\//, "");
}
