import { fmtMoney } from "../lib/format";
import { nearestIndex, useElementWidth, xTickIndices } from "../lib/chart-utils";
import { useState } from "preact/hooks";
import { ChartTooltip } from "./chart-tooltip";
import type { CashFlowRow } from "@engine";

interface CashFlowChartProps {
  rows: CashFlowRow[];
}

const H = 376;
const M = { top: 16, right: 16, bottom: 28, left: 56 };
const BARS_H = 180; // height of the diverging cash-flow area
const GAP = 20; // gap between the two charts

/**
 * Cash flow + net worth, two panels in one pixel-space SVG.
 *
 * Top panel is diverging: income plots above the zero line, spending
 * and taxes stack below it. One bar slot per year (instead of three
 * side-by-side grouped bars) so bars stay legible on narrow screens —
 * a ~50-year horizon used to render 3px grouped bars.
 *
 * Both panels share a band-scale x axis: row i sits at the center of
 * its year slot, so bars, lines, ticks, and the hover cursor all use
 * the same x(i).
 *
 * Interaction: pointer hover or keyboard arrows move a cursor index →
 * vertical guide + tooltip readout. The svg is 1:1 pixels (width/height
 * attrs equal the viewBox), so axis labels never shrink below their
 * nominal size; below CHART_MIN_WIDTH the wrapper scrolls instead.
 */
