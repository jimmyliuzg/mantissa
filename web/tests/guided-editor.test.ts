import { signal } from "@preact/signals";
import { h, render } from "preact";
import { act } from "preact/test-utils";
import { afterEach, describe, expect, it } from "vitest";
import { ConfigDrawer } from "../src/components/config-drawer";
import { getPath, setPath } from "../src/lib/config-edit";
import {
	configFieldId,
	accountTax,
	effectiveSavingsOrder,
	focusConfigField,
	nextItemId,
	removeAccount,
	removeListItem,
	setSavingsOrder,
} from "../src/lib/guided-editor";
import type { PlanStore } from "../src/state/plan-store";

const SAMPLE = {
	name: "Example plan",
	primary: {
		name: "Alex",
		birth_date: "1980-01-01",
		retirement_date: "2040-01-01",
	},
	spouse: null,
	economic: { inflation: 0.0254 },
	accounts: [
		{
			id: "brokerage",
			name: "Investments",
			type: "brokerage",
			tax_treatment: "taxable",
			balance: 120000,
			cost_basis: 95000,
		},
		{
			id: "roth",
			name: "Roth IRA",
			type: "roth_ira",
			tax_treatment: "roth",
			balance: 30000,
		},
	],
	income_streams: [
		{
			id: "salary",
			name: "Salary",
			owner: "primary",
			monthly_amount: 5000,
			start_date: "2027-01-01",
			end_date: "2040-01-01",
		},
	],
	expenses: [
		{
			id: "living",
			name: "Living costs",
			monthly_amount: 3000,
			start_date: "2027-01-01",
			end_date: "2070-01-01",
		},
	],
	mortgages: [],
	withdrawal_strategy: "fixed",
	social_security: { primary_benefit_at_67: 2400, primary_claiming_age: 67 },
};
let host: HTMLDivElement | undefined;
function mount(initial: unknown = SAMPLE) {
	const config = signal<unknown>(structuredClone(initial));
  const sims = signal(1000);
	const history: unknown[] = [];
	const replaceConfig = (next: unknown) => {
		if (JSON.stringify(next) === JSON.stringify(config.value)) return;
		history.push(config.value);
		config.value = next;
	};
	const store = {
		config,
		sims,
		seed: 42,
		state: signal({ kind: "idle" }),
		replaceConfig,
		setConfigField(path: string, value: unknown) {
			replaceConfig(setPath(config.value, path, value));
		},
		removeConfigField(path: string) {
			replaceConfig(
				JSON.parse(JSON.stringify(setPath(config.value, path, undefined))),
			);
		},
		setSims(value: number) {
			sims.value = value;
		},
		history,
	} as unknown as PlanStore & { history: unknown[] };
	host = document.createElement("div");
	document.body.append(host);
	act(() => render(h(ConfigDrawer, { store }), host!));
	return store;
}
function change(path: string, value: string) {
	const element = document.getElementById(configFieldId(path)) as
		| HTMLInputElement
		| HTMLSelectElement;
	expect(element).not.toBeNull();
	act(() => {
		element.value = value;
		element.dispatchEvent(new Event("change", { bubbles: true }));
	});
}
function fillThenBlur(path: string, value: string) {
	const element = document.getElementById(configFieldId(path)) as HTMLInputElement;
	expect(element).not.toBeNull();
	act(() => {
		element.value = value;
		element.dispatchEvent(new Event("input", { bubbles: true }));
		element.dispatchEvent(new Event("blur", { bubbles: false }));
	});
}
function button(text: string): HTMLButtonElement {
	const found = [...host!.querySelectorAll("button")].find(
		(item) => item.textContent === text,
	);
	expect(found).toBeDefined();
	return found!;
}
afterEach(() => {
	if (host) {
		act(() => render(null, host!));
		host.remove();
		host = undefined;
	}
});

