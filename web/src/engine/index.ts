/**
 * The engine seam. The rest of the app imports `engine` from here and
 * never reaches into a specific implementation. To swap Pyodide for a
 * future server backend, change this file only.
 */

import { createWorkerEngine } from "./worker-client";
import type { Engine } from "./types";

export const engine: Engine = createWorkerEngine(() => new Worker(new URL("./worker.ts", import.meta.url)));
export type { Engine, GoalOutcomes, Kpis, CashFlowRow, McResult, McPercentilePoint, RunOptions, RunResult, Warning } from "./types";
