import { type RunResult, engine } from "@engine";
import { type Signal, signal } from "@preact/signals";
import { getPath, setPath } from "../lib/config-edit";
import { saveDraft } from "../lib/drafts";

export type EngineState =
	| { kind: "idle" }
	| { kind: "loading" }
	| { kind: "running" }
	| { kind: "ready"; result: RunResult; runId: number; runtimeMs: number }
	| { kind: "error"; message: string };
export interface PlanStore {
	config: Signal<unknown>;
	sims: Signal<number>;
	seed: number;
	state: Signal<EngineState>;
	isCurrent: Signal<boolean>;
	canUndo: Signal<boolean>;
	draftSaved: Signal<boolean>;
	setConfigField(path: string, value: unknown): void;
	removeConfigField(path: string): void;
	replaceConfig(config: unknown): void;
	setSims(n: number): void;
	bootstrap(): Promise<void>;
	rerun(): Promise<void>;
	cancel(): void;
	undo(): void;
	reset(): void;
}
export function createPlanStore(
	initial: unknown,
	initialSims = 1000,
	initialSeed = 42,
): PlanStore {
	const config = signal(initial),
		sims = signal(initialSims),
		seed = initialSeed;
	const state = signal<EngineState>({ kind: "idle" });
	const isCurrent = signal(false),
		canUndo = signal(false),
		draftSaved = signal(true);
	const history: unknown[] = [];
	let revision = 0,
		requested = 0,
		completed = 0,
		generation = 0;
	let active: Promise<void> | null = null;
	function save() {
		draftSaved.value = saveDraft(config.value, sims.value, seed);
	}
	function replaceConfig(next: unknown) {
		if (JSON.stringify(next) === JSON.stringify(config.value)) return;
		history.push(config.value);
		if (history.length > 50) history.shift();
		config.value = next;
		canUndo.value = true;
		revision++;
		isCurrent.value = false;
		save();
	}
	function setConfigField(path: string, value: unknown) {
		let next = setPath(config.value, path, value);
		const estimated = getPath(next, "input_metadata.estimated_fields");
		if (Array.isArray(estimated)) {
			const canonical = path.replace(/\.(\d+)(?=\.|$)/g, "[$1]");
			next = setPath(
				next,
				"input_metadata.estimated_fields",
				estimated.filter((p) => p !== canonical),
			);
		}
		replaceConfig(next);
	}
	function removeConfigField(path: string) {
		// JSON serialization removes undefined optional values from downloads and drafts.
		replaceConfig(
			JSON.parse(JSON.stringify(setPath(config.value, path, undefined))),
		);
	}
	function setSims(n: number) {
		if (sims.value === n) return;
		sims.value = n;
		revision++;
		isCurrent.value = false;
		save();
	}
	function undo() {
		if (!history.length) return;
		config.value = history.pop();
		canUndo.value = history.length > 0;
		revision++;
		isCurrent.value = false;
		save();
	}
	function reset() {
		replaceConfig(initial);
	}
	async function runLoop(myGeneration: number) {
		while (completed < requested && myGeneration === generation) {
			const target = requested,
				inputRevision = revision;
			const input = config.value,
				count = sims.value;
			const t0 = performance.now();
			try {
				if (!engine.isReady()) {
					state.value = { kind: "loading" };
					await engine.bootstrap();
				}
				if (myGeneration !== generation) return;
				if (target !== requested) {
					completed = target;
					continue;
				}
				state.value = { kind: "running" };
				const result = await engine.run(input, {
					simulations: count,
					method: "gaussian",
					seed,
				});
				if (myGeneration !== generation) return;
				if (target === requested) {
					isCurrent.value = inputRevision === revision;
					state.value = {
						kind: "ready",
						result,
						runId: target,
						runtimeMs: Math.round(performance.now() - t0),
					};
				}
			} catch (error) {
				if (myGeneration !== generation) return;
				if (target === requested) {
					state.value = { kind: "error", message: String(error) };
					isCurrent.value = false;
				}
			}
			completed = target;
		}
	}
	function rerun() {
		requested++;
		if (!active) {
			const myGeneration = generation;
			active = runLoop(myGeneration).finally(() => {
				if (myGeneration === generation) active = null;
			});
		}
		return active;
	}
	function cancel() {
		generation++;
		completed = requested;
		active = null;
		engine.cancel?.();
		isCurrent.value = false;
		state.value = { kind: "idle" };
	}
	return {
		config,
		sims,
		seed,
		state,
		isCurrent,
		canUndo,
		draftSaved,
		replaceConfig,
		setConfigField,
		removeConfigField,
		setSims,
		undo,
		reset,
		cancel,
		rerun,
		bootstrap: rerun,
	};
}
