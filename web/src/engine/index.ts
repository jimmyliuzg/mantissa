/**
 * The engine seam. The rest of the app imports `engine` from here and
 * never reaches into a specific implementation. To swap Pyodide for a
 * future server backend, change this file only.
 */

import { pyodideEngine } from "./pyodide";
import type { Engine } from "./types";

export const engine: Engine = pyodideEngine;
export type { Engine, Kpis, CashFlowRow, McResult, RunOptions, RunResult, Warning } from "./types";
