import { describe, expect, it } from "vitest";
import { createWorkerEngine } from "../src/engine/worker-client";
function harness() {
	const workers: Array<any> = [];
	const engine = createWorkerEngine(() => {
		const worker = {
			onmessage: null as any,
			onerror: null as any,
			messages: [] as any[],
			terminated: false,
			postMessage(message: unknown) {
				this.messages.push(message);
			},
			terminate() {
				this.terminated = true;
			},
		};
		workers.push(worker);
		return worker;
	});
	const answer = (result?: unknown) => {
		const worker = workers.at(-1)!;
		worker.onmessage({ data: { id: worker.messages.at(-1).id, result } });
	};
	return { engine, workers, answer };
}
describe("worker engine boundary", () => {
	it("boots once, exchanges structured inputs and correlates results", async () => {
		const { engine, workers, answer } = harness();
		const boot = engine.bootstrap(),
			same = engine.bootstrap();
		expect(workers).toHaveLength(1);
		expect(workers[0].messages).toHaveLength(1);
		answer();
		await Promise.all([boot, same]);
		expect(engine.isReady()).toBe(true);
		const run = engine.run(
			{ name: "Fictional" },
			{ simulations: 500, method: "gaussian", seed: 999 },
		);
		expect(workers[0].messages.at(-1)).toMatchObject({
			kind: "run",
			config: { name: "Fictional" },
			options: { seed: 999 },
		});
		answer({ generatedAt: 1 });
		expect(await run).toEqual({ generatedAt: 1 });
	});
	it("cancellation stops CPU work and permits a new worker on retry", async () => {
		const { engine, workers, answer } = harness();
		const boot = engine.bootstrap();
		answer();
		await boot;
		const run = engine.run(
			{},
			{ simulations: 500, method: "gaussian", seed: 42 },
		);
		const rejection = expect(run).rejects.toThrow("stopped");
		engine.cancel?.();
		await rejection;
		expect(workers[0].terminated).toBe(true);
		expect(engine.isReady()).toBe(false);
		const retry = engine.bootstrap();
		expect(workers).toHaveLength(2);
		answer();
		await retry;
		expect(engine.isReady()).toBe(true);
	});
	it("can immediately retry a cancelled cold start without losing its new bootstrap", async () => {
		const { engine, workers, answer } = harness();
		const old = engine.bootstrap();
		const rejection = expect(old).rejects.toThrow("stopped");
		engine.cancel?.();
		const retry = engine.bootstrap();
		await rejection;
		const same = engine.bootstrap();
		expect(workers[1].messages).toHaveLength(1);
		answer();
		await Promise.all([retry, same]);
		expect(engine.isReady()).toBe(true);
	});
	it("surfaces worker failures and retries bootstrap", async () => {
		const { engine, workers, answer } = harness();
		const boot = engine.bootstrap();
		const failure = expect(boot).rejects.toThrow("unavailable");
		workers[0].onerror({ message: "unavailable", preventDefault() {} });
		await failure;
		const retry = engine.bootstrap();
		answer();
		await retry;
		expect(engine.isReady()).toBe(true);
	});
});
