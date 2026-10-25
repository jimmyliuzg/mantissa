/**
 * Hover/focus readout for the SVG charts. Positioned by the parent's
 * .chart-wrap (position: relative), flips to the left half of the
 * cursor, and never eats pointer events.
 *
 * role="status" + aria-live: keyboard users hear values as arrow keys
 * move the cursor.
 */
export interface TooltipRow {
  label: string;
  value: string;
  /** CSS color for the series dot, e.g. "var(--series-income)". */
  color?: string;
}

export function ChartTooltip({
  x,
  chartWidth,
  title,
  rows,
}: {
  x: number;
  chartWidth: number;
  title: string;
  rows: TooltipRow[];
}) {
  const flip = x > chartWidth / 2;
  // <output> has the implicit "status" role — semantic, no ARIA needed.
  return (
    <output
      class="chart-tooltip"
      style={{
        left: `${x}px`,
        transform: flip ? "translateX(calc(-100% - 12px))" : "translateX(12px)",
      }}
      aria-live="polite"
    >
      <div class="chart-tooltip__title">{title}</div>
      {rows.map((r) => (
        <div class="chart-tooltip__row" key={r.label}>
          <span>
            {r.color && (
              <span class="chart-tooltip__dot" style={{ background: r.color }} aria-hidden="true" />
            )}
            {r.label}
          </span>
          <span class="chart-tooltip__value">{r.value}</span>
        </div>
      ))}
    </output>
  );
}
