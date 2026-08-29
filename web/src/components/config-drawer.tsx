import { useState } from "preact/hooks";
import { getPath } from "../lib/config-edit";
import type { PlanStore } from "../state/plan-store";

interface ConfigDrawerProps {
  store: PlanStore;
}

interface FieldDef {
  path: string;
  label: string;
  kind: "number" | "date" | "text" | "select";
  options?: readonly string[];
  step?: number;
  hint?: string;
}

/**
 * Curated field set. We expose the 80%-case fields directly and route
 * the rest through the "Advanced JSON" textarea. Adding a field here
 * is the only change needed to make it editable in the UI.
 */
const FIELDS: ReadonlyArray<FieldDef> = [
  { path: "name", label: "Plan name", kind: "text" },
  { path: "state", label: "State (2-letter)", kind: "text" },
  { path: "withdrawal_rate", label: "Withdrawal rate", kind: "number", step: 0.005, hint: "0.04 = 4%" },

  { path: "primary.birth_date", label: "Primary birth date", kind: "date" },
  { path: "primary.retirement_date", label: "Primary retirement date", kind: "date" },
  { path: "primary.longevity_age", label: "Primary longevity age", kind: "number", step: 1 },

  { path: "spouse.birth_date", label: "Spouse birth date", kind: "date" },
  { path: "spouse.retirement_date", label: "Spouse retirement date", kind: "date" },
  { path: "spouse.longevity_age", label: "Spouse longevity age", kind: "number", step: 1 },

  { path: "economic.inflation", label: "Inflation", kind: "number", step: 0.001, hint: "0.025 = 2.5%" },
  { path: "economic.medical_inflation", label: "Medical inflation", kind: "number", step: 0.001 },
  { path: "economic.investment_return_mean", label: "Mean real return", kind: "number", step: 0.005 },
  { path: "economic.investment_return_volatility", label: "Return volatility", kind: "number", step: 0.005 },
];

/**
 * Editable list items: accounts[].balance/growth_rate/monthly_contribution
 * and expenses[].monthly_amount, income_streams[].monthly_amount. These
 * are surfaced in a collapsible section so the drawer stays manageable.
 */
export function ConfigDrawer({ store }: ConfigDrawerProps) {
  const config = store.config.value;
  const sims = store.sims.value;

  return (
    <aside class="drawer" aria-label="Edit plan">
      <header>
        <h3>Plan</h3>
        <p class="muted small">Edits re-run the engine after 400 ms.</p>
      </header>

      <fieldset>
        <legend>Top level</legend>
        {FIELDS.filter((f) => !f.path.includes(".")).map((f) => (
          <Field key={f.path} field={f} value={getPath(config, f.path)} onChange={(v) => store.setConfigField(f.path, v)} />
        ))}
      </fieldset>

      <fieldset>
        <legend>Primary</legend>
        {FIELDS.filter((f) => f.path.startsWith("primary.")).map((f) => (
          <Field key={f.path} field={f} value={getPath(config, f.path)} onChange={(v) => store.setConfigField(f.path, v)} />
        ))}
      </fieldset>

      <fieldset>
        <legend>Spouse</legend>
        {FIELDS.filter((f) => f.path.startsWith("spouse.")).map((f) => (
          <Field key={f.path} field={f} value={getPath(config, f.path)} onChange={(v) => store.setConfigField(f.path, v)} />
        ))}
      </fieldset>

      <fieldset>
        <legend>Economics</legend>
        {FIELDS.filter((f) => f.path.startsWith("economic.")).map((f) => (
          <Field key={f.path} field={f} value={getPath(config, f.path)} onChange={(v) => store.setConfigField(f.path, v)} />
        ))}
      </fieldset>

      <ListField
        title="Accounts"
        itemPathPrefix="accounts"
        fieldLabelFor={(i, field) => `Account #${i + 1} ${field}`}
        fields={[
          { name: "balance", kind: "number", step: 1000 },
          { name: "growth_rate", kind: "number", step: 0.005 },
          { name: "monthly_contribution", kind: "number", step: 50 },
        ]}
        store={store}
        config={config}
      />

      <ListField
        title="Expenses"
        itemPathPrefix="expenses"
        fieldLabelFor={(i, field) => `Expense #${i + 1} ${field}`}
        fields={[{ name: "monthly_amount", kind: "number", step: 50 }]}
        store={store}
        config={config}
      />

      <ListField
        title="Income streams"
        itemPathPrefix="income_streams"
        fieldLabelFor={(i, field) => `Income #${i + 1} ${field}`}
        fields={[{ name: "monthly_amount", kind: "number", step: 50 }]}
        store={store}
        config={config}
      />

      <fieldset>
        <legend>Monte Carlo</legend>
        <label class="row">
          <span>Simulations</span>
          <select
            value={String(sims)}
            onChange={(e) => store.setSims(Number((e.currentTarget as HTMLSelectElement).value))}
          >
            <option value="500">500 · fast</option>
            <option value="1000">1,000 · default</option>
            <option value="5000">5,000 · thorough</option>
          </select>
        </label>
        <p class="muted small">
          5k sims takes ~100 s in browser. Use 1k for the explore loop.
        </p>
      </fieldset>

      <AdvancedJson store={store} config={config} />
    </aside>
  );
}

