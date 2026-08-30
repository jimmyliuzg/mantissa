import { fmtMoney } from "../lib/format";
import type { CashFlowRow, McResult, McPercentilePoint } from "@engine";

interface MonteCarloFanProps {
  percentiles: McResult["percentiles"];
  cashFlow: CashFlowRow[];
  medianFinal: number;
  yearlyPercentiles?: McPercentilePoint[];
}

const W = 880;
const H = 240;
const M = { top: 16, right: 16, bottom: 28, left: 56 };

/**
 * M4 fan chart: shows the p10/p25/p50/p75/p90 net-worth percentile
 * band across the entire projection horizon, plus the deterministic
 * net-worth line. When the engine doesn't return yearly percentiles
 * (older wheels, snapshot from before this field existed), the chart
 * falls back to a single final-year vertical line so the page still
 * renders something useful.
 */
export function MonteCarloFan({
  percentiles,
  cashFlow,
  medianFinal,
  yearlyPercentiles = [],
}: MonteCarloFanProps) {
  if (cashFlow.length === 0) return <p class="muted">no rows</p>;

  // Determine the y-range from the band when available, otherwise
  // from the deterministic net-worth line. We pad by 5% on each side.
  const allValues = yearlyPercentiles.length > 0
    ? yearlyPercentiles.flatMap((p) => [p.p10, p.p25, p.p50, p.p75, p.p90])
    : cashFlow.map((r) => r.netWorth);
  const minY = Math.min(...allValues, 0);
  const maxY = Math.max(...allValues, 1);
  const pad = (maxY - minY) * 0.05;
  const lo = minY - pad;
  const hi = maxY + pad;

  const innerW = W - M.left - M.right;
  const innerH = H - M.top - M.bottom;

  // X axis: year 2026 = age 35 by default, or we just use the row index.
  const xAt = (i: number) => M.left + (i / Math.max(1, cashFlow.length - 1)) * innerW;
  const yAt = (v: number) => M.top + innerH - ((v - lo) / (hi - lo)) * innerH;

  // Build a smooth path through the given key of the per-age data.
  const line = (key: keyof McPercentilePoint) => {
    if (yearlyPercentiles.length === 0) return "";
    let d = `M ${xAt(0)} ${yAt(yearlyPercentiles[0]![key] as number)}`;
    for (let i = 1; i < yearlyPercentiles.length; i++) {
      d += ` L ${xAt(i)} ${yAt(yearlyPercentiles[i]![key] as number)}`;
    }
    return d;
  };

  // Build a band path: outline the upper bound forward, then the lower
  // bound backward, closing into a polygon.
  const band = (upper: keyof McPercentilePoint, lower: keyof McPercentilePoint) => {
    if (yearlyPercentiles.length === 0) return "";
    let d = `M ${xAt(0)} ${yAt(yearlyPercentiles[0]![upper] as number)}`;
    for (let i = 1; i < yearlyPercentiles.length; i++) {
      d += ` L ${xAt(i)} ${yAt(yearlyPercentiles[i]![upper] as number)}`;
    }
    for (let i = yearlyPercentiles.length - 1; i >= 0; i--) {
      d += ` L ${xAt(i)} ${yAt(yearlyPercentiles[i]![lower] as number)}`;
    }
    return `${d} Z`;
  };

  // Deterministic net-worth line, anchored to the same x range.
  const nwPath = (() => {
    let d = `M ${xAt(0)} ${yAt(cashFlow[0]!.netWorth)}`;
    for (let i = 1; i < cashFlow.length; i++) {
      d += ` L ${xAt(i)} ${yAt(cashFlow[i]!.netWorth)}`;
    }
    return d;
  })();

  const yTicks = [lo, lo + (hi - lo) / 2, hi];
  const xTickIdxs = [0, Math.floor(cashFlow.length / 2), cashFlow.length - 1];

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Monte Carlo distribution" class="chart">
      {/* Y grid */}
      <g class="grid">
        {yTicks.map((v) => (
          <line
            x1={M.left}
            x2={W - M.right}
            y1={yAt(v)}
            y2={yAt(v)}
            stroke="currentColor"
            stroke-opacity="0.1"
          />
        ))}
      </g>

      {/* Fan bands: p10-p90 outer, p25-p75 inner. Both are drawn when
          yearly data is available. */}
      {yearlyPercentiles.length > 0 && (
        <>
          <path d={band("p90", "p10")} class="series series--fan-outer" />
          <path d={band("p75", "p25")} class="series series--fan-inner" />
          <path d={line("p50")} class="series series--fan-median" />
        </>
      )}

      {/* Deterministic net-worth line. */}
      <path d={nwPath} class="series series--networth" fill="none" />

      {/* Fallback: when no yearly data, draw a single vertical line
          at the final year showing p10/p90 from `percentiles`. */}
      {yearlyPercentiles.length === 0 && (
        <>
          <line
            x1={xAt(cashFlow.length - 1)}
            x2={xAt(cashFlow.length - 1)}
            y1={yAt(percentiles[0]?.value ?? 0)}
            y2={yAt(percentiles[4]?.value ?? 0)}
            class="series series--fan-outer"
          />
          <circle
            cx={xAt(cashFlow.length - 1)}
            cy={yAt(medianFinal)}
            r="3"
            class="series series--fan-median"
          />
        </>
      )}

      {/* Y axis labels */}
      <g class="axis axis--y">
        {yTicks.map((v) => (
          <text
            x={M.left - 6}
            y={yAt(v) + 3}
            text-anchor="end"
            font-size="10"
          >
            {fmtMoney(v)}
          </text>
        ))}
      </g>
      {/* X axis labels (years) */}
      <g class="axis axis--x">
        {xTickIdxs.map((i) => {
          const row = cashFlow[i];
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
