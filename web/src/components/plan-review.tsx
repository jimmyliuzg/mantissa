import { fmtMoney, fmtPct } from "../lib/format";
import { summarizePlan } from "../lib/plan-review";

interface PlanReviewProps {
  config: unknown;
  sims: number;
  onRun: () => void;
}

/** Read-only preflight for every uploaded config. All data remains local. */
export function PlanReview({ config, sims, onRun }: PlanReviewProps) {
  const review = summarizePlan(config);

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
          <ValueList entries={review.assumptions} />
          <details class="review-detail">
            <summary>People in this plan</summary>
            <Json
              value={{
                primary: (config as Record<string, unknown>)?.primary,
                spouse: (config as Record<string, unknown>)?.spouse,
              }}
            />
          </details>
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
              {review.accounts.map((account, index) => (
                <span
                  key={`${account.name}-${index}`}
                  class="allocation__segment"
                  style={{ width: `${account.share * 100}%` }}
                  title={`${account.name}: ${fmtMoney(account.balance)} (${fmtPct(account.share)})`}
                />
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
        <ConfigSection title="Mortgages & debts" items={review.mortgages} />
        {review.events.map(([name, items]) => (
          <ConfigSection key={name} title={label(name)} items={items} />
        ))}
      </section>

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
            <Value value={value} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Value({ value }: { value: unknown }) {
  if (typeof value === "number") return <>{value >= 1_000 ? fmtMoney(value) : String(value)}</>;
  if (typeof value === "boolean") return <>{value ? "Yes" : "No"}</>;
  if (typeof value === "string") return <>{value}</>;
  if (value === null) return <>None</>;
  return <code>{JSON.stringify(value)}</code>;
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
function label(key: string): string {
  return key.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}
