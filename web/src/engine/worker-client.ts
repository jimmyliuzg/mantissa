import type { Engine, RunOptions, RunResult } from "./types";

type WorkerLike = Pick<
	Worker,
	"postMessage" | "terminate" | "onmessage" | "onerror"
>;
export function createWorkerEngine(makeWorker: () => WorkerLike): Engine {
	let worker: WorkerLike | null = null;
	let ready = false;
	let bootstrapPromise: Promise<void> | null = null;
	let nextId = 0;
	let generation = 0;
	const pending = new Map<
		number,
		{ resolve: (value: unknown) => void; reject: (error: Error) => void }
	>();
	function stop(message: string) {
		generation++;
		worker?.terminate();
		worker = null;
		ready = false;
		bootstrapPromise = null;
		for (const entry of pending.values()) entry.reject(new Error(message));
		pending.clear();
	}
	function request(
		kind: "bootstrap" | "run",
		config?: unknown,
		options?: RunOptions,
	): Promise<unknown> {
		if (!worker) {
			worker = makeWorker();
			worker.onmessage = ({ data }) => {
				const entry = pending.get(data.id);
				if (!entry) return;
				pending.delete(data.id);
				if (data.error) entry.reject(new Error(data.error));
				else entry.resolve(data.result);
			};
			worker.onerror = (event) => {
				event.preventDefault?.();
				stop(event.message || "Calculation worker failed. Retry to reload it.");
			};
		}
		const id = ++nextId;
		return new Promise((resolve, reject) => {
			pending.set(id, { resolve, reject });
			try {
				worker!.postMessage({ id, kind, config, options });
			} catch (error) {
				pending.delete(id);
				reject(error instanceof Error ? error : new Error(String(error)));
			}
		});
	}
	return {
		isReady: () => ready,
		bootstrap() {
			if (ready) return Promise.resolve();
			if (!bootstrapPromise) {
				const started = generation;
				bootstrapPromise = request("bootstrap")
					.then(() => {
						if (started === generation) ready = true;
					})
					.catch((error) => {
						if (started === generation) bootstrapPromise = null;
						throw error;
					});
			}
			return bootstrapPromise;
		},
		async run(config, options) {
			if (!ready) throw new Error("Engine is not ready. Retry to load it.");
			return (await request("run", config, options)) as RunResult;
		},
		cancel() {
			stop("Calculation stopped. Run again to continue.");
		},
	};
}
