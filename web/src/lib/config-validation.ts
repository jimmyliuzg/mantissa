/** Small import boundary; financial and modeling rules remain in the Python engine. */
export function record(value: unknown, path: string): Record<string, unknown> {
	if (!value || typeof value !== "object" || Array.isArray(value)) {
		throw new Error(`${path} must be an object.`);
	}
	return value as Record<string, unknown>;
}

export function finiteNumber(value: unknown, path: string): number {
	if (
		typeof value !== "number" ||
		!Number.isFinite(value) ||
		Math.abs(value) > 1e16
	) {
		throw new Error(`${path} must be a finite, reasonably sized number.`);
	}
	return value;
}

export function validateJsonTree(value: unknown): void {
	let nodes = 0;
	const visit = (item: unknown, path: string, depth: number) => {
		if (++nodes > 50_000 || depth > 30)
			throw new Error("Plan data is too large or deeply nested.");
		if (typeof item === "number") finiteNumber(item, path);
		if (typeof item === "string" && item.length > 100_000)
			throw new Error(`${path} is too long.`);
		if (!item || typeof item !== "object") return;
		for (const [key, child] of Object.entries(item)) {
			if (["__proto__", "prototype", "constructor"].includes(key))
				throw new Error(`${path}.${key} is not allowed.`);
			visit(child, `${path}.${key}`, depth + 1);
		}
	};
	visit(value, "plan", 0);
}

function date(value: unknown, path: string): void {
	if (
		typeof value !== "string" ||
		!/^\d{4}-\d{2}-\d{2}$/.test(value) ||
		!Number.isFinite(Date.parse(value)) ||
		new Date(value).toISOString().slice(0, 10) !== value
	) {
		throw new Error(`${path} must be a calendar date (YYYY-MM-DD).`);
	}
}

export function validateConfig(value: unknown): Record<string, unknown> {
	validateJsonTree(value);
	const config = record(value, "Plan");
	if (config.name !== undefined && typeof config.name !== "string")
		throw new Error("Plan name must be text.");
	for (const field of ["primary", "spouse"]) {
		if (field === "spouse" && config[field] == null) continue;
		const person = record(config[field], field);
		date(person.birth_date, `${field}.birth_date`);
		date(person.retirement_date, `${field}.retirement_date`);
		if (person.longevity_age !== undefined) {
			const age = finiteNumber(person.longevity_age, `${field}.longevity_age`);
			if (age <= 0 || age > 130)
				throw new Error(`${field}.longevity_age must be between 1 and 130.`);
		}
	}
	if (config.economic !== undefined) record(config.economic, "economic");
	for (const field of [
		"accounts",
		"income_streams",
		"expenses",
		"mortgages",
		"windfalls",
		"housing_events",
		"roth_conversions",
		"rollover_events",
		"dependents",
		"age_events",
	]) {
		const list = config[field];
		if (list === undefined) continue;
		if (!Array.isArray(list) || list.length > 1000)
			throw new Error(`${field} must be a list with at most 1,000 entries.`);
		list.forEach((entry, index) => record(entry, `${field}[${index}]`));
	}
	const accounts = (config.accounts ?? []) as Record<string, unknown>[];
	const ids = new Set<string>();
	accounts.forEach((account, index) => {
		if (typeof account.id !== "string" || !account.id.trim())
			throw new Error(`accounts[${index}].id must be nonempty text.`);
		if (ids.has(account.id))
			throw new Error(`accounts[${index}].id duplicates another account.`);
		ids.add(account.id);
		if (account.balance !== undefined)
			finiteNumber(account.balance, `accounts[${index}].balance`);
	});
	return config;
}

export function validateSimulationOptions(sims: unknown, seed: unknown): void {
	if (
		typeof sims !== "number" ||
		!Number.isInteger(sims) ||
		sims < 1 ||
		sims > 5000
	) {
		throw new Error("Simulations must be a whole number between 1 and 5,000.");
	}
	if (
		typeof seed !== "number" ||
		!Number.isSafeInteger(seed) ||
		seed < 0 ||
		seed > 0xffffffff
	) {
		throw new Error("Seed must be a whole number between 0 and 4,294,967,295.");
	}
}