export function CashFlowChart({ rows }: CashFlowChartProps) {
  const [wrapRef, width] = useElementWidth<HTMLDivElement>(880);
  const [cursor, setCursor] = useState<number | null>(null);

  if (rows.length === 0) return <p class="muted">no rows</p>;

  const innerW = width - M.left - M.right;
  const groupW = innerW / rows.length;
  const xAt = (i: number) => M.left + (i + 0.5) * groupW;

  // --- Top panel: diverging cash flow ---
  const inMax = Math.max(...rows.map((r) => r.income), 1);
  const outMax = Math.max(...rows.map((r) => r.expenses + r.taxes), 1);
  const pad = Math.max(inMax, outMax) * 0.05;
  const hi = inMax + pad;
  const lo = -outMax - pad;
  const yCf = (v: number) => M.top + ((hi - v) / (hi - lo)) * BARS_H;
  const zeroY = yCf(0);

  const barW = Math.max(2, Math.min(groupW * 0.55, 18));

  // --- Bottom panel: net worth line ---
  const nwTop = M.top + BARS_H + GAP;
  const nwH = H - nwTop - M.bottom;
  const nwMin = Math.min(...rows.map((r) => r.netWorth), 0);
  const nwMax = Math.max(...rows.map((r) => r.netWorth), 1);
  const nwPad = (nwMax - nwMin) * 0.05;
  const nwLo = nwMin - nwPad * 0.2;
  const nwHi = nwMax + nwPad;
  const yNw = (v: number) => nwTop + nwH - ((v - nwLo) / (nwHi - nwLo)) * nwH;

  let nwPath = `M ${xAt(0)} ${yNw(rows[0]!.netWorth)}`;
  for (let i = 1; i < rows.length; i++) {
    nwPath += ` L ${xAt(i)} ${yNw(rows[i]!.netWorth)}`;
  }

  const cfTicks = [hi, 0, lo];
  const nwTicks = [nwLo, (nwLo + nwHi) / 2, nwHi];
  const xTicks = xTickIndices(rows.length, innerW);

  const idx = cursor;
  const cur = idx !== null ? rows[idx] : undefined;

  function onPointerMove(e: PointerEvent) {
    const rect = (e.currentTarget as SVGElement).getBoundingClientRect();
    setCursor(nearestIndex(e.clientX - rect.left - M.left, innerW, rows.length));
  }

  function onKeyDown(e: KeyboardEvent) {
    const last = rows.length - 1;
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
        aria-label={`Cash flow and net worth, ${rows.length} years. Focus and use left arrow and right arrow keys to inspect individual years.`}
        class="chart"
        tabIndex={0}
        onPointerMove={onPointerMove}
        onPointerLeave={() => setCursor(null)}
        onKeyDown={onKeyDown}
        onBlur={() => setCursor(null)}
      >
        {/* Top panel: diverging cash flow */}
        <g>
          {cfTicks.map((v) => (
            <line
              key={v}
              x1={M.left}
              x2={width - M.right}
              y1={yCf(v)}
              y2={yCf(v)}
              stroke="currentColor"
              stroke-opacity="0.08"
            />
          ))}
          {/* Zero line separates income (up) from spending + taxes (down) */}
          <line
            x1={M.left}
            x2={width - M.right}
            y1={zeroY}
            y2={zeroY}
            stroke="currentColor"
            stroke-opacity="0.45"
          />
          {rows.map((r, i) => {
            const x = xAt(i) - barW / 2;
            const yIn = yCf(r.income);
            const yExp = yCf(-r.expenses);
            const yTax = yCf(-(r.expenses + r.taxes));
            return (
              <g key={r.year}>
                <rect
                  x={x}
                  y={yIn}
                  width={barW}
                  height={zeroY - yIn}
                  class="series series--income-bar"
                />
                <rect
                  x={x}
                  y={zeroY}
                  width={barW}
                  height={yExp - zeroY}
                  class="series series--expenses-bar"
                />
                <rect
                  x={x}
                  y={yExp}
                  width={barW}
                  height={yTax - yExp}
                  class="series series--taxes-bar"
                />
              </g>
            );
          })}
          {cfTicks.map((v) => (
            <text
              key={v}
              x={M.left - 6}
              y={yCf(v) + 3}
              text-anchor="end"
              font-size="10"
              class="muted"
            >
              {fmtMoney(v)}
            </text>
          ))}
          <text x={M.left} y={M.top - 4} font-size="10" class="muted">
            Cash flow: income above zero · spending + taxes below ($ / yr)
          </text>
        </g>

        {/* Bottom panel: net worth */}
        <g>
          {nwTicks.map((v) => (
            <line
              key={v}
              x1={M.left}
              x2={width - M.right}
              y1={yNw(v)}
              y2={yNw(v)}
              stroke="currentColor"
              stroke-opacity="0.08"
            />
          ))}
          <path d={nwPath} class="series series--networth" fill="none" />
          {nwTicks.map((v) => (
            <text
              key={v}
              x={M.left - 6}
              y={yNw(v) + 3}
              text-anchor="end"
              font-size="10"
              class="muted"
            >
              {fmtMoney(v)}
            </text>
          ))}
          <text x={M.left} y={nwTop - 4} font-size="10" class="muted">
            Net worth
          </text>
        </g>

        {/* Cursor: guide line + dots on the read series */}
        {cur && (
          <g aria-hidden="true">
            <line x1={xAt(idx!)} x2={xAt(idx!)} y1={M.top} y2={H - M.bottom} class="chart-guide" />
            <circle cx={xAt(idx!)} cy={yCf(cur.income)} r="3" fill="var(--series-income)" />
            <circle cx={xAt(idx!)} cy={yNw(cur.netWorth)} r="3" fill="var(--series-networth)" />
          </g>
        )}

        {/* Shared x axis */}
        <g class="axis axis--x">
          {xTicks.map((i) => {
            const row = rows[i];
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
            { label: "Income", value: fmtMoney(cur.income), color: "var(--series-income)" },
            { label: "Spending", value: fmtMoney(cur.expenses), color: "var(--series-expenses)" },
            { label: "Taxes", value: fmtMoney(cur.taxes), color: "var(--series-taxes)" },
            { label: "Net cash flow", value: fmtMoney(cur.netCashFlow) },
            { label: "Net worth", value: fmtMoney(cur.netWorth) },
          ]}
        />
      )}
    </div>
  );
}
