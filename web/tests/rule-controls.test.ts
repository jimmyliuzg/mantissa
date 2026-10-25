import { signal } from "@preact/signals";
import { h, render } from "preact";
import { act } from "preact/test-utils";
import { afterEach, describe, expect, it } from "vitest";
import { RuleControls } from "../src/components/rule-controls";
import { getPath } from "../src/lib/config-edit";
import { configFieldId } from "../src/lib/guided-editor";
import type { PlanStore } from "../src/state/plan-store";

const SAMPLE = {
  name: "Example plan",
  start_year: 2026,
  primary: { name: "Alex", birth_date: "1980-01-01", retirement_date: "2040-01-01" },
  spouse: { name: "Sam", birth_date: "1981-01-01", retirement_date: "2041-01-01" },
};
let host: HTMLDivElement | undefined;

function mount(initial: unknown = SAMPLE) {
  const config = signal<unknown>(structuredClone(initial));
  const replaceConfig = (next: unknown) => {
    config.value = next;
  };
  const store = {
    config,
    sims: signal(1000),
    seed: 42,
    state: signal({ kind: "idle" }),
    replaceConfig,
    setConfigField() {},
    removeConfigField() {},
    setSims() {},
  } as unknown as PlanStore;
  host = document.createElement("div");
  document.body.append(host);
  act(() => render(h(RuleControls, { store }), host!));
  return store;
}