describe("guided editor", () => {
	it("renders real strategy choices and percentages without changing engine units", () => {
		const store = mount();
		expect(
			document.getElementById(configFieldId("withdrawal_strategy"))?.tagName,
		).toBe("SELECT");
		change("withdrawal_strategy", "percent_of_portfolio");
		expect(getPath(store.config.value, "withdrawal_strategy")).toBe(
			"percent_of_portfolio",
		);
		expect(
			(
				document.getElementById(
					configFieldId("withdrawal_rate"),
				) as HTMLInputElement
			).value,
		).toBe("4");
		change("economic.inflation", "3.125");
		expect(getPath(store.config.value, "economic.inflation")).toBe(0.03125);
		change("accounts.0.balance", "250001");
		expect(getPath(store.config.value, "accounts.0.balance")).toBe(250001);
	});
	it("commits typed text, number, date and cash-flow values on blur exactly once", () => {
		const store = mount();
		fillThenBlur("name", "Updated plan");
		fillThenBlur("accounts.0.balance", "234567");
		fillThenBlur("income_streams.0.end_date", "2038-01-01");
		fillThenBlur("income_streams.0.monthly_amount", "6200");
		expect(getPath(store.config.value, "name")).toBe("Updated plan");
		expect(getPath(store.config.value, "accounts.0.balance")).toBe(234567);
		expect(getPath(store.config.value, "income_streams.0.end_date")).toBe(
			"2038-01-01",
		);
		expect(getPath(store.config.value, "income_streams.0.monthly_amount")).toBe(
			6200,
		);
		expect(store.history).toHaveLength(4);
	});
	it("commits empty text on blur so the engine can validate the resulting config", () => {
		const store = mount();
		fillThenBlur("name", "");
		expect(getPath(store.config.value, "name")).toBe("");
		expect(store.history).toHaveLength(1);
	});
	it("clears optional basis instead of silently converting it to zero", () => {
		const store = mount();
		change("accounts.0.cost_basis", "");
		expect(
			getPath(store.config.value, "accounts.0.cost_basis"),
		).toBeUndefined();
		change("accounts.0.cost_basis", "110001.25");
		expect(getPath(store.config.value, "accounts.0.cost_basis")).toBe(
			110001.25,
		);
		act(() =>
			(
				host!.querySelector(
					'[aria-label="Use default for Taxable cost basis ($)"]',
				) as HTMLButtonElement
			).click(),
		);
		expect(
			getPath(store.config.value, "accounts.0.cost_basis"),
		).toBeUndefined();
	});
	it("adds named accounts with unique IDs and exposes relevant tax fields", () => {
		const store = mount();
		expect(
			document.getElementById(
				configFieldId("accounts.0.roth_first_contribution_year"),
			) === null,
		).toBe(true);
		expect(
			document.getElementById(
				configFieldId("accounts.1.roth_first_contribution_year"),
			),
		).not.toBeNull();
		act(() => button("Add account").click());
		change("accounts.2.name", "Workplace plan");
		change("accounts.2.type", "401k");
		expect(getPath(store.config.value, "accounts.2.tax_treatment")).toBe(
			"pre_tax",
		);
		expect(
			document.getElementById(configFieldId("accounts.2.cost_basis")),
		).toBeNull();
		const ids = (
			getPath(store.config.value, "accounts") as { id: string }[]
		).map((item) => item.id);
		expect(new Set(ids).size).toBe(3);
	});
	it("uses engine tax defaults and only exposes applicable Roth and owner fields", () => {
		const store = mount({ ...SAMPLE, spouse: { name: "Sam" } });
		change("accounts.0.type", "hsa");
		expect(getPath(store.config.value, "accounts.0.tax_treatment")).toBe(
			"tax_exempt",
		);
		expect(
			document.getElementById(
				configFieldId("accounts.0.roth_contribution_basis"),
			),
		).toBeNull();
		const owner = document.getElementById(
			configFieldId("accounts.0.owner"),
		) as HTMLSelectElement;
		expect([...owner.options].map((option) => option.value)).toEqual([
			"primary",
			"spouse",
		]);
		change("accounts.0.type", "529");
		expect(getPath(store.config.value, "accounts.0.tax_treatment")).toBe(
			"tax_exempt",
		);
		change("accounts.0.type", "roth_401k");
		expect(
			document.getElementById(
				configFieldId("accounts.0.roth_first_contribution_year"),
			),
		).not.toBeNull();
		expect(
			document.getElementById(
				configFieldId("accounts.0.roth_contribution_basis"),
			),
		).toBeNull();
		expect(accountTax("529")).toBe("tax_exempt");
	});
	it("converts annual amounts to the existing monthly contract and edits dates and Social Security", () => {
		const store = mount();
		const select = [...host!.querySelectorAll("select")].find(
			(item) => item.previousElementSibling?.textContent === "Amount frequency",
		)!;
		act(() => {
			select.value = "annual";
			select.dispatchEvent(new Event("change", { bubbles: true }));
		});
		change("income_streams.0.monthly_amount", "123456");
		change("income_streams.0.end_date", "2038-01-01");
		change("social_security.primary_benefit_at_67", "2345");
		change("social_security.primary_claiming_age", "70");
		expect(getPath(store.config.value, "income_streams.0.monthly_amount")).toBe(
			10288,
		);
		expect(getPath(store.config.value, "income_streams.0.end_date")).toBe(
			"2038-01-01",
		);
		expect(
			getPath(store.config.value, "social_security.primary_claiming_age"),
		).toBe(70);
		expect(
			getPath(store.config.value, "social_security.primary_benefit_at_67"),
		).toBe(2345);
	});
	it("reaches an input from a readiness path and opens collapsed sections", () => {
		mount();
		const field = document.getElementById(
			configFieldId("accounts[0].cost_basis"),
		)!;
		expect(field.closest("details")?.open).toBe(false);
		expect(focusConfigField("accounts[0].cost_basis")).toBe(true);
		expect(field.closest("details")?.open).toBe(true);
		expect(document.activeElement).toBe(field);
		expect(focusConfigField("accounts")).toBe(true);
	});
	it("preserves the last valid plan when Advanced JSON fails structural validation", () => {
		const store = mount();
		const original = store.config.value;
		const textarea = document.getElementById(
			"advanced-plan-json",
		) as HTMLTextAreaElement;
		act(() => {
			textarea.value = "[]";
			textarea.dispatchEvent(new Event("input", { bubbles: true }));
		});
		act(() => button("Apply JSON").click());
		expect(store.config.value).toBe(original);
		expect(host!.querySelector('[role="alert"]')?.textContent).toMatch(
			/object/,
		);
	});
	it("keeps complex income amounts in Advanced JSON to avoid overwriting salary or equity contracts", () => {
		mount({
			...SAMPLE,
			income_streams: [
				{ ...SAMPLE.income_streams[0], base_salary: { annual: 100000 } },
			],
		});
		expect(
			document.getElementById(configFieldId("income_streams.0.monthly_amount")),
		).toBeNull();
		expect(host!.textContent).toMatch(/detailed salary, bonus or equity/);
	});
});

