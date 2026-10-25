import { describe, expect, it } from "vitest";
import { buildSlimConfig, DEFAULT_ANSWERS, savingsTotal, type WizardAnswers } from "../src/slim/types";
import fixtures from "../../tests/fixtures/wizard-contract.json";

const now = new Date(2030, 5, 15);
describe("wizard engine contract", () => {
  it.each(fixtures)("matches the native engine fixture: $name", ({ answers, config }) => {
    expect(buildSlimConfig({ ...DEFAULT_ANSWERS, ...answers } as WizardAnswers, now)).toEqual(config);
  });
  it("keeps full annual income rather than rounding monthly values", () => {
    const cfg = buildSlimConfig({ ...DEFAULT_ANSWERS, annualIncome: 100_000 }, now);
    expect(cfg.income_streams[0]!.monthly_amount * 12).toBeCloseTo(100_000);
    expect(cfg.income_streams[0]!.start_date).toBe("2031-01-01");
  });
  it("uses the sum of optional account balances", () => {
    expect(savingsTotal({ ...DEFAULT_ANSWERS, accountBreakdown: true, cashAssets: 100, traditionalAssets: 200 })).toBe(300);
  });
  it("preserves unknown basis and explicit zero separately", () => {
    const cfg = buildSlimConfig({ ...DEFAULT_ANSWERS, accountBreakdown: true, brokerageAssets: 1000, brokerageBasis: 0, rothAssets: 1000 }, now);
    expect(cfg.accounts.find((a) => a.id === "brokerage")!.cost_basis).toBe(0);
    expect(cfg.accounts.find((a) => a.id === "roth")).not.toHaveProperty("roth_contribution_basis");
  });
  it("disables benefits with canonical zero fields", () => {
    const cfg = buildSlimConfig({ ...DEFAULT_ANSWERS, hasSocialSecurity: false }, now);
    expect(cfg.social_security.primary_benefit_at_67).toBe(0);
    expect(cfg.social_security.spouse_benefit_at_67).toBe(0);
    expect(cfg.expenses[0]!.is_must_spend).toBe(true);
    expect(cfg.legacy_goal).toBe(0);
  });
});
