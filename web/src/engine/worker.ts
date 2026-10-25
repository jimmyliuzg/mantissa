import { pyodideEngine } from "./pyodide";
import type { RunOptions } from "./types";

// One worker owns one Python runtime. Requests are serialized defensively here,
// as well as coalesced in the plan store, so Python globals never overlap.
const scope = globalThis as unknown as {
	onmessage: ((event: MessageEvent) => void) | null;
	postMessage: (message: unknown) => void;
};
let queue = Promise.resolve();
scope.onmessage = ({
	data,
}: MessageEvent<{
	id: number;
	kind: "bootstrap" | "run";
	config?: unknown;
	options?: RunOptions;
}>) => {
	queue = queue.then(async () => {
		try {
			await pyodideEngine.bootstrap();
			const result =
				data.kind === "run"
					? await pyodideEngine.run(data.config, data.options!)
					: undefined;
			scope.postMessage({ id: data.id, result });
		} catch (error) {
			scope.postMessage({ id: data.id, error: String(error) });
		}
	});
};
