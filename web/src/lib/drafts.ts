const KEY = "mantissa:remembered-plan";
const FLAG = "mantissa:remember-plan";
export function rememberedPlan(): string | null {
	try {
		return localStorage.getItem(FLAG) === "yes"
			? localStorage.getItem(KEY)
			: null;
	} catch {
		return null;
	}
}
export function remembersPlan(): boolean {
	try {
		return localStorage.getItem(FLAG) === "yes";
	} catch {
		return false;
	}
}
export function saveDraft(config: unknown, sims = 1000, seed = 42): boolean {
	try {
		sessionStorage.setItem("mantissa:config", JSON.stringify(config));
		sessionStorage.setItem(
			"mantissa:run-options",
			JSON.stringify({ sims, seed }),
		);
		if (remembersPlan())
			localStorage.setItem(KEY, JSON.stringify({ config, sims, seed }));
		return true;
	} catch {
		return false;
	}
}
export function setRememberPlan(
	remember: boolean,
	config: unknown,
	sims: number,
	seed: number,
): boolean {
	try {
		if (remember) {
			localStorage.setItem(FLAG, "yes");
			localStorage.setItem(KEY, JSON.stringify({ config, sims, seed }));
		} else {
			localStorage.removeItem(FLAG);
			localStorage.removeItem(KEY);
		}
		return true;
	} catch {
		return false;
	}
}
export function clearDrafts() {
	for (const key of [
		"mantissa:config",
		"mantissa:run-options",
		"mantissa:wizard-draft",
		"mantissa:reviewed-config",
	]) {
		try {
			sessionStorage.removeItem(key);
		} catch {
			/* Storage may be unavailable. */
		}
	}
	try {
		localStorage.removeItem(KEY);
		localStorage.removeItem(FLAG);
	} catch {
		/* No saved data available. */
	}
}
