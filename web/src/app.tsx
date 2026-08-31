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
 * static host (GitHub Pages, Cloudflare Pages, plain python -m http.server)
 * without configuring a rewrite to index.html. M4 will add a real
 * /review/:id path-style URL with a server-side rewrite in CI.
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
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  return (
    <div class="app">
      <TopBar />
      <main>
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
        <span class="muted">All data stays in your browser.</span>
      </footer>
    </div>
  );
}

function navigate(path: string) {
  // Hash navigation: setting hash triggers the hashchange event.
  window.location.hash = path.replace(/^\//, "");
}
