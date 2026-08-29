import { fmtMoney, fmtPct } from "../lib/format";
import type { Kpis } from "@engine";

interface KpiRowProps {
  kpis: Kpis;
}

export function KpiRow({ kpis }: KpiRowProps) {
  const items: Array<{ label: string; value: string; tone?: "good" | "bad" | "neutral" }> = [
    {
      label: "Success rate",
      value: fmtPct(kpis.successRate),
      tone: kpis.successRate >= 0.9 ? "good" : kpis.successRate >= 0.7 ? "neutral" : "bad",
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
    { label: "Simulations", value: kpis.numSimulations.toLocaleString(), tone: "neutral" },
  ];

  return (
    <div class="kpi-row" role="list">
      {items.map((it) => (
        <div class="kpi" role="listitem" data-tone={it.tone ?? "neutral"}>
          <span class="kpi-label">{it.label}</span>
          <span class="kpi-value">{it.value}</span>
        </div>
      ))}
    </div>
  );
}
