import { useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";
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

export const WIZARD_DRAFT_KEY = "mantissa:wizard-draft";

function loadDraft(): { step: number; answers: WizardAnswers } {
  try {
    const saved = JSON.parse(sessionStorage.getItem(WIZARD_DRAFT_KEY) ?? "null");
    if (saved && typeof saved.answers === "object" && saved.answers !== null) {
      const answers = { ...DEFAULT_ANSWERS };
      // Persist only known answer fields with the expected primitive type.
      for (const key of Object.keys(answers) as Array<keyof WizardAnswers>) {
        const value = saved.answers[key];
        const expected = DEFAULT_ANSWERS[key];
        if (expected !== null && typeof value === typeof expected && (typeof value !== "number" || Number.isFinite(value)) || expected === null && (value === null || typeof value === "number" && Number.isFinite(value))) {
          (answers as unknown as Record<string, unknown>)[key] = value;
        }
      }
      if (!["low", "medium", "high"].includes(answers.risk)) answers.risk = "medium";
      if (!["fixed", "dynamic", "guardrails"].includes(answers.spendingStrategy)) answers.spendingStrategy = "fixed";
      if (!["none", "stock_index", "balanced", "income"].includes(answers.incomeProfile)) answers.incomeProfile = "stock_index";
      if (!STATES.some((state) => state.code === answers.state)) answers.state = "CA";
      return { step: Number.isInteger(saved.step) ? Math.max(0, Math.min(STEPS.length - 1, saved.step)) : 0, answers };
    }
  } catch { /* Storage may be disabled or a previous draft malformed. */ }
  return { step: 0, answers: { ...DEFAULT_ANSWERS } };
}

/** Optional details stay local to this browser session. */
export function Wizard() {
  const [draft] = useState(loadDraft);
  const [step, setStep] = useState(draft.step);
  const [answers, setAnswers] = useState<WizardAnswers>(draft.answers);
  const [saved, setSaved] = useState(false);
  const [handoffError, setHandoffError] = useState<string | null>(null);
  const stepRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    try {
      sessionStorage.setItem(WIZARD_DRAFT_KEY, JSON.stringify({ step, answers }));
      setSaved(true);
    } catch { setSaved(false); }
  }, [step, answers]);
  useLayoutEffect(() => {
    stepRef.current?.querySelector<HTMLElement>("h2")?.focus();
  }, [step]);
  function resetDraft() {
    try { sessionStorage.removeItem(WIZARD_DRAFT_KEY); } catch { /* Already unavailable. */ }
    setAnswers({ ...DEFAULT_ANSWERS });
    setStep(0);
  }

  function update<K extends keyof WizardAnswers>(key: K, value: WizardAnswers[K]) {
    setAnswers((a) => ({ ...a, [key]: value }));
  }

  function validStep() {
    const inputs = stepRef.current?.querySelectorAll<HTMLInputElement>("input") ?? [];
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
    try {
      sessionStorage.setItem("mantissa:config", JSON.stringify(cfg));
      sessionStorage.removeItem("mantissa:run-options");
      sessionStorage.setItem("mantissa:reviewed-config", JSON.stringify(cfg));
      window.location.hash = "#/review";
    } catch {
      setHandoffError("Browser session storage is unavailable. Download your plan to keep it, or enable session storage before opening results.");
    }
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
        <h1>Start a retirement plan</h1>
        <div class="wizard-draft"><span role="status">{saved ? "Draft saved for this browser session" : "Session storage unavailable; download to keep your plan"}</span><button type="button" class="linkish" onClick={resetDraft}>Reset answers</button></div>
        <Progress current={step} total={STEPS.length} />
      </header>

      <div class="wizard-step" ref={stepRef}>
        {STEPS[step]?.key === "review" ? (
          <Review answers={answers} onEdit={setStep} />
        ) : (
          <Step
            stepKey={STEPS[step]?.key as keyof WizardAnswers}
            answers={answers}
            onChange={update}
          />
        )}
      </div>

      {handoffError && <p class="error" role="alert">{handoffError}</p>}
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
              Download plan
            </button>
            <button type="button" class="btn btn--primary" onClick={openInViewer}>
              See results →
            </button>
          </div>
        )}
      </footer>
    </section>
  );
}

