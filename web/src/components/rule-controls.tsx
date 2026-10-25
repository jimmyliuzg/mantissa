import { useEffect, useState } from "preact/hooks";
import { getPath, setPath } from "../lib/config-edit";
import { configFieldId, type ConfigObject } from "../lib/guided-editor";
import type { PlanStore } from "../state/plan-store";

const OWNER_LABELS = { primary: "You", spouse: "Partner" } as const;
type Owner = keyof typeof OWNER_LABELS;

function cloneConfig(config: unknown): ConfigObject {
  return JSON.parse(JSON.stringify(config ?? {})) as ConfigObject;
}

function writeField(store: PlanStore, path: string, value: unknown, remove = false) {
  let config = cloneConfig(store.config.value);
  if (path.startsWith("policy.")) {
    const existing = getPath(config, "policy");
    if (!existing || typeof existing !== "object") {
      config = setPath(config, "policy", { schema_version: 1, changes: [] }) as ConfigObject;
    } else if (getPath(config, "policy.schema_version") == null) {
      config = setPath(config, "policy.schema_version", 1) as ConfigObject;
      if (!Array.isArray(getPath(config, "policy.changes")))
        config = setPath(config, "policy.changes", []) as ConfigObject;
    }
  } else if (path.startsWith("contribution_policy.")) {
    const existing = getPath(config, "contribution_policy");
    if (!existing || typeof existing !== "object") {
      config = setPath(config, "contribution_policy", { owners: {} }) as ConfigObject;
    }
    if (getPath(config, "contribution_policy.owners") == null)
      config = setPath(config, "contribution_policy.owners", {}) as ConfigObject;
  }
  config = setPath(config, path, remove ? undefined : value) as ConfigObject;
  if (remove) config = JSON.parse(JSON.stringify(config)) as ConfigObject;
  store.replaceConfig(config);
}

function openingYear(config: unknown): number {
  const start = getPath(config, "start_year");
  if (typeof start === "number" && Number.isInteger(start)) return start;
  return new Date().getFullYear();
}

export function RuleControls({ store }: { store: PlanStore }) {
  const config = store.config.value;
  const spousePresent = getPath(config, "spouse") != null;
  const owners: Owner[] = spousePresent ? ["primary", "spouse"] : ["primary"];
  return (
    <>
      <ContributionEligibility store={store} owners={owners} />
      <FutureRules store={store} openingYear={openingYear(config)} />
    </>
  );
}

function ContributionEligibility({
  store,
  owners,
}: {
  store: PlanStore;
  owners: Owner[];
}) {
  return (
    <details>
      <summary>
        <strong>Contribution eligibility</strong>
      </summary>
      <p class="muted small">
        Declare what you know. Unknown eligibility stays unset, so the model will block IRA or HSA
        funding when it cannot establish a limit.
      </p>
      {owners.map((owner) => (
        <fieldset key={owner}>
          <legend>{OWNER_LABELS[owner]}</legend>
          <SelectControl
            store={store}
            path={`contribution_policy.owners.${owner}.workplace_plan`}
            label="Covered by a workplace plan"
            valueMap={{ yes: true, no: false }}
            options={[
              { value: "unknown", label: "Unknown" },
              { value: "yes", label: "Yes" },
              { value: "no", label: "No" },
            ]}
          />
          <SelectControl
            store={store}
            path={`contribution_policy.owners.${owner}.ira_deduction`}
            label="Traditional IRA treatment"
            defaultValue="unknown"
            options={[
              { value: "unknown", label: "Unknown" },
              { value: "deductible", label: "Deductible" },
              { value: "nondeductible", label: "Nondeductible (unsupported)" },
            ]}
          />
          <label
            class="row"
            htmlFor={configFieldId(`contribution_policy.owners.${owner}.spousal_ira_eligible`)}
          >
            <span>Eligible for spousal IRA contributions</span>
            <input
              id={configFieldId(`contribution_policy.owners.${owner}.spousal_ira_eligible`)}
              type="checkbox"
              checked={
                getPath(
                  store.config.value,
                  `contribution_policy.owners.${owner}.spousal_ira_eligible`,
                ) === true
              }
              onChange={(event) =>
                writeField(
                  store,
                  `contribution_policy.owners.${owner}.spousal_ira_eligible`,
                  true,
                  !event.currentTarget.checked,
                )
              }
            />
          </label>
          <label
            class="row"
            htmlFor={configFieldId(`contribution_policy.owners.${owner}.hsa_eligible`)}
          >
            <span>Declare HSA eligibility</span>
            <input
              id={configFieldId(`contribution_policy.owners.${owner}.hsa_eligible`)}
              type="checkbox"
              checked={
                getPath(store.config.value, `contribution_policy.owners.${owner}.hsa_eligible`) ===
                true
              }
              onChange={(event) =>
                writeField(
                  store,
                  `contribution_policy.owners.${owner}.hsa_eligible`,
                  true,
                  !event.currentTarget.checked,
                )
              }
            />
          </label>
          <SelectControl
            store={store}
            path={`contribution_policy.owners.${owner}.hsa_coverage`}
            label="HSA coverage"
            defaultValue="none"
            options={[
              { value: "none", label: "None" },
              { value: "individual", label: "Individual" },
              { value: "family", label: "Family" },
            ]}
          />
          <NumberControl
            store={store}
            path={`contribution_policy.owners.${owner}.hsa_eligible_months`}
            label="Eligible HSA months (optional)"
            min={0}
            max={12}
            step={1}
            optional
            hint="Leave blank if you do not know the eligible months. This is required to model HSA contributions from age 65 onward."
          />
          <NumberControl
            store={store}
            path={`contribution_policy.owners.${owner}.hsa_employer_contribution_by_year.${openingYear(store.config.value)}`}
            label={`Employer HSA contribution in ${openingYear(store.config.value)} ($)`}
            min={0}
            step={100}
            optional
            hint="Employer deposits count toward the HSA limit and are not taken from your savings."
          />
        </fieldset>
      ))}
    </details>
  );
}

