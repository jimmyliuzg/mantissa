import { describe, expect, it } from "vitest";
import LZString from "lz-string";
import type { RunResult } from "../src/engine/types";
import {
	buildShareUrl,
	decodeConfig,
	decodeSnapshot,
	encodeConfig,
	encodeSnapshot,
	shareByteSize,
	type ShareableConfig,
	type ShareableSnapshot,
	MAX_SHARE_CHARACTERS,
	MAX_SHARE_JSON_CHARACTERS,
	omitPlanNames,
} from "../src/lib/share-codec";

const SAMPLE_CONFIG: ShareableConfig = {
	config: {
		name: "demo",
		primary: {
			name: "P",
			birth_date: "1991-01-01",
			retirement_date: "2056-01-01",
			longevity_age: 92,
		},
		spouse: {
			name: "(none)",
			birth_date: "1991-01-01",
			retirement_date: "2056-01-01",
			longevity_age: 92,
		},
		economic: {
			inflation: 0.025,
			investment_return_mean: 0.06,
			investment_return_volatility: 0.13,
		},
		accounts: [
			{
				id: "b",
				name: "B",
				type: "brokerage",
				tax_treatment: "taxable",
				balance: 250000,
			},
		],
		income_streams: [],
		expenses: [],
		state: "CA",
	},
	sims: 1000,
	seed: 42,
};

