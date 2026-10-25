import type { CashFlowRow, GoalOutcomes, RunResult } from "@engine";
import { fmtMoney, fmtPct } from "../lib/format";

const causeLabels: Record<string, string> = {
  account_access: "Account access",
  unassessed_access: "Account access unassessed",
  liquid_capital: "Spendable-capital shortfall",
  housing_purchase: "Housing purchase funding",
  funding_gap: "Combined funding gap",
};

export function OutcomeSummary({ result }: { result: RunResult }) {
  const o = result.outcomes;
  if (!o) return <p class="plan-summary" data-tone="info">
    This saved result reports combined success of {fmtPct(result.kpis.successRate)}.
    Separate spending, access and legacy outcomes are unavailable. Rerun the plan to calculate them.
  </p>;
  const gapYears = Object.keys(o.first_funding_shortfall_year_counts).sort();
  return <section class="panel" aria-label="Outcome definitions">
    <h2>Outcome notes</h2>
    <p>Spending coverage, account access and legacy attainment measure different parts of the plan.</p>
    <p>Legacy target: {fmtMoney(o.legacy_target_base_year)} in {o.base_year} purchasing power.{o.legacy_target_base_year === 0 && " No positive legacy target is specified."}</p>
    {result.kpis.provisional && <p>This is a provisional estimate. Refine missing and estimated inputs before using it to set a retirement date.</p>}
    <details><summary>How these outcomes are measured</summary>
    <p>Adjusted budgets include modeled expenses, taxes and required housing funding. Planned spending requires that funding without cuts above $1 in base-year dollars. These measure the simulated path; they do not rerun a higher budget that the strategy reduced.</p>
    <p>Account access measures gaps attributable to restricted balances. It can be clear even when spendable capital runs out.
      {o.account_access_met_rate === null && " Account access is unassessed because account detail is incomplete or the unrestricted diagnostic policy is enabled."}
    </p>
    <p>Legacy attainment compares final wealth after estate tax with a target of {fmtMoney(o.legacy_target_base_year)} in {o.base_year} purchasing power, independently of earlier funding gaps.
      {o.terminal_estate_estimate_runs > 0 && ` ${o.terminal_estate_estimate_runs} runs use a terminal estate-tax estimate for this goal; historical cash-flow and combined-success values are unchanged.`}
    </p>
    <p class="muted small">Spending and legacy rates use {o.denominators.spending} and {o.denominators.legacy} runs; account access uses {o.denominators.account_access} assessed runs. Combined success retains the historical joint metric.</p>
    </details>
    <details><summary>Monte Carlo funding gaps</summary>
      <p>{gapYears.length ? `Earliest first funding gap in any run: ${gapYears[0]}.` : "No funding gaps occurred in these runs."}</p>
      {gapYears.length > 0 && <ul>{gapYears.map(year => <li key={year}>{year}: {o.first_funding_shortfall_year_counts[year]} runs with their first gap</li>)}</ul>}
      {Object.keys(o.first_funding_shortfall_cause_counts).length > 0 && <>
        <p>Causes of the first gap can overlap; their counts should not be added.</p>
        <ul>{Object.entries(o.first_funding_shortfall_cause_counts).map(([cause, count]) => <li key={cause}>{causeLabels[cause] ?? cause}: {count} runs</li>)}</ul>
      </>}
    </details>
  </section>;
}

export function SpendingDetail({ rows, outcomes }: { rows: CashFlowRow[]; outcomes?: GoalOutcomes }) {
  if (!rows.some(row => row.fundingShortfall !== undefined)) return null;
  const firstGap = rows.find(row => row.adjustedSpendingMet === false);
  return <section class="panel">
    <h2>Spending and funding</h2>
    <p>Deterministic projection: {firstGap ? `first funding gap in ${firstGap.year}.` : "no funding gaps."} The table compares planned and adjusted expense budgets; unmet funding also includes taxes and required housing purchases.</p>
    {outcomes && <p class="muted small">Amounts are {outcomes.monetary_convention === "real" ? `in ${outcomes.base_year} purchasing power` : "in nominal dollars for each year"}.</p>}
    <details><summary>Annual spending, cuts and funding gaps</summary>
      <div class="table-wrap"><table class="review-data-table">
        <thead><tr><th>Year</th><th>Planned expenses</th><th>Adjusted expenses</th><th>Budget cut</th><th>Unmet funding</th><th>Cause</th></tr></thead>
        <tbody>{rows.map(row => <tr key={row.year}>
          <th>{row.year}</th><td>{row.plannedExpenses === undefined ? "Unavailable" : fmtMoney(row.plannedExpenses)}</td><td>{fmtMoney(row.expenses)}</td><td>{fmtMoney(row.spendingCut ?? 0)}</td><td>{fmtMoney(row.fundingShortfall ?? 0)}</td>
          <td>{row.fundingShortfallCauses?.map(cause => causeLabels[cause] ?? cause).join(", ") || "None"}</td>
        </tr>)}</tbody>
      </table></div>
    </details>
  </section>;
}
