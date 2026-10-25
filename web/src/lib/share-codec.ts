/** Versioned, size-bounded browser-local sharing. Links contain readable plan data. */
import LZString from "lz-string";
import type { RunResult } from "../engine/types";
import {
	finiteNumber,
	record,
	validateConfig,
	validateJsonTree,
	validateSimulationOptions,
} from "./config-validation";

const PREFIX_CONFIG = "c1-";
const PREFIX_SNAPSHOT = "s2-";
export const MAX_SHARE_CHARACTERS = 250_000;
export const MAX_SHARE_JSON_CHARACTERS = 1_000_000;

function encode(value: unknown, prefix: string): string {
	const json = JSON.stringify(value);
	if (json.length > MAX_SHARE_JSON_CHARACTERS)
		throw new Error(
			"This plan is too large for a share link. Download the plan instead.",
		);
	const hash =
		prefix +
		LZString.compressToBase64(json)
			.replace(/\+/g, "-")
			.replace(/\//g, "_")
			.replace(/=+$/, "");
	if (hash.length > MAX_SHARE_CHARACTERS)
		throw new Error(
			"This plan is too large for a share link. Download the plan instead.",
		);
	return hash;
}

/* LZ decoder adapted from lz-string (MIT), Copyright (c) 2013 pieroxy.
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
 * Unlike the upstream decoder, this stops before producing an oversized result.
 */
function boundedDecompress(compressed: string): string {
	const alphabet =
		"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
	let index = 0;
	let bit = 0;
	let current = 0;
	function read(bits: number): number {
		let value = 0;
		for (let position = 0; position < bits; position++) {
			if (bit === 0) {
				if (index >= compressed.length)
					throw new Error("Share link is truncated or could not decompress.");
				current = alphabet.indexOf(compressed[index++]!);
				if (current < 0)
					throw new Error("Share link contains invalid characters.");
				bit = 32;
			}
			if (current & bit) value += 2 ** position;
			bit >>= 1;
		}
		return value;
	}
	const initial = read(2);
	if (initial === 2) return "";
	if (initial > 1) throw new Error("Share link could not decompress.");
	let previous = String.fromCharCode(read(initial === 0 ? 8 : 16));
	const dictionary: string[] = ["", "", "", previous];
	const result = [previous];
	let outputLength = previous.length;
	let size = 4;
	let enlargeIn = 4;
	let bits = 3;
	while (true) {
		let code = read(bits);
		if (code === 2) return result.join("");
		if (code === 0 || code === 1) {
			dictionary[size++] = String.fromCharCode(read(code === 0 ? 8 : 16));
			code = size - 1;
			enlargeIn--;
		}
		if (enlargeIn === 0) {
			enlargeIn = 2 ** bits;
			bits++;
		}
		const entry =
			dictionary[code] || (code === size ? previous + previous[0] : undefined);
		if (entry === undefined)
			throw new Error("Share link could not decompress.");
		outputLength += entry.length;
		if (outputLength > MAX_SHARE_JSON_CHARACTERS)
			throw new Error("Expanded share data is too large.");
		result.push(entry);
		dictionary[size++] = previous + entry[0];
		enlargeIn--;
		previous = entry;
		if (enlargeIn === 0) {
			enlargeIn = 2 ** bits;
			bits++;
		}
	}
}

function decode(hash: string, prefixes: string[]): unknown {
	const prefix = prefixes.find((p) => hash.startsWith(p));
	if (!prefix)
		throw new Error(`bad share hash: expected ${prefixes.join(" or ")}`);
	if (hash.length > MAX_SHARE_CHARACTERS)
		throw new Error("Share link is too large.");
	const payload = hash.slice(prefix.length);
	if (!payload || !/^[A-Za-z0-9_-]+$/.test(payload))
		throw new Error("Share link contains invalid characters.");
	const json = boundedDecompress(payload.replace(/-/g, "+").replace(/_/g, "/"));
	try {
		return JSON.parse(json);
	} catch {
		throw new Error("Share link does not contain valid JSON.");
	}
}

export interface ShareableConfig {
	config: unknown;
	sims: number;
	seed: number;
}
export interface SnapshotProvenance {
	model: "mantissa";
	snapshotSchema: 1 | 2;
	createdAt: number;
	engineVersion?: string;
}
export interface ShareableSnapshot extends ShareableConfig {
	schemaVersion?: 1 | 2;
	provenance?: SnapshotProvenance;
	result: RunResult;
}

function validateEnvelope(value: unknown): ShareableConfig {
	const envelope = record(value, "Share payload");
	validateConfig(envelope.config);
	validateSimulationOptions(envelope.sims, envelope.seed);
	return envelope as unknown as ShareableConfig;
}

function normalizeResult(value: unknown): RunResult {
	validateJsonTree(value);
	const result = record(value, "Snapshot result");
	const kpis = record(result.kpis, "result.kpis");
	for (const key of [
		"successRate",
		"medianFinalNetWorth",
		"p10FinalNetWorth",
		"p90FinalNetWorth",
		"medianLifetimeTaxes",
		"outOfSavingsRate",
		"numSimulations",
	])
		finiteNumber(kpis[key], `result.kpis.${key}`);
	if (!Array.isArray(result.cashFlow) || result.cashFlow.length > 250)
		throw new Error("result.cashFlow must contain at most 250 annual rows.");
	result.cashFlow.forEach((row, i) => {
		const item = record(row, `result.cashFlow[${i}]`);
		for (const key of [
			"year",
			"primaryAge",
			"income",
			"expenses",
			"taxes",
			"netWorth",
			"netCashFlow",
		])
			finiteNumber(item[key], `result.cashFlow[${i}].${key}`);
	});
	const mc = record(result.mc, "result.mc");
	if (!["gaussian", "historical"].includes(String(mc.method)))
		throw new Error("result.mc.method is not supported.");
	if (!Array.isArray(mc.percentiles) || mc.percentiles.length > 100)
		throw new Error("result.mc.percentiles must be a list.");
	mc.percentiles.forEach((entry, i) => {
		const point = record(entry, `result.mc.percentiles[${i}]`);
		finiteNumber(point.percentile, "percentile");
		finiteNumber(point.value, "percentile value");
	});
	const yearly = mc.yearlyPercentiles ?? [];
	if (!Array.isArray(yearly) || yearly.length > 250)
		throw new Error(
			"result.mc.yearlyPercentiles must contain at most 250 annual rows.",
		);
	yearly.forEach((entry, i) => {
		const point = record(entry, `result.mc.yearlyPercentiles[${i}]`);
		for (const key of ["age", "p10", "p25", "p50", "p75", "p90"])
			finiteNumber(point[key], `yearlyPercentiles[${i}].${key}`);
	});
	const warnings = result.warnings ?? [];
	if (!Array.isArray(warnings) || warnings.length > 2000)
		throw new Error("result.warnings must be a list.");
	warnings.forEach((entry, i) => {
		const warning = record(entry, `result.warnings[${i}]`);
		if (
			typeof warning.message !== "string" ||
			typeof warning.category !== "string" ||
			!["info", "warning", "error"].includes(String(warning.severity))
		)
			throw new Error(`result.warnings[${i}] is invalid.`);
	});
	if (result.outcomes !== undefined) {
		const outcomes = record(result.outcomes, "result.outcomes");
		if (outcomes.schema_version !== 1)
			throw new Error("Snapshot outcome version is not supported.");
		for (const key of [
			"planned_spending_met_rate",
			"adjusted_spending_met_rate",
			"legacy_target_met_rate",
			"terminal_estate_estimate_runs",
			"base_year",
			"legacy_target_base_year",
		])
			finiteNumber(outcomes[key], `result.outcomes.${key}`);
		const denominators = record(
			outcomes.denominators,
			"result.outcomes.denominators",
		);
		for (const key of ["spending", "account_access", "legacy"])
			finiteNumber(denominators[key], `result.outcomes.denominators.${key}`);
		record(
			outcomes.first_funding_shortfall_year_counts,
			"result.outcomes.first_funding_shortfall_year_counts",
		);
		record(
			outcomes.first_funding_shortfall_cause_counts,
			"result.outcomes.first_funding_shortfall_cause_counts",
		);
		if (!["real", "nominal"].includes(String(outcomes.monetary_convention)))
			throw new Error("Snapshot monetary convention is invalid.");
	}
	if (result.inputReadiness !== undefined) {
		const readiness = record(result.inputReadiness, "result.inputReadiness");
		if (
			typeof readiness.provisional !== "boolean" ||
			typeof readiness.access_assessed !== "boolean" ||
			!Array.isArray(readiness.items)
		)
			throw new Error("Snapshot input readiness is invalid.");
		readiness.items.forEach((entry, i) => {
			const item = record(entry, `result.inputReadiness.items[${i}]`);
			if (
				typeof item.path !== "string" ||
				typeof item.detail !== "string" ||
				!["provided", "estimated", "missing"].includes(String(item.status))
			)
				throw new Error(`result.inputReadiness.items[${i}] is invalid.`);
		});
	}
	finiteNumber(result.runtimeMs, "result.runtimeMs");
	finiteNumber(result.generatedAt, "result.generatedAt");
	return {
		...result,
		mc: { ...mc, yearlyPercentiles: yearly },
		warnings,
	} as unknown as RunResult;
}

export function encodeConfig(share: ShareableConfig): string {
	validateEnvelope(share);
	return encode(share, PREFIX_CONFIG);
}
export function decodeConfig(hash: string): ShareableConfig {
	return validateEnvelope(decode(hash, [PREFIX_CONFIG]));
}
export function encodeSnapshot(snapshot: ShareableSnapshot): string {
	validateEnvelope(snapshot);
	const result = normalizeResult(snapshot.result);
	return encode(
		{
			...snapshot,
			schemaVersion: 2,
			provenance: {
				...snapshot.provenance,
				model: "mantissa",
				snapshotSchema: 2,
				createdAt: result.generatedAt,
			},
			result,
		},
		PREFIX_SNAPSHOT,
	);
}
export function decodeSnapshot(hash: string): ShareableSnapshot {
	const value = decode(hash, [PREFIX_SNAPSHOT, "s1-"]);
	validateEnvelope(value);
	const snapshot = record(value, "Snapshot");
	const schemaVersion = hash.startsWith("s1-") ? 1 : 2;
	if (
		snapshot.schemaVersion !== undefined &&
		snapshot.schemaVersion !== schemaVersion
	)
		throw new Error("Snapshot schema version is not supported.");
	const result = normalizeResult(snapshot.result);
	if (snapshot.provenance !== undefined) {
		const provenance = record(snapshot.provenance, "Snapshot provenance");
		if (
			provenance.model !== "mantissa" ||
			provenance.snapshotSchema !== schemaVersion
		)
			throw new Error("Snapshot provenance is not supported.");
		finiteNumber(provenance.createdAt, "provenance.createdAt");
		if (
			provenance.engineVersion !== undefined &&
			typeof provenance.engineVersion !== "string"
		)
			throw new Error("provenance.engineVersion must be text.");
	}
	return {
		...snapshot,
		schemaVersion,
		provenance: snapshot.provenance ?? {
			model: "mantissa",
			snapshotSchema: schemaVersion,
			createdAt: result.generatedAt,
		},
		result,
	} as ShareableSnapshot;
}

export function readShareFromLocation(): {
	kind: "config" | "snapshot";
	hash: string;
} | null {
	const h = window.location.hash;
	const qIdx = h.indexOf("?");
	if (qIdx === -1) return null;
	const params = new URLSearchParams(h.slice(qIdx + 1));
	const d = params.get("d");
	if (d) return { kind: "config", hash: d };
	const s = params.get("s");
	return s ? { kind: "snapshot", hash: s } : null;
}
export function buildShareUrl(
	kind: "config" | "snapshot",
	hash: string,
): string {
	return `${window.location.origin}${window.location.pathname}#/review?${kind === "config" ? "d" : "s"}=${hash}`;
}
export function shareByteSize(hash: string): number {
	return new Blob([hash]).size;
}

/** Omit user-provided labels, preserving IDs and all financial assumptions. */
export function omitPlanNames(config: unknown): unknown {
	const clean = (value: unknown): unknown => {
		if (Array.isArray(value)) return value.map(clean);
		if (!value || typeof value !== "object") return value;
		return Object.fromEntries(
			Object.entries(value).map(([key, item]) => [
				key,
				key === "name" ? "Unnamed" : key === "description" ? "" : clean(item),
			]),
		);
	};
	return clean(config);
}
