import { h, render } from "preact";
import { act } from "preact/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Wizard, WIZARD_DRAFT_KEY } from "../src/pages/wizard";
import { PlanReview } from "../src/components/plan-review";
import { Landing } from "../src/pages/landing";
import { buildSlimConfig, DEFAULT_ANSWERS } from "../src/slim/types";

let host: HTMLDivElement;
beforeEach(() => { sessionStorage.clear(); host = document.createElement("div"); document.body.append(host); });
afterEach(() => { act(() => render(null, host)); host.remove(); vi.restoreAllMocks(); });
function click(text: string) {
  const el = [...host.querySelectorAll("button")].find((button) => button.textContent?.includes(text));
  expect(el, text).toBeTruthy();
  act(() => el!.click());
}
function field(text: string) {
  const el = [...host.querySelectorAll("label")].find((label) => label.textContent?.includes(text))?.querySelector("input");
  expect(el, text).toBeTruthy(); return el!;
}
function fill(text: string, value: string) {
  act(() => { const el = field(text); el.value = value; el.dispatchEvent(new Event("input", { bubbles: true })); });
}

describe("website onboarding reliability", () => {
  it("accepts exact savings and income while rejecting blank or negative required values", () => {
    act(() => render(h(Wizard, {}), host));
    click("Next"); click("Next");
    fill("Investable assets", "250001.37");
    expect(field("Investable assets").validity.valid).toBe(true);
    click("Next");
    expect(host.textContent).toContain("Your current income");
    fill("Annual income", "123456.78");
    expect(field("Annual income").validity.valid).toBe(true);
    click("Next");
    fill("Annual spending in retirement", "");
    click("Next");
    expect(host.textContent).toContain("Step 5 of 9");
    fill("Annual spending in retirement", "-1");
    click("Next");
    expect(host.textContent).toContain("Step 5 of 9");
  });
  it("restores the exact step and answers after remount and resets explicitly", () => {
    act(() => render(h(Wizard, {}), host));
    click("Next"); click("Next");
    fill("Investable assets", "789123"); click("Next");
    act(() => render(null, host));
    act(() => render(h(Wizard, {}), host));
    expect(host.textContent).toContain("Step 4 of 9");
    click("Back"); expect(field("Investable assets").value).toBe("789123");
    click("Reset answers"); expect(host.textContent).toContain("Step 1 of 9");
    expect(JSON.parse(sessionStorage.getItem(WIZARD_DRAFT_KEY)!).answers.investableAssets).toBe(250000);
  });
  it("announces choices, focuses each step and keeps the existing short path", () => {
    act(() => render(h(Wizard, {}), host));
    expect(document.activeElement).toBe(host.querySelector("h2"));
    click("Already retired");
    expect([...host.querySelectorAll("button")].find(el => el.textContent === "Already retired")?.getAttribute("aria-pressed")).toBe("true");
    expect(host.textContent).not.toContain("Age you want to retire");
    click("Next"); expect(document.activeElement).toBe(host.querySelector("h2"));
    click("Next"); click("Next");
    expect(host.textContent).toContain("No employment income");
  });
  it("warns about unsupported state coverage before results", () => {
    sessionStorage.setItem(WIZARD_DRAFT_KEY, JSON.stringify({ step: 5, answers: { ...DEFAULT_ANSWERS, state: "NY" } }));
    act(() => render(h(Wizard, {}), host));
    expect(host.textContent).toContain("State income tax is not modeled for NY");
    act(() => render(h(PlanReview, { config: buildSlimConfig({ ...DEFAULT_ANSWERS, state: "NY" }), sims: 1000, onRun() {} }), host));
    expect(host.textContent).toContain("State income tax is not modeled for NY");
    expect(host.textContent).not.toContain("$2.0k");
    expect(host.querySelector(".value-list")?.textContent).toContain(String(new Date().getFullYear() + 1));
    expect(host.textContent).not.toContain("None configured");
  });
  it("stages a reviewed wizard plan once and offers direct answer editing", () => {
    sessionStorage.setItem(WIZARD_DRAFT_KEY, JSON.stringify({ step: 8, answers: DEFAULT_ANSWERS }));
    act(() => render(h(Wizard, {}), host));
    act(() => host.querySelector<HTMLButtonElement>('[aria-label="Edit State"]')!.click());
    expect(host.textContent).toContain("Step 6 of 9");
    click("Next"); click("Next"); click("Next"); click("See results");
    expect(sessionStorage.getItem("mantissa:reviewed-config")).toBe(sessionStorage.getItem("mantissa:config"));
  });
  it("rejects malformed imports without replacing a working plan", async () => {
    sessionStorage.setItem("mantissa:config", "existing-plan");
    const open = vi.fn();
    act(() => render(h(Landing, { onOpenViewer: open, onOpenWizard() {} }), host));
    const input = host.querySelector<HTMLInputElement>('input[type="file"]')!;
    const file = new File(["[]"], "bad.json", { type: "application/json" });
    Object.defineProperty(file, "text", { value: async () => "[]" });
    Object.defineProperty(input, "files", { value: [file] });
    await act(async () => { input.dispatchEvent(new Event("change", { bubbles: true })); });
    expect(open).not.toHaveBeenCalled();
    expect(sessionStorage.getItem("mantissa:config")).toBe("existing-plan");
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("Could not import");
  });
  it("makes the sample a primary landing action and removes the unavailable report", () => {
    act(() => render(h(Landing, { onOpenViewer() {}, onOpenWizard() {} }), host));
    expect(host.textContent).toContain("Start a plan");
    expect(host.textContent).toContain("Explore a sample plan");
    expect(host.textContent).not.toContain("Coming soon");
  });
});

describe("optional wizard schedule contract", () => {
  it("omits employment for already-retired users and includes spouse benefits", () => {
    const config = buildSlimConfig({ ...DEFAULT_ANSWERS, alreadyRetired: true, hasSpouse: true, spouseAlreadyRetired: true, spouseMonthlySocialSecurity: 1801 });
    expect(config.income_streams).toEqual([]);
    expect(config.primary.retirement_date).toBe(`${config.start_year}-01-01`);
    expect(config.spouse!.retirement_date).toBe(`${config.start_year}-01-01`);
    expect(config.social_security.spouse_benefit_at_67).toBe(1801);
  });
  it("makes current and retirement budgets meet at the exclusive retirement boundary", () => {
    const config = buildSlimConfig({ ...DEFAULT_ANSWERS, currentAnnualSpending: 45001, annualSpending: 60001 });
    const current = config.expenses.find(expense => expense.id === "current-living")!;
    const retirement = config.expenses.find(expense => expense.id === "living")!;
    expect(current.monthly_amount * 12).toBeCloseTo(45001);
    expect(current.end_date).toBe(config.primary.retirement_date);
    expect(retirement.start_date).toBe(current.end_date);
    expect(retirement.monthly_amount * 12).toBeCloseTo(60001);
  });
});
