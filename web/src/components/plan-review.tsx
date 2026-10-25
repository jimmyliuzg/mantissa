import { fmtMoney, fmtPct } from "../lib/format";
import {
  type ReviewAccount,
  summarizePlan,
  TREATMENT_LABELS,
  treatmentKey,
  type TreatmentKey,
} from "../lib/plan-review";

interface PlanReviewProps {
  config: unknown;
  sims: number;
  onRun: () => void;
}

/** Read-only preflight for every uploaded config. All data remains local. */
export function PlanReview({ config, sims, onRun }: PlanReviewProps) {
  const review = summarizePlan(config);
  const root = config as Record<string, unknown>;
  const basicAssumptions = review.assumptions.filter(([key, value]) => value === null || typeof value !== "object");
  const advancedAssumptions = review.assumptions.filter(([, value]) => value !== null && typeof value === "object");

  return (
    <section class="config-review">
      <header class="config-review__header">
        <div>
          <p class="eyebrow">Plan review</p>
          <h1>{review.name}</h1>
          <p class="muted">
            Confirm inputs before running {sims.toLocaleString()} market simulations in this
            browser.
          </p>
        </div>
        <button type="button" class="btn btn--primary" onClick={onRun}>
          Run projection →
        </button>
      </header>

      {typeof root.state === "string" && root.state.toUpperCase() !== "CA" && <p class="coverage-notice" role="status">State income tax is not modeled for {root.state} and will be zero. Only California state income tax is currently modeled. Results may overstate available spending.</p>}
      <section class="review-stats" aria-label="Current financial snapshot">
        <Stat label="Current assets" value={fmtMoney(review.totalAssets)} />
        <Stat
          label="Current debts"
          value={fmtMoney(review.totalDebt)}
          tone={review.totalDebt > 0 ? "bad" : undefined}
        />
        <Stat
          label="Estimated net worth"
          value={fmtMoney(review.netWorth)}
          tone={review.netWorth >= 0 ? "good" : "bad"}
        />
        <Stat label="Monthly contributions" value={fmtMoney(review.monthlyContributions)} />
      </section>

      <section class="panel">
        <SectionTitle title="Household & plan settings" detail={review.household.join(" · ")} />
        <div class="review-columns">
          <ValueList entries={basicAssumptions} />
          <div>{["primary", "spouse"].map((key) => {
            const person = root[key] as Record<string, unknown> | null;
            return person && <div key={key}><h3>{text(person.name) || label(key)}</h3><ValueList entries={Object.entries(person).filter(([field]) => field !== "name")} /></div>;
          })}</div>
        </div>
      </section>

      <section class="panel">
        <SectionTitle
          title="Current accounts"
          detail={`${review.accounts.length} account${review.accounts.length === 1 ? "" : "s"}`}
        />
        {review.accounts.length > 0 ? (
          <>
            <div class="allocation" aria-label="Account allocation by current balance">
              {sortedForAllocation(review.accounts).map((account, index) => (
                <span
                  key={`${account.name}-${index}`}
                  class={`allocation__segment tint-${treatmentKey(account.taxTreatment)}`}
                  style={{ width: `${account.share * 100}%` }}
                  title={`${account.name}: ${fmtMoney(account.balance)} (${fmtPct(account.share)}) · ${account.taxTreatment}`}
                />
              ))}
            </div>
            <div class="allocation-legend">
              {treatmentTotals(review.accounts).map((group) => (
                <span class="allocation-legend__item" key={group.key}>
                  <span class={`allocation-legend__swatch tint-${group.key}`} aria-hidden="true" />
                  {TREATMENT_LABELS[group.key]} · {fmtPct(group.share)}
                </span>
              ))}
            </div>
            <p class="mobile-table-hint muted small">Swipe the table to see every account field.</p>
            <div class="table-wrap">
              <table class="review-data-table">
                <thead>
                  <tr>
                    <th>Account</th>
                    <th>Owner</th>
                    <th>Type</th>
                    <th>Tax treatment</th>
                    <th>Balance</th>
                    <th>Allocation</th>
                    <th>Contribution</th>
                    <th>Growth</th>
                  </tr>
                </thead>
                <tbody>
                  {review.accounts.map((account, index) => (
                    <tr key={`${account.name}-${index}`}>
                      <th>{account.name}</th>
                      <td>{account.owner}</td>
                      <td>{account.type}</td>
                      <td>{account.taxTreatment}</td>
                      <td>{fmtMoney(account.balance)}</td>
                      <td>{fmtPct(account.share)}</td>
                      <td>{fmtMoney(account.monthlyContribution)}/mo</td>
                      <td>
                        {account.growthRate === null
                          ? "Engine assumption"
                          : fmtPct(account.growthRate)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <Empty label="No accounts configured." />
        )}
      </section>

      <section class="review-grid">
        <ConfigSection title="Income streams" items={review.incomeStreams} />
        <ConfigSection title="Expenses" items={review.expenses} />
        {review.mortgages.length > 0 && <ConfigSection title="Mortgages & debts" items={review.mortgages} />}
        {review.events.filter(([, items]) => items.length > 0).map(([name, items]) => (
          <ConfigSection key={name} title={label(name)} items={items} />
        ))}
      </section>

      {advancedAssumptions.length > 0 && <details class="panel review-detail"><summary>Detailed model assumptions</summary><ValueList entries={advancedAssumptions} /></details>}
      {review.unknownEntries.length > 0 && (
        <section class="panel">
          <SectionTitle title="Additional configured data" detail="Preserved for the engine" />
          <ValueList entries={review.unknownEntries} />
        </section>
      )}

      <details class="panel review-detail review-detail--raw">
        <summary>Complete JSON configuration</summary>
        <p class="muted small">
          Every field supplied to Mantissa. This is the exact local config that will run.
        </p>
        <Json value={config} />
      </details>
    </section>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "good" | "bad" }) {
  return (
    <div class="review-stat" data-tone={tone}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function SectionTitle({ title, detail }: { title: string; detail: string }) {
  return (
    <header class="review-section-title">
      <h2>{title}</h2>
      <span class="muted small">{detail}</span>
    </header>
  );
}

function ConfigSection({ title, items }: { title: string; items: Record<string, unknown>[] }) {
  return (
    <section class="panel review-config-section">
      <SectionTitle title={title} detail={`${items.length} configured`} />
      {items.length === 0 ? (
        <Empty label="None configured." />
      ) : (
        items.map((item) => (
          <details
            key={`${title}-${text(item.id) || text(item.name) || JSON.stringify(item)}`}
            class="review-detail"
            open={items.length === 1}
          >
            <summary>{text(item.name) || text(item.id) || title}</summary>
            <ValueList entries={Object.entries(item).filter(([key]) => !key.startsWith("_"))} />
          </details>
        ))
      )}
    </section>
  );
}

function ValueList({ entries }: { entries: Array<[string, unknown]> }) {
  return (
    <dl class="value-list">
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt>{label(key)}</dt>
          <dd>
            <Value field={key} value={value} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Value({ field, value }: { field: string; value: unknown }) {
  if (typeof value === "number") {
    if (/year|age/i.test(field)) return <>{String(value)}</>;
    if (/rate|fraction|share|pct|inflation|return|reduction|appreciation/i.test(field)) return <>{fmtPct(value)}</>;
    if (/amount|balance|basis|contribution|legacy goal|legacy_goal|payment|principal/i.test(field)) return <>{fmtMoney(value)}</>;
    return <>{String(value)}</>;
  }
  if (typeof value === "boolean") return <>{value ? "Yes" : "No"}</>;
  if (typeof value === "string") {
    const labels: Record<string, string> = { fixed: "Fixed spending", dynamic: "Adjust to portfolio health", guardrails: "Portfolio guardrails", penalty_free: "Penalty-free withdrawals", allow_penalties: "Allow early-withdrawal penalties", real: "Today’s purchasing power", nominal: "Future dollars" };
    return <>{labels[value] ?? value}</>;
  }
  if (value === null) return <>None</>;
  if (Array.isArray(value)) return <>{value.map((item, index) => <span key={index}>{index > 0 ? ", " : ""}<Value field={field} value={item} /></span>)}</>;
  return <ValueList entries={Object.entries(value as Record<string, unknown>)} />;
}

function Empty({ label }: { label: string }) {
  return <p class="muted small">{label}</p>;
}
function Json({ value }: { value: unknown }) {
  return <pre class="data">{JSON.stringify(value, null, 2)}</pre>;
}
function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** Segments grouped visually: same treatment adjacent, largest first. */
function sortedForAllocation(accounts: ReviewAccount[]): ReviewAccount[] {
  return [...accounts].sort(
    (a, b) =>
      treatmentKey(a.taxTreatment).localeCompare(treatmentKey(b.taxTreatment)) ||
      b.balance - a.balance,
  );
}

/** Present treatments with combined balance and share, largest first. */
function treatmentTotals(accounts: ReviewAccount[]): Array<{ key: TreatmentKey; share: number }> {
  const total = accounts.reduce((sum, a) => sum + a.balance, 0);
  const byKey = new Map<TreatmentKey, number>();
  for (const a of accounts) {
    const key = treatmentKey(a.taxTreatment);
    byKey.set(key, (byKey.get(key) ?? 0) + a.balance);
  }
  return [...byKey.entries()]
    .map(([key, balance]) => ({ key, share: total > 0 ? balance / total : 0 }))
    .sort((a, b) => b.share - a.share);
}
function label(key: string): string {
  return key.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}
