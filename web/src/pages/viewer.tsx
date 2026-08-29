import { useEffect, useMemo, useState } from "preact/hooks";
import { type RunResult } from "@engine";
import { ConfigDrawer } from "../components/config-drawer";
import { KpiRow } from "../components/kpi-row";
import { CashFlowChart } from "../components/cash-flow-chart";
import { MonteCarloFan } from "../components/monte-carlo-fan";
import { fmtMoney, fmtPct } from "../lib/format";
import { useDebouncedEffect } from "../lib/use-debounced-effect";
import { createPlanStore, type EngineState } from "../state/plan-store";

/**
 * M2 viewer: editable. Loads config from sessionStorage, creates a
 * per-page plan store, debounces re-runs 400 ms after the last edit.
 */
export function Viewer() {
  const initialConfig = useMemo(() => {
    const raw = sessionStorage.getItem("mantissa:config");
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }, []);

  if (!initialConfig) {
    return (
      <section class="viewer">
        <p class="error">No config loaded. Go back and upload a .json file.</p>
        <p>
          <a href="#/">← back to upload</a>
        </p>
      </section>
    );
  }

  return <ViewerBody initialConfig={initialConfig} />;
}

function ViewerBody({ initialConfig }: { initialConfig: unknown }) {
  // Per-page store. Created once.
  const [store] = useState(() => createPlanStore(initialConfig, 1000));
  // Subscribe to the state signal.
  const stateValue = store.state.value;

  // Bootstrap engine on first mount.
  useEffect(() => {
    void store.bootstrap();
  }, [store]);

  // Debounced re-run on config or sims change.
  useDebouncedEffect(
    () => {
      void store.rerun();
    },
    [store.config.value, store.sims.value],
    400,
  );

  return (
    <section class="viewer viewer--editable">
      <header class="viewer-header">
        <div>
          <h2>{(store.config.value as { name?: string } | null)?.name ?? "Mantissa plan"}</h2>
          <p class="muted small">
            {store.sims.value.toLocaleString()} simulations · {runStatusLabel(stateValue)}
          </p>
        </div>
        <DownloadButton config={store.config.value} />
      </header>

      <div class="layout">
        <ConfigDrawer store={store} />
        <div class="results">
          {stateValue.kind === "error" && (
            <p class="error">{stateValue.message}</p>
          )}
          {stateValue.kind === "ready" ? (
            <Ready result={stateValue.result} />
          ) : (
            <p class="muted">Waiting for first run…</p>
          )}
        </div>
      </div>
    </section>
  );
}

function Ready({ result }: { result: RunResult }) {
  return (
    <>
      <KpiRow kpis={result.kpis} />

      <section class="panel">
        <h3>Cash flow</h3>
        <CashFlowChart rows={result.cashFlow} />
        <p class="muted small">
          Income {fmtMoney(result.cashFlow.reduce((s, r) => s + r.income, 0))} · Expenses{" "}
          {fmtMoney(result.cashFlow.reduce((s, r) => s + r.expenses, 0))} · Taxes{" "}
          {fmtMoney(result.cashFlow.reduce((s, r) => s + r.taxes, 0))} · Success rate{" "}
          {fmtPct(result.kpis.successRate)}
        </p>
      </section>

      <section class="panel">
        <h3>Monte Carlo fan</h3>
        <MonteCarloFan
          percentiles={result.mc.percentiles}
          cashFlow={result.cashFlow}
          medianFinal={result.kpis.medianFinalNetWorth}
        />
      </section>

      <details>
        <summary>Raw data ({result.cashFlow.length} rows)</summary>
        <pre class="data">{JSON.stringify(result, null, 2)}</pre>
      </details>
    </>
  );
}

function DownloadButton({ config }: { config: unknown }) {
  return (
    <button
      type="button"
      class="btn"
      onClick={() => {
        const blob = new Blob([JSON.stringify(config, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "plan.json";
        a.click();
        URL.revokeObjectURL(url);
      }}
    >
      Download config
    </button>
  );
}

function runStatusLabel(s: EngineState): string {
  switch (s.kind) {
    case "idle":
      return "idle";
    case "loading":
      return "loading engine…";
    case "running":
      return "running…";
    case "ready":
      return "ready";
    case "error":
      return "error";
  }
}
