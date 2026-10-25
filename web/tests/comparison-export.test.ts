import { h, render } from "preact";
import { act } from "preact/test-utils";
import { describe, expect, it } from "vitest";
import { PlanComparison } from "../src/components/plan-comparison";
import { cashFlowCsv } from "../src/lib/export";
import type { RunResult } from "../src/engine/types";
const result = {
	kpis: { medianFinalNetWorth: 1000, medianLifetimeTaxes: 0 },
	outcomes: {
		planned_spending_met_rate: 0.5,
		adjusted_spending_met_rate: 1,
		account_access_met_rate: null,
		legacy_target_base_year: 0,
	},
	cashFlow: [
		{
			year: 2027,
			fundingShortfallCauses: ["account_access", "liquid_capital"],
		},
	],
} as unknown as RunResult;
describe("comparison and export", () => {
	it("compares completed baseline measures with percentage-point changes", () => {
		const host = document.createElement("div");
		act(() =>
			render(
				h(PlanComparison, {
					result,
					name: "Baseline",
					current: true,
					sims: 500,
					seed: 42,
				}),
				host,
			),
		);
		act(() => (host.querySelector("button") as HTMLButtonElement).click());
		act(() =>
			render(
				h(PlanComparison, {
					result: {
						...result,
						outcomes: { ...result.outcomes!, planned_spending_met_rate: 0.7 },
					},
					name: "Variant",
					current: true,
					sims: 500,
					seed: 42,
				}),
				host,
			),
		);
		expect(host.textContent).toContain("20.0 percentage points");
		expect(host.textContent).toContain("Unassessed / not set");
	});
	it("exports explicit annual columns and preserves overlapping cause names", () => {
		const csv = cashFlowCsv(result);
		expect(csv).toContain("plannedExpenses");
		expect(csv).toContain('"account_access; liquid_capital"');
	});
});
