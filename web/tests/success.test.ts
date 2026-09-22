import { describe, expect, it } from "vitest";
import { SUCCESS_THRESHOLDS, successTone } from "../src/lib/success";

describe("successTone", () => {
  it("maps rates to one shared band table", () => {
    expect(successTone(1)).toBe("good");
    expect(successTone(SUCCESS_THRESHOLDS.good)).toBe("good"); // 0.75 inclusive
    expect(successTone(0.74)).toBe("warn");
    expect(successTone(SUCCESS_THRESHOLDS.fair)).toBe("warn"); // 0.50 inclusive
    expect(successTone(0.49)).toBe("bad");
    expect(successTone(0)).toBe("bad");
  });

  it("keeps the excellent tier distinct from the good floor", () => {
    expect(SUCCESS_THRESHOLDS.excellent).toBeGreaterThan(SUCCESS_THRESHOLDS.good);
    expect(SUCCESS_THRESHOLDS.good).toBeGreaterThan(SUCCESS_THRESHOLDS.fair);
  });
});
