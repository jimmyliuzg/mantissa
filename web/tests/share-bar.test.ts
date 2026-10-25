import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { h, render } from "preact";
import { act } from "preact/test-utils";
import { signal } from "@preact/signals";
import { ShareBar } from "../src/components/share-bar";
import { decodeConfig, decodeSnapshot } from "../src/lib/share-codec";
import type { PlanStore } from "../src/state/plan-store";
import type { RunResult } from "../src/engine/types";

const result: RunResult = {
	kpis: {
		successRate: 1,
		medianFinalNetWorth: 10,
		p10FinalNetWorth: 1,
		p90FinalNetWorth: 100,
		medianLifetimeTaxes: 2,
		outOfSavingsRate: 0,
		numSimulations: 1000,
	},
	cashFlow: [],
	mc: { percentiles: [], yearlyPercentiles: [], method: "gaussian" },
	runtimeMs: 10,
	generatedAt: 12345,
	warnings: [
		{
			year: null,
			severity: "warning",
			category: "coverage",
			message: "Limited state coverage",
		},
	],
	inputReadiness: { provisional: true, access_assessed: false, items: [] },
};
let root: HTMLDivElement;
let writeText = vi.fn();
const store = {
	config: signal({
		name: "Private name",
		primary: {
			name: "Alex",
			birth_date: "1980-01-01",
			retirement_date: "2045-01-01",
		},
		spouse: null,
		economic: {},
		accounts: [{ id: "cash", name: "Savings", balance: 250001 }],
	}),
	sims: signal(1000),
	seed: 42,
} as PlanStore;

function button(text: string): HTMLButtonElement {
	const found = [...root.querySelectorAll("button")].find(
		(item) => item.textContent === text,
	);
	if (!found) throw new Error(`Missing button ${text}`);
	return found;
}
async function click(text: string) {
	await act(async () => button(text).click());
}
function linkPayload(): string {
	const value = root.querySelector<HTMLTextAreaElement>("textarea")?.value;
	if (!value) throw new Error("No generated fallback link");
	return value.slice(value.indexOf("?") + 3);
}

beforeEach(() => {
	root = document.createElement("div");
	document.body.append(root);
	writeText = vi.fn().mockResolvedValue(undefined);
	Object.defineProperty(navigator, "clipboard", {
		configurable: true,
		value: { writeText },
	});
	HTMLDialogElement.prototype.showModal = function () {
		this.setAttribute("open", "");
	};
	HTMLDialogElement.prototype.close = function () {
		this.removeAttribute("open");
	};
});
afterEach(() => {
	render(null, root);
	root.remove();
	vi.restoreAllMocks();
});

describe("explicit share dialog", () => {
	it("does not copy on opening, then copies complete frozen results", async () => {
		render(h(ShareBar, { store, result }), root);
		await click("Share plan");
		expect(writeText).not.toHaveBeenCalled();
		expect(root.textContent).toContain("Anyone with this link");
		await click("Create and copy link");
		expect(decodeSnapshot(linkPayload()).result).toEqual(result);
		expect(writeText).toHaveBeenCalledWith(
			root.querySelector("textarea")?.value,
		);
	});
	it("offers the actual generated URL when clipboard access fails", async () => {
		writeText.mockRejectedValue(new Error("Denied"));
		render(h(ShareBar, { store, result: null }), root);
		await click("Share plan");
		await click("Create and copy link");
		expect(root.querySelector("textarea")?.readOnly).toBe(true);
		expect(root.querySelector('[role="alert"]')?.textContent).toContain(
			"generated link below",
		);
		expect(decodeConfig(linkPayload()).config).toEqual(store.config.value);
	});
	it("omits plan names only when selected and retains financial assumptions", async () => {
		render(h(ShareBar, { store, result: null }), root);
		await click("Share plan");
		await act(async () =>
			root.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
		);
		await click("Create and copy link");
		const config = decodeConfig(linkPayload()).config as {
			name: string;
			accounts: { id: string; balance: number }[];
		};
		expect(config.name).toBe("Unnamed");
		expect(config.accounts[0]).toMatchObject({ id: "cash", balance: 250001 });
		expect((store.config.value as { name: string }).name).toBe("Private name");
	});
});