describe("account routing safety", () => {
	it("removes routing references and reindexes readiness without mutating original input", () => {
		const config = {
			...SAMPLE,
			savings_order: ["brokerage", "roth"],
			surplus_account_id: "brokerage",
			input_metadata: {
				estimated_fields: [
					"accounts[0].cost_basis",
					"accounts[1].roth_contribution_basis",
					"balance_date",
				],
			},
		};
		const next = removeAccount(config, "brokerage");
		expect(getPath(next, "savings_order")).toEqual(["roth"]);
		expect(getPath(next, "surplus_account_id")).toBeUndefined();
		expect(Object.hasOwn(next as object, "surplus_account_id")).toBe(false);
		expect(getPath(next, "input_metadata.estimated_fields")).toEqual([
			"accounts[0].roth_contribution_basis",
			"balance_date",
		]);
		expect(config.accounts).toHaveLength(2);
	});
	it("refuses removal of accounts and spending referenced by events", () => {
		expect(() =>
			removeAccount(
				{ ...SAMPLE, windfalls: [{ goes_to_account: "brokerage" }] },
				"brokerage",
			),
		).toThrow(/reference/);
		expect(() =>
			removeAccount(
				{ ...SAMPLE, mortgages: [{ property_id: "brokerage" }] },
				"brokerage",
			),
		).toThrow(/reference/);
		expect(() =>
			removeListItem(
				{ ...SAMPLE, age_events: [{ expense_id: "living" }] },
				"expenses",
				0,
			),
		).toThrow(/age event/);
	});
	it("normalizes explicit priorities and preserves legacy caps when changing order", () => {
		const config = {
			accounts: [
				{ id: "a", contribution_priority: 1, monthly_contribution: 500 },
				{ id: "b", contribution_priority: 2, annual_contribution_cap: 20000 },
			],
			savings_order: ["a", "b"],
		};
		const next = setSavingsOrder(config, ["b", "a"]);
		expect(effectiveSavingsOrder(next)).toEqual(["b", "a"]);
		expect(getPath(next, "accounts.0.annual_contribution_cap")).toBe(6000);
		expect(getPath(next, "accounts.0.monthly_contribution")).toBe(0);
		expect(effectiveSavingsOrder(setSavingsOrder(next, ["b"]))).toEqual(["b"]);
		expect(
			nextItemId([{ id: "account_1" }, { id: "account_3" }], "account"),
		).toBe("account_2");
	});
	it("matches engine priority fallback for legacy monthly contributions", () => {
		expect(
			effectiveSavingsOrder({
				savings_order: ["a"],
				accounts: [
					{ id: "a", monthly_contribution: 0 },
					{ id: "legacy", contribution_priority: 0, monthly_contribution: 400 },
					{ id: "off", contribution_priority: 0, monthly_contribution: 0 },
				],
			}),
		).toEqual(["a", "legacy"]);
	});
});
