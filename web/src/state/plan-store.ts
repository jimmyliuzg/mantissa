import { type RunResult, engine } from "@engine";
import { type Signal, signal } from "@preact/signals";
import { setPath } from "../lib/config-edit";

/**
 * Reactive plan store. M2's single source of truth.
 *
 *   config signal ── debounce 400ms ──► runEffect ──► state signal
 *
 * Stale in-flight runs are dropped by checking the run id — no engine
 * cancellation needed. To swap engines, change engine/index.ts.
 */

export type EngineState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "running" }
  | { kind: "ready"; result: RunResult; runId: number; runtimeMs: number }
  | { kind: "error"; message: string };

export interface PlanStore {
  config: Signal<unknown>;
  sims: Signal<number>;
  /** RNG seed for every run. Comes from the share link so recipients
   *  reproduce the sender's numbers; defaults to 42. */
  seed: number;
  state: Signal<EngineState>;
  setConfigField: (path: string, value: unknown) => void;
  setSims: (n: number) => void;
  bootstrap: () => Promise<void>;
  rerun: () => Promise<void>;
}

export function createPlanStore(initial: unknown, initialSims = 1000, initialSeed = 42): PlanStore {
  const config = signal<unknown>(initial);
  const sims = signal<number>(initialSims);
  const seed = initialSeed;
  const state = signal<EngineState>({ kind: "idle" });

  let runCounter = 0;

  async function rerun(): Promise<void> {
    const myRun = ++runCounter;
    state.value = { kind: "running" };
    // Yield a frame so the progress UI paints before the (blocking)
    // Pyodide call hogs the main thread.
    await new Promise((r) => setTimeout(r, 30));
    if (myRun !== runCounter) return;
    const t0 = performance.now();
    try {
      const result = await engine.run(config.value, {
        simulations: sims.value,
        method: "gaussian",
        seed,
      });
      // Drop stale results — only the most recent run wins.
      if (myRun !== runCounter) return;
      state.value = {
        kind: "ready",
        result,
        runId: myRun,
        runtimeMs: Math.round(performance.now() - t0),
      };
    } catch (e) {
      if (myRun !== runCounter) return;
      state.value = { kind: "error", message: String(e) };
    }
  }

  function setConfigField(path: string, value: unknown): void {
    config.value = setPath(config.value, path, value);
  }

  function setSims(n: number): void {
    sims.value = n;
  }

  async function bootstrap(): Promise<void> {
    if (state.value.kind === "loading") return;
    if (engine.isReady() && state.value.kind === "idle") {
      await rerun();
      return;
    }
    if (state.value.kind === "ready" || state.value.kind === "error") {
      // Re-run with current config; engine is already booted.
      await rerun();
      return;
    }
    state.value = { kind: "loading" };
    try {
      await engine.bootstrap();
      await rerun();
    } catch (e) {
      state.value = { kind: "error", message: `engine bootstrap failed: ${String(e)}` };
    }
  }

  return { config, sims, seed, state, setConfigField, setSims, bootstrap, rerun };
}