function select(path: string, value: string) {
  const element = document.getElementById(configFieldId(path)) as HTMLSelectElement;
  expect(element).not.toBeNull();
  act(() => {
    element.value = value;
    element.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

function input(path: string, value: string, blur = false) {
  const element = document.getElementById(configFieldId(path)) as HTMLInputElement;
  expect(element).not.toBeNull();
  act(() => {
    element.value = value;
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    if (blur) element.dispatchEvent(new Event("blur", { bubbles: false }));
  });
}

function button(label: string) {
  const found = [...host!.querySelectorAll("button")].find(
    (element) => element.textContent === label,
  );
  expect(found).toBeDefined();
  return found!;
}

afterEach(() => {
  if (host) act(() => render(null, host!));
  host?.remove();
  host = undefined;
});

describe("contribution and future rule controls", () => {
  it("starts collapsed with unknown eligibility and leaves defaults unset", () => {
    const store = mount();
    const details = [...host!.querySelectorAll("details")];
    expect(details.every((item) => !item.open)).toBe(true);
    expect(
      (
        document.getElementById(
          configFieldId("contribution_policy.owners.primary.workplace_plan"),
        ) as HTMLSelectElement
      ).value,
    ).toBe("unknown");
    expect(
      (
        document.getElementById(
          configFieldId("contribution_policy.owners.primary.ira_deduction"),
        ) as HTMLSelectElement
      ).value,
    ).toBe("unknown");
    expect(
      (
        document.getElementById(
          configFieldId("contribution_policy.owners.primary.hsa_eligible"),
        ) as HTMLInputElement
      ).checked,
    ).toBe(false);
    expect(getPath(store.config.value, "contribution_policy")).toBeUndefined();
    expect(getPath(store.config.value, "policy")).toBeUndefined();
  });

  it("serializes owner eligibility, employer HSA deposits, and optional months", () => {
    const store = mount();
    select("contribution_policy.owners.primary.workplace_plan", "yes");
    select("contribution_policy.owners.primary.ira_deduction", "nondeductible");
    const eligible = document.getElementById(
      configFieldId("contribution_policy.owners.primary.hsa_eligible"),
    ) as HTMLInputElement;
    const spousal = document.getElementById(
      configFieldId("contribution_policy.owners.primary.spousal_ira_eligible"),
    ) as HTMLInputElement;
    act(() => {
      eligible.checked = true;
      eligible.dispatchEvent(new Event("change", { bubbles: true }));
      spousal.checked = true;
      spousal.dispatchEvent(new Event("change", { bubbles: true }));
    });
    select("contribution_policy.owners.primary.hsa_coverage", "family");
    input("contribution_policy.owners.primary.hsa_eligible_months", "6", true);
    input(
      "contribution_policy.owners.primary.hsa_employer_contribution_by_year.2026",
      "1250",
      true,
    );
    const owner = getPath(store.config.value, "contribution_policy.owners.primary") as Record<
      string,
      unknown
    >;
    expect(owner.workplace_plan).toBe(true);
    expect(owner.ira_deduction).toBe("nondeductible");
    expect(owner.spousal_ira_eligible).toBe(true);
    expect(owner.hsa_eligible).toBe(true);
    expect(owner.hsa_coverage).toBe("family");
    expect(owner.hsa_eligible_months).toBe(6);
    expect(owner.hsa_employer_contribution_by_year).toEqual({ 2026: 1250 });
    expect(getPath(store.config.value, "policy")).toBeUndefined();
  });

  it("creates valid policy metadata and stores percentage inputs as decimals", () => {
    const store = mount();
    input("policy.contribution_growth_rate", "2.5", true);
    act(() => button("Add temporary forecast").click());
    input("policy.changes.0.start_year", "2030", true);
    input("policy.changes.0.end_year", "2040", true);
    input("policy.changes.0.tax.federal_rate_addition", "5.5", true);
    input("policy.changes.0.contributions.hsa_individual", "5000", true);
    input("policy.changes.0.contributions.hsa_family", "10000", true);
    const policy = getPath(store.config.value, "policy") as Record<string, unknown>;
    expect(policy.schema_version).toBe(1);
    expect(policy.contribution_growth_rate).toBe(0.025);
    expect(policy.changes).toEqual([
      {
        id: "forecast-1",
        start_year: 2030,
        end_year: 2040,
        tax: { federal_rate_addition: 0.055 },
        contributions: { hsa_individual: 5000, hsa_family: 10000 },
      },
    ]);
  });

  it("holds invalid year drafts out of the policy until they are valid", () => {
    const store = mount();
    act(() => button("Add temporary forecast").click());
    input("policy.changes.0.start_year", "18");
    expect(getPath(store.config.value, "policy.changes.0.start_year")).toBe(2026);
    expect(host!.querySelector('[role="alert"]')?.textContent).toContain("at least 1900");
    input("policy.changes.0.start_year", "2031", true);
    expect(getPath(store.config.value, "policy.changes.0.start_year")).toBe(2031);
  });

  it("preserves existing advanced policy fields and removes only the selected forecast", () => {
    const advanced = {
      ...SAMPLE,
      policy: {
        schema_version: 1,
        contribution_growth_rate: 0.03,
        custom_policy_note: "keep me",
        changes: [
          {
            id: "first",
            start_year: 2030,
            end_year: 2035,
            tax: { standard_deduction: { mfj: 55_000 }, custom_tax_field: 9 },
            contributions: { hsa_family: 12_000, custom_contribution: 8 },
            custom_change_field: { preserve: true },
          },
          { id: "second", start_year: 2040, tax: {}, contributions: {} },
        ],
      },
    };
    const store = mount(advanced);
    input("policy.changes.0.tax.federal_rate_addition", "2", true);
    const changes = getPath(store.config.value, "policy.changes") as Record<string, unknown>[];
    expect(changes[0]).toMatchObject({
      id: "first",
      custom_change_field: { preserve: true },
      tax: {
        standard_deduction: { mfj: 55_000 },
        custom_tax_field: 9,
        federal_rate_addition: 0.02,
      },
      contributions: { hsa_family: 12_000, custom_contribution: 8 },
    });
    expect(getPath(store.config.value, "policy.custom_policy_note")).toBe("keep me");
    act(() => button("Remove forecast").click());
    expect(
      (getPath(store.config.value, "policy.changes") as Record<string, unknown>[]).map(
        (item) => item.id,
      ),
    ).toEqual(["second"]);
  });

  it("repairs a missing policy version on first policy edit without dropping other keys", () => {
    const store = mount({ ...SAMPLE, policy: { custom_policy_note: "keep" } });
    input("policy.tax_threshold_growth_rate", "3", true);
    expect(getPath(store.config.value, "policy.schema_version")).toBe(1);
    expect(getPath(store.config.value, "policy.changes")).toEqual([]);
    expect(getPath(store.config.value, "policy.custom_policy_note")).toBe("keep");
  });
});
