import { h, render } from "preact";
import { act } from "preact/test-utils";
import { describe, expect, it } from "vitest";
import { Wizard } from "../src/pages/wizard";
import { KpiRow } from "../src/components/kpi-row";
import { createPlanStore } from "../src/state/plan-store";

function click(host: HTMLElement, text: string) {
  const button = Array.from(host.querySelectorAll("button")).find((el) => el.textContent?.includes(text));
  expect(button, text).toBeDefined();
  act(() => button!.click());
}

describe("optional refinements", () => {
  it("keeps the short path and preserves optional account input when navigating", () => {
    const host = document.createElement("div");
    act(() => render(h(Wizard, {}), host));
    click(host, "Next"); click(host, "Next");
    expect(host.textContent).toContain("Use a total for now");
    expect(host.textContent).toContain("account access unassessed");
    click(host, "Break down my accounts");
    const input=Array.from(host.querySelectorAll("label")).find(el=>el.textContent?.includes("Taxable brokerage"))!.querySelector("input")!;
    act(() => {input.value="123000";input.dispatchEvent(new Event("input",{bubbles:true}));});
    expect(host.textContent).toContain("$123.0k");
    click(host,"Next");click(host,"Back");
    expect(host.textContent).toContain("$123.0k");
    expect(host.querySelectorAll("details")).toHaveLength(1);
  });
  it("labels provisional outcomes and unassessed access", () => {
    const host=document.createElement("div");
    render(h(KpiRow,{kpis:{successRate:1,provisional:true,accessAssessed:false,medianFinalNetWorth:1e6,p10FinalNetWorth:0,p90FinalNetWorth:2e6,medianLifetimeTaxes:0,outOfSavingsRate:0,numSimulations:10,spendingCutFrequency:.5,maximumSpendingCutFraction:.1,medianYearsWithSpendingCuts:3}}),host);
    expect(host.textContent).toContain("Provisional combined success (legacy)");
    expect(host.textContent).toContain("Unassessed");
    expect(host.textContent).toContain("Runs needing spending cuts");
    expect(host.textContent).not.toContain("Account access failure rate");
  });
  it("marks an edited estimate provided without clearing other estimates", () => {
    const store=createPlanStore({primary:{birth_date:"1990-01-01"},input_metadata:{estimated_fields:["primary.birth_date","economic.inflation"]}});
    store.setConfigField("primary.birth_date","1989-02-01");
    expect((store.config.value as {input_metadata:{estimated_fields:string[]}}).input_metadata.estimated_fields).toEqual(["economic.inflation"]);
  });
});
