import type { RunResult } from "@engine";
export function cashFlowCsv(result: RunResult): string {
	const keys = [
		"year",
		"primaryAge",
		"spouseAge",
		"income",
		"plannedExpenses",
		"expenses",
		"spendingCut",
		"taxes",
		"fundingShortfall",
		"fundingShortfallCauses",
		"netCashFlow",
		"netWorth",
	] as const;
	const cell = (value: unknown) =>
		`"${String(Array.isArray(value) ? value.join("; ") : (value ?? "")).replace(/"/g, '""')}"`;
	return [
		keys.join(","),
		...result.cashFlow.map((row) =>
			keys.map((key) => cell(row[key])).join(","),
		),
	].join("\r\n");
}
export function downloadFile(contents: string, name: string, type: string) {
	const url = URL.createObjectURL(new Blob([contents], { type }));
	const a = document.createElement("a");
	a.href = url;
	a.download = name;
	a.click();
	setTimeout(() => URL.revokeObjectURL(url), 0);
}
