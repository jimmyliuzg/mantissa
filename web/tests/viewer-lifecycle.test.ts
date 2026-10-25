import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { h, render } from "preact";
import { act } from "preact/test-utils";
import type { RunResult } from "../src/engine/types";

const mocks = vi.hoisted(() => ({ ready: false, bootstrap: vi.fn(), run: vi.fn(), cancel: vi.fn() }));
vi.mock("@engine", () => ({ engine: { isReady: () => mocks.ready, bootstrap: mocks.bootstrap, run: mocks.run, cancel: mocks.cancel } }));
import { Viewer, ViewerBody } from "../src/pages/viewer";
import { decodeSnapshot, encodeSnapshot } from "../src/lib/share-codec";

const config = { name: "Synthetic lifecycle plan", primary: { name: "Example", birth_date: "1980-01-01", retirement_date: "2045-01-01", longevity_age: 95 }, spouse: null, economic: {}, accounts: [{id: "cash", name: "Cash", type: "checking", tax_treatment: "taxable", balance: 250001}], income_streams: [], expenses: [] };
const result: RunResult = {
  kpis: { successRate: .95, medianFinalNetWorth: 500000, p10FinalNetWorth: 100000, p90FinalNetWorth: 1000000, medianLifetimeTaxes: 50000, outOfSavingsRate: .05, numSimulations: 1000 },
  cashFlow: [{year: 2026, primaryAge: 46, spouseAge: null, income: 100000, expenses: 60000, taxes: 10000, netWorth: 280001, netCashFlow: 30000}],
  mc: {percentiles: [{percentile: 50, value: 500000}], yearlyPercentiles: [], method: "gaussian"},
  outcomes: {schema_version: 1, planned_spending_met_rate: .9, adjusted_spending_met_rate: .97, account_access_met_rate: null, legacy_target_met_rate: .8, terminal_estate_estimate_runs: 1000, denominators: {spending: 1000, account_access: 0, legacy: 1000}, base_year: 2026, monetary_convention: "real", legacy_target_base_year: 200000, first_funding_shortfall_year_counts: {"2040": 3}, first_funding_shortfall_cause_counts: {liquid_capital: 3}},
  warnings: [{year: null, severity: "warning", category: "coverage", message: "Synthetic coverage warning"}],
  inputReadiness: {provisional: true, access_assessed: false, items: [{path: "accounts[0].cost_basis", status: "missing", detail: "Synthetic missing basis"}]}, runtimeMs: 10, generatedAt: 12345,
};
let root: HTMLDivElement;
let writeText = vi.fn();
function initial(kind: "config" | "snapshot") { return { kind, config: structuredClone(config), sims: 1000, seed: 314159, ...(kind === "snapshot" ? {result} : {}) }; }
async function mount(kind: "config" | "snapshot") { await act(async () => render(h(ViewerBody, {initial: initial(kind)}), root)); }
async function settle(milliseconds = 700) { await act(async () => { await new Promise(resolve => setTimeout(resolve, milliseconds)); }); }
async function editName(value: string) {
  await act(async () => {
    const input = root.querySelector<HTMLInputElement>("#config-name");
    if (!input) throw new Error("Missing editable plan name");
    input.closest("details")!.open = true;
    input.value = value; input.dispatchEvent(new Event("change", {bubbles: true}));
  });
}
async function click(text: string) {
  await act(async () => {
    const button = [...root.querySelectorAll("button")].find(item => item.textContent === text);
    if (!button) throw new Error(`Missing button ${text}`);
    button.click();
  });
}

beforeEach(() => {
  root = document.createElement("div"); document.body.append(root);
  sessionStorage.clear(); localStorage.clear(); history.replaceState(null, "", "/#/review");
  vi.clearAllMocks(); mocks.ready = false;
  mocks.bootstrap.mockImplementation(async () => { mocks.ready = true; });
  mocks.run.mockResolvedValue(result);
  writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {configurable: true, value: {writeText}});
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
});
afterEach(() => { act(() => render(null, root)); root.remove(); vi.unstubAllGlobals(); });

describe("mounted viewer lifecycle", () => {
  it("keeps snapshots frozen without bootstrapping, then runs exactly once after an edit using the shared seed", async () => {
    history.replaceState(null, "", "/#/review?s=" + encodeSnapshot({config, sims: 1000, seed: 314159, result}));
    await mount("snapshot"); await settle();
    expect(mocks.bootstrap).not.toHaveBeenCalled(); expect(mocks.run).not.toHaveBeenCalled();
    expect(root.textContent).toContain("Synthetic coverage warning");
    expect(root.textContent).toContain("Planned spending met without cuts");
    await editName("Updated synthetic plan"); await settle();
    expect(mocks.bootstrap).toHaveBeenCalledTimes(1); expect(mocks.run).toHaveBeenCalledTimes(1);
    expect(mocks.run).toHaveBeenLastCalledWith(expect.objectContaining({name: "Updated synthetic plan"}), {simulations: 1000, method: "gaussian", seed: 314159});
    expect(location.hash).toBe("#/review");
    expect(JSON.parse(sessionStorage.getItem("mantissa:config")!)).toMatchObject({name: "Updated synthetic plan"});
  });
  it("runs a regular plan once on mount without a second debounced initial run", async () => {
    await mount("config"); await settle();
    expect(mocks.bootstrap).toHaveBeenCalledTimes(1); expect(mocks.run).toHaveBeenCalledTimes(1);
  });
  it("keeps previous results clearly stale after failure and exposes a working retry", async () => {
    await mount("snapshot");
    mocks.run.mockRejectedValueOnce(new Error("Synthetic calculation failure"));
    await editName("Failed variant"); await settle();
    expect(root.textContent).toContain("Calculation failed. Results below are from the previous completed run.");
    expect(root.textContent).toContain("Synthetic calculation failure");
    await click("Retry projection");
    expect(mocks.run).toHaveBeenCalledTimes(2);
    expect(root.textContent).not.toContain("Calculation failed. Results below");
  });
  it("presents malformed shared links as recoverable errors and preserves the local draft", async () => {
    const saved = JSON.stringify(config); sessionStorage.setItem("mantissa:config", saved);
    history.replaceState(null, "", "/#/review?s=s2-broken");
    await act(async () => render(h(Viewer, {}), root));
    expect(root.textContent).toContain("Could not open this plan");
    expect(root.querySelector('[role="alert"]')?.textContent).toBeTruthy();
    expect(sessionStorage.getItem("mantissa:config")).toBe(saved);
    expect(mocks.bootstrap).not.toHaveBeenCalled(); expect(mocks.run).not.toHaveBeenCalled();
  });
  it("shares all displayed outcomes, warnings and readiness from a mounted viewer", async () => {
    await mount("snapshot"); await click("Share plan"); await click("Create and copy link");
    const url = root.querySelector<HTMLTextAreaElement>('textarea[aria-label="Generated share link"]')!.value;
    const hash = new URLSearchParams(url.slice(url.indexOf("?") + 1)).get("s")!;
    const shared = decodeSnapshot(hash);
    expect(shared.result).toEqual(result);
    expect(shared.seed).toBe(314159); expect(writeText).toHaveBeenCalledWith(url);
    expect(mocks.bootstrap).not.toHaveBeenCalled(); expect(mocks.run).not.toHaveBeenCalled();
  });
});
