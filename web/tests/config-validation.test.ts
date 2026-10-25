import { describe, expect, it } from "vitest";
import { validateConfig } from "../src/lib/config-validation";

const plan = () => ({
	name: "Sample",
	primary: {
		birth_date: "1980-01-01",
		retirement_date: "2045-01-01",
		longevity_age: 95,
	},
	spouse: null,
	economic: {},
	accounts: [{ id: "cash", balance: 250001 }],
	income_streams: [],
	expenses: [],
});

describe("imported plan validation", () => {
	it("accepts minimal engine-compatible config without expanding defaults", () => {
    const config = { primary: plan().primary };
    expect(validateConfig(config)).toBe(config);
    expect(config).not.toHaveProperty("accounts");
  });
  it("accepts exact balances and preserves optional advanced settings", () => {
		const config = { ...plan(), custom_model_setting: { future: true } };
		expect(validateConfig(config)).toBe(config);
	});
	it("rejects invalid dates and reports the field", () => {
		expect(() =>
			validateConfig({
				...plan(),
				primary: { ...plan().primary, birth_date: "1980-02-31" },
			}),
		).toThrow(/primary.birth_date/);
	});
	it("rejects nonfinite values, repeated IDs and malformed lists", () => {
		expect(() =>
			validateConfig({ ...plan(), accounts: [{ id: "a", balance: Infinity }] }),
		).toThrow(/balance/);
		expect(() =>
			validateConfig({ ...plan(), accounts: [{ id: "a" }, { id: "a" }] }),
		).toThrow(/duplicates/);
		expect(() => validateConfig({ ...plan(), expenses: {} })).toThrow(
			/expenses/,
		);
	});
	it("rejects unsafe nested keys before later immutable edits", () => {
		expect(() =>
			validateConfig(
				JSON.parse(
					JSON.stringify(plan()).replace(
						'"economic":{}',
						'"economic":{"__proto__":{"polluted":true}}',
					),
				),
			),
		).toThrow(/not allowed/);
	});
});
