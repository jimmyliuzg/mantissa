import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  ready: false,
  bootstrap: vi.fn(),
  run: vi.fn().mockResolvedValue({ runtimeMs: 1 }),
}));
vi.mock("@engine", () => ({
  engine: {
    isReady: () => mocks.ready,
    bootstrap: mocks.bootstrap,
    run: mocks.run,
  },
}));
import { createPlanStore } from "../src/state/plan-store";

describe("plan store bootstrap retry", () => {
  it("boots again after a failed load before trying to run a plan", async () => {
    mocks.bootstrap.mockRejectedValueOnce(new Error("network failed"));
    const store = createPlanStore({});
    await store.bootstrap();
    expect(store.state.value.kind).toBe("error");
    expect(mocks.run).not.toHaveBeenCalled();
    mocks.bootstrap.mockImplementationOnce(async () => {
      mocks.ready = true;
    });
    await store.bootstrap();
    expect(mocks.bootstrap).toHaveBeenCalledTimes(2);
    expect(mocks.run).toHaveBeenCalledTimes(1);
    expect(store.state.value.kind).toBe("ready");
  });
});
