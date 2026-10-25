/**
 * Shared chart geometry helpers.
 *
 * Charts render 1:1 pixels (svg width/height attributes match the
 * viewBox), so font sizes are real device px — no more 10px labels
 * shrinking to ~4px inside a scaled 880-unit viewBox on mobile.
 * Below CHART_MIN_WIDTH the wrapper scrolls horizontally instead of
 * shrinking further.
 */
import { useEffect, useRef, useState } from "preact/hooks";

export const CHART_MIN_WIDTH = 480;

/**
 * Measure a container and keep `width >= CHART_MIN_WIDTH`.
 * Returns a ref to attach to the scroll wrapper.
 */
export function useElementWidth<T extends HTMLElement>(fallback: number) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setWidth(Math.max(CHART_MIN_WIDTH, el.clientWidth));
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

/**
 * Evenly-spaced x-axis tick indices (year labels) that never crowd:
 * labels are >= ~minLabelPx apart, stepping through round year gaps
 * (1, 2, 5, 10, ...), always including the first row and the last.
 *
 * When the final row falls just after a tick closer than minLabelPx,
 * the last tick slides to the final row instead of stacking a second
 * label on top of it.
 */
export function xTickIndices(len: number, innerWidth: number, minLabelPx = 56): number[] {
  if (len <= 1) return [0];
  const span = len - 1;
  const rawStep = Math.max(1, Math.ceil((span * minLabelPx) / Math.max(1, innerWidth)));
  const candidates = [1, 2, 5, 10, 20, 25, 50];
  const step = candidates.find((c) => c >= rawStep) ?? Math.ceil(rawStep / 50) * 50;

  const out: number[] = [];
  for (let i = 0; i <= span; i += step) out.push(i);
  const lastTick = out.at(-1) ?? 0;
  if (lastTick !== span) {
    const pxPerIndex = innerWidth / span;
    const remainderPx = (span - lastTick) * pxPerIndex;
    if (remainderPx < minLabelPx * 0.6 && out.length > 1) {
      out.pop(); // last two labels would overlap — slide the final one
    }
    out.push(span);
  }
  return out;
}

/** Map a pointer x-position (relative to the plot area) to a row index. */
export function nearestIndex(pxInPlot: number, innerWidth: number, len: number): number {
  if (len <= 1) return 0;
  const t = Math.min(1, Math.max(0, pxInPlot / Math.max(1, innerWidth)));
  return Math.round(t * (len - 1));
}
