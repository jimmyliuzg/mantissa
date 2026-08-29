import { fmtMoney } from "../lib/format";
import type { CashFlowRow, McResult } from "@engine";

interface MonteCarloFanProps {
  percentiles: McResult["percentiles"];
  cashFlow: CashFlowRow[];
  medianFinal: number;
}

const W = 880;
const H = 240;
const M = { top: 16, right: 16, bottom: 28, left: 56 };

/**
 * M1 fan chart: shows the p10/p25/p50/p75/p90 net-worth percentile band
 * at the final year + the deterministic net-worth line over time.
 * Defer the full per-year fan to M2 when we have MC trajectories.
 */
export function MonteCarloFan({ percentiles, cashFlow, medianFinal }: MonteCarloFanProps) {
  if (cashFlow.length === 0) return <p class="muted">no rows</p>;

  const p = Object.fromEntries(percentiles.map((pp) => [pp.percentile, pp.value])) as Record<
    number,
    number
  >;

  const innerW = W - M.left - M.right;
  const innerH = H - M.top - M.bottom;

  const nwValues = cashFlow.map((r) => r.netWorth);
  const minY = Math.min(...nwValues, p[10] ?? Infinity);
  const maxY = Math.max(...nwValues, p[90] ?? -Infinity);
  const range = Math.max(1, maxY - minY);

  const xAt = (i: number) => M.left + (i / Math.max(1, cashFlow.length - 1)) * innerW;
  const yAt = (v: number) => M.top + innerH - ((v - minY) / range) * innerH;

  const line = (vals: number[]) => {
    if (vals.length === 0) return "";
    let d = `M ${xAt(0)} ${yAt(vals[0]!)}`;
    for (let i = 1; i < vals.length; i++) d += ` L ${xAt(i)} ${yAt(vals[i]!)}`;
    return d;
  };

  // Fan band: from p10 to p90 at the final year. M1 shows this as a
  // vertical span; M2 will replace with the full per-year band.
  const finalX = xAt(cashFlow.length - 1);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Monte Carlo distribution" class="chart">
      <path d={line(nwValues)} class="series series--networth" fill="none" />
      <line
        x1={finalX}
        x2={finalX}
        y1={yAt(p[10] ?? minY)}
        y2={yAt(p[90] ?? maxY)}
        class="series series--fan"
      />
      <line
        x1={finalX - 4}
        x2={finalX + 4}
        y1={yAt(p[10] ?? minY)}
        y2={yAt(p[10] ?? minY)}
        class="series series--fan-edge"
      />
      <line
        x1={finalX - 4}
        x2={finalX + 4}
        y1={yAt(p[90] ?? maxY)}
        y2={yAt(p[90] ?? maxY)}
        class="series series--fan-edge"
      />
      <circle
        cx={finalX}
        cy={yAt(medianFinal)}
        r="3"
        class="series series--fan-median"
      />

      <g class="axis axis--y">
        {[0, 0.5, 1].map((t) => (
          <text
            x={M.left - 6}
            y={yAt(minY + t * range) + 3}
            text-anchor="end"
            font-size="10"
          >
            {fmtMoney(minY + t * range)}
          </text>
        ))}
      </g>
      <g class="axis axis--x">
        {[0, Math.floor(cashFlow.length / 2), cashFlow.length - 1].map((i) => {
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
