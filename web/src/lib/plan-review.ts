export interface ReviewAccount {
  name: string;
  owner: string;
  type: string;
  taxTreatment: string;
  balance: number;
  monthlyContribution: number;
  growthRate: number | null;
  share: number;
}

export interface PlanReviewSummary {
  name: string;
  household: string[];
  totalAssets: number;
  totalDebt: number;
  netWorth: number;
  monthlyContributions: number;
  accounts: ReviewAccount[];
  incomeStreams: Record<string, unknown>[];
  expenses: Record<string, unknown>[];
  mortgages: Record<string, unknown>[];
  events: Array<[string, Record<string, unknown>[]]>;
  assumptions: Array<[string, unknown]>;
  unknownEntries: Array<[string, unknown]>;
}

const KNOWN_TOP_LEVEL = new Set([
  "_comment",
  "_notes",
  "name",
  "description",
  "schema_version",
  "primary",
  "spouse",
  "economic",
  "accounts",
  "income_streams",
  "expenses",
  "mortgages",
  "windfalls",
  "housing_events",
  "roth_conversions",
  "rollover_events",
  "age_events",
  "dependents",
  "social_security",
  "glidepath",
  "withdrawal_strategy",
  "withdrawal_rate",
  "guardrail_floor_pct",
  "guardrail_ceiling_pct",
  "legacy_goal",
  "state",
  "family_size",
  "savings_order",
  "monetary_convention",
  "stress_level",
  "survivor_expense_ratio",
]);

function asRecord(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(asRecord) : [];
}

function text(value: unknown, fallback = "Not specified"): string {
  return typeof value === "string" && value.length > 0 ? value : fallback;
}

function number(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function debtBalance(mortgage: Record<string, unknown>): number {
  return (
    number(mortgage.balance) || number(mortgage.remaining_balance) || number(mortgage.principal)
  );
}

/** Convert loose Mantissa JSON into review-safe display data without dropping fields. */
export function summarizePlan(config: unknown): PlanReviewSummary {
  const root = asRecord(config);
  const primary = asRecord(root.primary);
  const spouse = asRecord(root.spouse);
  const household = [text(primary.name, "Primary")];
  if (root.spouse !== null && Object.keys(spouse).length > 0)
    household.push(text(spouse.name, "Spouse"));

  const rawAccounts = records(root.accounts);
  const totalAssets = rawAccounts.reduce((sum, account) => sum + number(account.balance), 0);
  const accounts = rawAccounts.map((account, index) => {
    const balance = number(account.balance);
    return {
      name: text(account.name, text(account.id, `Account ${index + 1}`)),
      owner: text(account.owner, "Primary"),
      type: text(account.type),
      taxTreatment: text(account.tax_treatment),
      balance,
      monthlyContribution: number(account.monthly_contribution),
      growthRate: typeof account.growth_rate === "number" ? account.growth_rate : null,
      share: totalAssets > 0 ? balance / totalAssets : 0,
    };
  });

  const mortgages = records(root.mortgages);
  const totalDebt = mortgages.reduce((sum, mortgage) => sum + debtBalance(mortgage), 0);
  const eventKeys = [
    "dependents",
    "windfalls",
    "housing_events",
    "roth_conversions",
    "rollover_events",
    "age_events",
  ];

  const assumptions: Array<[string, unknown]> = [
    ["State", root.state],
    ["Withdrawal strategy", root.withdrawal_strategy],
    ["Withdrawal rate", root.withdrawal_rate],
    ["Monetary convention", root.monetary_convention],
    ["Legacy goal", root.legacy_goal],
    ["Economic assumptions", root.economic],
    ["Social Security", root.social_security],
    ["Glidepath", root.glidepath],
  ];

  return {
    name: text(root.name, "Mantissa plan"),
    household,
    totalAssets,
    totalDebt,
    netWorth: totalAssets - totalDebt,
    monthlyContributions: accounts.reduce((sum, account) => sum + account.monthlyContribution, 0),
    accounts,
    incomeStreams: records(root.income_streams),
    expenses: records(root.expenses),
    mortgages,
    events: eventKeys.map((key) => [key, records(root[key])]),
    assumptions: assumptions.filter(([, value]) => value !== undefined),
    unknownEntries: Object.entries(root).filter(([key]) => !KNOWN_TOP_LEVEL.has(key)),
  };
}
