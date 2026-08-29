import { describe, expect, it } from "vitest";
import { fmtMoney, fmtPct } from "../src/lib/format";

describe("fmtMoney", () => {
  it("formats billions", () => {
    expect(fmtMoney(1.5e9)).toBe("$1.50B");
  });
  it("formats millions", () => {
    expect(fmtMoney(2.34e6)).toBe("$2.34M");
  });
  it("formats thousands", () => {
    expect(fmtMoney(7500)).toBe("$7.5k");
  });
  it("formats sub-thousand", () => {
    expect(fmtMoney(500)).toBe("$500");
  });
  it("handles negatives", () => {
    expect(fmtMoney(-1.5e6)).toBe("-$1.50M");
  });
  it("handles zero", () => {
    expect(fmtMoney(0)).toBe("$0");
  });
});

describe("fmtPct", () => {
  it("formats as 1dp percent", () => {
    expect(fmtPct(0.013)).toBe("1.3%");
    expect(fmtPct(0.982)).toBe("98.2%");
    expect(fmtPct(1)).toBe("100.0%");
    expect(fmtPct(0)).toBe("0.0%");
  });
});
