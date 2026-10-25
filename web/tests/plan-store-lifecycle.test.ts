import { beforeEach, describe, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({
	run: vi.fn(),
	bootstrap: vi.fn().mockResolvedValue(undefined),
	cancel: vi.fn(),
}));
vi.mock("@engine", () => ({ engine: { isReady: () => true, ...mocks } }));
import { createPlanStore } from "../src/state/plan-store";
const result = { runtimeMs: 1, generatedAt: 1 };
beforeEach(() => {
	mocks.run.mockReset();
	sessionStorage.clear();
	localStorage.clear();
});
describe("plan execution and drafts", () => {
	it("serializes work and coalesces intermediate requests without publishing stale results", async () => {
		let finish!: (value: any) => void;
		mocks.run
			.mockImplementationOnce(
				() =>
					new Promise((resolve) => {
						finish = resolve;
					}),
			)
			.mockResolvedValue(result);
		const store = createPlanStore({ name: "First" });
		const first = store.rerun();
		store.setConfigField("name", "Intermediate");
		void store.rerun();
		store.setConfigField("name", "Latest");
		const latest = store.rerun();
		expect(mocks.run).toHaveBeenCalledTimes(1);
		finish(result);
		await Promise.all([first, latest]);
		expect(mocks.run).toHaveBeenCalledTimes(2);
		expect(mocks.run.mock.calls[1]![0]).toEqual({ name: "Latest" });
		expect(store.isCurrent.value).toBe(true);
	});
	it("persists edits and supports undo, reset and removal of optional inputs", () => {
		const store = createPlanStore({
			name: "First",
			balance_date: "2027-01-01",
		});
		store.setConfigField("name", "Edited");
		expect(JSON.parse(sessionStorage.getItem("mantissa:config")!).name).toBe(
			"Edited",
		);
		store.removeConfigField("balance_date");
		expect(store.config.value).not.toHaveProperty("balance_date");
		store.undo();
		expect(store.config.value).toHaveProperty("balance_date", "2027-01-01");
		store.reset();
		expect(store.config.value).toHaveProperty("name", "First");
	});
	it("does not mark old results current when edits have not yet requested a run", async () => {
		let finish!: (value: any) => void;
		mocks.run.mockImplementationOnce(
			() =>
				new Promise((resolve) => {
					finish = resolve;
				}),
		);
		const store = createPlanStore({ name: "First" });
		const run = store.rerun();
		store.setConfigField("name", "Edited");
		finish(result);
		await run;
		expect(store.state.value.kind).toBe("ready");
		expect(store.isCurrent.value).toBe(false);
	});
});
