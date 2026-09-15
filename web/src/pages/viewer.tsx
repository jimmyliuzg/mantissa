import type { RunResult } from "@engine";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { CashFlowChart } from "../components/cash-flow-chart";
import { ConfigDrawer } from "../components/config-drawer";
import { EngineStatus } from "../components/engine-status";
import { KpiRow } from "../components/kpi-row";
import { MonteCarloFan } from "../components/monte-carlo-fan";
import { PlanReview } from "../components/plan-review";
import { RunBadge, RunProgress } from "../components/run-progress";
import { ShareBar } from "../components/share-bar";
import { fmtMoney, fmtPct } from "../lib/format";
import {
  type ShareableSnapshot,
  decodeConfig,
  decodeSnapshot,
  readShareFromLocation,
} from "../lib/share-codec";
import { useDebouncedEffect } from "../lib/use-debounced-effect";
import { createPlanStore } from "../state/plan-store";

/**
 * M4 viewer: editable, shareable. Loads the config from one of three
 * places, in priority order:
 *   1. URL hash: `?d=<config-hash>` or `?s=<snapshot-hash>`
 *   2. sessionStorage: legacy landing-page upload path
 *   3. Nothing: show a "no config" message
 *
 * Snapshot loads render the result immediately without running the
 * engine. Any edit clears the snapshot and re-runs.
 */
export function Viewer() {
  const initial = useMemo(() => loadInitial(), []);
  const [showReview, setShowReview] = useState(() => initial?.kind === "config");

  if (!initial) {
    return (
      <section class="viewer">
        <p class="error">No config loaded. Go back and upload a .json file.</p>
        <p>
          <a href="#/">← back to upload</a>
        </p>
      </section>
    );
  }

  if (showReview && initial.kind === "config") {
    return (
      <PlanReview config={initial.config} sims={initial.sims} onRun={() => setShowReview(false)} />
    );
  }

  return <ViewerBody initial={initial} />;
}

type InitialState =
  | { kind: "config"; config: unknown; sims: number; seed: number }
  | { kind: "snapshot"; config: unknown; sims: number; seed: number; result: RunResult };

function loadInitial(): InitialState | null {
  // 1. URL hash share.
  const share = readShareFromLocation();
  if (share) {
    try {
      if (share.kind === "config") {
        const c = decodeConfig(share.hash);
        return { kind: "config", config: c.config, sims: c.sims, seed: c.seed };
      }
      const s = decodeSnapshot(share.hash);
      return {
        kind: "snapshot",
        config: s.config,
        sims: s.sims,
        seed: s.seed,
        result: s.result as unknown as RunResult,
      };
    } catch (e) {
      console.error("bad share link", e);
      return null;
    }
  }
  // 2. sessionStorage from landing page.
  const raw = sessionStorage.getItem("mantissa:config");
  if (raw) {
    try {
      return {
        kind: "config",
        config: JSON.parse(raw),
        sims: 1000,
        seed: 42,
      };
    } catch {
      return null;
    }
  }
  return null;
}

