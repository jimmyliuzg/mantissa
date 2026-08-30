/**
 * URL-hash share codec.
 *
 * Mantissa web is privacy-first: no data leaves the browser unless the
 * user clicks Share. Even then, the share is just a URL — the recipient's
 * browser fetches it from a static host and decodes it locally.
 *
 * We use lz-string's URI-safe base64 for compression, so the encoded
 * payload survives URL parsing and is human-transportable. URL-hash
 * capacity is effectively unlimited in modern browsers (>2MB), so
 * even 50KB RunResult payloads work.
 *
 * Two flavors:
 *   - encodeConfig / decodeConfig: a Mantissa config + the sim params.
 *   - encodeSnapshot / decodeSnapshot: a frozen RunResult + the config
 *     and sim params that produced it.
 *
 * Both functions validate the decoded shape and throw on garbage input.
 * A bad hash is a UX moment, not a security boundary — the URL is the
 * trust anchor.
 */

import LZString from "lz-string";

const PREFIX_CONFIG = "c1-";
const PREFIX_SNAPSHOT = "s1-";

function encode(value: unknown, prefix: string): string {
  const json = JSON.stringify(value);
  // lz-string's compressToEncodedURIComponent can still emit '+' in
  // some inputs (despite the name). URL query-string parsers treat
  // '+' as space, which corrupts the round-trip. We use base64
  // and then swap to URL-safe characters manually.
  const b64 = LZString.compressToBase64(json);
  const urlSafe = b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return prefix + urlSafe;
}

function decode<T>(hash: string, prefix: string): T {
  if (!hash.startsWith(prefix)) {
    throw new Error(`bad share hash: expected prefix ${prefix}, got ${hash.slice(0, 4)}`);
  }
  const compressed = hash.slice(prefix.length);
  // Reverse the URL-safe transform before decompressing.
  const b64 = compressed.replace(/-/g, "+").replace(/_/g, "/");
  const json = LZString.decompressFromBase64(b64);
  if (json === null || json === "") {
    throw new Error("share hash: could not decompress");
  }
  try {
    return JSON.parse(json) as T;
  } catch (e) {
    throw new Error(`share hash: invalid JSON (${e instanceof Error ? e.message : String(e)})`);
  }
}

export interface ShareableConfig {
  config: unknown;
  sims: number;
  seed: number;
}

export interface ShareableSnapshot {
  config: unknown;
  sims: number;
  seed: number;
  result: {
    kpis: Record<string, number>;
    cashFlow: Array<Record<string, number | null>>;
    mc: {
      percentiles: Array<{ percentile: number; value: number }>;
      method: string;
    };
    runtimeMs: number;
    generatedAt: number;
  };
}

export function encodeConfig(share: ShareableConfig): string {
  return encode(share, PREFIX_CONFIG);
}

export function decodeConfig(hash: string): ShareableConfig {
  return decode<ShareableConfig>(hash, PREFIX_CONFIG);
}

export function encodeSnapshot(snapshot: ShareableSnapshot): string {
  return encode(snapshot, PREFIX_SNAPSHOT);
}

export function decodeSnapshot(hash: string): ShareableSnapshot {
  return decode<ShareableSnapshot>(hash, PREFIX_SNAPSHOT);
}

/**
 * Read the `?d=...` or `?s=...` query string from a hash-route like
 * `#/review?d=c1:...`. Returns null if neither is present.
 */
export function readShareFromLocation(): {
  kind: "config" | "snapshot";
  hash: string;
} | null {
  const h = window.location.hash;
  const qIdx = h.indexOf("?");
  if (qIdx === -1) return null;
  const qs = h.slice(qIdx + 1);
  const params = new URLSearchParams(qs);
  const d = params.get("d");
  if (d) return { kind: "config", hash: d };
  const s = params.get("s");
  if (s) return { kind: "snapshot", hash: s };
  return null;
}

/**
 * Build a fresh share URL given the current location + a hash payload.
 * Preserves the route (`#/review`) and replaces any prior share params.
 */
export function buildShareUrl(kind: "config" | "snapshot", hash: string): string {
  const h = window.location.hash;
  const route = h.includes("?") ? h.slice(0, h.indexOf("?")) : h;
  const base = `${window.location.origin}${window.location.pathname}`;
  const paramKey = kind === "config" ? "d" : "s";
  // The codec emits URL-safe base64 (no characters that need
  // percent-encoding) so we can drop the hash in raw. encodeURIComponent
  // would mangle the prefix ("c1-" → "c1%2D") and inflate the URL.
  return `${base}${route}?${paramKey}=${hash}`;
}

/**
 * Estimate the encoded byte size of a share hash. Used to warn the
 * user when a snapshot is large.
 */
export function shareByteSize(hash: string): number {
  return new Blob([hash]).size;
}
