import { h, render } from "preact";
import { describe, expect, it } from "vitest";
import type { GoalOutcomes, RunResult } from "../src/engine/types";
import { KpiRow } from "../src/components/kpi-row";
import { OutcomeSummary, SpendingDetail } from "../src/components/outcome-summary";

const outcomes: GoalOutcomes = {
  schema_version:1,planned_spending_met_rate:0,adjusted_spending_met_rate:1,
  account_access_met_rate:1,legacy_target_met_rate:0,
  denominators:{spending:10,account_access:10,legacy:10},base_year:2030,
  terminal_estate_estimate_runs:10,monetary_convention:"real",legacy_target_base_year:200_000,
  first_funding_shortfall_year_counts:{},first_funding_shortfall_cause_counts:{},
};
const result: RunResult = {
  kpis:{successRate:0,medianFinalNetWorth:88_000,p10FinalNetWorth:0,p90FinalNetWorth:1e6,
    medianLifetimeTaxes:0,outOfSavingsRate:0,numSimulations:10},outcomes,cashFlow:[],
  warnings:[],mc:{percentiles:[],method:"gaussian",yearlyPercentiles:[]},runtimeMs:0,generatedAt:0,
};

describe("goal outcome presentation",()=>{
  it("reports funded adjusted spending separately from planned spending and legacy",()=>{
    const host=document.createElement('div');
    render(h(KpiRow,{kpis:result.kpis,outcomes}),host);
    const cards=host.querySelectorAll('.kpi-row')[0]!.textContent!;
    expect(cards).toContain('Planned spending met without cuts0.0%');
    expect(cards).toContain('Adjusted budget funded100.0%');
    expect(cards).toContain('After-estate legacy target met0.0%');
    expect(host.textContent).toContain('Combined success (legacy)');
  });
  it("leaves unknown access unassessed and explains denominators",()=>{
    const unknown={...outcomes,account_access_met_rate:null,denominators:{...outcomes.denominators,account_access:0}};
    const host=document.createElement('div');
    render(h(OutcomeSummary,{result:{...result,outcomes:unknown}}),host);
    expect(host.textContent).toContain('Account access is unassessed');
    expect(host.textContent).toContain('0 assessed runs');
    expect(host.textContent).toContain('independently of earlier funding gaps');
  });
  it("does not invent separate outcomes for old snapshots",()=>{
    const host=document.createElement('div');
    render(h(OutcomeSummary,{result:{...result,outcomes:undefined}}),host);
    expect(host.textContent).toContain('Separate spending, access and legacy outcomes are unavailable');
    expect(host.textContent).toContain('Rerun');
  });
  it("does not infer over-saving or an average-market path from terminal wealth",()=>{
    const host=document.createElement('div');
    render(h(OutcomeSummary,{result:{...result,kpis:{...result.kpis,successRate:1,medianFinalNetWorth:50e6}}}),host);
    expect(host.textContent).not.toMatch(/over-saving|retire earlier|average market|nearly all/);
  });
  it("shows overlapping first-gap causes without adding their counts",()=>{
    const host=document.createElement('div');
    render(h(OutcomeSummary,{result:{...result,outcomes:{...outcomes,
      first_funding_shortfall_year_counts:{2031:2},first_funding_shortfall_cause_counts:{account_access:2,liquid_capital:2}}}}),host);
    expect(host.textContent).toContain('2031');
    expect(host.textContent).toContain('counts should not be added');
    expect(host.textContent).toContain('Account access: 2 runs');
  });
  it("shows planned, adjusted, cut and unfunded amounts on the deterministic path",()=>{
    const host=document.createElement('div');
    render(h(SpendingDetail,{rows:[{year:2031,primaryAge:41,spouseAge:null,income:0,
      plannedExpenses:20_000,expenses:18_000,spendingCut:2000,taxes:0,netWorth:5000,
      netCashFlow:-18_000,fundingShortfall:1000,adjustedSpendingMet:false,fundingShortfallCauses:['account_access']}]}),host);
    expect(host.textContent).toContain('first funding gap in 2031');
    expect(host.textContent).toContain('Planned expenses');
    expect(host.textContent).toContain('Adjusted expenses');
    expect(host.textContent).toContain('Unmet funding');
    expect(host.textContent).toContain('Account access');
  });
});
