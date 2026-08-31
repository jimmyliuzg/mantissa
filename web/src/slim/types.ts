/**
 * Wizard types and the slim-config builder.
 *
 * The slim config is the smallest Mantissa config that the engine can
 * parse end-to-end (verified in the M0 spike). The wizard collects
 * answers in a flat WizardAnswers shape, then `buildSlimConfig()`
 * serializes to the engine's expected schema.
 *
 * Engine contract this code accommodates (see plan findings #3 and #4):
 *   - `spouse` may be `null` for a single household. The engine applies
 *     single-filer tax rules and projects through the primary's longevity.
 *   - `income_streams[].id`, `monthly_amount`, `end_date`, `is_w2`,
 *     `social_security_taxable` are required by the engine parser even
 *     though the schema doesn't enforce them.
 *   - `expenses[].id`, `monthly_amount`, `end_date`, `category`,
 *     `essential`, `inflation_adjusted` likewise.
 */

export type RiskTolerance = "low" | "medium" | "high";

export interface WizardAnswers {
  primaryAge: number;
  primaryRetirementAge: number;
  primaryLongevity: number;
  hasSpouse: boolean;
  spouseAge: number | null;
  spouseRetirementAge: number | null;
  spouseLongevity: number | null;
  investableAssets: number;
  annualIncome: number;
  annualSpending: number;
  state: string;
  hasSocialSecurity: boolean;
  monthlySocialSecurity: number;
  risk: RiskTolerance;
}

export const DEFAULT_ANSWERS: WizardAnswers = {
  primaryAge: 35,
  primaryRetirementAge: 65,
  primaryLongevity: 92,
  hasSpouse: false,
  spouseAge: null,
  spouseRetirementAge: null,
  spouseLongevity: null,
  investableAssets: 250_000,
  annualIncome: 120_000,
  annualSpending: 60_000,
  state: "CA",
  hasSocialSecurity: true,
  monthlySocialSecurity: 2_400,
  risk: "medium",
};

function today(): string {
  // YYYY-MM-DD in the user's local zone. Used for start dates; engine
  // treats them as anchors for active years.
  return new Date().toISOString().slice(0, 10);
}

function birthDate(age: number): string {
  const now = new Date();
  // If today is the user's birthday already this year, age is exact;
  // otherwise subtract one. Either way, an approximate ISO date is
  // what the engine expects.
  return new Date(now.getFullYear() - age, now.getMonth(), now.getDate())
    .toISOString()
    .slice(0, 10);
}

function retirementDate(age: number, currentAge: number): string {
  const yearsUntil = Math.max(0, age - currentAge);
  const now = new Date();
  return new Date(now.getFullYear() + yearsUntil, now.getMonth(), now.getDate())
    .toISOString()
    .slice(0, 10);
}

function riskParams(risk: RiskTolerance): { mean: number; vol: number } {
  switch (risk) {
    case "low":
      return { mean: 0.04, vol: 0.08 };
    case "high":
      return { mean: 0.08, vol: 0.18 };
    case "medium":
      return { mean: 0.06, vol: 0.13 };
  }
}

/**
 * Synthesize a single-account config that holds all the user's
 * investable assets. We pick `taxable` so the engine doesn't apply
 * contribution caps or required minimum distributions.
 */
function accountsFromAssets(assets: number): unknown[] {
  if (assets <= 0) return [];
  return [
    {
      id: "brokerage",
      name: "Brokerage",
      type: "brokerage",
      tax_treatment: "taxable",
      balance: assets,
      growth_rate: 0.07,
    },
  ];
}

/**
 * Build the slim config. Returns a deep object that the engine
 * accepts. The shape follows the example config in
 * `examples/sample_config.json`, NOT the schema validator's looser
 * subset (Finding #3 from the M0 spike).
 */
export function buildSlimConfig(answers: WizardAnswers): unknown {
  const { mean, vol } = riskParams(answers.risk);
  const startDate = today();
  // End date: max(primary longevity, spouse longevity) + a few years buffer.
  const maxLongevity = Math.max(
    answers.primaryLongevity,
    answers.spouseLongevity ?? answers.primaryLongevity,
  );
  const longevityEndYear = new Date().getFullYear() + (maxLongevity - answers.primaryAge) + 5;
  const endDate = `${longevityEndYear}-12-31`;

  const accounts = accountsFromAssets(answers.investableAssets);
  const monthlyIncome = Math.round(answers.annualIncome / 12);
  const monthlySpending = Math.round(answers.annualSpending / 12);

  return {
    name: "Wizard plan",
    description: "Created with the Mantissa web wizard.",
    primary: {
      name: "Primary",
      birth_date: birthDate(answers.primaryAge),
      retirement_date: retirementDate(answers.primaryRetirementAge, answers.primaryAge),
      longevity_age: answers.primaryLongevity,
    },
    // Spouse is optional in the engine (issue #3). When the user
    // is single, emit null so the engine projects to the primary's
    // death year + 1 and treats the household as single from the
    // start (no spousal SS, no survivor transition). ACA family size
    // is computed dynamically from the snapshot; family_size in the
    // config is now a warning if present, so we omit it.
    spouse: answers.hasSpouse
      ? {
          name: "Spouse",
          birth_date: birthDate(answers.spouseAge ?? answers.primaryAge),
          retirement_date: retirementDate(
            answers.spouseRetirementAge ?? answers.primaryRetirementAge,
            answers.spouseAge ?? answers.primaryAge,
          ),
          longevity_age: answers.spouseLongevity ?? answers.primaryLongevity,
        }
      : null,
    economic: {
      inflation: 0.025,
      medical_inflation: 0.04,
      housing_appreciation: 0.035,
      investment_return_mean: mean,
      investment_return_volatility: vol,
    },
    accounts,
    income_streams:
      monthlyIncome > 0
        ? [
            {
              id: "salary",
              name: "Salary",
              owner: "primary",
              monthly_amount: monthlyIncome,
              start_date: startDate,
              end_date: retirementDate(answers.primaryRetirementAge, answers.primaryAge),
              growth_rate: 0.02,
              is_w2: true,
              social_security_taxable: true,
            },
          ]
        : [],
    expenses:
      monthlySpending > 0
        ? [
            {
              id: "living",
              name: "Living expenses",
              monthly_amount: monthlySpending,
              start_date: startDate,
              end_date: endDate,
              category: "essential",
              essential: true,
              inflation_adjusted: true,
            },
          ]
        : [],
    social_security: answers.hasSocialSecurity
      ? {
          primary_pia: answers.monthlySocialSecurity,
          claiming_age_primary: 67,
        }
      : null,
    withdrawal_strategy: "fixed",
    withdrawal_rate: 0.04,
    state: answers.state,
    monetary_convention: "real",
    savings_order: accounts.map((a) => (a as { id: string }).id),
    // Default glidepath: 100% equity in early career, ramps to 40%
    // by retirement with a 5-year bond tent, then back to 40-50%
    // post-retirement. Without a glidepath the engine assumes 100%
    // equity forever, which makes a 60-year horizon compound to
    // lottery-ticket numbers regardless of contributions.
    glidepath: {
      equity_by_age: { 30: 1.0, 50: 0.8, 60: 0.5, 70: 0.4, 90: 0.4 },
      pre_retirement_years: 10,
      post_retirement_years: 5,
      tent_equity_pct: 0.4,
      tent_ramp_years: 10,
    },
  };
}
