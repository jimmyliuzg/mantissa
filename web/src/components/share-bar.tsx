import { useEffect, useRef, useState } from "preact/hooks";
import {
	buildShareUrl,
	encodeConfig,
	encodeSnapshot,
	omitPlanNames,
	shareByteSize,
} from "../lib/share-codec";
import type { PlanStore } from "../state/plan-store";
import type { RunResult } from "@engine";

interface ShareBarProps {
	store: PlanStore;
	result: RunResult | null;
}

/** Sharing is explicit: opening this dialog does not copy or send a plan. */
export function ShareBar({ store, result }: ShareBarProps) {
	const [open, setOpen] = useState(false);
	const [kind, setKind] = useState<"config" | "snapshot">("snapshot");
	const [omitNames, setOmitNames] = useState(false);
	const [url, setUrl] = useState("");
	const [message, setMessage] = useState("");
	const [error, setError] = useState("");
	const dialog = useRef<HTMLDialogElement>(null);
	const shareButton = useRef<HTMLButtonElement>(null);

	useEffect(() => {
		if (!open || !dialog.current) return;
		if (dialog.current.showModal) dialog.current.showModal();
		else dialog.current.setAttribute("open", "");
	}, [open]);

	function close() {
		dialog.current?.close?.();
		setOpen(false);
		shareButton.current?.focus();
	}
	function resetLink() {
		setUrl("");
		setMessage("");
		setError("");
	}
	function generate(): string | null {
		try {
			const share = {
				config: omitNames
					? omitPlanNames(store.config.value)
					: store.config.value,
				sims: store.sims.value,
				seed: store.seed,
			};
			const actualKind = result ? kind : "config";
			const hash =
				actualKind === "snapshot" && result
					? encodeSnapshot({ ...share, result })
					: encodeConfig(share);
			const generated = buildShareUrl(actualKind, hash);
			setUrl(generated);
			setError("");
			setMessage(
				`Link ready (${formatBytes(shareByteSize(hash))}). Review it below, then copy or download it.`,
			);
			return generated;
		} catch (e) {
			setError(
				e instanceof Error ? e.message : "Could not create this share link.",
			);
			return null;
		}
	}
	async function copy() {
		const generated = url || generate();
		if (!generated) return;
		try {
			if (!navigator.clipboard?.writeText)
				throw new Error("Clipboard unavailable");
			await navigator.clipboard.writeText(generated);
			setMessage(
				"Link copied. Anyone you give it to can read the included plan data.",
			);
			setError("");
		} catch {
			setError(
				"Could not copy automatically. Select and copy the generated link below, or download it.",
			);
		}
	}
	function download() {
		const generated = url || generate();
		if (!generated) return;
		const objectUrl = URL.createObjectURL(
			new Blob([generated + "\n"], { type: "text/plain" }),
		);
		const anchor = document.createElement("a");
		anchor.href = objectUrl;
		anchor.download = "mantissa-share-link.txt";
		anchor.click();
		setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
	}

	return (
		<div class="share-bar">
			<button
				ref={shareButton}
				class="btn"
				type="button"
				onClick={() => {
					resetLink();
					setOpen(true);
				}}
			>
				Share plan
			</button>
			{open && (
				<dialog
					ref={dialog}
					class="panel"
					aria-labelledby="share-title"
					onCancel={(e) => {
						e.preventDefault();
						close();
					}}
					style={{
						maxWidth: "min(36rem, calc(100vw - 2rem))",
						width: "100%",
						maxHeight: "85vh",
						overflow: "auto",
						color: "var(--fg)",
						background: "var(--bg-elev)",
						border: "1px solid var(--border)",
					}}
				>
					<h2 id="share-title">Share this plan</h2>
					<p>
						Anyone with this link can read the included plan data. The link
						contains account balances, income, spending and other plan details.
						It is not encrypted and has no expiry or revocation.
					</p>
					<fieldset>
						<legend>What to include</legend>
						<label style={{ display: "block", marginBottom: ".75rem" }}>
							<input
								type="radio"
								name="share-kind"
								value="config"
								checked={kind === "config" || !result}
								onChange={() => {
									setKind("config");
									resetLink();
								}}
							/>{" "}
							Plan inputs — the recipient runs a new projection.
						</label>
						<label style={{ display: "block" }}>
							<input
								type="radio"
								name="share-kind"
								value="snapshot"
								disabled={!result}
								checked={kind === "snapshot" && !!result}
								onChange={() => {
									setKind("snapshot");
									resetLink();
								}}
							/>{" "}
							Plan inputs and frozen results — includes outcomes, model warnings
							and input readiness.
						</label>
						{!result && (
							<p>A completed projection is needed to include frozen results.</p>
						)}
					</fieldset>
					<label style={{ display: "block", margin: "1rem 0" }}>
						<input
							type="checkbox"
							checked={omitNames}
							onChange={(event) => {
								setOmitNames(event.currentTarget.checked);
								resetLink();
							}}
						/>{" "}
						Replace names and descriptions in plan inputs
					</label>
					<p class="muted">
						Replacing names does not anonymize a plan. Account IDs, dates and
						financial details remain included. No plan data is uploaded when
						generating this link.
					</p>
					<div style={{ display: "flex", gap: ".5rem", flexWrap: "wrap" }}>
						<button
							class="btn btn--primary"
							type="button"
							onClick={() => void copy()}
						>
							Create and copy link
						</button>
						<button class="btn" type="button" onClick={download}>
							Download link
						</button>
						<button class="btn" type="button" onClick={close}>
							Close
						</button>
					</div>
					{url && (
						<label style={{ display: "block", marginTop: "1rem" }}>
							Generated share link
							<textarea
								aria-label="Generated share link"
								readOnly
								value={url}
								rows={4}
								style={{
									display: "block",
									width: "100%",
									boxSizing: "border-box",
									overflowWrap: "anywhere",
								}}
								onFocus={(event) => event.currentTarget.select()}
							/>
						</label>
					)}
					{message && (
						<p role="status" aria-live="polite">
							{message}
						</p>
					)}
					{error && <p role="alert">{error}</p>}
				</dialog>
			)}
		</div>
	);
}
function formatBytes(n: number): string {
	return n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1)} kB`;
}
