import { describe, expect, it } from "vitest";
import { buildSlimConfig, DEFAULT_ANSWERS } from "../src/slim/types";

describe("buildSlimConfig", () => {
  it("returns an object with the engine-required top-level shape", () => {
    const cfg = buildSlimConfig(DEFAULT_ANSWERS) as Record<string, unknown>;
    expect(cfg).toHaveProperty("primary");
    expect(cfg).toHaveProperty("spouse");
    expect(cfg).toHaveProperty("economic");
    expect(Array.isArray(cfg.accounts)).toBe(true);
    expect(Array.isArray(cfg.income_streams)).toBe(true);
    expect(Array.isArray(cfg.expenses)).toBe(true);
  });

  it("synthesizes a far-future stub spouse when hasSpouse=false", () => {
    const cfg = buildSlimConfig({ ...DEFAULT_ANSWERS, hasSpouse: false }) as {
      spouse: { name: string; birth_date: string };
    };
    expect(cfg.spouse.name).toBe("(none)");
    expect(cfg.spouse.birth_date.startsWith("21")).toBe(true);
  });

  it("emits a real spouse object when hasSpouse=true", () => {
    const cfg = buildSlimConfig({
      ...DEFAULT_ANSWERS,
      hasSpouse: true,
      spouseAge: 33,
      spouseRetirementAge: 65,
      spouseLongevity: 94,
    }) as { spouse: { name: string; birth_date: string; longevity_age: number } };
    expect(cfg.spouse.name).toBe("Spouse");
    expect(cfg.spouse.longevity_age).toBe(94);
    expect(cfg.spouse.birth_date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("maps risk tolerance to economic params", () => {
    const low = buildSlimConfig({ ...DEFAULT_ANSWERS, risk: "low" }) as {
      economic: { investment_return_mean: number; investment_return_volatility: number };
    };
    const med = buildSlimConfig({ ...DEFAULT_ANSWERS, risk: "medium" }) as {
      economic: { investment_return_mean: number; investment_return_volatility: number };
    };
    const high = buildSlimConfig({ ...DEFAULT_ANSWERS, risk: "high" }) as {
      economic: { investment_return_mean: number; investment_return_volatility: number };
    };
    expect(low.economic.investment_return_volatility).toBeLessThan(
      med.economic.investment_return_volatility,
    );
    expect(med.economic.investment_return_volatility).toBeLessThan(
      high.economic.investment_return_volatility,
    );
  });

  it("rounds monthly income / spending to integers", () => {
    const cfg = buildSlimConfig({
      ...DEFAULT_ANSWERS,
      annualIncome: 100_000,
      annualSpending: 36_000,
    }) as {
      income_streams: Array<{ monthly_amount: number }>;
      expenses: Array<{ monthly_amount: number }>;
    };
    expect(cfg.income_streams[0]?.monthly_amount).toBe(8_333);
    expect(cfg.expenses[0]?.monthly_amount).toBe(3_000);
  });

  it("emits one brokerage account equal to the user's assets", () => {
    const cfg = buildSlimConfig({
      ...DEFAULT_ANSWERS,
      investableAssets: 500_000,
    }) as { accounts: Array<{ type: string; balance: number }> };
    expect(cfg.accounts).toHaveLength(1);
    expect(cfg.accounts[0]?.type).toBe("brokerage");
    expect(cfg.accounts[0]?.balance).toBe(500_000);
  });

  it("omits income_streams and expenses rows when the user enters 0", () => {
    const cfg = buildSlimConfig({
      ...DEFAULT_ANSWERS,
      annualIncome: 0,
      annualSpending: 0,
    }) as { income_streams: unknown[]; expenses: unknown[] };
    expect(cfg.income_streams).toHaveLength(0);
    expect(cfg.expenses).toHaveLength(0);
  });

  it("populates every engine-required field on income_streams and expenses", () => {
    // Engine requires id, name, owner, monthly_amount, start_date,
    // end_date, growth_rate, is_w2, social_security_taxable on
    // income_streams; id, name, monthly_amount, start_date, end_date,
    // category, essential, inflation_adjusted on expenses.
    const cfg = buildSlimConfig(DEFAULT_ANSWERS) as {
      income_streams: Array<Record<string, unknown>>;
      expenses: Array<Record<string, unknown>>;
    };
    const incKeys = Object.keys(cfg.income_streams[0] ?? {}).sort();
    expect(incKeys).toEqual(
      [
        "end_date",
        "growth_rate",
        "id",
        "is_w2",
        "monthly_amount",
        "name",
        "owner",
        "social_security_taxable",
        "start_date",
      ].sort(),
    );
    const expKeys = Object.keys(cfg.expenses[0] ?? {}).sort();
    expect(expKeys).toEqual(
      [
        "category",
        "end_date",
        "essential",
        "id",
        "inflation_adjusted",
        "monthly_amount",
        "name",
        "start_date",
      ].sort(),
    );
  });

  it("emits an ISO date for every date field", () => {
    const cfg = buildSlimConfig(DEFAULT_ANSWERS) as {
      primary: { birth_date: string; retirement_date: string };
      spouse: { birth_date: string; retirement_date: string };
      income_streams: Array<{ start_date: string; end_date: string }>;
      expenses: Array<{ start_date: string; end_date: string }>;
    };
    const dateFields = [
      cfg.primary.birth_date,
      cfg.primary.retirement_date,
      cfg.spouse.birth_date,
      cfg.spouse.retirement_date,
      cfg.income_streams[0]?.start_date,
      cfg.income_streams[0]?.end_date,
      cfg.expenses[0]?.start_date,
      cfg.expenses[0]?.end_date,
    ];
    for (const d of dateFields) {
      expect(d).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    }
  });
});
