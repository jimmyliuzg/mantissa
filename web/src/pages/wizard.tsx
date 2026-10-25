import { useState } from "preact/hooks";
import { fmtMoney } from "../lib/format";
import { buildSlimConfig, DEFAULT_ANSWERS, savingsTotal, type WizardAnswers } from "../slim/types";

const STEPS: ReadonlyArray<{
  key: keyof WizardAnswers | "review";
  title: string;
  blurb?: string;
}> = [
  { key: "primaryAge", title: "Your current age and when you want to retire" },
  { key: "hasSpouse", title: "Do you have a spouse or partner to plan for?" },
  { key: "investableAssets", title: "How much have you saved toward retirement?" },
  { key: "annualIncome", title: "Your current annual income (before tax)" },
  { key: "annualSpending", title: "How much do you expect to spend in retirement each year?" },
  { key: "state", title: "What state do you live in?" },
  { key: "hasSocialSecurity", title: "Estimated Social Security benefit" },
  { key: "risk", title: "How much investment risk are you comfortable with?" },
  { key: "review", title: "Review and download" },
];

/**
 * Nine-step wizard. The user answers 8 questions, sees a review step,
 * then either downloads the JSON or hands it to the viewer.
 */
export function Wizard() {
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<WizardAnswers>(DEFAULT_ANSWERS);

  function update<K extends keyof WizardAnswers>(key: K, value: WizardAnswers[K]) {
    setAnswers((a) => ({ ...a, [key]: value }));
  }

  function validStep() {
    const inputs = document.querySelectorAll<HTMLInputElement>(".wizard-step input");
    for (const input of inputs) {
      if (!input.checkValidity()) { input.reportValidity(); return false; }
    }
    return true;
  }

  function next() {
    if (!validStep()) return;
    setStep((s) => Math.min(STEPS.length - 1, s + 1));
  }
  function prev() {
    setStep((s) => Math.max(0, s - 1));
  }

  function openInViewer() {
    const cfg = buildSlimConfig(answers);
    sessionStorage.setItem("mantissa:config", JSON.stringify(cfg));
    window.location.hash = "#/review";
  }

  function download() {
    const cfg = buildSlimConfig(answers);
    const blob = new Blob([JSON.stringify(cfg, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "plan.json";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section class="wizard">
      <header class="wizard-header">
        <h1>Start from scratch</h1>
        <Progress current={step} total={STEPS.length} />
      </header>

      <div class="wizard-step">
        {STEPS[step]?.key === "review" ? (
          <Review answers={answers} />
        ) : (
          <Step
            stepKey={STEPS[step]?.key as keyof WizardAnswers}
            answers={answers}
            onChange={update}
          />
        )}
      </div>

      <footer class="wizard-footer">
        <button type="button" class="btn" onClick={prev} disabled={step === 0}>
          ← Back
        </button>
        {step < STEPS.length - 1 ? (
          <button type="button" class="btn btn--primary" onClick={next}>
            Next →
          </button>
        ) : (
          <div class="wizard-footer__final">
            <button type="button" class="btn" onClick={download}>
              Download plan.json
            </button>
            <button type="button" class="btn btn--primary" onClick={openInViewer}>
              Open in viewer →
            </button>
          </div>
        )}
      </footer>
    </section>
  );
}

function Progress({ current, total }: { current: number; total: number }) {
  return (
    <div class="progress" aria-label={`Step ${current + 1} of ${total}`}>
      {Array.from({ length: total }).map((_, i) => (
        <span key={i} class={`progress-dot ${i <= current ? "done" : ""}`} />
      ))}
    </div>
  );
}

interface StepProps {
  stepKey: keyof WizardAnswers;
  answers: WizardAnswers;
  onChange: <K extends keyof WizardAnswers>(key: K, value: WizardAnswers[K]) => void;
}

function Step({ stepKey, answers, onChange }: StepProps) {
  switch (stepKey) {
    case "primaryAge":
      return (
        <StepGroup title="Your age and retirement timing">
          <NumberField
            label="Current age"
            value={answers.primaryAge}
            onChange={(v) => {
              onChange("primaryAge", v);
              if (answers.primaryRetirementAge < v + 1) {
                onChange("primaryRetirementAge", v + 30);
              }
            }}
            min={18}
            max={90}
          />
          <NumberField
            label="Age you want to retire"
            value={answers.primaryRetirementAge}
            onChange={(v) => onChange("primaryRetirementAge", v)}
            min={answers.primaryAge + 1}
            max={Math.max(80, answers.primaryAge + 1)}
          />
          <NumberField
            label="Plan through age (longevity)"
            value={answers.primaryLongevity}
            onChange={(v) => onChange("primaryLongevity", v)}
            min={Math.max(answers.primaryRetirementAge + 1, 70)}
            max={110}
            hint="How long to model the plan. 92 is a common default."
          />
        </StepGroup>
      );
    case "hasSpouse":
      return (
        <StepGroup title="Spouse or partner?">
          <ChoiceField
            value={answers.hasSpouse}
            options={[
              { value: false, label: "Just me" },
              { value: true, label: "Yes, with a spouse or partner" },
            ]}
            onChange={(v) => onChange("hasSpouse", v)}
          />
          {answers.hasSpouse && (
            <>
              <NumberField
                label="Spouse's current age"
                value={answers.spouseAge ?? answers.primaryAge}
                onChange={(v) => onChange("spouseAge", v)}
                min={18}
                max={90}
              />
              <NumberField
                label="Spouse's retirement age"
                value={answers.spouseRetirementAge ?? answers.primaryRetirementAge}
                onChange={(v) => onChange("spouseRetirementAge", v)}
                min={(answers.spouseAge ?? answers.primaryAge) + 1}
                max={Math.max(80, (answers.spouseAge ?? answers.primaryAge) + 1)}
              />
              <NumberField
                label="Spouse's longevity"
                value={answers.spouseLongevity ?? answers.primaryLongevity}
                onChange={(v) => onChange("spouseLongevity", v)}
                min={70}
                max={110}
              />
            </>
          )}
        </StepGroup>
      );
    case "investableAssets":
      return (
        <StepGroup title="How much have you saved?">
          <p class="muted small">
            Total across all retirement and brokerage accounts. Don't include your home.
          </p>
          <ChoiceField value={answers.accountBreakdown} options={[
            { value: false, label: "Use a total for now" },
            { value: true, label: "Break down my accounts (optional)" },
          ]} onChange={(v) => onChange("accountBreakdown", v)} />
          {!answers.accountBreakdown && <MoneyField
            label="Investable assets"
            value={answers.investableAssets}
            onChange={(v) => onChange("investableAssets", v)}
            step={10_000}
          />}
          {answers.accountBreakdown && <>
            <MoneyField label="Cash and savings" value={answers.cashAssets} onChange={(v) => onChange("cashAssets", v)} />
            <MoneyField label="Taxable brokerage" value={answers.brokerageAssets} onChange={(v) => onChange("brokerageAssets", v)} />
            <MoneyField label="Traditional IRA / 401(k)" value={answers.traditionalAssets} onChange={(v) => onChange("traditionalAssets", v)} />
            <MoneyField label="Roth IRA" value={answers.rothAssets} onChange={(v) => onChange("rothAssets", v)} />
            <p>Total: {fmtMoney(savingsTotal(answers))}. New savings go to cash or brokerage. Account ownership defaults to the primary person; workplace Roth and individual owners can be refined in the editor.</p>
          </>}
          <label class="row"><span>Statement date (optional)</span><input type="date" value={answers.balanceDate} onInput={(e) => onChange("balanceDate", e.currentTarget.value)} /></label>
          <p class="muted small">The annual model starts next January. Entered balances carry unchanged to that date. Skipping the breakdown leaves account access unassessed.</p>
          <details><summary>Refine tax assumptions (optional)</summary>
            {answers.accountBreakdown && <>
              <OptionalNumber label="Brokerage cost basis ($)" value={answers.brokerageBasis} onChange={(v) => onChange("brokerageBasis", v)} />
              <OptionalNumber label="Or approximate unrealized gain (% of value)" value={answers.unrealizedGainPercent} onChange={(v) => onChange("unrealizedGainPercent", v)} max={100} />
              <OptionalNumber label="Roth IRA regular contributions remaining ($)" value={answers.rothPrincipal} onChange={(v) => onChange("rothPrincipal", v)} />
              <OptionalNumber label="First Roth contribution year" value={answers.rothFirstYear} onChange={(v) => onChange("rothFirstYear", v)} max={new Date().getFullYear()} />
            </>}
            <label class="row"><span>Taxable investment income</span><select value={answers.incomeProfile} onChange={(e) => onChange("incomeProfile", e.currentTarget.value as WizardAnswers["incomeProfile"])}>
              <option value="stock_index">Stock index estimate</option><option value="balanced">Balanced estimate</option><option value="income">Income-focused estimate</option><option value="none">No annual distributions</option>
            </select></label>
            <p class="muted small">Profiles use illustrative yields, included in total return, with reinvestment. Review the resolved yields after running; advanced JSON supports exact yields and cash distributions. Blank basis remains unknown. Exact basis takes priority over the gain estimate.</p>
          </details>
        </StepGroup>
      );
    case "annualIncome":
      return (
        <StepGroup title="Your current income">
          <p class="muted small">Gross pay, before tax. Salary + bonus + any side income.</p>
          <MoneyField
            label="Annual income (today's dollars)"
            value={answers.annualIncome}
            onChange={(v) => onChange("annualIncome", v)}
            step={5_000}
          />
        </StepGroup>
      );
    case "annualSpending":
      return (
        <StepGroup title="Retirement spending">
          <p class="muted small">In today's dollars. Used before and after retirement; refine time periods in the editor.</p>
          <MoneyField
            label="Annual spending in retirement"
            value={answers.annualSpending}
            onChange={(v) => onChange("annualSpending", v)}
            step={2_500}
          />
          <details><summary>Allow flexible spending (optional)</summary>
            <NumberField label="Flexible share of annual spending (%)" value={answers.flexibleSpendingPercent} onChange={(v) => onChange("flexibleSpendingPercent", v)} min={0} max={100} />
            <NumberField label="Maximum cut to flexible spending (%)" value={answers.maximumFlexibleCutPercent} onChange={(v) => onChange("maximumFlexibleCutPercent", v)} min={0} max={100} />
            <ChoiceField value={answers.spendingStrategy} options={[{ value: "fixed", label: "Keep spending fixed" }, { value: "dynamic", label: "Adjust to portfolio health" }, { value: "guardrails", label: "Use portfolio guardrails" }]} onChange={(v) => onChange("spendingStrategy", v)} />
            <p class="muted small">Cuts apply only to the flexible category and stay within your limit. Essential spending remains protected. Adjustments start when both people are retired.</p>
          </details>
        </StepGroup>
      );
    case "state":
      return (
        <StepGroup title="State of residence">
          <p class="muted small">Affects state income tax. Pick the state you'll retire in.</p>
          <label class="row">
            <span>State</span>
            <select
              value={answers.state}
              onChange={(e) => onChange("state", (e.currentTarget as HTMLSelectElement).value)}
            >
              {STATES.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
        </StepGroup>
      );
    case "hasSocialSecurity":
      return (
        <StepGroup title="Social Security">
          <ChoiceField
            value={answers.hasSocialSecurity}
            options={[
              { value: true, label: "Estimate it for me" },
              { value: false, label: "Skip — I'll add it later" },
            ]}
            onChange={(v) => onChange("hasSocialSecurity", v)}
          />
          {answers.hasSocialSecurity && (
            <MoneyField
              label="Estimated monthly benefit at age 67"
              value={answers.monthlySocialSecurity}
              onChange={(v) => onChange("monthlySocialSecurity", v)}
              step={100}
              hint="Illustrative estimate for the primary person. Use your personalized ssa.gov estimate; add spousal benefits in the editor."
            />
          )}
        </StepGroup>
      );
    case "risk":
      return (
        <StepGroup title="Investment risk tolerance">
          <p class="muted small">
            Low = mostly bonds. Medium = balanced. High = mostly stocks. These change the stock/bond allocation and retirement glidepath; the same market assumptions apply to each.
          </p>
          <ChoiceField
            value={answers.risk}
            options={[
              { value: "low", label: "Low — protect what I have" },
              { value: "medium", label: "Medium — balanced" },
              { value: "high", label: "High — maximize growth" },
            ]}
            onChange={(v) => onChange("risk", v)}
          />
        </StepGroup>
      );
    default:
      return null;
  }
}

function Review({ answers }: { answers: WizardAnswers }) {
  const rows: Array<[string, string]> = [
    [
      "Primary age / retire / longevity",
      `${answers.primaryAge} / ${answers.primaryRetirementAge} / ${answers.primaryLongevity}`,
    ],
    [
      "Spouse",
      answers.hasSpouse
        ? `yes — age ${answers.spouseAge}, retire ${answers.spouseRetirementAge}, longevity ${answers.spouseLongevity}`
        : "no (single household)",
    ],
    ["Investable assets", fmtMoney(savingsTotal(answers))],
    ["Account detail", answers.accountBreakdown ? "Provided; refine owners in editor" : "Total only — account access unassessed"],
    ["Statement date", answers.balanceDate || "Current estimate; date unconfirmed"],
    ["Legacy goal", "$0 initially; edit to add a legacy target"],
    ["Spending flexibility", `${answers.flexibleSpendingPercent}% flexible; ${answers.maximumFlexibleCutPercent}% maximum cut; ${answers.spendingStrategy}`],
    ["Annual income", fmtMoney(answers.annualIncome)],
    ["Annual spending", fmtMoney(answers.annualSpending)],
    ["State", answers.state],
    [
      "Social Security",
      answers.hasSocialSecurity ? `${fmtMoney(answers.monthlySocialSecurity)}/mo at 67` : "skipped",
    ],
    ["Risk", answers.risk],
  ];
  return (
    <div>
      <h2>Review</h2>
      <p class="muted small">
        These answers produce a Mantissa config. You can edit anything in the viewer, or download
        the JSON to use with the CLI.
      </p>
      <table class="review-table">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <th>{k}</th>
              <td>{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StepGroup({ title, children }: { title: string; children: preact.ComponentChildren }) {
  return (
    <div>
      <h2>{title}</h2>
      <div class="step-group">{children}</div>
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  step,
  hint,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  hint?: string;
}) {
  return (
    <label class="row">
      <span>{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step ?? 1}
        onInput={(e) => {
          const el = e.currentTarget as HTMLInputElement;
          // Number("") === 0 — an empty field would commit age 0.
          // Reject empty/partial input until it parses.
          const raw = el.value.trim();
          if (raw === "" || raw === "-" || raw === ".") return;
          const v = Number(raw);
          if (!Number.isFinite(v)) return;
          onChange(v);
        }}
        onBlur={(e) => {
          const el = e.currentTarget as HTMLInputElement;
          if (el.value.trim() === "") el.value = String(value);
        }}
      />
      {hint && <small class="muted">{hint}</small>}
    </label>
  );
}

function OptionalNumber({ label, value, onChange, max }: { label: string; value: number | null; onChange: (v: number | null) => void; max?: number }) {
  return <label class="row"><span>{label}</span><input type="number" min={0} max={max} value={value ?? ""} placeholder="Unknown / skip" onInput={(e) => {
    const raw = e.currentTarget.value;
    if (raw === "") onChange(null);
    else if (Number.isFinite(Number(raw))) onChange(Number(raw));
  }} /></label>;
}

function MoneyField(props: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step?: number;
  hint?: string;
}) {
  return <NumberField {...props} min={0} step={props.step ?? 1} />;
}

function ChoiceField<T extends string | boolean>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: ReadonlyArray<{ value: T; label: string }>;
  onChange: (v: T) => void;
}) {
  return (
    <div class="choice-field">
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          class={`choice ${value === o.value ? "choice--selected" : ""}`}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

const STATES: ReadonlyArray<{ code: string; name: string }> = [
  { code: "AL", name: "Alabama" },
  { code: "AK", name: "Alaska" },
  { code: "AZ", name: "Arizona" },
  { code: "AR", name: "Arkansas" },
  { code: "CA", name: "California" },
  { code: "CO", name: "Colorado" },
  { code: "CT", name: "Connecticut" },
  { code: "DE", name: "Delaware" },
  { code: "FL", name: "Florida" },
  { code: "GA", name: "Georgia" },
  { code: "HI", name: "Hawaii" },
  { code: "ID", name: "Idaho" },
  { code: "IL", name: "Illinois" },
  { code: "IN", name: "Indiana" },
  { code: "IA", name: "Iowa" },
  { code: "KS", name: "Kansas" },
  { code: "KY", name: "Kentucky" },
  { code: "LA", name: "Louisiana" },
  { code: "ME", name: "Maine" },
  { code: "MD", name: "Maryland" },
  { code: "MA", name: "Massachusetts" },
  { code: "MI", name: "Michigan" },
  { code: "MN", name: "Minnesota" },
  { code: "MS", name: "Mississippi" },
  { code: "MO", name: "Missouri" },
  { code: "MT", name: "Montana" },
  { code: "NE", name: "Nebraska" },
  { code: "NV", name: "Nevada" },
  { code: "NH", name: "New Hampshire" },
  { code: "NJ", name: "New Jersey" },
  { code: "NM", name: "New Mexico" },
  { code: "NY", name: "New York" },
  { code: "NC", name: "North Carolina" },
  { code: "ND", name: "North Dakota" },
  { code: "OH", name: "Ohio" },
  { code: "OK", name: "Oklahoma" },
  { code: "OR", name: "Oregon" },
  { code: "PA", name: "Pennsylvania" },
  { code: "RI", name: "Rhode Island" },
  { code: "SC", name: "South Carolina" },
  { code: "SD", name: "South Dakota" },
  { code: "TN", name: "Tennessee" },
  { code: "TX", name: "Texas" },
  { code: "UT", name: "Utah" },
  { code: "VT", name: "Vermont" },
  { code: "VA", name: "Virginia" },
  { code: "WA", name: "Washington" },
  { code: "WV", name: "West Virginia" },
  { code: "WI", name: "Wisconsin" },
  { code: "WY", name: "Wyoming" },
];
