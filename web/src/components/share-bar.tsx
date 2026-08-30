import { useState } from "preact/hooks";
import {
  buildShareUrl,
  encodeConfig,
  encodeSnapshot,
  shareByteSize,
  type ShareableSnapshot,
} from "../lib/share-codec";
import type { PlanStore } from "../state/plan-store";
import type { RunResult } from "@engine";

interface ShareBarProps {
  store: PlanStore;
  result: RunResult | null;
}

type CopyState = "idle" | "copied" | "error";

/**
 * Share bar: two buttons.
 *   - Copy link: share the config + sim params. Recipient re-runs.
 *   - Copy snapshot link: share the config + the frozen RunResult.
 *     Recipient renders instantly, no engine wait. Carries a "this is
 *     a snapshot" UX cue.
 *
 * Both encode to the URL hash, so the share is a static URL the
 * recipient can open on any host — no backend, no data leaves the
 * device until the recipient navigates to the link.
 */
export function ShareBar({ store, result }: ShareBarProps) {
  const [includeSnapshot, setIncludeSnapshot] = useState(true);
  const [copyState, setCopyState] = useState<CopyState>("idle");
  const [copiedKind, setCopiedKind] = useState<"config" | "snapshot" | null>(null);
  const [size, setSize] = useState<{ kind: "config" | "snapshot"; bytes: number } | null>(null);

  async function copy(kind: "config" | "snapshot") {
    const sims = store.sims.value;
    const seed = 42;
    const config = store.config.value;
    let hash: string;
    if (kind === "config") {
      hash = encodeConfig({ config, sims, seed });
    } else {
      if (!result) {
        setCopyState("error");
        return;
      }
      const snapshot: ShareableSnapshot = {
        config,
        sims,
        seed,
        result: {
          kpis: result.kpis as unknown as Record<string, number>,
          cashFlow: result.cashFlow as unknown as Array<Record<string, number | null>>,
          mc: result.mc as unknown as ShareableSnapshot["result"]["mc"],
          runtimeMs: result.runtimeMs,
          generatedAt: result.generatedAt,
        },
      };
      hash = encodeSnapshot(snapshot);
    }
    setSize({ kind, bytes: shareByteSize(hash) });
    const url = buildShareUrl(kind, hash);

    // Feature-detect the clipboard API. On insecure contexts (http://),
    // file://, or when the page lacks the clipboard-write permission,
    // navigator.clipboard is undefined or writeText rejects. Fall back
    // to a less intrusive message that auto-dismisses.
    if (!navigator.clipboard?.writeText) {
      setCopyState("error");
      setTimeout(() => setCopyState("idle"), 2000);
      return;
    }
    try {
      await navigator.clipboard.writeText(url);
      setCopiedKind(kind);
      setCopyState("copied");
      setTimeout(() => setCopyState("idle"), 2000);
    } catch {
      setCopyState("error");
      setTimeout(() => setCopyState("idle"), 2000);
    }
  }

  // The checkbox picks which share button is the primary one
  // (visually highlighted). When 'snapshot' is selected and we have
  // a result, that button is primary; otherwise the config button is.
  const primary: "config" | "snapshot" = includeSnapshot ? "snapshot" : "config";
  const hasResult = result !== null;

  return (
    <div class="share-bar" role="group" aria-label="Share this plan">
      <button
        type="button"
        class={`btn ${primary === "config" ? "btn--primary" : ""}`.trim()}
        onClick={() => void copy("config")}
        title="Share the config. Recipient's browser re-runs the engine (~20s for 1k sims)."
        aria-label="Copy config share link"
      >
        Copy link
      </button>
      <button
        type="button"
        class={`btn ${primary === "snapshot" ? "btn--primary" : ""}`.trim()}
        onClick={() => void copy("snapshot")}
        disabled={!hasResult}
        title="Share the config plus the frozen result. Recipient renders instantly without a re-run."
        aria-label="Copy snapshot share link (includes frozen Monte Carlo result)"
      >
        Copy snapshot link
      </button>
      <label class="share-toggle">
        <input
          type="checkbox"
          checked={includeSnapshot}
          onChange={(e) => setIncludeSnapshot((e.currentTarget as HTMLInputElement).checked)}
          aria-label="Default share to snapshot link (recipient sees the same numbers instantly without a re-run)"
        />
        <span>Snapshot by default</span>
      </label>

      {copyState === "copied" && size && (
        <span class="share-toast" data-tone="good" role="status" aria-live="polite">
          Copied {size.kind === "snapshot" ? "snapshot" : "config"} link ({formatBytes(size.bytes)})
        </span>
      )}
      {copyState === "error" && (
        <span class="share-toast" data-tone="bad" role="alert">
          Could not copy. Long-press the URL bar to copy manually.
        </span>
      )}
    </div>
  );
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} kB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}