function Progress({ current, total }: { current: number; total: number }) {
  return (
    <div class="wizard-progress"><span>Step {current + 1} of {total}</span><div class="progress" aria-hidden="true">
      {Array.from({ length: total }).map((_, i) => (
        <span key={i} class={`progress-dot ${i <= current ? "done" : ""}`} />
      ))}
    </div></div>
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
          <ChoiceField value={answers.alreadyRetired} options={[{ value: false, label: "Planning to retire" }, { value: true, label: "Already retired" }]} onChange={(v) => onChange("alreadyRetired", v)} />
          <NumberField
            label="Current age"
            value={answers.primaryAge}
            onChange={(v) => {
              onChange("primaryAge", v);
              if (!answers.alreadyRetired && answers.primaryRetirementAge < v + 1) {
                onChange("primaryRetirementAge", Math.min(110, v + 1));
              }
            }}
            min={18}
            max={90}
          />
          {!answers.alreadyRetired && <NumberField
            label="Age you want to retire"
            value={answers.primaryRetirementAge}
            onChange={(v) => onChange("primaryRetirementAge", v)}
            min={answers.primaryAge + 1}
            max={109}
          />}
          <NumberField
            label="Plan through age (longevity)"
            value={answers.primaryLongevity}
            onChange={(v) => onChange("primaryLongevity", v)}
            min={Math.max((answers.alreadyRetired ? answers.primaryAge : answers.primaryRetirementAge) + 1, 70)}
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
          <p class="muted small">A two-person plan uses the engine’s married-household tax assumptions. Other filing arrangements need a separate plan.</p>
          {answers.hasSpouse && (
            <>
              <NumberField
                label="Spouse's current age"
                value={answers.spouseAge ?? answers.primaryAge}
                onChange={(v) => onChange("spouseAge", v)}
                min={18}
                max={90}
              />
              <ChoiceField value={answers.spouseAlreadyRetired} options={[{ value: false, label: "Spouse is planning to retire" }, { value: true, label: "Spouse is already retired" }]} onChange={(v) => onChange("spouseAlreadyRetired", v)} />
              {!answers.spouseAlreadyRetired && <NumberField
                label="Spouse's retirement age"
                value={answers.spouseRetirementAge ?? answers.primaryRetirementAge}
                onChange={(v) => onChange("spouseRetirementAge", v)}
                min={(answers.spouseAge ?? answers.primaryAge) + 1}
                max={109}
              />}
              <NumberField
                label="Spouse's longevity"
                value={answers.spouseLongevity ?? answers.primaryLongevity}
                onChange={(v) => onChange("spouseLongevity", v)}
                min={Math.max(70, (answers.spouseAlreadyRetired ? answers.spouseAge ?? answers.primaryAge : answers.spouseRetirementAge ?? answers.primaryRetirementAge) + 1)}
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
          <p class="muted small">Primary person’s gross employment pay, before tax. Modeled as wages until retirement; other income can be added in the editor.</p>
          {answers.alreadyRetired ? <p>No employment income is added for an already-retired primary person. Add ongoing work or other income after your first estimate.</p> : <MoneyField
            label="Annual income (today's dollars)"
            value={answers.annualIncome}
            onChange={(v) => onChange("annualIncome", v)}
            step={5_000}
          />}
        </StepGroup>
      );
    case "annualSpending":
      return (
        <StepGroup title="Retirement spending">
          <p class="muted small">In today's dollars. This is also your current budget unless you add a different amount below.</p>
          <MoneyField
            label="Annual spending in retirement"
            value={answers.annualSpending}
            onChange={(v) => onChange("annualSpending", v)}
            step={2_500}
          />
          {!answers.alreadyRetired && <details><summary>Different current spending (optional)</summary><OptionalNumber label="Annual spending before primary retirement ($)" value={answers.currentAnnualSpending} onChange={(v) => onChange("currentAnnualSpending", v)} /><p class="muted small">Blank uses the retirement budget throughout. A separate current budget is essential spending until the primary person retires, then the retirement budget and flexibility apply.</p></details>}
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
          <p class="muted small">Pick the state you’ll retire in. California is currently the only state with a modeled state income tax.</p>
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
          {answers.state !== "CA" && <p class="coverage-notice" role="status">State income tax is not modeled for {answers.state}; it will be zero in this estimate. Federal taxes are still modeled. Results may overstate available spending.</p>}
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
              hint="Illustrative estimate for the primary person. Use your personalized ssa.gov estimate."
            />
          )}
          {answers.hasSocialSecurity && answers.hasSpouse && <MoneyField label="Spouse’s estimated monthly benefit at age 67" value={answers.spouseMonthlySocialSecurity} onChange={(v) => onChange("spouseMonthlySocialSecurity", v)} hint="Enter the spouse’s own estimate; zero leaves this benefit out. Claiming ages can be changed in the editor." />}
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

function Review({ answers, onEdit }: { answers: WizardAnswers; onEdit: (step: number) => void }) {
  const projection = buildSlimConfig(answers);
  const rows: Array<[string, string]> = [
    [
      "Primary age / retire / longevity",
      `${answers.primaryAge} / ${answers.alreadyRetired ? "already retired" : answers.primaryRetirementAge} / ${answers.primaryLongevity}`,
    ],
    [
      "Spouse",
      answers.hasSpouse
        ? `yes — age ${answers.spouseAge ?? answers.primaryAge}, ${answers.spouseAlreadyRetired ? "already retired" : `retire ${answers.spouseRetirementAge ?? answers.primaryRetirementAge}`}, longevity ${answers.spouseLongevity ?? answers.primaryLongevity}`
        : "no (single household)",
    ],
    ["Investable assets", fmtMoney(savingsTotal(answers))],
    ["Account detail", answers.accountBreakdown ? "Provided; refine owners in editor" : "Total only — account access unassessed"],
    ["Statement date", answers.balanceDate || "Current estimate; date unconfirmed"],
    ["Legacy goal", "$0 initially; edit to add a legacy target"],
    ["Spending flexibility", `${answers.flexibleSpendingPercent}% flexible; ${answers.maximumFlexibleCutPercent}% maximum cut; ${answers.spendingStrategy}`],
    ["Annual employment income", fmtMoney(answers.alreadyRetired ? 0 : answers.annualIncome)],
    ["Annual retirement spending", fmtMoney(answers.annualSpending)],
    ["Annual current spending", fmtMoney(answers.alreadyRetired ? answers.annualSpending : answers.currentAnnualSpending ?? answers.annualSpending)],
    ["State", answers.state],
    [
      "Social Security",
      answers.hasSocialSecurity ? `${fmtMoney(answers.monthlySocialSecurity)}/mo at 67${answers.hasSpouse ? `; spouse ${fmtMoney(answers.spouseMonthlySocialSecurity)}/mo at 67` : ""}` : "skipped",
    ],
    ["Risk", answers.risk],
  ];
  return (
    <div>
      <h2 tabIndex={-1}>Review your plan</h2>
      <p class="muted small">
        Check these estimates, then see your results. You can refine accounts, income and assumptions after the first run. Balances carry unchanged to next January when the annual projection starts.
      </p>
      {projection.primary.retirement_date === `${projection.start_year}-01-01` && <p class="muted small">The primary person is retired when this projection opens in {projection.start_year}; no employment wages are modeled before that date.</p>}
      {answers.state !== "CA" && <p class="coverage-notice">State income tax is not modeled for {answers.state} and will be zero. Results may overstate available spending.</p>}
      <table class="review-table">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <th>{k}</th>
              <td>{v}</td>
              <td>{k !== "Legacy goal" && <button type="button" class="linkish" onClick={() => onEdit(k.startsWith("Primary") ? 0 : k === "Spouse" ? 1 : ["Investable assets", "Account detail", "Statement date"].includes(k) ? 2 : k.includes("income") ? 3 : k.includes("spending") || k === "Spending flexibility" ? 4 : k === "State" ? 5 : k === "Social Security" ? 6 : 7)} aria-label={`Edit ${k}`}>Edit</button>}</td>
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
      <h2 tabIndex={-1}>{title}</h2>
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
  step?: number | "any";
  hint?: string;
}) {
  return (
    <label class="row">
      <span>{label}</span>
      <input
        type="number"
        required
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
      />
      {hint && <small class="muted">{hint}</small>}
    </label>
  );
}

function OptionalNumber({ label, value, onChange, max }: { label: string; value: number | null; onChange: (v: number | null) => void; max?: number }) {
  return <label class="row"><span>{label}</span><input type="number" step={label.includes("year") ? 1 : "any"} min={0} max={max} value={value ?? ""} placeholder="Unknown / skip" onInput={(e) => {
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
  return <NumberField {...props} min={0} step="any" />;
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
          aria-pressed={value === o.value}
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
