import { h, render } from "preact";
import { describe, expect, it } from "vitest";
import { KpiRow } from "../src/components/kpi-row";

const baseline = {
  successRate: 0.8,
  medianFinalNetWorth: 1_000_000,
  p10FinalNetWorth: 0,
  p90FinalNetWorth: 2_000_000,
  medianLifetimeTaxes: 100_000,
  outOfSavingsRate: 0.2,
  numSimulations: 100,
};

describe("access outcome KPIs", () => {
  it("shows access and depletion outcomes separately", () => {
    const host = document.createElement("div");
    render(
      h(KpiRow, { kpis: { ...baseline, accessFailureRate: 0.1, portfolioDepletionRate: 0.15 } }),
      host,
    );
    const text = host.textContent ?? "";
    expect(text).toContain("Account access failure rate");
    expect(text).toContain("Portfolio depletion rate");
    expect(text).toContain("10.0%");
    expect(text).toContain("15.0%");
  });

  it("does not imply access validation in old snapshots", () => {
    const host = document.createElement("div");
    render(h(KpiRow, { kpis: baseline }), host);
    expect(host.textContent).not.toContain("Account access failure rate");
  });
});
