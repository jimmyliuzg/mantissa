import { fmtMoney } from "../lib/format";
import type { CashFlowRow } from "@engine";

interface CashFlowChartProps {
  rows: CashFlowRow[];
}

const W = 880;
const H = 280;
const M = { top: 16, right: 16, bottom: 28, left: 56 };

/**
 * Stacked area: income (top), taxes (middle), expenses (bottom), with a
 * net-worth line overlay. Hand-rolled SVG so we ship zero chart deps.
 */
export function CashFlowChart({ rows }: CashFlowChartProps) {
  if (rows.length === 0) return <p class="muted">no rows</p>;

  const innerW = W - M.left - M.right;
  const innerH = H - M.top - M.bottom;

  const xAt = (i: number) => M.left + (i / Math.max(1, rows.length - 1)) * innerW;

  // Stack bottom→top: expenses, taxes, income. Net worth is a separate line.
  const maxStack = Math.max(
    ...rows.map((r) => r.income + r.taxes + r.expenses),
    1,
  );
  const maxNW = Math.max(...rows.map((r) => r.netWorth), 1);

  const yExp = (v: number) => M.top + innerH - (v / maxStack) * innerH;
  const yTax = (v: number) => yExp(v) - (v / maxStack) * innerH; // stacked above expenses
  const yInc = (v: number) => yTax(v) - (v / maxStack) * innerH;
  const yNW = (v: number) => M.top + innerH - (v / maxNW) * innerH;

  const pathFor = (vals: number[], yFn: (v: number) => number) => {
    if (vals.length === 0) return "";
    let d = `M ${xAt(0)} ${yFn(vals[0]!)}`;
    for (let i = 1; i < vals.length; i++) d += ` L ${xAt(i)} ${yFn(vals[i]!)}`;
    return d;
  };
  const areaFor = (vals: number[], yFn: (v: number) => number, baseline: number) => {
    if (vals.length === 0) return "";
    let d = `M ${xAt(0)} ${baseline}`;
    for (let i = 0; i < vals.length; i++) d += ` L ${xAt(i)} ${yFn(vals[i]!)}`;
    for (let i = vals.length - 1; i >= 0; i--) d += ` L ${xAt(i)} ${baseline}`;
    return `${d} Z`;
  };

  const baseY = M.top + innerH;
  const expensesArea = areaFor(rows.map((r) => r.expenses), yExp, baseY);
  const taxesArea = areaFor(rows.map((r) => r.taxes), yTax, yExp(rows[0]?.expenses ?? 0));
  const incomeArea = areaFor(
    rows.map((r) => r.income),
    yInc,
    yTax(rows[0]?.taxes ?? 0),
  );
  const nwPath = pathFor(rows.map((r) => r.netWorth), yNW);

  // Y-axis ticks: 0, mid, max
  const yTicks = [0, maxStack / 2, maxStack];

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label="Cash flow over time"
      class="chart"
    >
      <g class="grid">
        {yTicks.map((v) => (
          <line
            x1={M.left}
            x2={W - M.right}
            y1={yExp(0) - (v / maxStack) * innerH}
            y2={yExp(0) - (v / maxStack) * innerH}
            stroke="currentColor"
            stroke-opacity="0.1"
          />
        ))}
      </g>
      <path d={expensesArea} class="series series--expenses" />
      <path d={taxesArea} class="series series--taxes" />
      <path d={incomeArea} class="series series--income" />
      <path d={nwPath} class="series series--networth" fill="none" />

      <g class="axis axis--y">
        {yTicks.map((v) => (
          <text
            x={M.left - 6}
            y={yExp(0) - (v / maxStack) * innerH + 3}
            text-anchor="end"
            font-size="10"
          >
            {fmtMoney(v)}
          </text>
        ))}
      </g>
      <g class="axis axis--x">
        {[0, Math.floor(rows.length / 2), rows.length - 1].map((i) => {
          const row = rows[i];
          if (!row) return null;
          return (
            <text x={xAt(i)} y={H - 8} text-anchor="middle" font-size="10">
              {row.year}
            </text>
          );
        })}
      </g>

      <g class="legend" transform={`translate(${M.left},${M.top - 4})`}>
        <Legend label="Income" cls="income" />
        <Legend label="Taxes" cls="taxes" />
        <Legend label="Expenses" cls="expenses" />
        <Legend label="Net worth" cls="networth" />
      </g>
    </svg>
  );
}

function Legend({ label, cls }: { label: string; cls: string }) {
  return (
    <g transform="translate(0,0)">
      <rect class={`legend-swatch legend-swatch--${cls}`} x="0" y="-8" width="10" height="10" />
      <text x="14" y="1" font-size="10">
        {label}
      </text>
      <g transform="translate(70,0)">
        <rect class={`legend-swatch legend-swatch--${cls}`} x="0" y="-8" width="10" height="10" />
        <text x="14" y="1" font-size="10">
          {label} 2
        </text>
      </g>
    </g>
  );
}
