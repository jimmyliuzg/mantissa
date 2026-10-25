import { useEffect, useState } from "preact/hooks";
import { getPath, setPath } from "../lib/config-edit";
import { validateConfig } from "../lib/config-validation";
import {
	accountTax,
	configFieldId,
	effectiveSavingsOrder,
	items,
	nextItemId,
	removeAccount,
	removeListItem,
	setSavingsOrder,
	type ConfigObject,
} from "../lib/guided-editor";
import type { PlanStore } from "../state/plan-store";
import { RuleControls } from "./rule-controls";

interface FieldDef {
	path: string;
	label: string;
	kind?: "number" | "date" | "text" | "select" | "percent" | "checkbox";
	options?: readonly (string | { value: string; label: string })[];
	hint?: string;
	optional?: boolean;
	min?: number;
	max?: number;
	step?: number;
	fallback?: unknown;
}

const ACCOUNT_TYPES = [
	"checking",
	"savings",
	"brokerage",
	"401k",
	"roth_401k",
	"trad_ira",
	"roth_ira",
	"hsa",
	"529",
	"real_estate",
	"vehicle",
	"other",
];
const TAX_OPTIONS = [
	{ value: "taxable", label: "Taxable" },
	{ value: "pre_tax", label: "Pre-tax" },
	{ value: "roth", label: "Roth" },
	{ value: "tax_exempt", label: "Tax-exempt" },
];
const STRATEGIES = [
	{ value: "fixed", label: "Keep planned spending" },
	{ value: "guardrails", label: "Guardrails" },
	{ value: "dynamic", label: "Dynamic" },
	{ value: "percent_of_portfolio", label: "Percentage of portfolio" },
	{ value: "floor_ceiling", label: "Floor and ceiling" },
];

