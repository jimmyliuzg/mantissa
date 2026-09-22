/**
 * PlanStore seed plumbing (P0 fix).
 *
 * Share links encode a seed; loadInitial passes it to createPlanStore.
 * A regression here silently re-runs every shared config with seed 42,
 * breaking the share-link reproducibility claim.
 */
import { describe, expect, it, vi } from "vitest";

const runMock = vi.fn().mockResolvedValue({
  kpis: {},
  cashFlow: [],
  mc: { percentiles: [], method: "gaussian", yearlyPercentiles: [] },
  warnings: [],
  runtimeMs: 1,
  generatedAt: 1,
});

vi.mock("@engine", () => ({
  engine: {
    isReady: () => true,
    bootstrap: vi.fn().mockResolvedValue(undefined),
    run: (...args: unknown[]) => runMock(...args),
  },
}));

import { createPlanStore } from "../src/state/plan-store";

describe("createPlanStore seed", () => {
  it("passes the provided seed to engine.run", async () => {
    const store = createPlanStore({ name: "t" }, 500, 999);
    await store.rerun();
    expect(runMock).toHaveBeenCalledTimes(1);
    expect(runMock.mock.calls[0]?.[1]).toMatchObject({ simulations: 500, seed: 999 });
    expect(store.seed).toBe(999);
  });

  it("defaults to seed 42 when absent", async () => {
    const store = createPlanStore({ name: "t" });
    await store.rerun();
    expect(store.seed).toBe(42);
    expect(runMock.mock.calls[1]?.[1]).toMatchObject({ seed: 42 });
  });
});
