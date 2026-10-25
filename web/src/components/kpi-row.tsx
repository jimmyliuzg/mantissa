import { fmtMoney, fmtPct } from "../lib/format";
import type { GoalOutcomes, Kpis } from "@engine";

interface KpiRowProps {
  kpis: Kpis;
  outcomes?: GoalOutcomes;
}

export function KpiRow({ kpis, outcomes }: KpiRowProps) {
  const items: Array<{ label: string; value: string; tone?: "good" | "warn" | "bad" | "neutral" }> =
    [
      {
        label: kpis.provisional ? "Provisional combined success (legacy)" : "Combined success (legacy)",
        value: fmtPct(kpis.successRate),
        tone: "neutral",
      },
      { label: "Median final net worth", value: fmtMoney(kpis.medianFinalNetWorth) },
      { label: "P10 final net worth", value: fmtMoney(kpis.p10FinalNetWorth), tone: "neutral" },
      { label: "P90 final net worth", value: fmtMoney(kpis.p90FinalNetWorth), tone: "good" },
      { label: "Median lifetime taxes", value: fmtMoney(kpis.medianLifetimeTaxes) },
      {
        label: "Out-of-savings rate (legacy)",
        value: fmtPct(kpis.outOfSavingsRate),
        tone: kpis.outOfSavingsRate > 0.1 ? "bad" : "neutral",
      },
      ...(kpis.accessAssessed === false ? [{ label: "Account access", value: "Unassessed", tone: "warn" as const }] : []),
      ...(kpis.spendingCutFrequency === undefined ? [] : [
        { label: "Runs needing spending cuts", value: fmtPct(kpis.spendingCutFrequency) },
        { label: "Median years with cuts", value: String(kpis.medianYearsWithSpendingCuts ?? 0) },
        { label: "Deepest annual spending cut", value: fmtPct(kpis.maximumSpendingCutFraction ?? 0) },
      ]),
      ...(kpis.accessFailureRate === undefined
        ? []
        : [
            {
              label: "Account access failure rate",
              value: fmtPct(kpis.accessFailureRate),
              tone: kpis.accessFailureRate > 0 ? ("warn" as const) : ("neutral" as const),
            },
          ]),
      ...(kpis.portfolioDepletionRate === undefined
        ? []
        : [
            {
              label: "Portfolio depletion rate",
              value: fmtPct(kpis.portfolioDepletionRate),
              tone: kpis.portfolioDepletionRate > 0.1 ? ("bad" as const) : ("neutral" as const),
            },
          ]),
      { label: "Simulations", value: kpis.numSimulations.toLocaleString(), tone: "neutral" },
    ];

  const primary = outcomes ? [
    { label: "Planned spending met without cuts", value: fmtPct(outcomes.planned_spending_met_rate) },
    { label: "Adjusted budget funded", value: fmtPct(outcomes.adjusted_spending_met_rate) },
    { label: "No account-access gaps", value: outcomes.account_access_met_rate === null ? "Unassessed" : fmtPct(outcomes.account_access_met_rate) },
    { label: "After-estate legacy target met", value: outcomes.legacy_target_base_year > 0 ? fmtPct(outcomes.legacy_target_met_rate) : "No target set" },
  ] : [];
  const cards = (rows: typeof items) => <div class="kpi-row" role="list">
    {rows.map((it) => <div key={it.label} class="kpi" role="listitem" data-tone={it.tone ?? "neutral"}>
      <span class="kpi-label">{it.label}</span><span class="kpi-value">{it.value}</span>
    </div>)}
  </div>;
  return <>
    {outcomes && cards(primary)}
    {outcomes ? <details><summary>Financial metrics, spending cuts and compatibility results</summary>{cards(items)}</details> : cards(items)}
  </>;
}