export function ConfigDrawer({ store }: { store: PlanStore }) {
	const config = store.config.value;
	const field = (definition: FieldDef) => (
		<Field key={definition.path} field={definition} store={store} />
	);
	return (
		<aside class="drawer" aria-label="Edit plan">
			<header>
				<h2>Edit plan</h2>
				<p class="muted small">
					Changes update your projection automatically. Rates are shown as
					percentages. Use “Use default” to clear an optional assumption.
				</p>
			</header>
			<details>
				<summary>
					<strong>Plan settings</strong>
				</summary>
				<fieldset>
					{field({ path: "name", label: "Plan name" })}
					{field({
						path: "balance_date",
						label: "Statement date",
						kind: "date",
						optional: true,
					})}
					{field({
						path: "legacy_goal",
						label: "Legacy goal (today’s dollars)",
						kind: "number",
						min: 0,
					})}
					{field({
						path: "withdrawal_strategy",
						label: "Spending strategy",
						kind: "select",
						options: STRATEGIES,
						fallback: "fixed",
					})}
					{getPath(config, "withdrawal_strategy") === "percent_of_portfolio" &&
						field({
							path: "withdrawal_rate",
							label: "Annual withdrawal (%)",
							kind: "percent",
							min: 0,
							max: 100,
							fallback: 0.04,
						})}
					{field({
						path: "state",
						label: "State (2-letter)",
						hint: "State income tax is modeled for California only. Other selections currently omit state income tax.",
					})}
				</fieldset>
			</details>
			<details>
				<summary>
					<strong>Household and Social Security</strong>
				</summary>
				{(["primary", "spouse"] as const)
					.filter((person) => getPath(config, person) != null)
					.map((person) => (
						<fieldset key={person}>
							<legend>
								{String(
									getPath(config, `${person}.name`) ??
										(person === "primary" ? "You" : "Partner"),
								)}
							</legend>
							{field({
								path: `${person}.name`,
								label: `${person === "primary" ? "Your" : "Partner’s"} name`,
							})}
							{field({
								path: `${person}.birth_date`,
								label: "Birth date",
								kind: "date",
							})}
							{field({
								path: `${person}.retirement_date`,
								label: "Retirement date",
								kind: "date",
							})}
							{field({
								path: `${person}.longevity_age`,
								label: "Plan through age",
								kind: "number",
								min: 1,
								max: 120,
								step: 1,
								fallback: 90,
							})}
							{field({
								path: `social_security.${person}_benefit_at_67`,
								label: "Social Security at 67 ($/month)",
								kind: "number",
								min: 0,
								fallback: person === "primary" ? 3000 : 2500,
							})}
							{field({
								path: `social_security.${person}_claiming_age`,
								label: "Claim Social Security at age",
								kind: "number",
								min: 62,
								max: 70,
								step: 1,
								fallback: 67,
							})}
							<p class="muted small">
								Enter the monthly benefit quoted for age 67. The engine adjusts
								it for your claiming age.
							</p>
						</fieldset>
					))}
			</details>
			<Accounts store={store} />
			<Savings store={store} />
			<RuleControls store={store} />
			<CashFlows store={store} kind="income_streams" />
			<CashFlows store={store} kind="expenses" />
			<details>
				<summary>
					<strong>Economic assumptions</strong>
				</summary>
				<fieldset>
					{field({
						path: "economic.inflation",
						label: "General inflation (%)",
						kind: "percent",
						min: 0,
						fallback: 0.0254,
						optional: true,
					})}
					{field({
						path: "economic.medical_inflation",
						label: "Medical inflation (%)",
						kind: "percent",
						min: 0,
						fallback: 0.0336,
						optional: true,
					})}
					{field({
						path: "economic.equity_real_return",
						label: "Equity real total return (%)",
						kind: "percent",
						fallback: 0.06,
						optional: true,
					})}
					{field({
						path: "economic.bond_real_return",
						label: "Bond real total return (%)",
						kind: "percent",
						fallback: 0.025,
						optional: true,
					})}
				</fieldset>
			</details>
			<details>
				<summary>
					<strong>Simulation settings</strong>
				</summary>
				<fieldset>
					<label class="row">
						<span>Simulations</span>
						<select
							value={String(store.sims.value)}
							onChange={(event) =>
								store.setSims(Number(event.currentTarget.value))
							}
						>
							<option value="500">500 · fast</option>
							<option value="1000">1,000 · default</option>
							<option value="5000">5,000 · thorough</option>
						</select>
					</label>
					<p class="muted small">
						More simulations take longer. Start with 500 or 1,000 while
						exploring.
					</p>
				</fieldset>
			</details>
			<AdvancedJson store={store} config={config} />
		</aside>
	);
}

