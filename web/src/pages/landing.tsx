import { useState } from "preact/hooks";

interface LandingProps {
  onOpenViewer: () => void;
  onOpenWizard: () => void;
}

/**
 * Landing page. Upload flow + wizard entry point.
 */
export function Landing({ onOpenViewer, onOpenWizard }: LandingProps) {
  const [err, setErr] = useState<string | null>(null);
  const [demoLoading, setDemoLoading] = useState(false);

  // Demo path: fetch the bundled sample config, stage it the same way
  // an upload would, then route to the viewer. BASE_URL makes it work
  // under any deploy base (/mantissa/ on GitHub Pages).
  async function onDemo(e: Event) {
    e.preventDefault();
    if (demoLoading) return;
    setDemoLoading(true);
    setErr(null);
    try {
      const base = (import.meta as { env?: { BASE_URL?: string } }).env?.BASE_URL ?? "/";
      const res = await fetch(`${base.replace(/\/$/, "")}/demo.json`);
      if (!res.ok) throw new Error(`demo fetch failed (${res.status})`);
      const parsed = JSON.parse(await res.text());
      sessionStorage.setItem("mantissa:config", JSON.stringify(parsed));
      onOpenViewer();
    } catch (e) {
      setErr(`Could not load the demo: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setDemoLoading(false);
    }
  }

  async function onFile(file: File) {
    setErr(null);
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      sessionStorage.setItem("mantissa:config", JSON.stringify(parsed));
      onOpenViewer();
    } catch (e) {
      setErr(`Could not parse JSON: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  return (
    <section class="landing">
      <h1>Review a Mantissa plan, in your browser.</h1>
      <p class="lede">
        Drop a <code>.json</code> config exported from <code>mantissa</code> and see a deterministic
        projection, Monte Carlo fan chart, tax breakdown, and warnings. Nothing is uploaded — the
        engine runs in your tab via Pyodide.
      </p>

      <div class="tiles">
        <label class="tile tile--upload">
          <span class="tile-title">Upload a config</span>
          <span class="tile-body">.json file. Parsed and run locally.</span>
          <input
            type="file"
            accept=".json,application/json"
            onChange={(e) => {
              const f = (e.currentTarget as HTMLInputElement).files?.[0];
              if (f) void onFile(f);
            }}
          />
        </label>
        <button type="button" class="tile tile--wizard" onClick={onOpenWizard}>
          <span class="tile-title">Start from scratch</span>
          <span class="tile-body">8-question wizard, then open in the viewer.</span>
        </button>
        <button type="button" class="tile tile--md" disabled>
          <span class="tile-title">View a markdown report</span>
          <span class="tile-body">Read-only rendering. Coming soon.</span>
        </button>
      </div>

      {err && <p class="error">{err}</p>}

      <details>
        <summary>Don't have a config?</summary>
        <p>
          Run <code>mantissa init &gt; my-plan.json</code> from the CLI, edit it, and drop it here.
          See the <a href="https://github.com/jimmyliuzg/mantissa">Mantissa repo</a> for the schema.
          Want to{" "}
          <button type="button" class="linkish" onClick={onDemo} disabled={demoLoading}>
            {demoLoading ? "loading demo…" : "try a viewer demo"}
          </button>
          ?
        </p>
      </details>
    </section>
  );
}
