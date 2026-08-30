import { fmtMoney } from "../lib/format";
import type { CashFlowRow } from "@engine";

interface CashFlowChartProps {
  rows: CashFlowRow[];
}

const W = 880;
const H = 320;
const M = { top: 16, right: 16, bottom: 28, left: 56 };
const TOP_H = 140;  // height of the cash-flow bars area
const GAP = 24;     // gap between the two charts

/**
 * Cash flow + net worth, two charts in one SVG.
 *
 * The top chart shows annual income, expenses, and taxes as a small
 * grouped-bar visualization. The bottom chart shows the deterministic
 * net-worth line on its own y-axis so the line is readable across
 * the whole horizon.
 *
 * Both share the x-axis (year) so the visual relationship between
 * cash flow and net worth is obvious.
 */
export function CashFlowChart({ rows }: CashFlowChartProps) {
  if (rows.length === 0) return <p class="muted">no rows</p>;

  const innerW = W - M.left - M.right;

  // --- X axis (shared) ---
  const xAt = (i: number) =>
    M.left + (i / Math.max(1, rows.length - 1)) * innerW;

  // --- Top chart: cash flow bars (income, expenses, taxes) ---
  const cfMax = Math.max(
    ...rows.map((r) => Math.max(r.income, r.expenses + r.taxes, r.taxes)),
    1,
  );
  const cfMin = 0;
  const cfPad = cfMax * 0.05;
  const cfLo = cfMin - cfPad * 0.2;
  const cfHi = cfMax + cfPad;
  const cfY = (v: number) =>
    M.top + TOP_H - ((v - cfLo) / (cfHi - cfLo)) * TOP_H;

  // Grouped bar widths: thin bars with a small gap.
  const groupW = innerW / Math.max(1, rows.length);
  const barW = Math.max(1, Math.min(groupW * 0.28, 16));
  const barGap = barW * 0.2;

  // --- Bottom chart: net worth line ---
  const nwTop = M.top + TOP_H + GAP;
  const nwH = H - nwTop - M.bottom;
  const nwMin = Math.min(...rows.map((r) => r.netWorth), 0);
  const nwMax = Math.max(...rows.map((r) => r.netWorth), 1);
  const nwPad = (nwMax - nwMin) * 0.05;
  const nwLo = nwMin - nwPad * 0.2;
  const nwHi = nwMax + nwPad;
  const nwY = (v: number) =>
    nwTop + nwH - ((v - nwLo) / (nwHi - nwLo)) * nwH;

  // Net worth line path.
  let nwPath = `M ${xAt(0)} ${nwY(rows[0]!.netWorth)}`;
  for (let i = 1; i < rows.length; i++) {
    nwPath += ` L ${xAt(i)} ${nwY(rows[i]!.netWorth)}`;
  }

  // X axis ticks: first, middle, last.
  const xTickIdxs = [
    0,
    Math.floor(rows.length / 2),
    rows.length - 1,
  ];
  const cfTicks = [cfLo, (cfLo + cfHi) / 2, cfHi];
  const nwTicks = [nwLo, (nwLo + nwHi) / 2, nwHi];

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Cash flow and net worth" class="chart">
      {/* Top chart: cash flow */}
      <g>
        {/* Background grid */}
        {cfTicks.map((v) => (
          <line
            x1={M.left}
            x2={W - M.right}
            y1={cfY(v)}
            y2={cfY(v)}
            stroke="currentColor"
            stroke-opacity="0.08"
          />
        ))}
        {/* Bars: income, expenses, taxes (per year) */}
        {rows.map((r, i) => {
          const x = xAt(i) - barW - barGap / 2;
          const yIn = cfY(r.income);
          const yEx = cfY(r.expenses);
          const yTx = cfY(r.taxes);
          return (
            <g key={r.year}>
              <rect
                x={x}
                y={yIn}
                width={barW}
                height={M.top + TOP_H - yIn}
                class="series series--income-bar"
              />
              <rect
                x={x + barW + barGap}
                y={yEx}
                width={barW}
                height={M.top + TOP_H - yEx}
                class="series series--expenses-bar"
              />
              <rect
                x={x + 2 * (barW + barGap)}
                y={yTx}
                width={barW}
                height={M.top + TOP_H - yTx}
                class="series series--taxes-bar"
              />
            </g>
          );
        })}
        {/* Top y-axis labels */}
        {cfTicks.map((v) => (
          <text
            x={M.left - 6}
            y={cfY(v) + 3}
            text-anchor="end"
            font-size="10"
            class="muted"
          >
            {fmtMoney(v)}
          </text>
        ))}
        {/* Top label */}
        <text x={M.left} y={M.top - 4} font-size="10" class="muted">
          Cash flow (income · expenses · taxes, $ / yr)
        </text>
      </g>

      {/* Bottom chart: net worth line */}
      <g>
        {/* Background grid */}
        {nwTicks.map((v) => (
          <line
            x1={M.left}
            x2={W - M.right}
            y1={nwY(v)}
            y2={nwY(v)}
            stroke="currentColor"
            stroke-opacity="0.08"
          />
        ))}
        {/* Net worth line */}
        <path d={nwPath} class="series series--networth" fill="none" />
        {/* Bottom y-axis labels */}
        {nwTicks.map((v) => (
          <text
            x={M.left - 6}
            y={nwY(v) + 3}
            text-anchor="end"
            font-size="10"
            class="muted"
          >
            {fmtMoney(v)}
          </text>
        ))}
        {/* Bottom label */}
        <text x={M.left} y={nwTop - 4} font-size="10" class="muted">
          Net worth
        </text>
      </g>

      {/* Shared x-axis labels (years) */}
      <g class="axis axis--x">
        {xTickIdxs.map((i) => {
          const row = rows[i];
          if (!row) return null;
          return (
            <text x={xAt(i)} y={H - 8} text-anchor="middle" font-size="10">
              {row.year}
            </text>
          );
        })}
      </g>
    </svg>
  );
}