export function Field({ field, store }: { field: FieldDef; store: PlanStore }) {
	const actual = getPath(store.config.value, field.path);
	const value = actual ?? field.fallback;
	const scaled =
		field.kind === "percent" && typeof value === "number"
			? Number((value * 100).toFixed(10))
			: value;
	const raw = scaled == null ? "" : String(scaled);
	const id = configFieldId(field.path);
	const [error, setError] = useState("");
	const commitNumber = (element: HTMLInputElement) => {
		if (element.value.trim() === "") {
			if (field.optional) {
				store.removeConfigField(field.path);
				setError("");
			} else {
				setError("Enter a value.");
			}
			return;
		}
		if (!element.checkValidity()) {
			setError(element.validationMessage);
			return;
		}
		const number = Number(element.value);
		if (Number.isFinite(number)) {
			store.setConfigField(
				field.path,
				field.kind === "percent" ? number / 100 : number,
			);
			setError("");
		}
	};
	const commitInput = (element: HTMLInputElement) => {
		if (field.kind === "number" || field.kind === "percent") {
			commitNumber(element);
		} else if (element.value || field.kind !== "date") {
			store.setConfigField(field.path, element.value);
			setError("");
		} else if (field.optional) {
			store.removeConfigField(field.path);
			setError("");
		} else {
			setError("Enter a date.");
		}
	};
	return (
		<div class="editor-field">
			<label class="row" htmlFor={id}>
				<span>{field.label}</span>
				{field.kind === "select" ? (
					<select
						id={id}
						value={raw}
						onChange={(event) => {
							if (!event.currentTarget.value && field.optional)
								store.removeConfigField(field.path);
							else store.setConfigField(field.path, event.currentTarget.value);
						}}
					>
						{field.options?.map((option) =>
							typeof option === "string" ? (
								<option key={option} value={option}>
									{option.replaceAll("_", " ")}
								</option>
							) : (
								<option key={option.value} value={option.value}>
									{option.label}
								</option>
							),
						)}
						{raw &&
							!field.options?.some(
								(option) =>
									(typeof option === "string" ? option : option.value) === raw,
							) && <option value={raw}>{raw}</option>}
					</select>
				) : field.kind === "checkbox" ? (
					<input
						id={id}
						type="checkbox"
						checked={Boolean(value)}
						onChange={(event) =>
							store.setConfigField(field.path, event.currentTarget.checked)
						}
					/>
				) : (
					<input
						id={id}
						type={
							field.kind === "percent" || field.kind === "number"
								? "number"
								: field.kind === "date"
									? "date"
									: "text"
						}
						value={raw}
						placeholder={field.optional ? "Default / unknown" : undefined}
						step={field.step ?? "any"}
						min={field.min}
						max={field.max}
						aria-invalid={error ? "true" : undefined}
						aria-describedby={
							error ? `${id}-error` : field.hint ? `${id}-hint` : undefined
						}
						onChange={(event) => commitInput(event.currentTarget)}
						onBlur={(event) => commitInput(event.currentTarget)}
					/>
				)}
			</label>
			{field.hint && (
				<p id={`${id}-hint`} class="muted small">
					{field.hint}
				</p>
			)}
			{error && (
				<p class="error small" id={`${id}-error`} role="alert">
					{error}
				</p>
			)}
			{field.optional && actual != null && (
				<button
					type="button"
					class="small"
					aria-label={`Use default for ${field.label}`}
					onClick={() => {
						store.removeConfigField(field.path);
						setError("");
					}}
				>
					Use default
				</button>
			)}
		</div>
	);
}

