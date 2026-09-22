/**
 * Success-rate bands, shared by every surface that judges a plan
 * (KPI row tone, plan-summary narrative). One table so a 80% plan
 * can never read "neutral" in the KPI grid while the summary below
 * calls it solid.
 *
 * excellent >= 0.95  — also gates the "over-saving" hint
 * good      >= 0.75  — plan holds in most scenarios
 * fair      >= 0.50  — works for a majority, vulnerable to downturns
 * below that         — runs out of money in most scenarios
 */
export const SUCCESS_THRESHOLDS = {
  excellent: 0.95,
  good: 0.75,
  fair: 0.5,
} as const;

export type SuccessTone = "good" | "warn" | "bad";

/** Tone for a success rate; drives KPI color and plan-summary border. */
export function successTone(rate: number): SuccessTone {
  if (rate >= SUCCESS_THRESHOLDS.good) return "good";
  if (rate >= SUCCESS_THRESHOLDS.fair) return "warn";
  return "bad";
}
