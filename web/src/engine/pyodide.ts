/**
 * Pyodide implementation of the engine seam.
 *
 * Boot sequence (one-time, on first call to `bootstrap()`):
 *   1. Load Pyodide from CDN (or self-hosted under /vendor/pyodide/).
 *   2. Load numpy from Pyodide's package index.
 *   3. Install click + tabulate via micropip.
 *   4. Install the mantissa wheel from `MANTISSA_WHEEL_URL` (default:
 *      `<base>/vendor/mantissa-<version>-py3-none-any.whl`).
 *
 * Per-run path:
 *   1. Serialize config to JSON, write to Pyodide's /tmp.
 *   2. Call RetirementPlanner.from_config + MonteCarloEngine.run.
 *   3. Return a normalized RunResult.
 *
 * Privacy: no network calls beyond the initial Pyodide + wheel load.
 * No data ever leaves the browser. Run results live only in JS memory.
 */

import type { Engine, Kpis, McResult, RunOptions, RunResult, Warning } from "./types";

const PYODIDE_VERSION = "0.27.7";
const PYODIDE_CDN = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;

declare global {
  interface Window {
    loadPyodide?: (opts: { indexURL: string }) => Promise<PyodideLike>;
  }
  // Avoid pulling in @types/pyodide (not installed). We only touch a few
  // surface methods, so a structural type is enough.
  // eslint-disable-next-line @typescript-eslint/no-empty-interface
  interface PyodideLike {
    globals: { set(k: string, v: unknown): void };
    runPythonAsync(code: string): Promise<unknown>;
    toPy(obj: unknown): unknown;
    pyimport(name: string): { install: (target: string) => Promise<void> };
    FS: { writeFile(p: string, data: Uint8Array): void };
    loadPackage(names: string[]): Promise<void>;
  }
}

let bootstrapPromise: Promise<void> | null = null;
let pyodide: PyodideLike | null = null;

async function loadPyodideScript(): Promise<void> {
  if (window.loadPyodide) return;
  await new Promise<void>((resolve, reject) => {
    const s = document.createElement("script");
    s.src = `${PYODIDE_CDN}pyodide.js`;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("failed to load Pyodide script"));
    document.head.appendChild(s);
  });
}

function wheelUrl(): string {
  // Vite injects import.meta.env.BASE_URL; default to "/" for dev.
  const baseRaw = (import.meta as { env?: { BASE_URL?: string } }).env?.BASE_URL ?? "/";
  const base = baseRaw.replace(/\/$/, "");
  // Version is hardcoded for v1. Bump when shipping a new mantissa release.
  // The wheel filename comes from pyproject.toml's [project] name = "mantissa".
  return `${base}/vendor/mantissa-0.2.0-py3-none-any.whl`;
}

export const pyodideEngine: Engine = {
  isReady: () => pyodide !== null,

  async bootstrap() {
    if (pyodide) return;
    if (bootstrapPromise) return bootstrapPromise;
    bootstrapPromise = (async () => {
      await loadPyodideScript();
      if (!window.loadPyodide) throw new Error("loadPyodide not on window after script load");
      pyodide = await window.loadPyodide({ indexURL: PYODIDE_CDN });

      // numpy ships with Pyodide; the rest comes from micropip.
      await pyodide.loadPackage(["numpy", "micropip"]);
      const micropip = pyodide.pyimport("micropip");
      for (const pkg of ["click", "tabulate"]) {
        await micropip.install(pkg);
      }

      // Mantissa wheel is served as a static asset alongside the app.
      await micropip.install(wheelUrl());

      // Smoke test — surface import errors early with a useful message.
      await pyodide.runPythonAsync(
        "import retirement_planner; from retirement_planner import RetirementPlanner, MonteCarloEngine",
      );
    })();
    return bootstrapPromise;
  },

  async run(config: unknown, opts: RunOptions): Promise<RunResult> {
    if (!pyodide) throw new Error("engine not bootstrapped; call bootstrap() first");
    const t0 = performance.now();

    pyodide.globals.set("MANTISSA_CONFIG", pyodide.toPy(config));
    pyodide.globals.set("MANTISSA_SIMS", opts.simulations);
    pyodide.globals.set("MANTISSA_METHOD", opts.method);
    pyodide.globals.set("MANTISSA_SEED", opts.seed);

    const code = `
import json, tempfile, os
from retirement_planner import RetirementPlanner, MonteCarloEngine

cfg = MANTISSA_CONFIG.to_py() if hasattr(MANTISSA_CONFIG, "to_py") else dict(MANTISSA_CONFIG)
fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
with open(path, "w") as f:
    json.dump(cfg, f, default=str)

planner = RetirementPlanner.from_config(path)
project = planner.project_cash_flow()
mc = MonteCarloEngine(planner).run(
    num_simulations=int(MANTISSA_SIMS),
    method=str(MANTISSA_METHOD),
    seed=int(MANTISSA_SEED),
)

def _norm_pctile(mc, p):
    return {"percentile": p, "value": mc.get(f"p{p}_final_nw", 0.0)}

result = {
    "kpis": {
        "successRate": mc.get("success_rate", 0.0),
        "medianFinalNetWorth": mc.get("median_final_nw", 0.0),
        "p10FinalNetWorth": mc.get("p10_final_nw", 0.0),
        "p90FinalNetWorth": mc.get("p90_final_nw", 0.0),
        "medianLifetimeTaxes": mc.get("median_taxes", 0.0),
        "outOfSavingsRate": mc.get("out_of_savings_rate", 0.0),
        "numSimulations": mc.get("num_simulations", 0),
    },
    "cashFlow": [
        {
            "year": r.get("year"),
            "primaryAge": r.get("primary_age"),
            "spouseAge": r.get("spouse_age"),
            "income": r.get("income", 0.0),
            "expenses": r.get("expenses", 0.0),
            "taxes": r.get("taxes", 0.0),
            "netWorth": r.get("net_worth", 0.0),
            "netCashFlow": r.get("net_cash_flow", 0.0),
        }
        for r in project
    ],
    "mc": {
        "percentiles": [_norm_pctile(mc, p) for p in (10, 25, 50, 75, 90)],
        "method": mc.get("method", "gaussian"),
    },
    "warnings": [],  # engine does not surface structured warnings; fill later
}
json.dumps(result)
`;
    const json = (await pyodide.runPythonAsync(code)) as string;
    const parsed = JSON.parse(json) as Omit<RunResult, "runtimeMs" | "generatedAt"> & {
      kpis: Kpis;
      mc: McResult;
      warnings: Warning[];
    };

    return {
      ...parsed,
      runtimeMs: Math.round(performance.now() - t0),
      generatedAt: Date.now(),
    };
  },
};