function FutureRules({ store, openingYear: year }: { store: PlanStore; openingYear: number }) {
  const changes =
    (getPath(store.config.value, "policy.changes") as ConfigObject[] | undefined) ?? [];
  const policy = getPath(store.config.value, "policy") as ConfigObject | undefined;
  return (
    <details>
      <summary>
        <strong>Future rule forecasts</strong>
      </summary>
      <p class="muted small">
        These are your forecasts, not published rules. A forecast applies through its end year,
        inclusive. Leave a value blank to use the model default.
      </p>
      <NumberControl
        store={store}
        path="policy.contribution_growth_rate"
        label="Contribution limit growth (%)"
        value={policy?.contribution_growth_rate}
        min={-50}
        max={100}
        step={0.1}
        scale={100}
        optional
        hint="Used to project indexed annual contribution limits."
      />
      <NumberControl
        store={store}
        path="policy.tax_threshold_growth_rate"
        label="Tax threshold growth (%)"
        value={policy?.tax_threshold_growth_rate}
        min={-50}
        max={100}
        step={0.1}
        scale={100}
        optional
        hint="Used to project indexed tax thresholds."
      />
      {changes.map((change, index) => (
        <ForecastEditor
          key={String(change.id ?? index)}
          store={store}
          index={index}
          change={change}
        />
      ))}
      <button
        type="button"
        onClick={() => {
          const current = changes;
          let n = 1;
          const ids = new Set(current.map((item) => item.id));
          while (ids.has(`forecast-${n}`)) n++;
          const next = [
            ...current,
            {
              id: `forecast-${n}`,
              start_year: year,
              tax: {},
              contributions: {},
            },
          ];
          writeField(store, "policy.changes", next);
        }}
      >
        Add temporary forecast
      </button>
    </details>
  );
}