function Accounts({ store }: { store: PlanStore }) {
	const config = store.config.value;
	const accounts = items(config, "accounts");
	const [error, setError] = useState("");
	return (
		<details>
			<summary id={configFieldId("accounts")} tabIndex={-1}>
				<strong>Accounts</strong>{" "}
				<span class="muted small">({accounts.length})</span>
			</summary>
			{getPath(config, "input_metadata.account_breakdown") === "missing" && (
				<div class="small">
					<p>
						Replace the total savings estimate with your actual accounts. Remove
						the estimate to avoid counting the same money twice, then confirm
						your breakdown.
					</p>
					<button
						type="button"
						onClick={() =>
							store.setConfigField(
								"input_metadata.account_breakdown",
								"provided",
							)
						}
					>
						Confirm account breakdown
					</button>
				</div>
			)}
			{accounts.map((account, index) => {
				const prefix = `accounts.${index}`;
				const type = String(account.type ?? "other");
				const tax = String(account.tax_treatment ?? accountTax(type));
				const cash = ["checking", "savings"].includes(type);
				const field = (
					definition: Omit<FieldDef, "path"> & { name: string },
				) => (
					<Field
						key={definition.name}
						store={store}
						field={{ ...definition, path: `${prefix}.${definition.name}` }}
					/>
				);
				return (
					<fieldset key={String(account.id)}>
						<legend>{String(account.name ?? `Account ${index + 1}`)}</legend>
						{field({ name: "name", label: "Account name" })}
						<label class="row" htmlFor={configFieldId(`${prefix}.type`)}>
							<span>Account type</span>
							<select
								id={configFieldId(`${prefix}.type`)}
								value={type}
								onChange={(event) => {
									const selected = event.currentTarget.value;
									let next = setPath(config, `${prefix}.type`, selected);
									next = setPath(
										next,
										`${prefix}.tax_treatment`,
										accountTax(selected),
									);
									if (
										account.owner === "joint" &&
										accountTax(selected) !== "taxable"
									)
										next = setPath(next, `${prefix}.owner`, "primary");
									if (["checking", "savings"].includes(selected))
										next = setPath(next, `${prefix}.asset_class`, "cash");
									else if (cash && account.asset_class === "cash")
										next = setPath(next, `${prefix}.asset_class`, null);
									store.replaceConfig(next);
								}}
							>
								{[...new Set([...ACCOUNT_TYPES, type])].map((value) => (
									<option value={value} key={value}>
										{value.replaceAll("_", " ")}
									</option>
								))}
							</select>
						</label>
						{field({
							name: "tax_treatment",
							label: "Tax treatment",
							kind: "select",
							options:
								accountTax(type) === "taxable"
									? TAX_OPTIONS
									: type === "401k"
										? TAX_OPTIONS.filter((option) =>
												["pre_tax", "roth"].includes(option.value),
											)
										: TAX_OPTIONS.filter(
												(option) => option.value === accountTax(type),
											),
							fallback: accountTax(type),
						})}
						{field({
							name: "owner",
							label: "Account owner",
							kind: "select",
							options: getPath(config, "spouse")
								? ["primary", "spouse"]
								: ["primary"],
							fallback: "primary",
						})}
						{field({
							name: "balance",
							label: "Balance ($)",
							kind: "number",
							min: 0,
						})}
						{tax === "taxable" &&
							!cash &&
							!["real_estate", "vehicle"].includes(type) &&
							field({
								name: "cost_basis",
								label: "Taxable cost basis ($)",
								kind: "number",
								min: 0,
								optional: true,
								hint: "If unknown, leave unset. The current engine uses opening balance as basis.",
							})}
						{tax === "roth" && (
							<>
								{type === "roth_ira" &&
									field({
										name: "roth_contribution_basis",
										label: "Roth regular contributions ($)",
										kind: "number",
										min: 0,
										fallback: 0,
										optional: true,
									})}
								{field({
									name: "roth_first_contribution_year",
									label: "First Roth contribution year",
									kind: "number",
									min: 1900,
									max:
										Number(getPath(config, "start_year")) ||
										new Date().getFullYear(),
									step: 1,
									optional: true,
								})}
							</>
						)}
						<details>
							<summary>Returns and distributions</summary>
							{tax === "taxable" &&
								field({
									name: "investment_income_profile",
									label: "Investment income profile",
									kind: "select",
									optional: true,
									fallback: "",
									options: [
										{ value: "", label: "Custom yields / no profile" },
										{ value: "none", label: "No distributions" },
										{
											value: "stock_index",
											label: "Stock index (illustrative)",
										},
										{ value: "balanced", label: "Balanced (illustrative)" },
										{ value: "income", label: "Income (illustrative)" },
										{ value: "cash", label: "Cash (illustrative)" },
									],
									hint: "Profiles estimate unspecified yields. Explicit yield fields override the profile.",
								})}
							{field({
								name: "growth_rate",
								label: "Real return override (%)",
								kind: "percent",
								optional: true,
								hint: "Unset uses portfolio assumptions. A zero override means no growth.",
							})}
							{field({
								name: "expense_ratio",
								label: "Annual fees (%)",
								kind: "percent",
								min: 0,
								max: 100,
								optional: true,
								fallback: 0,
							})}
							{tax === "taxable" && (
								<>
									{field({
										name: "interest_yield",
										label: "Interest yield (%)",
										kind: "percent",
										min: 0,
										max: 100,
										optional: true,
									})}
									{field({
										name: "dividend_yield",
										label: "Dividend yield (%)",
										kind: "percent",
										min: 0,
										max: 100,
										optional: true,
									})}
									{field({
										name: "capital_gain_yield",
										label: "Capital-gain distribution yield (%)",
										kind: "percent",
										min: 0,
										max: 100,
										optional: true,
									})}
									{field({
										name: "qualified_dividend_share",
										label: "Qualified share of dividends (%)",
										kind: "percent",
										min: 0,
										max: 100,
										optional: true,
									})}
								</>
							)}
						</details>
						<button
							type="button"
							onClick={() => {
								try {
									store.replaceConfig(
										removeAccount(config, String(account.id)),
									);
									setError("");
								} catch (caught) {
									setError(
										String(caught instanceof Error ? caught.message : caught),
									);
								}
							}}
						>
							Remove {String(account.name ?? "account")}
						</button>
					</fieldset>
				);
			})}
			{error && (
				<p class="error small" role="alert">
					{error}
				</p>
			)}
			<button
				type="button"
				onClick={() =>
					store.setConfigField("accounts", [
						...accounts,
						{
							id: nextItemId(accounts, "account"),
							name: "New account",
							type: "brokerage",
							tax_treatment: "taxable",
							owner: "primary",
							balance: 0,
						},
					])
				}
			>
				Add account
			</button>
		</details>
	);
}

