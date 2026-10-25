/** Optional refinements serialize to the same Python config used by the CLI. */
export type RiskTolerance = "low" | "medium" | "high";
export type IncomeProfile = "none" | "stock_index" | "balanced" | "income";

export interface WizardAnswers {
  primaryAge: number;
  alreadyRetired: boolean;
  spouseAlreadyRetired: boolean;
  currentAnnualSpending: number | null;
  spouseMonthlySocialSecurity: number;
  primaryRetirementAge: number;
  primaryLongevity: number;
  hasSpouse: boolean;
  spouseAge: number | null;
  spouseRetirementAge: number | null;
  spouseLongevity: number | null;
  investableAssets: number;
  accountBreakdown: boolean;
  cashAssets: number;
  brokerageAssets: number;
  traditionalAssets: number;
  rothAssets: number;
  balanceDate: string;
  brokerageBasis: number | null;
  unrealizedGainPercent: number | null;
  rothPrincipal: number | null;
  rothFirstYear: number | null;
  incomeProfile: IncomeProfile;
  annualIncome: number;
  annualSpending: number;
  flexibleSpendingPercent: number;
  maximumFlexibleCutPercent: number;
  spendingStrategy: "fixed" | "dynamic" | "guardrails";
  state: string;
  hasSocialSecurity: boolean;
  monthlySocialSecurity: number;
  risk: RiskTolerance;
}

export const DEFAULT_ANSWERS: WizardAnswers = {
  alreadyRetired: false, spouseAlreadyRetired: false, currentAnnualSpending: null, spouseMonthlySocialSecurity: 0,
  primaryAge: 35, primaryRetirementAge: 65, primaryLongevity: 92,
  hasSpouse: false, spouseAge: null, spouseRetirementAge: null, spouseLongevity: null,
  investableAssets: 250_000, accountBreakdown: false,
  cashAssets: 0, brokerageAssets: 0, traditionalAssets: 0, rothAssets: 0,
  balanceDate: "", brokerageBasis: null, unrealizedGainPercent: null,
  rothPrincipal: null, rothFirstYear: null, incomeProfile: "stock_index",
  annualIncome: 120_000, annualSpending: 60_000,
  flexibleSpendingPercent: 0, maximumFlexibleCutPercent: 25, spendingStrategy: "fixed",
  state: "CA", hasSocialSecurity: true, monthlySocialSecurity: 2_400, risk: "medium",
};

export function savingsTotal(a: WizardAnswers): number {
  return a.accountBreakdown
    ? a.cashAssets + a.brokerageAssets + a.traditionalAssets + a.rothAssets
    : a.investableAssets;
}

