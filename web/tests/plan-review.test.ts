import { describe, expect, it } from "vitest";
import { summarizePlan } from "../src/lib/plan-review";

describe("summarizePlan", () => {
  it("creates an account snapshot with allocation and debt", () => {
    const review = summarizePlan({
      name: "Household plan",
      primary: { name: "Alex", birth_date: "1980-01-01", retirement_date: "2045-01-01" },
      spouse: null,
      accounts: [
        { id: "brokerage", name: "Brokerage", type: "brokerage", tax_treatment: "taxable", balance: 120_000 },
        { id: "ira", name: "IRA", type: "trad_ira", tax_treatment: "pre_tax", balance: 80_000 },
      ],
      mortgages: [{ name: "Home", balance: 50_000, monthly_payment: 2_000 }],
    });

    expect(review.name).toBe("Household plan");
    expect(review.totalAssets).toBe(200_000);
    expect(review.totalDebt).toBe(50_000);
    expect(review.netWorth).toBe(150_000);
    expect(review.accounts.map((account) => account.share)).toEqual([0.6, 0.4]);
    expect(review.household).toEqual(["Alex"]);
  });

  it("retains empty and unknown config data for the complete review", () => {
    const review = summarizePlan({
      primary: { name: "Alex" },
      accounts: [],
      custom_goal: { label: "Fund cabin", target: 500_000 },
    });

    expect(review.totalAssets).toBe(0);
    expect(review.accounts).toEqual([]);
    expect(review.unknownEntries).toEqual([["custom_goal", { label: "Fund cabin", target: 500_000 }]]);
  });
});
