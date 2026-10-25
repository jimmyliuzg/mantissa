import { fmtMoney, fmtPct } from "../lib/format";
import { successTone } from "../lib/success";
import type { Kpis } from "@engine";

interface KpiRowProps {
  kpis: Kpis;
}

export function KpiRow({ kpis }: KpiRowProps) {
  const items: Array<{ label: string; value: string; tone?: "good" | "warn" | "bad" | "neutral" }> =
    [
      {
        label: kpis.provisional ? "Provisional success rate" : "Success rate",
        value: fmtPct(kpis.successRate),
        // Same band as the plan summary below the charts — one table
        // (lib/success) so the two can never disagree.
        tone: kpis.provisional ? "neutral" : successTone(kpis.successRate),
      },
      { label: "Median final net worth", value: fmtMoney(kpis.medianFinalNetWorth) },
      { label: "P10 final net worth", value: fmtMoney(kpis.p10FinalNetWorth), tone: "neutral" },
      { label: "P90 final net worth", value: fmtMoney(kpis.p90FinalNetWorth), tone: "good" },
      { label: "Median lifetime taxes", value: fmtMoney(kpis.medianLifetimeTaxes) },
      {
        label: "Out-of-savings rate",
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

  return (
    <div class="kpi-row" role="list">
      {items.map((it) => (
        <div key={it.label} class="kpi" role="listitem" data-tone={it.tone ?? "neutral"}>
          <span class="kpi-label">{it.label}</span>
          <span class="kpi-value">{it.value}</span>
        </div>
      ))}
    </div>
  );
}
