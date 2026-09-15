import { useEffect, useState } from "preact/hooks";
import type { EngineState } from "../state/plan-store";

/**
 * Indeterminate progress UI for engine work.
 *
 * The Pyodide `engine.run()` call is atomic — Python gives no per-sim
 * callbacks — so real percentages aren't available. This renders a
 * thin top bar + staged status text + elapsed timer instead of a fake
 * % that would lie. `aria-live` keeps screen readers posted.
 */
export function RunProgress({ state, sims }: { state: EngineState; sims: number }) {
  if (state.kind !== "loading" && state.kind !== "running") return null;
  return (
    <div class="run-progress" role="status" aria-live="polite">
      <div class="run-progress-bar" aria-hidden="true">
        <span />
      </div>
      <div class="run-progress-body">
        <span class="spinner" aria-hidden="true" />
        <div>
          <strong>{labelForState(state.kind)}</strong>
          <p class="muted small">
            {state.kind === "loading"
              ? "First visit loads Pyodide + mantissa (~10 s). Subsequent runs reuse it."
              : `${sims.toLocaleString()} market simulations · all data stays in your browser.`}{" "}
            <Elapsed />
          </p>
        </div>
      </div>
    </div>
  );
}

/** Compact badge for the viewer header — keeps prior results readable. */
export function RunBadge({ state }: { state: EngineState }) {
  if (state.kind === "running" || state.kind === "loading") {
    return (
      <span class="run-badge run-badge--busy" role="status" aria-live="polite">
        <span class="spinner spinner--small" aria-hidden="true" />
        {state.kind === "loading" ? "loading engine…" : "running…"}
      </span>
    );
  }
  if (state.kind === "ready") return <span class="run-badge run-badge--ready">ready</span>;
  if (state.kind === "error") return <span class="run-badge run-badge--error">error</span>;
  return <span class="run-badge">idle</span>;
}

export function labelForState(kind: "loading" | "running"): string {
  return kind === "loading" ? "Loading engine…" : "Running projection + Monte Carlo…";
}

function Elapsed() {
  const [s, setS] = useState(0);
  useEffect(() => {
    const t0 = performance.now();
    const t = setInterval(() => setS((performance.now() - t0) / 1000), 200);
    return () => clearInterval(t);
  }, []);
  return <span class="mono">· {s.toFixed(1)} s</span>;
}
