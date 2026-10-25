import { describe, expect, it } from "vitest";
import { CHART_MIN_WIDTH, nearestIndex, xTickIndices } from "../src/lib/chart-utils";

describe("xTickIndices", () => {
  it("labels every row when they fit", () => {
    expect(xTickIndices(11, 800)).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  });

  it("steps through round year gaps on a long horizon", () => {
    const ticks = xTickIndices(100, 460); // 100 years, narrow plot
    expect(ticks[0]).toBe(0);
    expect(ticks[ticks.length - 1]).toBe(99);
    // step picked from round candidates
    const step = (ticks[1] ?? 0) - (ticks[0] ?? 0);
    expect([1, 2, 5, 10, 20, 25, 50].some((c) => c >= step)).toBe(true);
    // no two labels closer than ~60% of minLabelPx
    const px = 460 / 99;
    for (let i = 1; i < ticks.length; i++) {
      const gap = (ticks[i] ?? 0) - (ticks[i - 1] ?? 0);
      expect(gap * px).toBeGreaterThanOrEqual(56 * 0.6 - 1);
    }
  });

  it("slides the final tick onto the last row when it would overlap", () => {
    // span 55, step 50 -> tick at 50 is only 9px before row 55
    const ticks = xTickIndices(56, 100);
    expect(ticks).toEqual([0, 55]);
  });

  it("handles degenerate inputs", () => {
    expect(xTickIndices(0, 800)).toEqual([0]);
    expect(xTickIndices(1, 800)).toEqual([0]);
    expect(xTickIndices(2, 0)).toEqual([0, 1]);
  });
});

describe("nearestIndex", () => {
  it("maps plot x to row index and clamps", () => {
    expect(nearestIndex(0, 100, 11)).toBe(0);
    expect(nearestIndex(50, 100, 11)).toBe(5);
    expect(nearestIndex(100, 100, 11)).toBe(10);
    expect(nearestIndex(-20, 100, 11)).toBe(0);
    expect(nearestIndex(500, 100, 11)).toBe(10);
    expect(nearestIndex(50, 100, 1)).toBe(0);
  });
});

describe("CHART_MIN_WIDTH", () => {
  it("keeps labels at or above a readable floor", () => {
    expect(CHART_MIN_WIDTH).toBeGreaterThanOrEqual(420);
  });
});
