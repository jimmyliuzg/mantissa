/**
 * Engine seam — the contract every UI component talks to.
 *
 * The Pyodide implementation lives in `pyodide.ts`. A future server-based
 * implementation can drop in as `api.ts` without touching the UI.
 *
 * Keep this file small. Anything you want to add here is probably better
 * in a UI-side adapter so the engine stays generic.
 */

export type McMethod = "gaussian" | "historical";

export interface RunOptions {
  /** Number of MC simulations. UI should cap at 5000 in v1. */
  simulations: number;
  /** Return generation method. */
  method: McMethod;
  /** RNG seed. Use a stable seed for share-link reproducibility. */
  seed: number;
}

export interface Kpis {
  successRate: number;
  medianFinalNetWorth: number;
  p10FinalNetWorth: number;
  p90FinalNetWorth: number;
  medianLifetimeTaxes: number;
  outOfSavingsRate: number;
  numSimulations: number;
}

export interface CashFlowRow {
  year: number;
  primaryAge: number;
  spouseAge: number | null;
  income: number;
  expenses: number;
  taxes: number;
  netWorth: number;
  netCashFlow: number;
}

export interface McResult {
  percentiles: { percentile: number; value: number }[];
  method: McMethod;
}

export interface Warning {
  year: number | null;
  category: string;
  message: string;
  severity: "info" | "warning" | "error";
}

export interface RunResult {
  kpis: Kpis;
  cashFlow: CashFlowRow[];
  mc: McResult;
  warnings: Warning[];
  /** Wall-clock runtime in milliseconds, for the UI run-status panel. */
  runtimeMs: number;
  /** When the run completed (epoch ms). */
  generatedAt: number;
}

export interface Engine {
  /**
   * True if the engine is loaded and ready to run. False until the first
   * `bootstrap()` call has resolved.
   */
  isReady(): boolean;
  /**
   * Load the engine and any required native deps. Idempotent.
   * Subsequent calls return immediately.
   */
  bootstrap(): Promise<void>;
  /**
   * Run a deterministic + Monte Carlo projection of the given config.
   * Throws on invalid config or engine error.
   */
  run(config: unknown, opts: RunOptions): Promise<RunResult>;
}
