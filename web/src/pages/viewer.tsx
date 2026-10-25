import { ModelWarnings } from "../components/model-warnings";
import type { RunResult } from "@engine";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { CashFlowChart } from "../components/cash-flow-chart";
import { ConfigDrawer } from "../components/config-drawer";
import { KpiRow } from "../components/kpi-row";
import { MonteCarloFan } from "../components/monte-carlo-fan";
import { PlanReview } from "../components/plan-review";
import { RunBadge, RunProgress } from "../components/run-progress";
import { ShareBar } from "../components/share-bar";
import { OutcomeSummary, SpendingDetail } from "../components/outcome-summary";
import { PlanComparison } from "../components/plan-comparison";
import {
	decodeConfig,
	decodeSnapshot,
	readShareFromLocation,
} from "../lib/share-codec";
import { validateConfig } from "../lib/config-validation";
import {
	clearDrafts,
	rememberedPlan,
	remembersPlan,
	saveDraft,
	setRememberPlan,
} from "../lib/drafts";
import { cashFlowCsv, downloadFile } from "../lib/export";
import { getPath } from "../lib/config-edit";
import { focusConfigField } from "../lib/guided-editor";
import { createPlanStore } from "../state/plan-store";
import "./viewer.css";

type InitialState = {
	kind: "config" | "snapshot";
	config: unknown;
	sims: number;
	seed: number;
	result?: RunResult;
	reviewed?: boolean;
};
export function loadInitial(): InitialState {
	const share = readShareFromLocation();
	if (share) {
		if (share.kind === "snapshot") {
			const decoded = decodeSnapshot(share.hash);
			return {
				kind: "snapshot",
				config: decoded.config,
				sims: decoded.sims,
				seed: decoded.seed,
				result: decoded.result,
			};
		}
		const decoded = decodeConfig(share.hash);
		return {
			kind: "config",
			config: decoded.config,
			sims: decoded.sims,
			seed: decoded.seed,
		};
	}
	const raw = sessionStorage.getItem("mantissa:config");
	if (raw) {
		const config = validateConfig(JSON.parse(raw));
		let sims = 1000,
			seed = 42;
		try {
			const options = JSON.parse(
				sessionStorage.getItem("mantissa:run-options") ?? "{}",
			);
			if ([500, 1000, 5000].includes(options.sims)) sims = options.sims;
			if (Number.isSafeInteger(options.seed)) seed = options.seed;
		} catch {
			/* Default settings remain valid. */
		}
		return {
			kind: "config",
			config,
			sims,
			seed,
			reviewed:
				sessionStorage.getItem("mantissa:reviewed-config") ===
				JSON.stringify(config),
		};
	}
	const remembered = rememberedPlan();
	if (remembered) {
		const value = JSON.parse(remembered);
		const config = validateConfig(value.config);
		saveDraft(config, value.sims, value.seed);
		return {
			kind: "config",
			config,
			sims: [500, 1000, 5000].includes(value.sims) ? value.sims : 1000,
			seed: Number.isSafeInteger(value.seed) ? value.seed : 42,
		};
	}
	throw new Error(
		"No saved plan is available. Start a plan or import an existing one.",
	);
}
export function Viewer() {
	const loaded = useMemo(() => {
		try {
			return { initial: loadInitial(), error: "" };
		} catch (error) {
			return {
				initial: null,
				error: error instanceof Error ? error.message : String(error),
			};
		}
	}, []);
	const [review, setReview] = useState(
		loaded.initial?.kind === "config" && !loaded.initial.reviewed,
	);
	if (!loaded.initial)
		return (
			<section class="viewer">
				<h1>Could not open this plan</h1>
				<p class="error" role="alert">
					{loaded.error}
				</p>
				<p>Your existing local draft has not been replaced.</p>
				<a href="#/">Start, resume or import a plan</a>
			</section>
		);
	if (review)
		return (
			<PlanReview
				config={loaded.initial.config}
				sims={loaded.initial.sims}
				onRun={() => {
					saveDraft(
						loaded.initial!.config,
						loaded.initial!.sims,
						loaded.initial!.seed,
					);
					sessionStorage.setItem(
						"mantissa:reviewed-config",
						JSON.stringify(loaded.initial!.config),
					);
					setReview(false);
				}}
			/>
		);
	return <ViewerBody initial={loaded.initial} />;
}
export function ViewerBody({ initial }: { initial: InitialState }) {
	const [store] = useState(() => {
		const s = createPlanStore(initial.config, initial.sims, initial.seed);
		if (initial.kind === "snapshot" && initial.result) {
			s.state.value = {
				kind: "ready",
				result: initial.result,
				runId: 0,
				runtimeMs: initial.result.runtimeMs,
			};
			s.isCurrent.value = true;
		} else
			s.draftSaved.value = saveDraft(
				initial.config,
				initial.sims,
				initial.seed,
			);
		return s;
	});
	const state = store.state.value;
	const config = store.config.value,
		sims = store.sims.value;
	const [snapshot, setSnapshot] = useState(initial.kind === "snapshot");
	const [mobilePanel, setMobilePanel] = useState<"results" | "edit">("results");
	const [remember, setRemember] = useState(remembersPlan());
	const [storageError, setStorageError] = useState("");
	const [refineMessage, setRefineMessage] = useState("");
	const lastReady = useRef<RunResult | null>(initial.result ?? null);
	const resultConfig = useRef(initial.config);
	if (state.kind === "ready") {
		lastReady.current = state.result;
		if (store.isCurrent.value) resultConfig.current = config;
	}
	const previous = useRef({ config, sims });
	const scheduledRun = useRef<ReturnType<typeof setTimeout> | null>(null);
	function clearScheduledRun() {
		if (scheduledRun.current !== null) {
			clearTimeout(scheduledRun.current);
			scheduledRun.current = null;
		}
	}
	useEffect(() => {
		if (initial.kind !== "snapshot") void store.bootstrap();
		return () => {
			if (["loading", "running"].includes(store.state.value.kind))
				store.cancel();
		};
	}, [store]);
	useEffect(() => {
		if (previous.current.config === config && previous.current.sims === sims)
			return;
		previous.current = { config, sims };
		setSnapshot(false);
		// An edited shared plan becomes a local draft; reloading must not reopen
		// the original immutable URL payload over the user's changes.
		if (readShareFromLocation())
			history.replaceState(null, "", `${location.pathname}#/review`);
		try {
			sessionStorage.setItem(
				"mantissa:reviewed-config",
				JSON.stringify(config),
			);
		} catch {
			/* Download remains available when storage is disabled. */
		}
		scheduledRun.current = setTimeout(() => {
			scheduledRun.current = null;
			void store.rerun();
		}, 600);
		return clearScheduledRun;
	}, [config, sims, store]);
	const result = state.kind === "ready" ? state.result : lastReady.current;
	const current = state.kind === "ready" && store.isCurrent.value;
	const busy = state.kind === "loading" || state.kind === "running";
	const name = String(getPath(config, "name") || "Retirement plan");
	function refine(path: string) {
		setMobilePanel("edit");
		requestAnimationFrame(() => {
			if (!focusConfigField(path))
				setRefineMessage(
					"Open the relevant plan section below. Advanced JSON includes every supported setting.",
				);
			else setRefineMessage("");
		});
	}
	return (
		<section class="viewer viewer--editable">
			<RunProgress state={state} sims={sims} />
			<header class="viewer-header">
				<div>
					<h1>{name}</h1>
					<p class="muted small">
						{sims.toLocaleString()} simulations · <RunBadge state={state} />
						{snapshot && " · shared snapshot"}
					</p>
				</div>
				<div class="viewer-actions">
					<ShareBar store={store} result={current ? result : null} />
					<button
						type="button"
						class="btn"
						onClick={() =>
							downloadFile(
								JSON.stringify(config, null, 2),
								"plan.json",
								"application/json",
							)
						}
					>
						Download plan
					</button>
				</div>
			</header>
			{snapshot && (
				<p class="snapshot-banner">
					Shared snapshot: these saved results stay fixed until you edit or run
					again.
				</p>
			)}
			<div class="plan-toolbar">
				<button
					class="btn"
					type="button"
					disabled={!store.canUndo.value}
					onClick={() => store.undo()}
				>
					Undo edit
				</button>
				<button
					class="btn"
					type="button"
					disabled={!store.canUndo.value}
					onClick={() => store.reset()}
				>
					Reset to opened plan
				</button>
				<button
					class="btn btn--primary"
					type="button"
					disabled={busy}
					onClick={() => {
						clearScheduledRun();
						setSnapshot(false);
						void store.rerun();
					}}
				>
					Run projection
				</button>
				{busy && (
					<button
						class="btn"
						type="button"
						onClick={() => {
							clearScheduledRun();
							store.cancel();
						}}
					>
						Stop calculation
					</button>
				)}
				<span role="status" class="muted small">
					{snapshot
						? "Shared plan: edit or download to keep a local copy"
						: store.draftSaved.value
							? "Draft saved in this browser session"
							: "Draft could not be saved. Download your plan."}
				</span>
				<label>
					<input
						type="checkbox"
						checked={remember}
						onChange={(event) => {
							const checked = event.currentTarget.checked;
							if (setRememberPlan(checked, config, sims, store.seed)) {
								setRemember(checked);
								setStorageError("");
							} else
								setStorageError(
									"This browser could not save the plan. Download it instead.",
								);
						}}
					/>{" "}
					Remember this plan on this device
				</label>
				<button
					class="btn"
					type="button"
					onClick={() => {
						clearDrafts();
						location.hash = "#/";
					}}
				>
					Clear local drafts
				</button>
			</div>
			{storageError && (
				<p role="alert" class="error">
					{storageError}
				</p>
			)}
			{state.kind === "error" && (
				<div class="panel" role="alert">
					<p class="error">{state.message}</p>
					<button class="btn" type="button" onClick={() => void store.rerun()}>
						Retry projection
					</button>
					<button
						class="btn"
						type="button"
						disabled={!store.canUndo.value}
						onClick={() => store.undo()}
					>
						Undo last edit
					</button>
				</div>
			)}
			<div class="viewer-tabs" role="group" aria-label="Plan view">
				<button
					class="btn"
					type="button"
					aria-pressed={mobilePanel === "results"}
					onClick={() => setMobilePanel("results")}
				>
					Results
				</button>
				<button
					class="btn"
					type="button"
					aria-pressed={mobilePanel === "edit"}
					onClick={() => setMobilePanel("edit")}
				>
					Edit plan
				</button>
			</div>
			{refineMessage && <p role="status">{refineMessage}</p>}
			<div class="layout" data-mobile-panel={mobilePanel}>
				<ConfigDrawer store={store} />
				<div class="results">
					{result ? (
						<>
							{!current && (
								<p class="result-status" role="status">
									{busy
										? "Calculating your latest edits. Results below are from the previous completed run."
										: state.kind === "error"
											? "Calculation failed. Results below are from the previous completed run."
											: "Inputs changed or calculation stopped. Run again to update these results."}
								</p>
							)}
							<Ready
								result={result}
								config={resultConfig.current}
								onRefine={refine}
							/>
							<PlanComparison
								result={result}
								name={name}
								current={current}
								sims={sims}
								seed={store.seed}
							/>
							<div class="result-exports">
								<button
									type="button"
									class="btn"
									disabled={!current}
									onClick={() =>
										downloadFile(
											cashFlowCsv(result),
											"cash-flow.csv",
											"text/csv",
										)
									}
								>
									Download cash-flow CSV
								</button>
								<button
									type="button"
									class="btn"
									disabled={!current}
									onClick={() => window.print()}
								>
									Print results
								</button>
								<p class="muted small">
									Results generated{" "}
									{new Date(result.generatedAt).toLocaleString()}. Monetary
									units are shown below.
								</p>
							</div>
						</>
					) : busy ? (
						<div class="panel" role="status">
							Loading the calculation engine and running your plan. You can keep
							editing.
						</div>
					) : (
						<p>Run the projection to see your results.</p>
					)}
				</div>
			</div>
		</section>
	);
}
function Ready({
	result,
	config,
	onRefine,
}: { result: RunResult; config: unknown; onRefine(path: string): void }) {
	const retirement = Number(
		String(getPath(config, "primary.retirement_date") ?? "").slice(0, 4),
	);
	const units = result.outcomes
		? result.outcomes.monetary_convention === "real"
			? `${result.outcomes.base_year} purchasing power`
			: "nominal dollars for each year"
		: "the saved plan’s monetary convention";
	return (
		<>
			<KpiRow kpis={result.kpis} outcomes={result.outcomes} />
			<ModelWarnings warnings={result.warnings} />
			{result.inputReadiness && (
				<section class="panel">
					<h2>
						{result.inputReadiness.provisional
							? "Refine this estimate"
							: "Input readiness"}
					</h2>
					<p class="muted small">
						Input completeness does not verify statements or guarantee an
						outcome. Review the missing or estimated inputs that matter to your
						plan.
					</p>
					<details>
						<summary>Provided, estimated and missing inputs</summary>
						<ul>
							{result.inputReadiness.items.map((item) => (
								<li key={item.path}>
									<strong>
										{humanPath(item.path)}: {item.status}
									</strong>{" "}
									— {item.detail}{" "}
									{item.status !== "provided" && (
										<button
											class="linkish"
											type="button"
											onClick={() => onRefine(item.path)}
										>
											Review input
										</button>
									)}
								</li>
							))}
						</ul>
					</details>
				</section>
			)}
			<OutcomeSummary result={result} />
			<SpendingDetail rows={result.cashFlow} outcomes={result.outcomes} />
			<section class="panel">
				<h2>Cash flow</h2>
				<p class="muted small">
					Amounts in {units}. Above zero: income. Below zero: spending and
					taxes. The lower line shows net worth.
				</p>
				<div class="chart-legend">
					<span class="legend-income">● Income</span>
					<span class="legend-spending">■ Spending</span>
					<span class="legend-taxes">▰ Taxes</span>
					<span class="legend-networth">— Net worth</span>
				</div>
				<CashFlowChart
					rows={result.cashFlow}
					retirementYear={Number.isFinite(retirement) ? retirement : undefined}
				/>
			</section>
			<section class="panel">
				<h2>Range of simulated outcomes</h2>
				<p class="muted small">
					Net worth in {units}. The outer band spans the 10th–90th percentiles;
					the inner band spans the 25th–75th. The median is the middle simulated
					result. The projection line follows the configured assumptions. These
					are simulated ranges, not guarantees.
				</p>
				<div class="chart-legend">
					<span class="legend-fan">▰ Simulated ranges</span>
					<span class="legend-median">┄ Simulated median</span>
					<span class="legend-networth">— Configured projection</span>
				</div>
				<MonteCarloFan
					percentiles={result.mc.percentiles}
					cashFlow={result.cashFlow}
					medianFinal={result.kpis.medianFinalNetWorth}
					yearlyPercentiles={result.mc.yearlyPercentiles}
				/>
			</section>
			<details>
				<summary>Result data ({result.cashFlow.length} years)</summary>
				<pre class="data">{JSON.stringify(result, null, 2)}</pre>
			</details>
		</>
	);
}
function humanPath(path: string) {
	return path
		.replace(
			/accounts\[(\d+)\]/g,
			(_, index: string) => `Account ${Number(index) + 1}`,
		)
		.replace(/[._]/g, " ")
		.replace(/\b\w/g, (character) => character.toUpperCase());
}
