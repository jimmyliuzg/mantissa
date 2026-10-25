import { fmtMoney } from "../lib/format";
import { nearestIndex, useElementWidth, xTickIndices } from "../lib/chart-utils";
import { useState } from "preact/hooks";
import { ChartTooltip } from "./chart-tooltip";
import type { CashFlowRow, McResult, McPercentilePoint } from "@engine";

interface MonteCarloFanProps {
  percentiles: McResult["percentiles"];
  cashFlow: CashFlowRow[];
  medianFinal: number;
  yearlyPercentiles?: McPercentilePoint[];
}

const H = 240;
const M = { top: 16, right: 16, bottom: 28, left: 56 };

/**
 * Fan chart: p10/p25/p50/p75/p90 net-worth bands across the horizon
 * plus the deterministic net-worth line. Pixel-space SVG (1:1 width/
 * height attrs) with hover/keyboard cursor readout; falls back to a
 * final-year vertical line when the engine returns no yearly
 * percentiles.
 */
export function MonteCarloFan({
  percentiles,
  cashFlow,
  medianFinal,
  yearlyPercentiles = [],
}: MonteCarloFanProps) {
  const [wrapRef, width] = useElementWidth<HTMLDivElement>(880);
  const [cursor, setCursor] = useState<number | null>(null);

  if (cashFlow.length === 0) return <p class="muted">no rows</p>;

  const allValues =
    yearlyPercentiles.length > 0
      ? yearlyPercentiles.flatMap((p) => [p.p10, p.p25, p.p50, p.p75, p.p90])
      : cashFlow.map((r) => r.netWorth);
  const minY = Math.min(...allValues, 0);
  const maxY = Math.max(...allValues, 1);
  const pad = (maxY - minY) * 0.05;
  const lo = minY - pad;
  const hi = maxY + pad;

  const innerW = width - M.left - M.right;
  const innerH = H - M.top - M.bottom;

  // Band scale: row i centered in its slot — matches the cash-flow chart.
  const groupW = innerW / cashFlow.length;
  const xAt = (i: number) => M.left + (i + 0.5) * groupW;
  const yAt = (v: number) => M.top + innerH - ((v - lo) / (hi - lo)) * innerH;

  const line = (key: keyof McPercentilePoint) => {
    if (yearlyPercentiles.length === 0) return "";
    let d = `M ${xAt(0)} ${yAt(yearlyPercentiles[0]![key] as number)}`;
    for (let i = 1; i < yearlyPercentiles.length; i++) {
      d += ` L ${xAt(i)} ${yAt(yearlyPercentiles[i]![key] as number)}`;
    }
    return d;
  };

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

  let nwPath = `M ${xAt(0)} ${yAt(cashFlow[0]!.netWorth)}`;
  for (let i = 1; i < cashFlow.length; i++) {
    nwPath += ` L ${xAt(i)} ${yAt(cashFlow[i]!.netWorth)}`;
  }

  const yTicks = [lo, lo + (hi - lo) / 2, hi];
  const xTicks = xTickIndices(cashFlow.length, innerW);

  const idx = cursor;
  const cur = idx !== null ? cashFlow[idx] : undefined;
  const curPct = idx !== null ? yearlyPercentiles[idx] : undefined;

  function onPointerMove(e: PointerEvent) {
    const rect = (e.currentTarget as SVGElement).getBoundingClientRect();
    setCursor(nearestIndex(e.clientX - rect.left - M.left, innerW, cashFlow.length));
  }

  function onKeyDown(e: KeyboardEvent) {
    const last = cashFlow.length - 1;
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      setCursor((c) => Math.max(0, (c ?? Math.floor(last / 2)) - 1));
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      setCursor((c) => Math.min(last, (c ?? Math.floor(last / 2)) + 1));
    } else if (e.key === "Home") {
      e.preventDefault();
      setCursor(0);
    } else if (e.key === "End") {
      e.preventDefault();
      setCursor(last);
    } else if (e.key === "Escape") {
      setCursor(null);
    }
  }

  return (
    <div class="chart-wrap" ref={wrapRef}>
      <svg
        width={width}
        height={H}
        viewBox={`0 0 ${width} ${H}`}
        role="img"
        aria-label={`Monte Carlo net-worth percentiles, ${cashFlow.length} years. Focus and use left arrow and right arrow keys to inspect individual years.`}
        class="chart"
        tabIndex={0}
        onPointerMove={onPointerMove}
        onPointerLeave={() => setCursor(null)}
        onKeyDown={onKeyDown}
        onBlur={() => setCursor(null)}
      >
        <g class="grid">
          {yTicks.map((v) => (
            <line
              key={v}
              x1={M.left}
              x2={width - M.right}
              y1={yAt(v)}
              y2={yAt(v)}
              stroke="currentColor"
              stroke-opacity="0.1"
            />
          ))}
        </g>

        {yearlyPercentiles.length > 0 && (
          <>
            <path d={band("p90", "p10")} class="series series--fan-outer" />
            <path d={band("p75", "p25")} class="series series--fan-inner" />
            <path d={line("p50")} class="series series--fan-median" />
          </>
        )}

        <path d={nwPath} class="series series--networth" fill="none" />

        {/* Fallback: no yearly data — single final-year p10/p90 line. */}
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

        {/* Cursor: guide + dots on median and deterministic line */}
        {cur && (
          <g aria-hidden="true">
            <line x1={xAt(idx!)} x2={xAt(idx!)} y1={M.top} y2={H - M.bottom} class="chart-guide" />
            <circle cx={xAt(idx!)} cy={yAt(cur.netWorth)} r="3" fill="var(--series-networth)" />
            {curPct && (
              <circle cx={xAt(idx!)} cy={yAt(curPct.p50)} r="3" fill="var(--series-fan-median)" />
            )}
          </g>
        )}

        <g class="axis axis--y">
          {yTicks.map((v) => (
            <text key={v} x={M.left - 6} y={yAt(v) + 3} text-anchor="end" font-size="10">
              {fmtMoney(v)}
            </text>
          ))}
        </g>
        <g class="axis axis--x">
          {xTicks.map((i) => {
            const row = cashFlow[i];
            if (!row) return null;
            return (
              <text key={i} x={xAt(i)} y={H - 8} text-anchor="middle" font-size="10">
                {row.year}
              </text>
            );
          })}
        </g>
      </svg>

      {cur && idx !== null && (
        <ChartTooltip
          x={xAt(idx)}
          chartWidth={width}
          title={`${cur.year} · age ${cur.primaryAge}`}
          rows={[
            ...(curPct
              ? ([
                  { label: "P90 net worth", value: fmtMoney(curPct.p90) },
                  {
                    label: "Median (P50)",
                    value: fmtMoney(curPct.p50),
                    color: "var(--series-fan-median)",
                  },
                  { label: "P10 net worth", value: fmtMoney(curPct.p10) },
                ] as const)
              : []),
            { label: "Deterministic", value: fmtMoney(cur.netWorth) },
          ]}
        />
      )}
    </div>
  );
}
