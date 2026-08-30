import { describe, expect, it } from "vitest";
import {
  buildShareUrl,
  decodeConfig,
  decodeSnapshot,
  encodeConfig,
  encodeSnapshot,
  shareByteSize,
  type ShareableConfig,
  type ShareableSnapshot,
} from "../src/lib/share-codec";

const SAMPLE_CONFIG: ShareableConfig = {
  config: {
    name: "demo",
    primary: { name: "P", birth_date: "1991-01-01", retirement_date: "2056-01-01", longevity_age: 92 },
    spouse: { name: "(none)", birth_date: "1991-01-01", retirement_date: "2056-01-01", longevity_age: 92 },
    economic: { inflation: 0.025, investment_return_mean: 0.06, investment_return_volatility: 0.13 },
    accounts: [{ id: "b", name: "B", type: "brokerage", tax_treatment: "taxable", balance: 250000 }],
    income_streams: [],
    expenses: [],
    state: "CA",
  },
  sims: 1000,
  seed: 42,
};

const SAMPLE_RESULT = {
  kpis: { successRate: 0.965, medianFinalNetWorth: 11_600_000 },
  cashFlow: [{ year: 2026, primaryAge: 35, spouseAge: null, income: 120_000, expenses: 60_000, taxes: 18_000, netWorth: 280_000, netCashFlow: 42_000 }],
  mc: { percentiles: [{ percentile: 50, value: 11_600_000 }], method: "gaussian" },
  runtimeMs: 18_000,
  generatedAt: Date.now(),
};

describe("encodeConfig / decodeConfig", () => {
  it("round-trips a config + sims + seed", () => {
    const hash = encodeConfig(SAMPLE_CONFIG);
    const back = decodeConfig(hash);
    expect(back).toEqual(SAMPLE_CONFIG);
  });

  it("produces a URL-safe string with the c1- prefix", () => {
    const hash = encodeConfig(SAMPLE_CONFIG);
    expect(hash.startsWith("c1-")).toBe(true);
    // URL-safe: no spaces, no +, no /, no ?, no #, no : — all of
    // which would need percent-encoding and could break link
    // unfurlers.
    expect(hash).not.toMatch(/[\s+/?#:]/);
  });

  it("rejects a hash with the wrong prefix", () => {
    expect(() => decodeConfig("s1-garbage")).toThrow(/bad share hash/);
    expect(() => decodeConfig("not-a-hash")).toThrow(/bad share hash/);
  });

  it("rejects an empty or malformed hash", () => {
    expect(() => decodeConfig("c1:")).toThrow();
    expect(() => decodeConfig("c1:!!!garbage!!!")).toThrow();
  });
});

describe("encodeSnapshot / decodeSnapshot", () => {
  it("round-trips a config + result bundle", () => {
    const snap: ShareableSnapshot = { ...SAMPLE_CONFIG, result: SAMPLE_RESULT };
    const hash = encodeSnapshot(snap);
    const back = decodeSnapshot(hash);
    expect(back).toEqual(snap);
  });

  it("snapshot is larger than config-only for the same config", () => {
    const cfgSize = shareByteSize(encodeConfig(SAMPLE_CONFIG));
    const snapSize = shareByteSize(encodeSnapshot({ ...SAMPLE_CONFIG, result: SAMPLE_RESULT }));
    expect(snapSize).toBeGreaterThan(cfgSize);
  });

  it("encodes large cash-flow arrays (1000 sims * 60 years)", () => {
    const big: ShareableSnapshot = {
      ...SAMPLE_CONFIG,
      result: {
        ...SAMPLE_RESULT,
        cashFlow: Array.from({ length: 60 }, (_, i) => ({
          year: 2026 + i,
          primaryAge: 35 + i,
          spouseAge: null,
          income: 120_000,
          expenses: 60_000,
          taxes: 18_000,
          netWorth: 250_000 + i * 10_000,
          netCashFlow: 42_000,
        })),
      },
    };
    const hash = encodeSnapshot(big);
    const back = decodeSnapshot(hash);
    expect(back.result.cashFlow).toHaveLength(60);
    expect(back.result.cashFlow[0]?.year).toBe(2026);
  });
});

describe("buildShareUrl", () => {
  it("builds a URL with the config query param on the current route", () => {
    const url = buildShareUrl("config", "c1-abc");
    expect(url).toMatch(/d=c1-abc$/);
  });

  it("builds a URL with the snapshot query param on the current route", () => {
    const url = buildShareUrl("snapshot", "s1-xyz");
    expect(url).toMatch(/s=s1-xyz$/);
  });

  it("does not percent-encode the hash (codec is already URL-safe)", () => {
    const url = buildShareUrl("config", "c1-N4IgLgpgFgrgJwQQwM4FoD..." as string);
    expect(url).not.toContain("%2D"); // no `-` percent-encoding
    expect(url).not.toContain("%3A"); // no `:` percent-encoding
  });
});

describe("shareByteSize", () => {
  it("returns a positive integer for any input", () => {
    expect(shareByteSize("c1:abc")).toBeGreaterThan(0);
    expect(Number.isInteger(shareByteSize("c1:abc"))).toBe(true);
  });
});
