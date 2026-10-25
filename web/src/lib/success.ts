/** Compatibility bands for the historical combined success metric.
 * These do not establish spending coverage or explain funding shortfalls.
 * Current goal panels report each outcome directly.
 */
export const SUCCESS_THRESHOLDS = {
  excellent: 0.95,
  good: 0.75,
  fair: 0.5,
} as const;

export type SuccessTone = "good" | "warn" | "bad";

/** Compatibility tone for consumers of the historical combined rate. */
export function successTone(rate: number): SuccessTone {
  if (rate >= SUCCESS_THRESHOLDS.good) return "good";
  if (rate >= SUCCESS_THRESHOLDS.fair) return "warn";
  return "bad";
}
