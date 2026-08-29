/**
 * Tiny immutable update helper for the config tree. We avoid lodash-style
 * deps to keep the bundle small. The config shape is "loose" in v1 (we
 * accept any JSON), so updateConfig works on a path string like
 * "economic.inflation" or "accounts.0.balance".
 */
export function setPath(obj: unknown, path: string, value: unknown): unknown {
  const parts = path.split(".");
  if (parts.length === 0) return value;
  // Clone the top level so Preact sees a new reference.
  const root = Array.isArray(obj) ? [...obj] : { ...(obj as Record<string, unknown>) };

  let cur: unknown = root;
  for (let i = 0; i < parts.length - 1; i++) {
    const k = parts[i]!;
    const next = cur as Record<string, unknown> | unknown[];
    const child = Array.isArray(next) ? next[Number(k)] : next[k];
    const cloned = Array.isArray(child) ? [...child] : { ...(child as Record<string, unknown>) };
    if (Array.isArray(next)) {
      (next as unknown[])[Number(k)] = cloned;
    } else {
      (next as Record<string, unknown>)[k] = cloned;
    }
    cur = cloned;
  }
  const last = parts[parts.length - 1]!;
  if (Array.isArray(cur)) {
    cur[Number(last)] = value;
  } else {
    (cur as Record<string, unknown>)[last] = value;
  }
  return root;
}

export function getPath(obj: unknown, path: string): unknown {
  const parts = path.split(".");
  let cur: unknown = obj;
  for (const k of parts) {
    if (cur == null) return undefined;
    if (Array.isArray(cur)) {
      cur = cur[Number(k)] as unknown;
    } else {
      cur = (cur as Record<string, unknown>)[k as string] as unknown;
    }
  }
  return cur;
}
