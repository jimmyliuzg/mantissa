import { useState } from "preact/hooks";
import type { RunResult } from "@engine";
import { fmtMoney, fmtPct } from "../lib/format";
interface Baseline {
	name: string;
	result: RunResult;
	sims: number;
	seed: number;
}
export function PlanComparison({
	result,
	name,
	current,
	sims,
	seed,
}: {
	result: RunResult;
	name: string;
	current: boolean;
	sims: number;
	seed: number;
}) {
	const [baseline, setBaseline] = useState<Baseline | null>(null);
	const rows: Array<{
		label: string;
		read: (r: RunResult) => number | null;
		money?: boolean;
	}> = [
		{
			label: "Planned spending met without cuts",
			read: (r) => r.outcomes?.planned_spending_met_rate ?? null,
		},
		{
			label: "Adjusted budget funded",
			read: (r) => r.outcomes?.adjusted_spending_met_rate ?? null,
		},
		{
			label: "No account-access gaps",
			read: (r) => r.outcomes?.account_access_met_rate ?? null,
		},
		{
			label: "After-estate legacy target met",
			read: (r) =>
				r.outcomes && r.outcomes.legacy_target_base_year > 0
					? r.outcomes.legacy_target_met_rate
					: null,
		},
		{
			label: "Median final net worth",
			read: (r) => r.kpis.medianFinalNetWorth,
			money: true,
		},
		{
			label: "Median lifetime taxes",
			read: (r) => r.kpis.medianLifetimeTaxes,
			money: true,
		},
	];
	const show = (v: number | null, money?: boolean) =>
		v === null ? "Unassessed / not set" : money ? fmtMoney(v) : fmtPct(v);
	return (
		<section class="panel" aria-label="Compare a baseline">
			<h2>Compare a change</h2>
			<p class="muted small">
				Save these results as a baseline, then edit retirement timing, spending
				or contributions. Both plans use the same engine. The baseline stays in
				this tab until you leave or reload.
			</p>
			<button
				class="btn"
				type="button"
				disabled={!current}
				onClick={() => setBaseline({ name, result, sims, seed })}
			>
				{baseline
					? "Replace baseline with current results"
					: "Save results as baseline"}
			</button>
			{baseline && (
				<>
					<button class="btn" type="button" onClick={() => setBaseline(null)}>
						Clear baseline
					</button>
					<p>
						Baseline: {baseline.name}. {baseline.sims.toLocaleString()}{" "}
						simulations; seed {baseline.seed}.
					</p>
					{!current && (
						<p role="status">
							Current inputs changed. Run the projection to compare the latest
							inputs.
						</p>
					)}
					{(baseline.sims !== sims || baseline.seed !== seed) && (
						<p class="error">
							Simulation count or seed differs; use the same settings for a more
							useful comparison.
						</p>
					)}
					<div class="table-wrap">
						<table class="review-data-table">
							<caption>Baseline and current completed results</caption>
							<thead>
								<tr>
									<th>Measure</th>
									<th>Baseline</th>
									<th>Current</th>
									<th>Change</th>
								</tr>
							</thead>
							<tbody>
								{rows.map((row) => {
									const a = row.read(baseline.result),
										b = row.read(result);
									return (
										<tr key={row.label}>
											<th>{row.label}</th>
											<td>{show(a, row.money)}</td>
											<td>{show(b, row.money)}</td>
											<td>
												{a === null || b === null
													? "—"
													: row.money
														? fmtMoney(b - a)
														: `${((b - a) * 100).toFixed(1)} percentage points`}
											</td>
										</tr>
									);
								})}
							</tbody>
						</table>
					</div>
				</>
			)}
		</section>
	);
}