function Field({
  field,
  value,
  onChange,
}: {
  field: FieldDef;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const raw = value === undefined || value === null ? "" : String(value);
  if (field.kind === "number") {
    return (
      <label class="row">
        <span>{field.label}</span>
        <input
          type="number"
          step={field.step}
          value={raw}
          onInput={(e) => {
            const v = (e.currentTarget as HTMLInputElement).value;
            onChange(v === "" ? null : Number(v));
          }}
        />
        {field.hint && <small class="muted">{field.hint}</small>}
      </label>
    );
  }
  if (field.kind === "date") {
    return (
      <label class="row">
        <span>{field.label}</span>
        <input
          type="date"
          value={raw}
          onChange={(e) => onChange((e.currentTarget as HTMLInputElement).value)}
        />
      </label>
    );
  }
  return (
    <label class="row">
      <span>{field.label}</span>
      <input
        type="text"
        value={raw}
        onChange={(e) => onChange((e.currentTarget as HTMLInputElement).value)}
      />
    </label>
  );
}

interface SubField {
  name: string;
  kind: "number" | "text" | "date";
  step?: number;
}

function ListField({
  title,
  itemPathPrefix,
  fieldLabelFor,
  fields,
  store,
  config,
}: {
  title: string;
  itemPathPrefix: string;
  fieldLabelFor: (i: number, field: string) => string;
  fields: SubField[];
  store: PlanStore;
  config: unknown;
}) {
  const list = (getPath(config, itemPathPrefix) as unknown[] | undefined) ?? [];
  const [open, setOpen] = useState(false);
  return (
    <details open={open} onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary>
        <strong>{title}</strong>{" "}
        <span class="muted small">({list.length})</span>
      </summary>
      <div class="list-field">
        {list.length === 0 && <p class="muted small">none</p>}
        {list.map((_item, i) => (
          <div class="list-field__item" key={`${itemPathPrefix}-${i}`}>
            {fields.map((f) => (
              <Field
                key={`${itemPathPrefix}-${i}-${f.name}`}
                field={{
                  path: `${itemPathPrefix}.${i}.${f.name}`,
                  label: fieldLabelFor(i, f.name),
                  kind: f.kind,
                  step: f.step,
                }}
                value={getPath(config, `${itemPathPrefix}.${i}.${f.name}`)}
                onChange={(v) => store.setConfigField(`${itemPathPrefix}.${i}.${f.name}`, v)}
              />
            ))}
          </div>
        ))}
      </div>
    </details>
  );
}

function AdvancedJson({ store, config }: { store: PlanStore; config: unknown }) {
  const [text, setText] = useState(() => JSON.stringify(config, null, 2));
  const [err, setErr] = useState<string | null>(null);

  // Keep the textarea in sync if config changes from elsewhere (e.g. on
  // initial load or after a successful non-text edit).
  // We deliberately do NOT write every keystroke back into config — that
  // would re-run the engine on every character. The user must click
  // "Apply" to commit.
  return (
    <details>
      <summary>
        <strong>Advanced JSON</strong>
      </summary>
      <textarea
        class="advanced-json"
        value={text}
        onInput={(e) => setText((e.currentTarget as HTMLTextAreaElement).value)}
        rows={12}
        spellcheck={false}
      />
      {err && <p class="error small">{err}</p>}
      <button
        type="button"
        onClick={() => {
          try {
            const parsed = JSON.parse(text);
            store.config.value = parsed;
            setErr(null);
          } catch (e) {
            setErr(String(e));
          }
        }}
      >
        Apply
      </button>
    </details>
  );
}
