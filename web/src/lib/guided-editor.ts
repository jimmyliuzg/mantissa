import { getPath, setPath } from "./config-edit";

export type ConfigObject = Record<string, unknown>;
export function configFieldId(path: string): string {
	return `config-${path.replace(/\[(\d+)\]/g, ".$1").replace(/\./g, "-")}`;
}

/** Call after revealing the editor tab. Opens collapsed ancestors before focus. */
export function focusConfigField(path: string): boolean {
	const input = document.getElementById(configFieldId(path));
	if (!input) return false;
	let ancestor = input.parentElement;
	while (ancestor) {
		if (ancestor instanceof HTMLDetailsElement) ancestor.open = true;
		ancestor = ancestor.parentElement;
	}
	input.focus();
	input.scrollIntoView?.({ block: "center" });
	return true;
}

export function items(config: unknown, path: string): ConfigObject[] {
	const value = getPath(config, path);
	return Array.isArray(value) ? (value as ConfigObject[]) : [];
}

export function nextItemId(list: ConfigObject[], prefix: string): string {
	const ids = new Set(list.map((item) => item.id));
	let n = 1;
	while (ids.has(`${prefix}_${n}`)) n++;
	return `${prefix}_${n}`;
}

export function accountTax(type: string): string {
	if (["401k", "trad_401k", "trad_ira", "traditional_ira"].includes(type))
		return "pre_tax";
	if (["roth_ira", "roth_401k"].includes(type)) return "roth";
	if (["hsa", "529"].includes(type)) return "tax_exempt";
	return "taxable";
}

/** Refuse removal when another event/stream depends on this account. */
export function removeAccount(config: unknown, id: string): unknown {
	const root = config as ConfigObject;
	const references = (value: unknown): boolean => {
		if (Array.isArray(value)) return value.some(references);
		if (value && typeof value === "object")
			return Object.entries(value).some(([key, child]) =>
				[
					"goes_to_account",
					"funding_account",
					"source_account",
					"target_account",
					"account_id",
					"property_id",
				].includes(key)
					? child === id
					: references(child),
			);
		return false;
	};
	if (
		Object.entries(root).some(
			([key, value]) =>
				!["accounts", "savings_order", "surplus_account_id"].includes(key) &&
				references(value),
		)
	) {
		throw new Error(
			"This account funds an income, expense or event. Update that reference before removing the account.",
		);
	}
	const index = items(config, "accounts").findIndex(
		(account) => account.id === id,
	);
	let next = removeListItem(config, "accounts", index);
	next = setPath(
		next,
		"savings_order",
		((getPath(config, "savings_order") as string[] | undefined) ?? []).filter(
			(value) => value !== id,
		),
	);
	if (getPath(config, "surplus_account_id") === id)
		next = removeConfigPath(next, "surplus_account_id");
	return next;
}

/** Remove an optional property while retaining immutable update semantics. */
function removeConfigPath(config: unknown, path: string): unknown {
	const parts = path.split(".");
	const root = Array.isArray(config)
		? [...config]
		: { ...(config as ConfigObject) };
	let source: unknown = config;
	let target: unknown = root;
	for (const part of parts.slice(0, -1)) {
		const sourceRecord = source as Record<string, unknown>;
		const targetRecord = target as Record<string, unknown>;
		const child = sourceRecord[part];
		const clone = Array.isArray(child)
			? [...child]
			: { ...(child as Record<string, unknown>) };
		targetRecord[part] = clone;
		source = child;
		target = clone;
	}
	delete (target as Record<string, unknown>)[parts.at(-1)!];
	return root;
}

export function removeListItem(
	config: unknown,
	path: string,
	index: number,
): unknown {
	if (index < 0) return config;
	const list = items(config, path);
	const id = list[index]?.id;
	if (
		path === "expenses" &&
		items(config, "age_events").some((event) => event.expense_id === id)
	) {
		throw new Error(
			"An age event changes this spending item. Update the event in Advanced JSON before removing it.",
		);
	}
	let next = setPath(
		config,
		path,
		list.filter((_item, i) => i !== index),
	);
	const estimated = getPath(config, "input_metadata.estimated_fields");
	if (Array.isArray(estimated)) {
		const pattern = new RegExp(`^${path}\\[(\\d+)\\]`);
		next = setPath(
			next,
			"input_metadata.estimated_fields",
			estimated.flatMap((entry) => {
				if (typeof entry !== "string") return [entry];
				const match = entry.match(pattern);
				if (!match) return [entry];
				const oldIndex = Number(match[1]);
				if (oldIndex === index) return [];
				return [
					oldIndex > index
						? entry.replace(pattern, `${path}[${oldIndex - 1}]`)
						: entry,
				];
			}),
		);
	}
	return next;
}

/** Normalize explicit priorities too: they override savings_order in old plans. */
export function setSavingsOrder(config: unknown, order: string[]): unknown {
	let next = setPath(config, "savings_order", order);
	next = setPath(
		next,
		"accounts",
		items(config, "accounts").map((account) => ({
			...account,
			contribution_priority: order.indexOf(String(account.id)) + 1,
			// A zero priority with a legacy monthly contribution is re-enabled by the engine.
			monthly_contribution: 0,
			...(!("annual_contribution_cap" in account) &&
			Number(account.monthly_contribution) > 0
				? { annual_contribution_cap: Number(account.monthly_contribution) * 12 }
				: {}),
		})),
	);
	return next;
}

export function effectiveSavingsOrder(config: unknown): string[] {
	const explicit =
		(getPath(config, "savings_order") as string[] | undefined) ?? [];
	let nextPriority = explicit.length + 1;
	return items(config, "accounts")
		.map((account, index) => {
			const id = String(account.id);
			let priority = Number(account.contribution_priority ?? 0);
			if (!("contribution_priority" in account)) {
				const position = explicit.indexOf(id);
				if (position >= 0) priority = position + 1;
			}
			if (priority === 0 && Number(account.monthly_contribution) > 0) {
				priority = nextPriority;
				nextPriority++;
			}
			return { id, index, priority };
		})
		.filter((account) => account.priority > 0)
		.sort((a, b) => a.priority - b.priority || a.index - b.index)
		.map((account) => account.id);
}