function Savings({ store }: { store: PlanStore }) {
	const config = store.config.value;
	const accounts = items(config, "accounts");
	const order = effectiveSavingsOrder(config);
	const eligible = accounts.filter(
		(account) =>
			account.liquid !== false &&
			(account.tax_treatment ?? accountTax(String(account.type))) ===
				"taxable" &&
			!["hsa", "529", "real_estate", "vehicle"].includes(String(account.type)),
	);
	const addable = accounts.filter(
		(account) =>
			account.liquid !== false &&
			!["real_estate", "vehicle"].includes(String(account.type)) &&
			!order.includes(String(account.id)),
	);
	return (
		<details>
			<summary>
				<strong>Savings destinations</strong>
			</summary>
			<p class="muted small">
				Available savings fund the accounts below in order, up to their annual
				caps. A cap of zero means unlimited. Remaining cash then goes to your
				excess savings destination.
			</p>
			<ol>
				{order.map((id, index) => {
					const accountIndex = accounts.findIndex(
						(account) => account.id === id,
					);
					const account = accounts[accountIndex];
					if (!account) return null;
					return (
						<li key={id}>
							<strong>{String(account.name)}</strong>
							<Field
								store={store}
								field={{
									path: `accounts.${accountIndex}.annual_contribution_cap`,
									label: `${String(account.name)} annual savings cap ($)`,
									kind: "number",
									min: 0,
									fallback:
										Number(account.monthly_contribution) > 0
											? Number(account.monthly_contribution) * 12
											: 0,
								}}
							/>
							<button
								type="button"
								disabled={index === 0}
								aria-label={`Move ${String(account.name)} earlier`}
								onClick={() => {
									const next = [...order];
									[next[index - 1], next[index]] = [
										next[index]!,
										next[index - 1]!,
									];
									store.replaceConfig(setSavingsOrder(config, next));
								}}
							>
								Move earlier
							</button>{" "}
							<button
								type="button"
								aria-label={`Stop prioritizing ${String(account.name)}`}
								onClick={() =>
									store.replaceConfig(
										setSavingsOrder(
											config,
											order.filter((value) => value !== id),
										),
									)
								}
							>
								Remove from order
							</button>
						</li>
					);
				})}
			</ol>
			{addable.length > 0 && (
				<label class="row">
					<span>Add savings priority</span>
					<select
						value=""
						onChange={(event) => {
							if (event.currentTarget.value)
								store.replaceConfig(
									setSavingsOrder(config, [
										...order,
										event.currentTarget.value,
									]),
								);
						}}
					>
						<option value="">Choose an account…</option>
						{addable.map((account) => (
							<option key={String(account.id)} value={String(account.id)}>
								{String(account.name)}
							</option>
						))}
					</select>
				</label>
			)}
			<Field
				store={store}
				field={{
					path: "surplus_account_id",
					label: "Excess savings go to",
					kind: "select",
					optional: true,
					fallback: "",
					options: [
						{
							value: "",
							label: "Automatic: checking, taxable account, then cash",
						},
						...eligible.map((account) => ({
							value: String(account.id),
							label: String(account.name),
						})),
					],
				}}
			/>
			<p class="muted small">
				Only liquid taxable accounts can receive excess savings. Account
				contribution rules may limit prioritized savings.
			</p>
		</details>
	);
}