export function buildSlimConfig(a: WizardAnswers, now = new Date()) {
  const year = now.getFullYear();
  const startYear = year + 1;
  const start = `${startYear}-01-01`;
  const birth = (age: number) => `${year - age}-01-01`;
  const retirement = (age: number, current: number) => `${Math.max(startYear, year + age - current)}-01-01`;
  const spouseAge = a.spouseAge ?? a.primaryAge;
  const spouseLongevity = a.spouseLongevity ?? a.primaryLongevity;
  const endYear = Math.max(year + a.primaryLongevity - a.primaryAge,
    a.hasSpouse ? year + spouseLongevity - spouseAge : 0) + 2;
  const primaryRetirement = a.alreadyRetired ? start : retirement(a.primaryRetirementAge, a.primaryAge);
  const spouseRetirement = a.spouseAlreadyRetired ? start : retirement(a.spouseRetirementAge ?? a.primaryRetirementAge, spouseAge);
  const profile = a.incomeProfile;
  const accounts: Array<Record<string, unknown>> = [];
  const add = (id: string, name: string, type: string, tax: string, balance: number, extra = {}) => {
    if (balance > 0) accounts.push({ id, name, type, tax_treatment: tax, balance, owner: "primary", ...extra });
  };
  const estimated = ["primary.birth_date", "primary.retirement_date", "economic.inflation", "economic.medical_inflation", "economic.housing_appreciation", "economic.equity_real_return", "economic.bond_real_return", "social_security.primary_benefit_at_67", "legacy_goal"];
  if (a.hasSpouse) estimated.push("spouse.birth_date", "spouse.retirement_date", "accounts.owner");
  if (a.accountBreakdown) {
    add("cash", "Cash", "checking", "taxable", a.cashAssets, { asset_class: "cash", investment_income_profile: "cash" });
    add("brokerage", "Brokerage", "brokerage", "taxable", a.brokerageAssets, {
      investment_income_profile: profile,
      ...(a.brokerageBasis !== null ? { cost_basis: a.brokerageBasis } :
        a.unrealizedGainPercent !== null ? { unrealized_gain_fraction: a.unrealizedGainPercent / 100 } : {}),
    });
    add("traditional", "Traditional retirement", "trad_ira", "pre_tax", a.traditionalAssets);
    add("roth", "Roth IRA", "roth_ira", "roth", a.rothAssets, {
      ...(a.rothPrincipal !== null ? { roth_contribution_basis: a.rothPrincipal } : {}),
      ...(a.rothFirstYear !== null ? { roth_first_contribution_year: a.rothFirstYear } : {}),
    });
  } else {
    add("aggregate", "Total savings (account types unknown)", "other", "taxable", a.investableAssets, { investment_income_profile: profile });
  }
  // All new savings go to an unrestricted taxable destination. This avoids
  // inventing IRA eligibility, contribution capacity or household ownership.
  const savingsId = a.accountBreakdown ? (a.cashAssets > 0 ? "cash" : "brokerage") : "aggregate";
  if (!accounts.some((acc) => acc.id === savingsId)) {
    accounts.push({ id: savingsId, name: "New taxable savings", type: "brokerage", tax_treatment: "taxable", balance: 0, cost_basis: 0, investment_income_profile: profile });
  }
  const equity = { low: 0.3, medium: 0.6, high: 0.85 }[a.risk];
  const flexible = a.annualSpending * a.flexibleSpendingPercent / 100;
  const expense = (id: string, name: string, amount: number, required: boolean) => ({
    id, name, monthly_amount: amount / 12, start_date: start, end_date: `${endYear}-12-31`,
    category: required ? "essential" : "discretionary", is_must_spend: required,
    min_reduction: required ? 0 : a.maximumFlexibleCutPercent / 100,
  });
  const expenses = [expense("living", "Essential living", a.annualSpending - flexible, true), expense("flexible", "Flexible spending", flexible, false)].filter((e) => e.monthly_amount > 0);
  if (a.currentAnnualSpending !== null && primaryRetirement > start) {
    // January 1 end dates are exclusive in the annual engine. The two
    // periods meet without overlapping or dropping a retirement year.
    for (const item of expenses) item.start_date = primaryRetirement;
    if (a.currentAnnualSpending > 0) expenses.unshift({ ...expense("current-living", "Current living", a.currentAnnualSpending, true), end_date: primaryRetirement });
  }
  return {
    name: "Wizard plan", description: "Created with the Mantissa web wizard; optional inputs may be provisional.",
    start_year: startYear,
    ...(a.balanceDate ? { balance_date: a.balanceDate } : {}),
    input_metadata: { account_breakdown: a.accountBreakdown ? "provided" : "missing", estimated_fields: estimated },
    primary: { name: "Primary", birth_date: birth(a.primaryAge), retirement_date: primaryRetirement, longevity_age: a.primaryLongevity },
    spouse: a.hasSpouse ? { name: "Spouse", birth_date: birth(spouseAge), retirement_date: spouseRetirement, longevity_age: spouseLongevity } : null,
    economic: { inflation: 0.025, medical_inflation: 0.04, housing_appreciation: 0.035, equity_real_return: 0.06, bond_real_return: 0.02 },
    accounts,
    income_streams: a.annualIncome > 0 && !a.alreadyRetired ? [{ id: "salary", name: "Salary", owner: "primary", monthly_amount: a.annualIncome / 12, start_date: start, end_date: primaryRetirement, growth_rate: 0.02, is_w2: true }] : [],
    expenses,
    social_security: { primary_benefit_at_67: a.hasSocialSecurity ? a.monthlySocialSecurity : 0, primary_claiming_age: 67, spouse_benefit_at_67: a.hasSpouse && a.hasSocialSecurity ? a.spouseMonthlySocialSecurity : 0, spouse_claiming_age: 67 },
    withdrawal_strategy: a.spendingStrategy, withdrawal_access_policy: "penalty_free", withdrawal_rate: 0.04,
    legacy_goal: 0, state: a.state, monetary_convention: "real", savings_order: [savingsId],
    glidepath: { equity_by_age: { 30: Math.min(1, equity + 0.2), 50: equity, 70: Math.max(0.2, equity - 0.15), 90: Math.max(0.2, equity - 0.15) }, pre_retirement_years: 5, post_retirement_years: 5, tent_equity_pct: Math.max(0.2, equity - 0.2), tent_ramp_years: 5 },
  };
}