const SAMPLE_RESULT: RunResult = {
  runMetadata: {
    schema_version: 1,
    model_version: "0.1.0",
    effective_seed: 42,
    method: "gaussian",
    scenario: "baseline",
    simulations: 1000,
    mortality_mode: "fixed",
    config_fingerprint: "a".repeat(64),
    rules_provenance: {
      catalog_version: "1",
      effective_years: {
        "2030": { tax: { status: "user" }, contributions: { status: "projected" } },
      },
    },
  },
	kpis: {
		successRate: 0.965,
		medianFinalNetWorth: 11_600_000,
		p10FinalNetWorth: 1_000_000,
		p90FinalNetWorth: 15_000_000,
		medianLifetimeTaxes: 100_000,
		outOfSavingsRate: 0.035,
		numSimulations: 1000,
	},
	cashFlow: [
		{
			year: 2026,
			primaryAge: 35,
			spouseAge: null,
			income: 120_000,
			expenses: 60_000,
			taxes: 18_000,
			netWorth: 280_000,
			netCashFlow: 42_000,
		},
	],
	mc: {
		percentiles: [{ percentile: 50, value: 11_600_000 }],
		method: "gaussian",
		yearlyPercentiles: [],
	},
	warnings: [
		{
			year: null,
			category: "state_coverage",
			severity: "warning",
			message: "Coverage limitation",
		},
	],
	inputReadiness: {
		provisional: true,
		access_assessed: false,
		items: [
			{ path: "accounts[0].balance", status: "estimated", detail: "Estimate" },
		],
	},
	outcomes: {
		schema_version: 1,
		planned_spending_met_rate: 0.9,
		adjusted_spending_met_rate: 0.98,
		account_access_met_rate: null,
		legacy_target_met_rate: 0.8,
		terminal_estate_estimate_runs: 1000,
		denominators: { spending: 1000, account_access: 0, legacy: 1000 },
		base_year: 2026,
		monetary_convention: "real",
		legacy_target_base_year: 2026,
		first_funding_shortfall_year_counts: { "2040": 1 },
		first_funding_shortfall_cause_counts: { access: 1 },
	},
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
		expect(back).toEqual({
			...snap,
			schemaVersion: 2,
			provenance: {
				model: "mantissa",
				snapshotSchema: 2,
				createdAt: SAMPLE_RESULT.generatedAt,
			},
		});
		expect(back.result.outcomes).toEqual(SAMPLE_RESULT.outcomes);
		expect(back.result.warnings).toEqual(SAMPLE_RESULT.warnings);
		expect(back.result.inputReadiness).toEqual(SAMPLE_RESULT.inputReadiness);
		expect(back.result.runMetadata).toEqual(SAMPLE_RESULT.runMetadata);
	});

	it("snapshot is larger than config-only for the same config", () => {
		const cfgSize = shareByteSize(encodeConfig(SAMPLE_CONFIG));
		const snapSize = shareByteSize(
			encodeSnapshot({ ...SAMPLE_CONFIG, result: SAMPLE_RESULT }),
		);
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
		const url = buildShareUrl(
			"config",
			"c1-N4IgLgpgFgrgJwQQwM4FoD..." as string,
		);
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

function uncheckedHash(value: unknown, prefix = "c1-"): string {
	return (
		prefix +
		LZString.compressToBase64(JSON.stringify(value))
			.replace(/\+/g, "-")
			.replace(/\//g, "_")
			.replace(/=+$/, "")
	);
}

describe("untrusted sharing boundary", () => {
	it("rejects JSON values and malformed simulation options before engine startup", () => {
		for (const config of [null, [], {}, "plan"])
			expect(() =>
				decodeConfig(uncheckedHash({ ...SAMPLE_CONFIG, config })),
			).toThrow();
		for (const sims of [-1, 0, 5001, 1.5, "1000"])
			expect(() =>
				decodeConfig(uncheckedHash({ ...SAMPLE_CONFIG, sims })),
			).toThrow(/Simulations/);
		expect(() =>
			decodeConfig(uncheckedHash({ ...SAMPLE_CONFIG, seed: -1 })),
		).toThrow(/Seed/);
	});
	it("rejects compressed and expanded oversize inputs", () => {
		expect(() =>
			decodeConfig("c1-" + "a".repeat(MAX_SHARE_CHARACTERS)),
		).toThrow(/too large/);
		const compressedBomb = uncheckedHash({
			repeated: "x".repeat(MAX_SHARE_JSON_CHARACTERS + 1),
		});
		expect(compressedBomb.length).toBeLessThan(MAX_SHARE_CHARACTERS);
		expect(() => decodeConfig(compressedBomb)).toThrow(
			/Expanded share data is too large/,
		);
	});
	it("normalizes original s1 links missing later result fields", () => {
		const { warnings, inputReadiness, outcomes, runMetadata, ...oldResult } = SAMPLE_RESULT;
		const { yearlyPercentiles, ...oldMc } = oldResult.mc;
		const back = decodeSnapshot(
			uncheckedHash(
				{ ...SAMPLE_CONFIG, result: { ...oldResult, mc: oldMc } },
				"s1-",
			),
		);
		expect(back.result.warnings).toEqual([]);
		expect(back.result.mc.yearlyPercentiles).toEqual([]);
		expect(back.result.outcomes).toBeUndefined();
		expect(back.result.runMetadata).toBeUndefined();
		expect(back.schemaVersion).toBe(1);
		expect(decodeSnapshot(encodeSnapshot(back)).schemaVersion).toBe(2);
	});
  it("rejects replay metadata with a seed that cannot round-trip exactly", () => {
    for (const effective_seed of [-1, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
      expect(() =>
        decodeSnapshot(
          uncheckedHash(
            {
              ...SAMPLE_CONFIG,
              result: {
                ...SAMPLE_RESULT,
                runMetadata: {
                  ...SAMPLE_RESULT.runMetadata,
                  effective_seed,
                },
              },
            },
            "s2-",
          ),
        ),
      ).toThrow(/metadata or replay seed/);
    }
  });
	it("rejects a malformed snapshot result and incompatible schema", () => {
		expect(() =>
			decodeSnapshot(
				uncheckedHash(
					{
						...SAMPLE_CONFIG,
						result: { ...SAMPLE_RESULT, cashFlow: "not rows" },
					},
					"s2-",
				),
			),
		).toThrow(/cashFlow/);
		expect(() =>
			decodeSnapshot(
				uncheckedHash(
					{ ...SAMPLE_CONFIG, schemaVersion: 99, result: SAMPLE_RESULT },
					"s2-",
				),
			),
		).toThrow(/version/);
	});
	it("preserves financial IDs when names and descriptions are omitted", () => {
		const original = {
			...(SAMPLE_CONFIG.config as object),
			description: "private narrative",
		};
		const sanitized = omitPlanNames(original) as Record<string, unknown>;
		expect(sanitized.name).toBe("Unnamed");
		expect(sanitized.description).toBe("");
		expect((sanitized.accounts as Record<string, unknown>[])[0]?.id).toBe("b");
		expect((sanitized.accounts as Record<string, unknown>[])[0]?.balance).toBe(
			250000,
		);
		expect((original as Record<string, unknown>).name).toBe("demo");
	});
});