function CashFlows({
	store,
	kind,
}: { store: PlanStore; kind: "income_streams" | "expenses" }) {
	const config = store.config.value;
	const list = items(config, kind);
	const income = kind === "income_streams";
	return (
		<details>
			<summary>
				<strong>{income ? "Income" : "Spending"}</strong>{" "}
				<span class="muted small">({list.length})</span>
			</summary>
			{list.map((item, index) => (
				<CashFlowItem
					key={String(item.id)}
					store={store}
					item={item}
					index={index}
					kind={kind}
				/>
			))}
			<button
				type="button"
				onClick={() => {
					const startYear =
						Number(getPath(config, "start_year")) ||
						new Date().getFullYear() + 1;
					const endYear = String(
						getPath(config, "primary.birth_date") ?? `${startYear - 40}-01-01`,
					).slice(0, 4);
					const end = Math.max(
						startYear,
						Number(endYear) +
							Number(getPath(config, "primary.longevity_age") ?? 90),
					);
					const next: ConfigObject = {
						id: nextItemId(list, income ? "income" : "expense"),
						name: income ? "New income" : "New spending",
						monthly_amount: 0,
						start_date: `${startYear}-01-01`,
						end_date: `${end}-12-31`,
						growth_rate: 0,
						...(income
							? { owner: "primary", is_w2: true }
							: { category: "general", is_must_spend: true }),
					};
					store.setConfigField(kind, [...list, next]);
				}}
			>
				Add {income ? "income" : "spending"}
			</button>
		</details>
	);
}