function ViewerBody({ initial }: { initial: InitialState }) {
  const [store] = useState(() => createPlanStore(initial.config, initial.sims));
  // Manually seeded: share links can encode any seed; default to 42
  // when the engine runs.
  const stateValue = store.state.value;
  const [isSnapshot, setIsSnapshot] = useState(initial.kind === "snapshot");
  // Stale-while-revalidate: keep the last good result on screen while
  // a re-run is in flight so edits don't blank the charts.
  const lastReady = useRef<RunResult | null>(initial.kind === "snapshot" ? initial.result : null);
  if (stateValue.kind === "ready") lastReady.current = stateValue.result;

  // Bootstrap engine on first mount.
  useEffect(() => {
    if (initial.kind === "snapshot") {
      // Snapshots render without running. We do still bootstrap the
      // engine so subsequent edits can re-run without a cold start.
      void store.bootstrap();
      // Push the snapshot into the store as if it were a successful run.
      store.state.value = {
        kind: "ready",
        result: initial.result,
        runId: 0,
        runtimeMs: initial.result.runtimeMs,
      };
      return;
    }
    void store.bootstrap();
  }, [store, initial]);

  // Debounced re-run on config or sims change, but NOT for snapshots
  // until the user edits something. (Re-runs would clobber the
  // snapshot's frozen numbers.)
  useDebouncedEffect(
    () => {
      if (isSnapshot) {
        // User has edited; clear the snapshot flag so future debounce
        // ticks actually re-run.
        setIsSnapshot(false);
      }
      void store.rerun();
    },
    [store.config.value, store.sims.value],
    400,
  );

  return (
    <section class="viewer viewer--editable">
      <EngineStatus />
      <RunProgress state={stateValue} sims={store.sims.value} />
      <header class="viewer-header">
        <div>
          <h1>{(store.config.value as { name?: string } | null)?.name ?? "Mantissa plan"}</h1>
          <p class="muted small">
            {store.sims.value.toLocaleString()} simulations · <RunBadge state={stateValue} />
            {isSnapshot && stateValue.kind === "ready" && " · shared snapshot"}
          </p>
        </div>
        <div class="viewer-actions">
          <ShareBar store={store} result={stateValue.kind === "ready" ? stateValue.result : null} />
          <DownloadButton config={store.config.value} />
        </div>
      </header>

      {isSnapshot && (
        <output class="snapshot-banner">
          Showing a shared snapshot. Edit any field to re-run the engine with your changes.
        </output>
      )}

      <div class="layout">
        <ConfigDrawer store={store} />
        <div class="results">
          {stateValue.kind === "error" && <p class="error">{stateValue.message}</p>}
          {stateValue.kind === "ready" ? (
            <Ready result={stateValue.result} />
          ) : lastReady.current ? (
            <div class="results--stale" aria-busy="true">
              <p class="muted small">Updating with your latest edits…</p>
              <Ready result={lastReady.current} />
            </div>
          ) : stateValue.kind === "idle" ? (
            <p class="muted">Waiting for first run…</p>
          ) : (
            <ResultsSkeleton />
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
      <PlanSummary kpis={result.kpis} />
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
          yearlyPercentiles={result.mc.yearlyPercentiles}
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

/** Shimmer placeholders shown while the first run has no prior result. */
function ResultsSkeleton() {
  return (
    <div aria-hidden="true">
      <div class="kpi-row">
        <div class="kpi skeleton" />
        <div class="kpi skeleton" />
        <div class="kpi skeleton" />
      </div>
      <div class="panel skeleton skeleton--tall" />
      <div class="panel skeleton skeleton--tall" />
    </div>
  );
}

function PlanSummary({ kpis }: { kpis: RunResult["kpis"] }) {
  const r = kpis.successRate;
  const nw = kpis.medianFinalNetWorth;
  const oos = kpis.outOfSavingsRate;

  if (r >= 0.95) {
    const overSaving = nw > 5_000_000;
    return (
      <p class="plan-summary" data-tone={overSaving ? "info" : "good"}>
        {overSaving
          ? `Success rate ${fmtPct(r)} with a median terminal net worth of ${fmtMoney(nw)} — this plan is over-saving. You could retire earlier, spend more in retirement, or set a smaller legacy goal. Try lowering "Annual spending in retirement" in the wizard to see what changes.`
          : `Success rate ${fmtPct(r)} — your plan covers retirement spending in nearly all market scenarios. Median terminal net worth is ${fmtMoney(nw)}.`}
      </p>
    );
  }
  if (r >= 0.75) {
    return (
      <p class="plan-summary" data-tone="good">
        Success rate {fmtPct(r)} — the plan holds up in most market scenarios. Median terminal net
        worth is {fmtMoney(nw)}.
      </p>
    );
  }
  if (r >= 0.5) {
    return (
      <p class="plan-summary" data-tone="warn">
        Success rate {fmtPct(r)} — the plan works in a majority of market scenarios but is
        vulnerable to extended downturns. Median terminal net worth is {fmtMoney(nw)}. Try
        increasing savings, lowering retirement spending, or delaying retirement.
      </p>
    );
  }
  return (
    <p class="plan-summary" data-tone="bad">
      Success rate {fmtPct(r)} — the plan runs out of money in {fmtPct(oos)} of scenarios. The
      numbers below show the median outcome, which assumes an average market. Consider higher
      savings, lower retirement spending, or a later retirement date.
    </p>
  );
}
