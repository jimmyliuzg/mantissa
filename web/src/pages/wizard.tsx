import { useState } from "preact/hooks";
import { buildSlimConfig, DEFAULT_ANSWERS, type WizardAnswers } from "../slim/types";

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
 * 10-step wizard. The user answers 8 questions, sees a review step,
 * then either downloads the JSON or hands it to the viewer.
 */
export function Wizard() {
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<WizardAnswers>(DEFAULT_ANSWERS);

  function update<K extends keyof WizardAnswers>(key: K, value: WizardAnswers[K]) {
    setAnswers((a) => ({ ...a, [key]: value }));
  }

  function next() {
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
        <h2>Start from scratch</h2>
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
            max={80}
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
                max={80}
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
          <MoneyField
            label="Investable assets"
            value={answers.investableAssets}
            onChange={(v) => onChange("investableAssets", v)}
            step={10_000}
          />
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
          <p class="muted small">In today's dollars. The engine will inflate this for you.</p>
          <MoneyField
            label="Annual spending in retirement"
            value={answers.annualSpending}
            onChange={(v) => onChange("annualSpending", v)}
            step={2_500}
          />
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
              hint="$2,400/mo is roughly the 2026 average. ssa.gov has your personalized estimate."
            />
          )}
        </StepGroup>
      );
    case "risk":
      return (
        <StepGroup title="Investment risk tolerance">
          <p class="muted small">
            Low = mostly bonds. Medium = 60/40. High = mostly stocks. The engine uses this
            for the mean and volatility of simulated returns.
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
    ["Primary age / retire / longevity", `${answers.primaryAge} / ${answers.primaryRetirementAge} / ${answers.primaryLongevity}`],
    [
      "Spouse",
      answers.hasSpouse
        ? `yes — age ${answers.spouseAge}, retire ${answers.spouseRetirementAge}, longevity ${answers.spouseLongevity}`
        : "no (single household)",
    ],
    ["Investable assets", fmtMoney(answers.investableAssets)],
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
      <h3>Review</h3>
      <p class="muted small">
        These answers produce a Mantissa config. You can edit anything in the viewer, or download the JSON to
        use with the CLI.
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
      <h3>{title}</h3>
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
          const v = Number((e.currentTarget as HTMLInputElement).value);
          if (!Number.isFinite(v)) return;
          onChange(v);
        }}
      />
      {hint && <small class="muted">{hint}</small>}
    </label>
  );
}

function MoneyField(props: { label: string; value: number; onChange: (v: number) => void; step?: number; hint?: string }) {
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

function fmtMoney(n: number): string {
  return n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

const STATES: ReadonlyArray<{ code: string; name: string }> = [
  { code: "AL", name: "Alabama" }, { code: "AK", name: "Alaska" }, { code: "AZ", name: "Arizona" },
  { code: "AR", name: "Arkansas" }, { code: "CA", name: "California" }, { code: "CO", name: "Colorado" },
  { code: "CT", name: "Connecticut" }, { code: "DE", name: "Delaware" }, { code: "FL", name: "Florida" },
  { code: "GA", name: "Georgia" }, { code: "HI", name: "Hawaii" }, { code: "ID", name: "Idaho" },
  { code: "IL", name: "Illinois" }, { code: "IN", name: "Indiana" }, { code: "IA", name: "Iowa" },
  { code: "KS", name: "Kansas" }, { code: "KY", name: "Kentucky" }, { code: "LA", name: "Louisiana" },
  { code: "ME", name: "Maine" }, { code: "MD", name: "Maryland" }, { code: "MA", name: "Massachusetts" },
  { code: "MI", name: "Michigan" }, { code: "MN", name: "Minnesota" }, { code: "MS", name: "Mississippi" },
  { code: "MO", name: "Missouri" }, { code: "MT", name: "Montana" }, { code: "NE", name: "Nebraska" },
  { code: "NV", name: "Nevada" }, { code: "NH", name: "New Hampshire" }, { code: "NJ", name: "New Jersey" },
  { code: "NM", name: "New Mexico" }, { code: "NY", name: "New York" }, { code: "NC", name: "North Carolina" },
  { code: "ND", name: "North Dakota" }, { code: "OH", name: "Ohio" }, { code: "OK", name: "Oklahoma" },
  { code: "OR", name: "Oregon" }, { code: "PA", name: "Pennsylvania" }, { code: "RI", name: "Rhode Island" },
  { code: "SC", name: "South Carolina" }, { code: "SD", name: "South Dakota" }, { code: "TN", name: "Tennessee" },
  { code: "TX", name: "Texas" }, { code: "UT", name: "Utah" }, { code: "VT", name: "Vermont" },
  { code: "VA", name: "Virginia" }, { code: "WA", name: "Washington" }, { code: "WV", name: "West Virginia" },
  { code: "WI", name: "Wisconsin" }, { code: "WY", name: "Wyoming" },
];
