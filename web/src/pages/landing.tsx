import { useState } from "preact/hooks";
import { validateConfig } from "../lib/config-validation";

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
      const parsed = validateConfig(JSON.parse(await res.text()));
      sessionStorage.setItem("mantissa:config", JSON.stringify(parsed));
      sessionStorage.removeItem("mantissa:run-options");
      sessionStorage.removeItem("mantissa:reviewed-config");
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
      if (file.size > 2_000_000) throw new Error("Plan files must be smaller than 2 MB.");
      const text = await file.text();
      const parsed = validateConfig(JSON.parse(text));
      sessionStorage.setItem("mantissa:config", JSON.stringify(parsed));
      sessionStorage.removeItem("mantissa:run-options");
      sessionStorage.removeItem("mantissa:reviewed-config");
      onOpenViewer();
    } catch (e) {
      setErr(`Could not import this plan: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  return (
    <section class="landing">
      <h1>Plan your retirement with a clearer picture.</h1>
      <p class="lede">
        Explore when you can retire, how much you can spend and how your savings may last.
        Start with a few estimates, then add detail at your own pace. Calculations run on your
        device; you choose whether to download or share your plan.
      </p>

      <div class="tiles">
        <button type="button" class="tile tile--wizard" onClick={onOpenWizard}>
          <span class="tile-title">Start a plan</span>
          <span class="tile-body">A short guided setup. Add details after your first estimate.</span>
        </button>
        <button type="button" class="tile" onClick={onDemo} disabled={demoLoading}>
          <span class="tile-title">{demoLoading ? "Loading sample…" : "Explore a sample plan"}</span>
          <span class="tile-body">See how results work using fictional household information.</span>
        </button>
        <label class="tile tile--upload">
          <span class="tile-title">Import an existing plan</span>
          <span class="tile-body">Choose a Mantissa .json file. Processed on your device.</span>
          <input aria-label="Import an existing plan" type="file" accept=".json,application/json" onChange={(e) => {
            const f = e.currentTarget.files?.[0];
            if (f) void onFile(f);
          }} />
        </label>
      </div>

      {err && <p class="error" role="alert">{err}</p>}

      <details>
        <summary>Using the command line or an existing plan?</summary>
        <p>Run <code>mantissa init</code> to create a starter plan, or import a config you already use.
          See the <a href="https://github.com/jimmyliuzg/mantissa">Mantissa documentation</a> for the configuration format.</p>
      </details>
    </section>
  );
}