function ForecastEditor({
  store,
  index,
  change,
}: {
  store: PlanStore;
  index: number;
  change: ConfigObject;
}) {
  const base = `policy.changes.${index}`;
  const label = typeof change.id === "string" ? change.id : `Forecast ${index + 1}`;
  return (
    <details class="rule-forecast">
      <summary>{label}</summary>
      <fieldset>
        <legend>Temporary rule forecast</legend>
        <NumberControl
          store={store}
          path={`${base}.start_year`}
          label="Start year"
          value={change.start_year}
          min={1900}
          max={3000}
          step={1}
        />
        <NumberControl
          store={store}
          path={`${base}.end_year`}
          label="End year (inclusive, optional)"
          value={change.end_year}
          min={1900}
          max={3000}
          step={1}
          optional
        />
        <NumberControl
          store={store}
          path={`${base}.tax.federal_rate_addition`}
          label="Federal rate addition (percentage points)"
          value={getPath(change, "tax.federal_rate_addition")}
          min={-100}
          max={100}
          step={0.1}
          scale={100}
          optional
          hint="Added to each federal bracket rate while this forecast applies."
        />
        <NumberControl
          store={store}
          path={`${base}.contributions.hsa_individual`}
          label="Individual HSA limit ($, optional)"
          value={getPath(change, "contributions.hsa_individual")}
          min={0}
          max={10_000_000}
          step={50}
          optional
        />
        <NumberControl
          store={store}
          path={`${base}.contributions.hsa_family`}
          label="Family HSA limit ($, optional)"
          value={getPath(change, "contributions.hsa_family")}
          min={0}
          max={10_000_000}
          step={50}
          optional
        />
        <button
          type="button"
          onClick={() => {
            const changes = (getPath(store.config.value, "policy.changes") as ConfigObject[]) ?? [];
            writeField(
              store,
              "policy.changes",
              changes.filter((_, row) => row !== index),
            );
          }}
        >
          Remove forecast
        </button>
      </fieldset>
    </details>
  );
}

function SelectControl({
  store,
  path,
  label,
  options,
  valueMap,
  defaultValue = "unknown",
}: {
  store: PlanStore;
  path: string;
  label: string;
  options: { value: string; label: string }[];
  valueMap?: Record<string, unknown>;
  defaultValue?: string;
}) {
  const actual = getPath(store.config.value, path);
  const value = valueMap
    ? (Object.entries(valueMap).find(([, mapped]) => mapped === actual)?.[0] ?? "unknown")
    : typeof actual === "string"
      ? actual
      : defaultValue;
  const id = configFieldId(path);
  return (
    <label class="row" htmlFor={id}>
      <span>{label}</span>
      <select
        id={id}
        value={value}
        onChange={(event) => {
          const selected = event.currentTarget.value;
          if (selected === "unknown") writeField(store, path, undefined, true);
          else writeField(store, path, valueMap?.[selected] ?? selected);
        }}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function NumberControl({
  store,
  path,
  label,
  value: suppliedValue,
  min,
  max,
  step,
  scale = 1,
  optional = false,
  hint,
}: {
  store: PlanStore;
  path: string;
  label: string;
  value?: unknown;
  min?: number;
  max?: number;
  step?: number;
  scale?: number;
  optional?: boolean;
  hint?: string;
}) {
  const actual = suppliedValue === undefined ? getPath(store.config.value, path) : suppliedValue;
  const display = typeof actual === "number" ? String(Number((actual * scale).toFixed(10))) : "";
  const [draft, setDraft] = useState(display);
  const [error, setError] = useState("");
  useEffect(() => setDraft(display), [display]);
  const id = configFieldId(path);
  const errorId = `${id}-error`;
  const commit = (raw: string, blur: boolean) => {
    if (!raw.trim()) {
      if (optional && blur) {
        if (getPath(store.config.value, path) !== undefined)
          writeField(store, path, undefined, true);
        setError("");
      } else if (!optional) setError("Enter a value.");
      return;
    }
    const number = Number(raw);
    if (
      !Number.isFinite(number) ||
      (min != null && number < min) ||
      (max != null && number > max)
    ) {
      setError(
        `Enter a number${min != null ? ` at least ${min}` : ""}${max != null ? ` and at most ${max}` : ""}.`,
      );
      return;
    }
    if (step === 1 && !Number.isInteger(number)) {
      setError("Enter a whole number.");
      return;
    }
    writeField(store, path, number / scale);
    setError("");
  };
  return (
    <div class="editor-field">
      <label class="row" htmlFor={id}>
        <span>{label}</span>
        <input
          id={id}
          type="number"
          value={draft}
          placeholder={optional ? "Optional" : undefined}
          min={min}
          max={max}
          step={step ?? "any"}
          aria-invalid={error ? "true" : undefined}
          aria-describedby={error ? errorId : undefined}
          onInput={(event) => setDraft(event.currentTarget.value)}
          onChange={(event) => {
            setDraft(event.currentTarget.value);
            commit(event.currentTarget.value, false);
          }}
          onBlur={(event) => commit(event.currentTarget.value, true)}
        />
      </label>
      {hint && <p class="muted small">{hint}</p>}
      {error && (
        <p id={errorId} class="error small" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
