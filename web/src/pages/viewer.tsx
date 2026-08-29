import { useEffect, useState } from "preact/hooks";
import { engine, type RunResult } from "@engine";
import { KpiRow } from "../components/kpi-row";
import { CashFlowChart } from "../components/cash-flow-chart";
import { MonteCarloFan } from "../components/monte-carlo-fan";
import { fmtMoney, fmtPct } from "../lib/format";

/**
 * Viewer page. M1 = read-only: load config from sessionStorage, run once,
 * render. M2 wires inline edits and debounced re-runs.
 */
export function Viewer() {
  const [result, setResult] = useState<RunResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [config, setConfig] = useState<unknown | null>(null);
  const [sims] = useState(1000);

  useEffect(() => {
    const raw = sessionStorage.getItem("mantissa:config");
    if (!raw) {
      setErr("No config loaded. Go back and upload a .json file.");
      return;
    }
    try {
      setConfig(JSON.parse(raw));
    } catch (e) {
      setErr(`Stored config is not valid JSON: ${String(e)}`);
    }
  }, []);

  useEffect(() => {
    if (!config) return;
    let cancelled = false;
    setErr(null);
    (async () => {
      try {
        await engine.bootstrap();
        const r = await engine.run(config, { simulations: sims, method: "gaussian", seed: 42 });
        if (!cancelled) setResult(r);
      } catch (e) {
        if (!cancelled) setErr(String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [config, sims]);

  if (err) {
    return (
      <section class="viewer">
        <p class="error">{err}</p>
        <p>
          <a href="#/">← back to upload</a>
        </p>
      </section>
    );
  }
  if (!result) {
    return (
      <section class="viewer">
        <p>Loading engine and running projection…</p>
      </section>
    );
  }

  return (
    <section class="viewer">
      <header class="viewer-header">
        <h2>{(config as { name?: string })?.name ?? "Mantissa plan"}</h2>
        <p class="muted">
          {result.kpis.numSimulations.toLocaleString()} simulations · ran in {result.runtimeMs} ms
        </p>
      </header>

      <KpiRow kpis={result.kpis} />

      <section class="panel">
        <h3>Cash flow</h3>
        <CashFlowChart rows={result.cashFlow} />
        <p class="muted small">
          Income {fmtMoney(result.cashFlow.reduce((s, r) => s + r.income, 0))} · Expenses{" "}
          {fmtMoney(result.cashFlow.reduce((s, r) => s + r.expenses, 0))} · Taxes{" "}
          {fmtMoney(result.cashFlow.reduce((s, r) => s + r.taxes, 0))} · Median success rate{" "}
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
    </section>
  );
}