function CashFlowItem({
	store,
	item,
	index,
	kind,
}: {
	store: PlanStore;
	item: ConfigObject;
	index: number;
	kind: "income_streams" | "expenses";
}) {
	const [period, setPeriod] = useState("monthly");
	const [error, setError] = useState("");
	const prefix = `${kind}.${index}`;
	const income = kind === "income_streams";
	const complexIncome =
		income &&
		(item.base_salary != null || item.bonus != null || item.equity != null);
	const oneTime = !income && item.is_one_time === true;
	const amountPath = oneTime
		? `${prefix}.one_time_amount`
		: `${prefix}.monthly_amount`;
	const value =
		Number(getPath(store.config.value, amountPath) ?? 0) *
		(!oneTime && period === "annual" ? 12 : 1);
	const commitAmount = (element: HTMLInputElement) => {
		if (element.value.trim() && element.checkValidity()) {
			store.setConfigField(
				amountPath,
				Number(element.value) / (!oneTime && period === "annual" ? 12 : 1),
			);
			setError("");
		} else setError(element.validationMessage || "Enter an amount.");
	};
	const field = (definition: Omit<FieldDef, "path"> & { name: string }) => (
		<Field
			key={definition.name}
			store={store}
			field={{ ...definition, path: `${prefix}.${definition.name}` }}
		/>
	);
	return (
		<fieldset>
			<legend>{String(item.name)}</legend>
			{field({ name: "name", label: income ? "Income name" : "Spending name" })}
			{complexIncome ? (
				<p class="muted small">
					This income uses detailed salary, bonus or equity compensation. Edit
					its amounts in Advanced JSON to preserve that structure.
				</p>
			) : (
				<>
					{!oneTime && (
						<label class="row">
							<span>Amount frequency</span>
							<select
								value={period}
								onChange={(event) => setPeriod(event.currentTarget.value)}
							>
								<option value="monthly">Monthly</option>
								<option value="annual">Annual</option>
							</select>
						</label>
					)}
					<label class="row" htmlFor={configFieldId(amountPath)}>
						<span>
							{oneTime
								? "One-time amount ($)"
								: `${period === "annual" ? "Annual" : "Monthly"} amount ($)`}
						</span>
						<input
							id={configFieldId(amountPath)}
							type="number"
							min="0"
							step="any"
							value={Number(value.toFixed(8))}
							onChange={(event) => commitAmount(event.currentTarget)}
							onBlur={(event) => commitAmount(event.currentTarget)}
						/>
					</label>
				</>
			)}
			{oneTime ? (
				field({ name: "one_time_date", label: "Payment date", kind: "date" })
			) : (
				<>
					{field({ name: "start_date", label: "Start date", kind: "date" })}
					{field({
						name: "end_date",
						label: "End date",
						kind: "date",
						hint: "A January 1 end date stops payments in the previous year. Other dates prorate that year.",
					})}
				</>
			)}
			{income ? (
				<>
					{field({
						name: "owner",
						label: "Income owner",
						kind: "select",
						options: getPath(store.config.value, "spouse")
							? ["primary", "spouse"]
							: ["primary"],
						fallback: "primary",
					})}
					{field({
						name: "is_w2",
						label: "W-2 wages",
						kind: "checkbox",
						fallback: true,
					})}
					<p class="muted small">
						Use the Social Security fields above for government retirement
						benefits. Non-W-2 income is modeled without payroll tax.
					</p>
					{field({
						name: "growth_rate",
						label: "Annual income growth (%)",
						kind: "percent",
						fallback: 0,
						optional: true,
					})}
				</>
			) : (
				<>
					{field({
						name: "category",
						label: "Category",
						kind: "select",
						options: [
							"general",
							"housing",
							{ value: "medical", label: "Medical / healthcare" },
							"education",
							"charity",
							"travel",
						],
						fallback: "general",
					})}
					{field({
						name: "is_must_spend",
						label: "Essential spending",
						kind: "checkbox",
						fallback: true,
					})}
					{field({
						name: "real_growth_rate",
						label: "Annual growth above inflation (%)",
						kind: "percent",
						fallback: Number(item.growth_rate ?? 0),
						optional: true,
					})}
				</>
			)}
			{error && (
				<p class="error small" role="alert">
					{error}
				</p>
			)}
			<button
				type="button"
				onClick={() => {
					try {
						store.replaceConfig(
							removeListItem(store.config.value, kind, index),
						);
						setError("");
					} catch (caught) {
						setError(caught instanceof Error ? caught.message : String(caught));
					}
				}}
			>
				Remove {String(item.name)}
			</button>
		</fieldset>
	);
}

function AdvancedJson({
	store,
	config,
}: { store: PlanStore; config: unknown }) {
	const [text, setText] = useState(() => JSON.stringify(config, null, 2));
	const [error, setError] = useState<string | null>(null);
	useEffect(() => {
		setText(JSON.stringify(config, null, 2));
	}, [config]);
	return (
		<details>
			<summary>
				<strong>Advanced JSON</strong>
			</summary>
			<label htmlFor="advanced-plan-json" class="small">
				Complete plan configuration
			</label>
			<textarea
				id="advanced-plan-json"
				class="advanced-json"
				value={text}
				onInput={(event) => setText(event.currentTarget.value)}
				rows={12}
				spellcheck={false}
			/>
			{error && (
				<p class="error small" role="alert">
					{error}
				</p>
			)}
			<button
				type="button"
				onClick={() => {
					try {
						store.replaceConfig(validateConfig(JSON.parse(text)));
						setError(null);
					} catch (caught) {
						setError(caught instanceof Error ? caught.message : String(caught));
					}
				}}
			>
				Apply JSON
			</button>
		</details>
	);
}
